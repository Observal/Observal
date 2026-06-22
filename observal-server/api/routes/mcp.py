# SPDX-FileCopyrightText: 2026 Subramania Raja <dhanpraja231@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 Shreem Seth <shreemseth26@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from fastapi_cache.decorator import cache
from loguru import logger as optic
from sqlalchemy import delete, func, select
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
from api.routes._component_archive import archive_listing, archived_install_warning, unarchive_listing
from api.routes.component_versions import create_version_router
from api.sanitize import escape_like
from database import async_session
from models.mcp import ListingStatus, McpDownload, McpListing, McpValidationResult, McpVersion
from models.user import User, UserRole
from schemas.mcp import (
    ClientAnalysis,
    McpAnalyzeRequest,
    McpAnalyzeResponse,
    McpDraftRequest,
    McpInstallRequest,
    McpInstallResponse,
    McpListingResponse,
    McpListingSummary,
    McpSubmitRequest,
    McpUpdateRequest,
)
from services.config_generator import generate_config
from services.editing_lock import _is_lock_expired, acquire_edit_lock, release_edit_lock
from services.mcp_validator import analyze_repo, run_validation

router = APIRouter(prefix="/api/v1/mcps", tags=["mcp"])


@router.post("/analyze", response_model=McpAnalyzeResponse)
async def analyze_mcp(
    req: McpAnalyzeRequest,
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.trace("user_id={}", current_user.id)
    result = await analyze_repo(req.git_url)
    return McpAnalyzeResponse(**result)


async def _store_client_analysis(listing: McpListing, analysis: ClientAnalysis, db: AsyncSession) -> None:
    """Store validation results from client-side (CLI) analysis."""
    optic.trace("listing={}, analysis={}", listing, analysis)
    await db.execute(delete(McpValidationResult).where(McpValidationResult.listing_id == listing.id))

    has_entry = bool(analysis.entry_point or analysis.framework)
    tool_count = len(analysis.tools)
    issue_count = len(analysis.issues)

    if analysis.framework:
        listing.framework = analysis.framework
    if analysis.command and not listing.command:
        listing.command = analysis.command
    if analysis.args and not listing.args:
        listing.args = analysis.args
    if analysis.docker_image and not listing.docker_image:
        listing.docker_image = analysis.docker_image

    if has_entry:
        detail = "Client-side analysis: found entry point"
        if analysis.framework:
            detail += f" ({analysis.framework})"
        listing.mcp_validated = True
    else:
        detail = "Client-side analysis: no recognized MCP framework detected"
        listing.mcp_validated = True

    db.add(McpValidationResult(listing_id=listing.id, stage="clone_and_inspect", passed=has_entry, details=detail))

    if tool_count or issue_count:
        manifest_detail = f"Client-side analysis: {tool_count} tool(s) found"
        if analysis.issues:
            manifest_detail += "\nIssues:\n- " + "\n- ".join(analysis.issues)
        db.add(
            McpValidationResult(
                listing_id=listing.id,
                stage="manifest_validation",
                passed=issue_count == 0,
                details=manifest_detail,
            )
        )

    await commit_or_name_conflict(db, "listing")


async def _run_validation_background(listing_id: str) -> None:
    """Run validation in the background with its own DB session."""
    optic.trace("listing_id={}", listing_id)
    async with async_session() as db:
        result = await db.execute(select(McpListing).where(McpListing.id == listing_id))
        listing = result.scalar_one_or_none()
        if not listing:
            return
        try:
            await run_validation(listing, db)
        except Exception:
            optic.error("Background validation failed for listing {}", listing_id)


@router.post("/submit", response_model=McpListingResponse)
async def submit_mcp(
    req: McpSubmitRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    # Names are global. The original submitter can replace a draft, but nobody
    # can take another user's name.
    optic.debug("mcp submit: name={}", req.name)
    existing = (await db.execute(select(McpListing).where(McpListing.name == req.name))).scalars().first()
    if existing:
        if existing.submitted_by == current_user.id and existing.status != ListingStatus.approved:
            await db.delete(existing)
            await db.flush()
        else:
            raise HTTPException(status_code=409, detail=f"An approved listing named '{req.name}' already exists")

    listing = McpListing(
        name=req.name,
        category=req.category,
        owner=req.owner,
        submitted_by=current_user.id,
        owner_org_id=current_user.org_id,
    )
    db.add(listing)
    await db.flush()

    version = McpVersion(
        listing_id=listing.id,
        version=req.version,
        description=req.description,
        transport=req.transport or ("sse" if req.url and not req.command else "stdio" if req.command else None),
        framework=req.framework,
        docker_image=req.docker_image,
        command=req.command,
        args=req.args,
        url=req.url,
        headers=[h.model_dump() for h in req.headers] if req.headers else None,
        auto_approve=req.auto_approve,
        environment_variables=[ev.model_dump() for ev in req.environment_variables],
        supported_harnesses=req.supported_harnesses,
        setup_instructions=req.setup_instructions,
        changelog=req.changelog,
        source_url=req.git_url,
        status=ListingStatus.pending,
        released_by=current_user.id,
        released_at=datetime.now(UTC),
    )
    db.add(version)
    await db.flush()

    listing.latest_version_id = version.id
    await commit_or_name_conflict(db, "listing")
    await db.refresh(listing)

    if req.client_analysis:
        # CLI already cloned and analyzed locally - store results directly
        await _store_client_analysis(listing, req.client_analysis, db)
    elif req.git_url:
        # Only run background validation if we have a git URL to clone
        background_tasks.add_task(_run_validation_background, str(listing.id))
    # Direct config submissions (no git_url) skip validation - config is user-provided
    return McpListingResponse.model_validate(listing)


@router.get("", response_model=list[McpListingSummary])
@cache(expire=ds.get_sync_int("data.cache_ttl_registry", 30), namespace="registry")
async def list_mcps(
    response: Response,
    category: str | None = Query(None),
    search: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_current_user),
):
    optic.debug("mcp list: search={}", search)
    stmt = (
        select(McpListing)
        .join(McpVersion, McpListing.latest_version_id == McpVersion.id)
        .where(McpVersion.status == ListingStatus.approved)
    )
    if category:
        stmt = stmt.where(McpListing.category == category)
    if search:
        safe = escape_like(search)
        stmt = stmt.where(McpListing.name.ilike(f"%{safe}%") | McpVersion.description.ilike(f"%{safe}%"))
    stmt = apply_visibility_filter(stmt, McpListing, current_user)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(stmt.order_by(McpListing.created_at.desc()).limit(limit).offset(offset))
    listings = [McpListingSummary.model_validate(r) for r in result.scalars().all()]
    response.headers["X-Total-Count"] = str(total or 0)
    return listings


@router.get("/my", response_model=list[McpListingSummary])
async def my_mcps(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.debug("my_mcps called")
    stmt = select(McpListing).where(McpListing.submitted_by == current_user.id).order_by(McpListing.created_at.desc())
    result = await db.execute(stmt)
    listings = [McpListingSummary.model_validate(r) for r in result.scalars().all()]
    return listings


@router.get("/{listing_id}", response_model=McpListingResponse)
async def get_mcp(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_current_user),
):
    optic.debug("mcp get: listing_id={}", listing_id)
    listing = await resolve_listing(McpListing, listing_id, db, require_status=ListingStatus.approved)
    if listing:
        resp = McpListingResponse.model_validate(listing)
        resp.user_permission = get_effective_component_permission(listing, current_user)
        return resp

    listing = await resolve_listing(McpListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    if check_listing_visibility(listing, current_user):
        resp = McpListingResponse.model_validate(listing)
        resp.user_permission = get_effective_component_permission(listing, current_user)
        return resp

    raise HTTPException(status_code=404, detail="Listing not found")


@router.post("/{listing_id}/install", response_model=McpInstallResponse)
async def install_mcp(
    listing_id: str,
    req: McpInstallRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.debug("mcp install: listing_id={}", listing_id)
    listing = await resolve_listing(McpListing, listing_id, db, require_status=ListingStatus.approved)
    if not listing:
        listing = await resolve_listing(McpListing, listing_id, db)
        if not listing or not check_listing_visibility(listing, current_user):
            raise HTTPException(status_code=404, detail="Listing not found or not approved")
        if (
            listing.status != ListingStatus.archived
            and get_effective_component_permission(listing, current_user) != "owner"
        ):
            raise HTTPException(status_code=404, detail="Listing not found or not approved")

    warnings = []
    if listing.status == ListingStatus.archived:
        warnings.append(archived_install_warning("MCP", listing.name))

    db.add(McpDownload(listing_id=listing.id, user_id=current_user.id, harness=req.harness))
    latest_version = getattr(listing, "latest_version", None)
    if latest_version:
        latest_version.download_count += 1
    await commit_or_name_conflict(db, "listing")

    from api.routes.config import derive_endpoints

    endpoints = await derive_endpoints(request)
    snippet = generate_config(
        listing,
        req.harness,
        observal_url=endpoints["api"],
        env_values=req.env_values,
        header_values=req.header_values,
    )
    return McpInstallResponse(listing_id=listing.id, harness=req.harness, config_snippet=snippet, warnings=warnings)


@router.post("/draft", response_model=McpListingResponse)
async def save_mcp_draft(
    req: McpDraftRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.trace("req={}", req)
    listing = McpListing(
        name=req.name,
        category=req.category,
        owner=req.owner or current_user.username or current_user.email,
        submitted_by=current_user.id,
        owner_org_id=current_user.org_id,
    )
    db.add(listing)
    await db.flush()

    version = McpVersion(
        listing_id=listing.id,
        version=req.version,
        description=req.description,
        transport=req.transport or ("sse" if req.url and not req.command else "stdio" if req.command else None),
        framework=req.framework,
        docker_image=req.docker_image,
        command=req.command,
        args=req.args,
        url=req.url,
        headers=[h.model_dump() for h in req.headers] if req.headers else None,
        auto_approve=req.auto_approve,
        environment_variables=[ev.model_dump() for ev in req.environment_variables],
        supported_harnesses=req.supported_harnesses,
        setup_instructions=req.setup_instructions,
        changelog=req.changelog,
        source_url=req.git_url,
        status=ListingStatus.draft,
        released_by=current_user.id,
        released_at=datetime.now(UTC),
    )
    db.add(version)
    await db.flush()

    listing.latest_version_id = version.id
    await commit_or_name_conflict(db, "listing")
    await db.refresh(listing)
    return McpListingResponse.model_validate(listing)


@router.put("/{listing_id}/draft", response_model=McpListingResponse)
async def update_mcp_draft(
    listing_id: str,
    req: McpUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.trace("listing_id={}", listing_id)
    listing = await resolve_listing(McpListing, listing_id, db)
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
        "framework",
        "docker_image",
        "command",
        "args",
        "url",
        "auto_approve",
        "transport",
        "supported_harnesses",
        "setup_instructions",
        "changelog",
    ):
        val = getattr(req, field)
        if val is not None:
            setattr(ver, field, val)

    if req.git_url is not None:
        ver.source_url = req.git_url
    if req.headers is not None:
        ver.headers = [h.model_dump() for h in req.headers]
    if req.environment_variables is not None:
        ver.environment_variables = [ev.model_dump() for ev in req.environment_variables]

    # Don't allow saving over another user's active lock
    if ver.is_editing and ver.editing_by != current_user.id and not _is_lock_expired(ver.editing_since):
        raise HTTPException(
            status_code=409,
            detail="This item is currently being edited by another user. Please try again later.",
        )
    release_edit_lock(ver, current_user.id, force=True)
    await db.flush()

    for field in ("name", "category", "owner"):
        val = getattr(req, field)
        if val is not None:
            setattr(listing, field, val)

    await commit_or_name_conflict(db, "listing")
    await db.refresh(listing)
    return McpListingResponse.model_validate(listing)


@router.post("/{listing_id}/start-edit")
async def start_edit_mcp(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.trace("listing_id={}", listing_id)
    listing = await resolve_listing(McpListing, listing_id, db)
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
    ver = (await db.execute(select(McpVersion).where(McpVersion.id == ver.id).with_for_update())).scalar_one()
    acquire_edit_lock(ver, current_user.id)
    await commit_or_name_conflict(db, "listing")
    return {"status": "locked"}


@router.post("/{listing_id}/cancel-edit")
async def cancel_edit_mcp(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.trace("listing_id={}", listing_id)
    listing = await resolve_listing(McpListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if get_effective_component_permission(listing, current_user) != "owner":
        raise HTTPException(status_code=403, detail="Not the listing owner")
    ver = listing.latest_version
    if not ver:
        raise HTTPException(status_code=400, detail="Listing has no version")
    release_edit_lock(ver, current_user.id)
    await commit_or_name_conflict(db, "listing")
    return {"status": "unlocked"}


@router.post("/{listing_id}/submit", response_model=McpListingResponse)
async def submit_mcp_draft(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.trace("listing_id={}", listing_id)
    listing = await resolve_listing(McpListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if get_effective_component_permission(listing, current_user) != "owner":
        raise HTTPException(status_code=403, detail="Not the listing owner")
    if listing.status not in (ListingStatus.draft, ListingStatus.rejected):
        raise HTTPException(status_code=400, detail="Listing is not a draft")

    if not listing.description:
        raise HTTPException(status_code=400, detail="Description is required before submitting")
    if not listing.git_url and not listing.command and not listing.url:
        raise HTTPException(status_code=400, detail="At least one of git_url, command, or url is required")

    listing.status = ListingStatus.pending
    await commit_or_name_conflict(db, "listing")
    await db.refresh(listing)
    return McpListingResponse.model_validate(listing)


@router.patch("/{listing_id}/archive")
async def archive_mcp(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    return await archive_listing(McpListing, listing_id, db, current_user, "listing")


@router.patch("/{listing_id}/unarchive")
async def unarchive_mcp(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    return await unarchive_listing(McpListing, listing_id, db, current_user, "listing")


@router.delete("/{listing_id}")
async def delete_mcp(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.debug("mcp delete: listing_id={}", listing_id)
    from models.feedback import Feedback

    listing = await resolve_listing(McpListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    is_admin = ROLE_HIERARCHY.get(current_user.role, 999) <= ROLE_HIERARCHY[UserRole.admin]
    if get_effective_component_permission(listing, current_user) != "owner":
        raise HTTPException(status_code=403, detail="Not authorized")
    if listing.status == ListingStatus.approved and not is_admin:
        raise HTTPException(status_code=400, detail="Cannot delete an approved listing. Contact an admin.")

    for r in (
        (await db.execute(select(Feedback).where(Feedback.listing_id == listing.id, Feedback.listing_type == "mcp")))
        .scalars()
        .all()
    ):
        await db.delete(r)
    for r in (await db.execute(select(McpDownload).where(McpDownload.listing_id == listing.id))).scalars().all():
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
    await commit_or_name_conflict(db, "listing")
    return {"deleted": str(listing_id)}


# --- Version sub-routes ---
router.include_router(create_version_router("mcp", McpListing, McpVersion))
