# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 Shreem Seth <shreemseth26@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi_cache.decorator import cache
from loguru import logger as optic
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import services.dynamic_settings as ds
from api.deps import (
    apply_visibility_filter,
    check_listing_visibility,
    commit_or_name_conflict,
    get_db,
    get_effective_component_permission,
    optional_current_user,
    require_role,
    resolve_listing,
)
from api.routes._component_archive import archive_listing, archived_install_warning, unarchive_listing
from api.routes.component_versions import create_version_router
from api.search import keyword_search
from models.hook import HookDownload, HookListing, HookVersion
from models.mcp import ListingStatus
from models.user import User, UserRole
from schemas.hook import (
    HookDraftRequest,
    HookFileEntry,
    HookInstallRequest,
    HookInstallResponse,
    HookListingResponse,
    HookListingSummary,
    HookSubmitRequest,
    HookUpdateRequest,
)
from services.editing_lock import _is_lock_expired, acquire_edit_lock, release_edit_lock

router = APIRouter(prefix="/api/v1/hooks", tags=["hooks"])


@router.post("/submit", response_model=HookListingResponse)
async def submit_hook(
    req: HookSubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.debug("hook submit: name={}", req.name)
    existing = await db.execute(select(HookListing).where(HookListing.name == req.name))
    if existing.scalars().first():
        raise HTTPException(status_code=409, detail=f"A hook named '{req.name}' already exists")

    listing = HookListing(
        name=req.name,
        owner=req.owner,
        submitted_by=current_user.id,
        owner_org_id=current_user.org_id,
    )
    db.add(listing)
    await db.flush()

    version = HookVersion(
        listing_id=listing.id,
        version=req.version,
        description=req.description,
        event=req.event,
        execution_mode=req.execution_mode,
        priority=req.priority,
        handler_type=req.handler_type,
        handler_config=req.handler_config,
        scope=req.scope,
        tool_filter=req.tool_filter,
        supported_harnesses=req.supported_harnesses,
        script_content=req.script_content,
        script_filename=req.script_filename,
        source_url=req.source_url,
        source_ref=req.source_ref,
        source_path=req.source_path,
        requirements=req.requirements,
        status=ListingStatus.pending,
        released_by=current_user.id,
        released_at=datetime.now(UTC),
    )
    db.add(version)
    await db.flush()

    listing.latest_version_id = version.id
    await commit_or_name_conflict(db, "hook")
    await db.refresh(listing)
    return HookListingResponse.model_validate(listing)


@router.get("", response_model=list[HookListingSummary])
@cache(expire=ds.get_sync_int("data.cache_ttl_registry", 30), namespace="registry")
async def list_hooks(
    response: Response,
    event: str | None = Query(None),
    scope: str | None = Query(None),
    search: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_current_user),
):
    optic.debug("hook list: search={}", search)
    stmt = (
        select(HookListing)
        .join(HookVersion, HookListing.latest_version_id == HookVersion.id)
        .where(HookVersion.status == ListingStatus.approved)
    )
    if event:
        stmt = stmt.where(HookVersion.event == event)
    if scope:
        stmt = stmt.where(HookVersion.scope == scope)
    search_rank = None
    if search:
        search_filter, search_rank = keyword_search(
            search,
            [HookListing.name, HookVersion.description, HookVersion.event, HookVersion.scope, HookVersion.handler_type],
            name_field=HookListing.name,
        )
        if search_filter is not None:
            stmt = stmt.where(search_filter)
    stmt = apply_visibility_filter(stmt, HookListing, current_user)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    order_by = [HookListing.created_at.desc()]
    if search_rank is not None:
        order_by.insert(0, search_rank.desc())
    result = await db.execute(stmt.order_by(*order_by).limit(limit).offset(offset))
    listings = [HookListingSummary.model_validate(r) for r in result.scalars().all()]
    response.headers["X-Total-Count"] = str(total or 0)
    return listings


@router.get("/my", response_model=list[HookListingSummary])
async def my_hooks(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.debug("my_hooks called")
    stmt = (
        select(HookListing).where(HookListing.submitted_by == current_user.id).order_by(HookListing.created_at.desc())
    )
    result = await db.execute(stmt)
    listings = [HookListingSummary.model_validate(r) for r in result.scalars().all()]
    return listings


@router.get("/{listing_id}", response_model=HookListingResponse)
async def get_hook(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_current_user),
):
    optic.debug("hook get: listing_id={}", listing_id)
    listing = await resolve_listing(HookListing, listing_id, db, require_status=ListingStatus.approved)
    if listing:
        resp = HookListingResponse.model_validate(listing)
        resp.user_permission = get_effective_component_permission(listing, current_user)
        return resp

    listing = await resolve_listing(HookListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    if check_listing_visibility(listing, current_user):
        resp = HookListingResponse.model_validate(listing)
        resp.user_permission = get_effective_component_permission(listing, current_user)
        return resp

    raise HTTPException(status_code=404, detail="Listing not found")


@router.post("/{listing_id}/install", response_model=HookInstallResponse)
async def install_hook(
    listing_id: str,
    req: HookInstallRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.debug("hook install: listing_id={}", listing_id)
    listing = await resolve_listing(HookListing, listing_id, db, require_status=ListingStatus.approved)
    if not listing:
        listing = await resolve_listing(HookListing, listing_id, db)
        if not listing or not check_listing_visibility(listing, current_user):
            raise HTTPException(status_code=404, detail="Listing not found or not approved")
        if (
            listing.status != ListingStatus.archived
            and get_effective_component_permission(listing, current_user) != "owner"
        ):
            raise HTTPException(status_code=404, detail="Listing not found or not approved")

    warnings = []
    if listing.status == ListingStatus.archived:
        warnings.append(archived_install_warning("hook", listing.name))

    db.add(HookDownload(listing_id=listing.id, user_id=current_user.id, harness=req.harness))
    latest_version = getattr(listing, "latest_version", None)
    if latest_version:
        latest_version.download_count += 1
    await commit_or_name_conflict(db, "hook")

    from services.hook_install_generator import generate_hook_install_config

    result = generate_hook_install_config(listing, req.harness)
    return HookInstallResponse(
        listing_id=listing.id,
        harness=req.harness,
        config_snippet=result.get("config_snippet", {}),
        config_path=result.get("config_path", ""),
        files=[HookFileEntry(**f) for f in result.get("files", [])],
        requirements=result.get("requirements", []),
        source_fetch=result.get("source_fetch"),
        notes=result.get("notes", []),
        warnings=warnings,
    )


@router.post("/draft", response_model=HookListingResponse)
async def save_hook_draft(
    req: HookDraftRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.trace("req={}", req)
    listing = HookListing(
        name=req.name,
        owner=req.owner or current_user.username or current_user.email,
        submitted_by=current_user.id,
        owner_org_id=current_user.org_id,
    )
    db.add(listing)
    await db.flush()

    version = HookVersion(
        listing_id=listing.id,
        version=req.version,
        description=req.description,
        event=req.event,
        execution_mode=req.execution_mode,
        priority=req.priority,
        handler_type=req.handler_type,
        handler_config=req.handler_config,
        scope=req.scope,
        tool_filter=req.tool_filter,
        supported_harnesses=req.supported_harnesses,
        script_content=req.script_content,
        script_filename=req.script_filename,
        source_url=req.source_url,
        source_ref=req.source_ref,
        source_path=req.source_path,
        requirements=req.requirements,
        status=ListingStatus.draft,
        released_by=current_user.id,
        released_at=datetime.now(UTC),
    )
    db.add(version)
    await db.flush()

    listing.latest_version_id = version.id
    await commit_or_name_conflict(db, "hook")
    await db.refresh(listing)
    return HookListingResponse.model_validate(listing)


@router.put("/{listing_id}/draft", response_model=HookListingResponse)
async def update_hook_draft(
    listing_id: str,
    req: HookUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.trace("listing_id={}", listing_id)
    listing = await resolve_listing(HookListing, listing_id, db)
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
        "event",
        "execution_mode",
        "priority",
        "handler_type",
        "handler_config",
        "scope",
        "tool_filter",
        "supported_harnesses",
        "script_content",
        "script_filename",
        "source_url",
        "source_ref",
        "source_path",
        "requirements",
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

    await commit_or_name_conflict(db, "hook")
    await db.refresh(listing)
    return HookListingResponse.model_validate(listing)


@router.post("/{listing_id}/start-edit")
async def start_edit_hook(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.trace("listing_id={}", listing_id)
    listing = await resolve_listing(HookListing, listing_id, db)
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
    ver = (await db.execute(select(HookVersion).where(HookVersion.id == ver.id).with_for_update())).scalar_one()
    acquire_edit_lock(ver, current_user.id)
    await commit_or_name_conflict(db, "hook")
    return {"status": "locked"}


@router.post("/{listing_id}/cancel-edit")
async def cancel_edit_hook(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.trace("listing_id={}", listing_id)
    listing = await resolve_listing(HookListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if get_effective_component_permission(listing, current_user) != "owner":
        raise HTTPException(status_code=403, detail="Not the listing owner")
    ver = listing.latest_version
    if not ver:
        raise HTTPException(status_code=400, detail="Listing has no version")
    release_edit_lock(ver, current_user.id)
    await commit_or_name_conflict(db, "hook")
    return {"status": "unlocked"}


@router.post("/{listing_id}/submit", response_model=HookListingResponse)
async def submit_hook_draft(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.trace("listing_id={}", listing_id)
    listing = await resolve_listing(HookListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if get_effective_component_permission(listing, current_user) != "owner":
        raise HTTPException(status_code=403, detail="Not the listing owner")
    if listing.status not in (ListingStatus.draft, ListingStatus.rejected):
        raise HTTPException(status_code=400, detail="Listing is not a draft")

    if not listing.description:
        raise HTTPException(status_code=400, detail="Description is required before submitting")

    listing.status = ListingStatus.pending
    await commit_or_name_conflict(db, "hook")
    await db.refresh(listing)
    return HookListingResponse.model_validate(listing)


@router.patch("/{listing_id}/archive")
async def archive_hook(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    return await archive_listing(HookListing, listing_id, db, current_user, "hook")


@router.patch("/{listing_id}/unarchive")
async def unarchive_hook(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    return await unarchive_listing(HookListing, listing_id, db, current_user, "hook")


# --- Version sub-routes ---
router.include_router(create_version_router("hook", HookListing, HookVersion))
