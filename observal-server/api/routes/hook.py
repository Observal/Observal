# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 Shreem Seth <shreemseth26@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from loguru import logger as optic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import (
    ROLE_HIERARCHY,
    apply_visibility_filter,
    check_listing_visibility,
    get_db,
    get_effective_component_permission,
    optional_current_user,
    require_role,
    resolve_listing,
)
from api.routes.component_versions import create_version_router
from api.sanitize import escape_like
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
    existing = await db.execute(
        select(HookListing).where(HookListing.name == req.name, HookListing.submitted_by == current_user.id)
    )
    if existing.scalars().first():
        raise HTTPException(status_code=409, detail=f"You already have a hook named '{req.name}'")

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
        supported_ides=req.supported_ides,
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
    await db.commit()
    await db.refresh(listing)
    return HookListingResponse.model_validate(listing)


@router.get("", response_model=list[HookListingSummary])
async def list_hooks(
    event: str | None = Query(None),
    scope: str | None = Query(None),
    search: str | None = Query(None),
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
    if search:
        safe = escape_like(search)
        stmt = stmt.where(HookListing.name.ilike(f"%{safe}%") | HookVersion.description.ilike(f"%{safe}%"))
    stmt = apply_visibility_filter(stmt, HookListing, current_user)
    result = await db.execute(stmt.order_by(HookListing.created_at.desc()))
    listings = [HookListingSummary.model_validate(r) for r in result.scalars().all()]
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
        if not listing or get_effective_component_permission(listing, current_user) != "owner":
            raise HTTPException(status_code=404, detail="Listing not found or not approved")

    db.add(HookDownload(listing_id=listing.id, user_id=current_user.id, ide=req.ide))
    await db.commit()

    from services.hook_install_generator import generate_hook_install_config

    result = generate_hook_install_config(listing, req.ide)
    return HookInstallResponse(
        listing_id=listing.id,
        ide=req.ide,
        config_snippet=result.get("config_snippet", {}),
        config_path=result.get("config_path", ""),
        files=[HookFileEntry(**f) for f in result.get("files", [])],
        requirements=result.get("requirements", []),
        source_fetch=result.get("source_fetch"),
        notes=result.get("notes", []),
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
        supported_ides=req.supported_ides,
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
    await db.commit()
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
        "supported_ides",
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

    await db.commit()
    await db.refresh(listing)
    if listing.status == ListingStatus.pending or listing.status == ListingStatus.rejected:
        pass
    else:
        pass
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
    await db.commit()
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
    await db.commit()
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
    await db.commit()
    await db.refresh(listing)
    return HookListingResponse.model_validate(listing)


@router.delete("/{listing_id}")
async def delete_hook(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.debug("hook delete: listing_id={}", listing_id)
    listing = await resolve_listing(HookListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    is_admin = ROLE_HIERARCHY.get(current_user.role, 999) <= ROLE_HIERARCHY[UserRole.admin]
    if get_effective_component_permission(listing, current_user) != "owner":
        raise HTTPException(status_code=403, detail="Not authorized")
    if listing.status == ListingStatus.approved and not is_admin:
        raise HTTPException(status_code=400, detail="Cannot delete an approved listing. Contact an admin.")

    for r in (await db.execute(select(HookDownload).where(HookDownload.listing_id == listing.id))).scalars().all():
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
    await db.commit()
    return {"deleted": str(listing_id)}


# --- Version sub-routes ---
router.include_router(create_version_router("hook", HookListing, HookVersion))
