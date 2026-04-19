import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db, require_role, resolve_listing
from models.mcp import ListingStatus
from models.prompt import PromptDownload, PromptListing
from models.user import User, UserRole
from schemas.prompt import (
    PromptDraftRequest,
    PromptListingResponse,
    PromptListingSummary,
    PromptRenderRequest,
    PromptRenderResponse,
    PromptSubmitRequest,
    PromptUpdateRequest,
)

router = APIRouter(prefix="/api/v1/prompts", tags=["prompts"])


@router.post("/submit", response_model=PromptListingResponse)
async def submit_prompt(
    req: PromptSubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    existing = await db.execute(
        select(PromptListing).where(PromptListing.name == req.name, PromptListing.submitted_by == current_user.id)
    )
    if existing.scalars().first():
        raise HTTPException(status_code=409, detail=f"You already have a prompt named '{req.name}'")

    listing = PromptListing(
        name=req.name,
        version=req.version,
        description=req.description,
        owner=req.owner,
        category=req.category,
        template=req.template,
        variables=req.variables,
        model_hints=req.model_hints,
        tags=req.tags,
        supported_ides=req.supported_ides,
        status=ListingStatus.pending,
        submitted_by=current_user.id,
        owner_org_id=current_user.org_id,
    )
    db.add(listing)
    await db.commit()
    await db.refresh(listing)
    return PromptListingResponse.model_validate(listing)


@router.get("", response_model=list[PromptListingSummary])
async def list_prompts(
    category: str | None = Query(None),
    search: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(PromptListing).where(PromptListing.status == ListingStatus.approved)
    if category:
        stmt = stmt.where(PromptListing.category == category)
    if search:
        stmt = stmt.where(PromptListing.name.ilike(f"%{search}%") | PromptListing.description.ilike(f"%{search}%"))
    result = await db.execute(stmt.order_by(PromptListing.created_at.desc()))
    return [PromptListingSummary.model_validate(r) for r in result.scalars().all()]


@router.get("/{listing_id}", response_model=PromptListingResponse)
async def get_prompt(listing_id: str, db: AsyncSession = Depends(get_db)):
    listing = await resolve_listing(PromptListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    return PromptListingResponse.model_validate(listing)


@router.post("/{listing_id}/install", response_model=dict)
async def install_prompt(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    listing = await resolve_listing(PromptListing, listing_id, db, require_status=ListingStatus.approved)
    if not listing:
        listing = await resolve_listing(PromptListing, listing_id, db)
        if not listing or listing.submitted_by != current_user.id:
            raise HTTPException(status_code=404, detail="Listing not found or not approved")

    db.add(PromptDownload(listing_id=listing.id, user_id=current_user.id, ide="api"))
    await db.commit()

    return {
        "listing_id": str(listing.id),
        "config_snippet": {
            "prompt": {
                "id": str(listing.id),
                "name": listing.name,
                "render_url": f"/api/v1/prompts/{listing.id}/render",
                "template_preview": listing.template[:200] if listing.template else "",
            },
        },
    }


@router.post("/{listing_id}/render", response_model=PromptRenderResponse)
async def render_prompt(
    listing_id: str,
    req: PromptRenderRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    listing = await resolve_listing(PromptListing, listing_id, db, require_status=ListingStatus.approved)
    if not listing:
        listing = await resolve_listing(PromptListing, listing_id, db)
        if not listing or listing.submitted_by != current_user.id:
            raise HTTPException(status_code=404, detail="Listing not found or not approved")

    rendered = listing.template
    for key, value in req.variables.items():
        rendered = re.sub(r"\{\{\s*" + re.escape(key) + r"\s*\}\}", value, rendered)

    from datetime import UTC, datetime

    from services.clickhouse import insert_spans

    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    try:
        await insert_spans(
            [
                {
                    "span_id": str(uuid.uuid4()),
                    "trace_id": str(uuid.uuid4()),
                    "type": "prompt_render",
                    "name": f"render:{listing.name}",
                    "start_time": now,
                    "end_time": now,
                    "latency_ms": 0,
                    "status": "success",
                    "project_id": "default",
                    "user_id": str(current_user.id),
                    "variables_provided": len(req.variables),
                    "template_tokens": len(listing.template.split()),
                    "rendered_tokens": len(rendered.split()),
                    "metadata": {},
                }
            ]
        )
    except Exception:
        pass

    return PromptRenderResponse(listing_id=listing.id, rendered=rendered)


@router.get("/my", response_model=list[PromptListingSummary])
async def my_prompts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    stmt = (
        select(PromptListing)
        .where(PromptListing.submitted_by == current_user.id)
        .order_by(PromptListing.created_at.desc())
    )
    result = await db.execute(stmt)
    return [PromptListingSummary.model_validate(r) for r in result.scalars().all()]


@router.post("/draft", response_model=PromptListingResponse)
async def save_prompt_draft(
    req: PromptDraftRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    listing = PromptListing(
        name=req.name,
        version=req.version,
        description=req.description,
        owner=req.owner or current_user.username or current_user.email,
        category=req.category,
        template=req.template,
        variables=req.variables,
        model_hints=req.model_hints,
        tags=req.tags,
        supported_ides=req.supported_ides,
        status=ListingStatus.draft,
        submitted_by=current_user.id,
        owner_org_id=current_user.org_id,
    )
    db.add(listing)
    await db.commit()
    await db.refresh(listing)
    return PromptListingResponse.model_validate(listing)


@router.put("/{listing_id}/draft", response_model=PromptListingResponse)
async def update_prompt_draft(
    listing_id: str,
    req: PromptUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    listing = await resolve_listing(PromptListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if listing.submitted_by != current_user.id:
        raise HTTPException(status_code=403, detail="Not the listing owner")
    if listing.status != ListingStatus.draft:
        raise HTTPException(status_code=400, detail="Listing is not a draft")

    for field in (
        "name",
        "version",
        "description",
        "owner",
        "category",
        "template",
        "variables",
        "model_hints",
        "tags",
        "supported_ides",
    ):
        val = getattr(req, field)
        if val is not None:
            setattr(listing, field, val)

    await db.commit()
    await db.refresh(listing)
    return PromptListingResponse.model_validate(listing)


@router.post("/{listing_id}/submit", response_model=PromptListingResponse)
async def submit_prompt_draft(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    listing = await resolve_listing(PromptListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if listing.submitted_by != current_user.id:
        raise HTTPException(status_code=403, detail="Not the listing owner")
    if listing.status != ListingStatus.draft:
        raise HTTPException(status_code=400, detail="Listing is not a draft")

    if not listing.description:
        raise HTTPException(status_code=400, detail="Description is required before submitting")
    if not listing.template:
        raise HTTPException(status_code=400, detail="Template is required before submitting")

    listing.status = ListingStatus.pending
    await db.commit()
    await db.refresh(listing)
    return PromptListingResponse.model_validate(listing)


@router.delete("/{listing_id}")
async def delete_prompt(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    listing = await resolve_listing(PromptListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if listing.submitted_by != current_user.id and current_user.role.value != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    for r in (await db.execute(select(PromptDownload).where(PromptDownload.listing_id == listing.id))).scalars().all():
        await db.delete(r)

    await db.delete(listing)
    await db.commit()
    return {"deleted": str(listing.id)}
