import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user, get_db, resolve_listing
from models.mcp import ListingStatus
from models.prompt import PromptDownload, PromptListing
from models.user import User
from schemas.prompt import (
    PromptListingResponse,
    PromptListingSummary,
    PromptRenderRequest,
    PromptRenderResponse,
    PromptSubmitRequest,
)

router = APIRouter(prefix="/api/v1/prompts", tags=["prompts"])


@router.post("/submit", response_model=PromptListingResponse)
async def submit_prompt(
    req: PromptSubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
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
    current_user: User = Depends(get_current_user),
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
    current_user: User = Depends(get_current_user),
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


@router.delete("/{listing_id}")
async def delete_prompt(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
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
