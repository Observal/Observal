import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import ROLE_HIERARCHY, get_db, optional_current_user, require_role, resolve_listing
from api.routes.component_versions import create_version_router
from api.sanitize import escape_like
from models.mcp import ListingStatus
from models.prompt import PromptDownload, PromptListing, PromptVersion
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
from services.audit_helpers import audit
from services.editing_lock import _is_lock_expired, acquire_edit_lock, release_edit_lock

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
        owner=req.owner,
        submitted_by=current_user.id,
        owner_org_id=current_user.org_id,
    )
    db.add(listing)
    await db.flush()

    version = PromptVersion(
        listing_id=listing.id,
        version=req.version,
        description=req.description,
        category=req.category,
        template=req.template,
        variables=req.variables,
        model_hints=req.model_hints,
        tags=req.tags,
        supported_ides=req.supported_ides,
        status=ListingStatus.pending,
        released_by=current_user.id,
        released_at=datetime.now(UTC),
    )
    db.add(version)
    await db.flush()

    listing.latest_version_id = version.id
    await db.commit()
    await db.refresh(listing)
    await audit(
        current_user, "prompt.submit", resource_type="prompt", resource_id=str(listing.id), resource_name=listing.name
    )
    return PromptListingResponse.model_validate(listing)


@router.get("", response_model=list[PromptListingSummary])
async def list_prompts(
    category: str | None = Query(None),
    search: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(PromptListing)
        .join(PromptVersion, PromptListing.latest_version_id == PromptVersion.id)
        .where(PromptVersion.status == ListingStatus.approved)
    )
    if category:
        stmt = stmt.where(PromptVersion.category == category)
    if search:
        safe = escape_like(search)
        stmt = stmt.where(PromptListing.name.ilike(f"%{safe}%") | PromptVersion.description.ilike(f"%{safe}%"))
    result = await db.execute(stmt.order_by(PromptListing.created_at.desc()))
    listings = [PromptListingSummary.model_validate(r) for r in result.scalars().all()]
    await audit(None, "prompt.list", resource_type="prompt")
    return listings


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
    listings = [PromptListingSummary.model_validate(r) for r in result.scalars().all()]
    await audit(current_user, "prompt.my_list", resource_type="prompt")
    return listings


@router.get("/{listing_id}", response_model=PromptListingResponse)
async def get_prompt(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_current_user),
):
    listing = await resolve_listing(PromptListing, listing_id, db, require_status=ListingStatus.approved)
    if listing:
        await audit(
            current_user, "prompt.view", resource_type="prompt", resource_id=str(listing.id), resource_name=listing.name
        )
        return PromptListingResponse.model_validate(listing)

    listing = await resolve_listing(PromptListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    if current_user and (
        listing.submitted_by == current_user.id
        or ROLE_HIERARCHY.get(current_user.role, 999) <= ROLE_HIERARCHY[UserRole.reviewer]
    ):
        await audit(
            current_user, "prompt.view", resource_type="prompt", resource_id=str(listing.id), resource_name=listing.name
        )
        return PromptListingResponse.model_validate(listing)

    raise HTTPException(status_code=404, detail="Listing not found")


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

    await audit(
        current_user, "prompt.install", resource_type="prompt", resource_id=str(listing.id), resource_name=listing.name
    )
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

    await audit(
        current_user, "prompt.render", resource_type="prompt", resource_id=str(listing.id), resource_name=listing.name
    )
    return PromptRenderResponse(listing_id=listing.id, rendered=rendered)


@router.post("/draft", response_model=PromptListingResponse)
async def save_prompt_draft(
    req: PromptDraftRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    listing = PromptListing(
        name=req.name,
        owner=req.owner or current_user.username or current_user.email,
        submitted_by=current_user.id,
        owner_org_id=current_user.org_id,
    )
    db.add(listing)
    await db.flush()

    version = PromptVersion(
        listing_id=listing.id,
        version=req.version,
        description=req.description,
        category=req.category,
        template=req.template,
        variables=req.variables,
        model_hints=req.model_hints,
        tags=req.tags,
        supported_ides=req.supported_ides,
        status=ListingStatus.draft,
        released_by=current_user.id,
        released_at=datetime.now(UTC),
    )
    db.add(version)
    await db.flush()

    listing.latest_version_id = version.id
    await db.commit()
    await db.refresh(listing)
    await audit(
        current_user,
        "prompt.draft.create",
        resource_type="prompt",
        resource_id=str(listing.id),
        resource_name=listing.name,
    )
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
    if listing.status not in (ListingStatus.draft, ListingStatus.rejected, ListingStatus.pending):
        raise HTTPException(status_code=400, detail="Only draft, rejected, or pending listings can be edited")

    ver = listing.latest_version
    if not ver:
        raise HTTPException(status_code=400, detail="Listing has no version to update")

    for field in (
        "version",
        "description",
        "category",
        "template",
        "variables",
        "model_hints",
        "tags",
        "supported_ides",
    ):
        val = getattr(req, field)
        if val is not None:
            setattr(ver, field, val)

    # Don't allow saving over another user's active lock
    if (
        ver.is_editing
        and ver.editing_by != current_user.id
        and not _is_lock_expired(ver.editing_since)
    ):
        raise HTTPException(
            status_code=409,
            detail="This item is currently being edited by another user. Please try again later.",
        )
    release_edit_lock(ver, current_user.id, force=True)
    await db.flush()

    for field in ("name", "owner"):
        val = getattr(req, field)
        if val is not None:
            setattr(listing, field, val)

    await db.commit()
    await db.refresh(listing)
    if listing.status == ListingStatus.pending:
        action = "prompt.pending.update"
    elif listing.status == ListingStatus.rejected:
        action = "prompt.rejected.update"
    else:
        action = "prompt.draft.update"
    await audit(
        current_user,
        action,
        resource_type="prompt",
        resource_id=str(listing.id),
        resource_name=listing.name,
    )
    return PromptListingResponse.model_validate(listing)


@router.post("/{listing_id}/start-edit")
async def start_edit_prompt(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    listing = await resolve_listing(PromptListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if listing.submitted_by != current_user.id:
        raise HTTPException(status_code=403, detail="Not the listing owner")
    ver = listing.latest_version
    if not ver:
        raise HTTPException(status_code=400, detail="Listing has no version")
    if ver.status not in (ListingStatus.pending, ListingStatus.draft, ListingStatus.rejected):
        raise HTTPException(status_code=400, detail=f"Cannot edit: listing is '{ver.status.value}'")
    # Re-fetch with row-level lock to prevent TOCTOU race
    ver = (
        await db.execute(
            select(PromptVersion).where(PromptVersion.id == ver.id).with_for_update()
        )
    ).scalar_one()
    acquire_edit_lock(ver, current_user.id)
    await db.commit()
    return {"status": "locked"}


@router.post("/{listing_id}/cancel-edit")
async def cancel_edit_prompt(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    listing = await resolve_listing(PromptListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if listing.submitted_by != current_user.id:
        raise HTTPException(status_code=403, detail="Not the listing owner")
    ver = listing.latest_version
    if not ver:
        raise HTTPException(status_code=400, detail="Listing has no version")
    release_edit_lock(ver, current_user.id)
    await db.commit()
    return {"status": "unlocked"}


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
    if listing.status not in (ListingStatus.draft, ListingStatus.rejected):
        raise HTTPException(status_code=400, detail="Listing is not a draft")

    if not listing.description:
        raise HTTPException(status_code=400, detail="Description is required before submitting")
    if not listing.template:
        raise HTTPException(status_code=400, detail="Template is required before submitting")

    listing.status = ListingStatus.pending
    await db.commit()
    await db.refresh(listing)
    await audit(
        current_user,
        "prompt.draft.submit",
        resource_type="prompt",
        resource_id=str(listing.id),
        resource_name=listing.name,
    )
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
    is_admin = ROLE_HIERARCHY.get(current_user.role, 999) <= ROLE_HIERARCHY[UserRole.admin]
    if listing.submitted_by != current_user.id and not is_admin:
        raise HTTPException(status_code=403, detail="Not authorized")
    if listing.status == ListingStatus.approved and not is_admin:
        raise HTTPException(status_code=400, detail="Cannot delete an approved listing. Contact an admin.")

    for r in (await db.execute(select(PromptDownload).where(PromptDownload.listing_id == listing.id))).scalars().all():
        await db.delete(r)

    # Break the circular FK (listing → latest_version → listing) before delete
    listing_name = listing.name
    listing.latest_version_id = None
    listing.latest_version = None
    await db.flush()
    # Delete versions explicitly to avoid SQLAlchemy circular dependency detection
    for ver in list(listing.versions):
        await db.delete(ver)
    await db.flush()
    await db.delete(listing)
    await db.commit()
    await audit(
        current_user, "prompt.delete", resource_type="prompt", resource_id=str(listing_id), resource_name=listing_name
    )
    return {"deleted": str(listing_id)}


# --- Version sub-routes ---
router.include_router(create_version_router("prompt", PromptListing, PromptVersion))
