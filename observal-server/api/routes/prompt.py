# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 Shreem Seth <shreemseth26@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi_cache.decorator import cache
from loguru import logger as optic
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import services.dynamic_settings as ds
from api.deps import (
    ROLE_HIERARCHY,
    apply_visibility_filter,
    check_listing_visibility,
    commit_or_name_conflict,
    get_db,
    get_effective_component_permission,
    optional_current_user,
    require_role,
    resolve_listing,
)
from api.routes._component_archive import archive_listing, unarchive_listing
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
from services.editing_lock import _is_lock_expired, acquire_edit_lock, release_edit_lock

router = APIRouter(prefix="/api/v1/prompts", tags=["prompts"])


@router.post("/submit", response_model=PromptListingResponse)
async def submit_prompt(
    req: PromptSubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.debug("prompt submit: name={}", req.name)
    existing = await db.execute(select(PromptListing).where(PromptListing.name == req.name))
    if existing.scalars().first():
        raise HTTPException(status_code=409, detail=f"A prompt named '{req.name}' already exists")

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
    await commit_or_name_conflict(db, "prompt")
    await db.refresh(listing)
    return PromptListingResponse.model_validate(listing)


@router.get("", response_model=list[PromptListingSummary])
@cache(expire=ds.get_sync_int("data.cache_ttl_registry", 30), namespace="registry")
async def list_prompts(
    response: Response,
    category: str | None = Query(None),
    search: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_current_user),
):
    optic.debug("prompt list: search={}", search)
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
    stmt = apply_visibility_filter(stmt, PromptListing, current_user)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(stmt.order_by(PromptListing.created_at.desc()).limit(limit).offset(offset))
    listings = [PromptListingSummary.model_validate(r) for r in result.scalars().all()]
    response.headers["X-Total-Count"] = str(total or 0)
    return listings


@router.get("/my", response_model=list[PromptListingSummary])
async def my_prompts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.debug("my_prompts called")
    stmt = (
        select(PromptListing)
        .where(PromptListing.submitted_by == current_user.id)
        .order_by(PromptListing.created_at.desc())
    )
    result = await db.execute(stmt)
    listings = [PromptListingSummary.model_validate(r) for r in result.scalars().all()]
    return listings


@router.get("/{listing_id}", response_model=PromptListingResponse)
async def get_prompt(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_current_user),
):
    optic.debug("prompt get: listing_id={}", listing_id)
    listing = await resolve_listing(PromptListing, listing_id, db, require_status=ListingStatus.approved)
    if listing:
        resp = PromptListingResponse.model_validate(listing)
        resp.user_permission = get_effective_component_permission(listing, current_user)
        return resp

    listing = await resolve_listing(PromptListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    if check_listing_visibility(listing, current_user):
        resp = PromptListingResponse.model_validate(listing)
        resp.user_permission = get_effective_component_permission(listing, current_user)
        return resp

    raise HTTPException(status_code=404, detail="Listing not found")


@router.post("/{listing_id}/render", response_model=PromptRenderResponse)
async def render_prompt(
    listing_id: str,
    req: PromptRenderRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.debug("prompt render")
    listing = await resolve_listing(PromptListing, listing_id, db, require_status=ListingStatus.approved)
    if not listing:
        listing = await resolve_listing(PromptListing, listing_id, db)
        if not listing or get_effective_component_permission(listing, current_user) != "owner":
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
    return PromptRenderResponse(listing_id=listing.id, rendered=rendered)


@router.post("/draft", response_model=PromptListingResponse)
async def save_prompt_draft(
    req: PromptDraftRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.trace("req={}", req)
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
    await commit_or_name_conflict(db, "prompt")
    await db.refresh(listing)
    return PromptListingResponse.model_validate(listing)


@router.put("/{listing_id}/draft", response_model=PromptListingResponse)
async def update_prompt_draft(
    listing_id: str,
    req: PromptUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.trace("listing_id={}", listing_id)
    listing = await resolve_listing(PromptListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if get_effective_component_permission(listing, current_user) != "owner":
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
    if ver.is_editing and ver.editing_by != current_user.id and not _is_lock_expired(ver.editing_since):
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

    await commit_or_name_conflict(db, "prompt")
    await db.refresh(listing)
    return PromptListingResponse.model_validate(listing)


@router.post("/{listing_id}/start-edit")
async def start_edit_prompt(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.trace("listing_id={}", listing_id)
    listing = await resolve_listing(PromptListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if get_effective_component_permission(listing, current_user) != "owner":
        raise HTTPException(status_code=403, detail="Not the listing owner")
    ver = listing.latest_version
    if not ver:
        raise HTTPException(status_code=400, detail="Listing has no version")
    if ver.status not in (ListingStatus.pending, ListingStatus.draft, ListingStatus.rejected):
        raise HTTPException(status_code=400, detail=f"Cannot edit: listing is '{ver.status.value}'")
    # Re-fetch with row-level lock to prevent TOCTOU race
    ver = (await db.execute(select(PromptVersion).where(PromptVersion.id == ver.id).with_for_update())).scalar_one()
    acquire_edit_lock(ver, current_user.id)
    await commit_or_name_conflict(db, "prompt")
    return {"status": "locked"}


@router.post("/{listing_id}/cancel-edit")
async def cancel_edit_prompt(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.trace("listing_id={}", listing_id)
    listing = await resolve_listing(PromptListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if get_effective_component_permission(listing, current_user) != "owner":
        raise HTTPException(status_code=403, detail="Not the listing owner")
    ver = listing.latest_version
    if not ver:
        raise HTTPException(status_code=400, detail="Listing has no version")
    release_edit_lock(ver, current_user.id)
    await commit_or_name_conflict(db, "prompt")
    return {"status": "unlocked"}


@router.post("/{listing_id}/submit", response_model=PromptListingResponse)
async def submit_prompt_draft(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.trace("listing_id={}", listing_id)
    listing = await resolve_listing(PromptListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if get_effective_component_permission(listing, current_user) != "owner":
        raise HTTPException(status_code=403, detail="Not the listing owner")
    if listing.status not in (ListingStatus.draft, ListingStatus.rejected):
        raise HTTPException(status_code=400, detail="Listing is not a draft")

    if not listing.description:
        raise HTTPException(status_code=400, detail="Description is required before submitting")
    if not listing.template:
        raise HTTPException(status_code=400, detail="Template is required before submitting")

    listing.status = ListingStatus.pending
    await commit_or_name_conflict(db, "prompt")
    await db.refresh(listing)
    return PromptListingResponse.model_validate(listing)


@router.patch("/{listing_id}/archive")
async def archive_prompt(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    return await archive_listing(PromptListing, listing_id, db, current_user, "prompt")


@router.patch("/{listing_id}/unarchive")
async def unarchive_prompt(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    return await unarchive_listing(PromptListing, listing_id, db, current_user, "prompt")


@router.delete("/{listing_id}")
async def delete_prompt(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.debug("prompt delete: listing_id={}", listing_id)
    listing = await resolve_listing(PromptListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    is_admin = ROLE_HIERARCHY.get(current_user.role, 999) <= ROLE_HIERARCHY[UserRole.admin]
    if get_effective_component_permission(listing, current_user) != "owner":
        raise HTTPException(status_code=403, detail="Not authorized")
    if listing.status == ListingStatus.approved and not is_admin:
        raise HTTPException(status_code=400, detail="Cannot delete an approved listing. Contact an admin.")

    for r in (await db.execute(select(PromptDownload).where(PromptDownload.listing_id == listing.id))).scalars().all():
        await db.delete(r)

    # Break the circular FK (listing → latest_version → listing) before delete
    listing.latest_version_id = None
    listing.latest_version = None
    await db.flush()
    # Delete versions explicitly to avoid SQLAlchemy circular dependency detection
    for ver in list(listing.versions):
        await db.delete(ver)
    await db.flush()
    await db.delete(listing)
    await commit_or_name_conflict(db, "prompt")
    return {"deleted": str(listing_id)}


# --- Version sub-routes ---
router.include_router(create_version_router("prompt", PromptListing, PromptVersion))
