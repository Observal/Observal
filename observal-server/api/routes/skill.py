# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 Shreem Seth <shreemseth26@gmail.com>
# SPDX-FileCopyrightText: 2026 tsitu0 <tomsitu0102@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi_cache.decorator import cache
from loguru import logger as optic
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import services.dynamic_settings as ds
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
from models.mcp import ListingStatus
from models.skill import SkillDownload, SkillListing, SkillVersion
from models.user import User, UserRole
from schemas.skill import (
    SkillDraftRequest,
    SkillInstallRequest,
    SkillInstallResponse,
    SkillListingResponse,
    SkillListingSummary,
    SkillSubmitRequest,
    SkillUpdateRequest,
)
from schemas.skill_commands import normalize_slash_command
from services.editing_lock import _is_lock_expired, acquire_edit_lock, release_edit_lock
from services.skill_validator import SkillValidationError, validate_skill_md, validate_skill_md_content_frontmatter

router = APIRouter(prefix="/api/v1/skills", tags=["skills"])


def _validate_stored_skill_md(skill_md_content: str | None, slash_command: str | None = None):
    try:
        return validate_skill_md_content_frontmatter(skill_md_content, slash_command=slash_command)
    except SkillValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/submit", response_model=SkillListingResponse)
async def submit_skill(
    req: SkillSubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.debug("submitting skill: {}", req.name)
    existing = await db.execute(
        select(SkillListing).where(SkillListing.name == req.name, SkillListing.submitted_by == current_user.id)
    )
    if existing.scalars().first():
        raise HTTPException(status_code=409, detail=f"You already have a skill named '{req.name}'")

    # Resolve name/description/slash_command - frontmatter wins when caller omits them.
    skill_md_content = req.skill_md_content
    validated = False
    name = req.name
    description = req.description
    slash_command = req.slash_command
    skill_path = req.skill_path
    delivery_mode = req.delivery_mode or "git_fetch"
    script_content = req.script_content
    script_filename = req.script_filename

    if delivery_mode == "registry_direct":
        # Registry direct: skill_md_content is required, no git validation
        if not skill_md_content:
            raise HTTPException(status_code=422, detail="skill_md_content is required for registry_direct delivery")
        content_analysis = _validate_stored_skill_md(skill_md_content, slash_command)
        fm = content_analysis.frontmatter
        if fm:
            fm_name = fm.get("name")
            fm_description = fm.get("description")
            if isinstance(fm_name, str) and not name:
                name = fm_name
            if isinstance(fm_description, str) and not description:
                description = fm_description
            if content_analysis.slash_command is not None:
                slash_command = content_analysis.slash_command
        validated = True  # Content is inline, no need to fetch from git
    elif req.git_url:
        try:
            analysis = await validate_skill_md(
                req.git_url,
                skill_path=req.skill_path,
                git_ref=req.git_ref or "main",
            )
            validated = True
            skill_md_content = skill_md_content or analysis.raw_content
            # Use discovered path if server auto-found it (user left skill_path as "/")
            if analysis.discovered_path:
                skill_path = analysis.discovered_path
            if not name:
                name = analysis.name
            if not description:
                description = analysis.description
            if slash_command is None:
                slash_command = analysis.slash_command
            elif analysis.slash_command is not None and slash_command != analysis.slash_command:
                raise HTTPException(status_code=422, detail="slash_command does not match SKILL.md frontmatter command")
        except SkillValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    if skill_md_content:
        content_analysis = _validate_stored_skill_md(skill_md_content, slash_command)
        if content_analysis.slash_command is not None:
            slash_command = content_analysis.slash_command

    if not name:
        raise HTTPException(status_code=422, detail="name is required")
    if not description:
        raise HTTPException(status_code=422, detail="description is required")
    try:
        slash_command = normalize_slash_command(slash_command)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid slash_command: {exc}") from exc

    # Re-check uniqueness with resolved name (may differ from req.name when auto-filled).
    if name != req.name:
        dup = await db.execute(
            select(SkillListing).where(SkillListing.name == name, SkillListing.submitted_by == current_user.id)
        )
        if dup.scalars().first():
            raise HTTPException(status_code=409, detail=f"You already have a skill named '{name}'")

    listing = SkillListing(
        name=name,
        owner=req.owner,
        submitted_by=current_user.id,
        owner_org_id=current_user.org_id,
    )
    db.add(listing)
    await db.flush()

    version = SkillVersion(
        listing_id=listing.id,
        version=req.version,
        description=description,
        skill_path=skill_path,
        git_url=req.git_url,
        git_ref=req.git_ref,
        skill_md_content=skill_md_content,
        delivery_mode=delivery_mode,
        script_content=script_content,
        script_filename=script_filename,
        validated=validated,
        target_agents=req.target_agents,
        task_type=req.task_type,
        slash_command=slash_command,
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
    return SkillListingResponse.model_validate(listing)


@router.get("", response_model=list[SkillListingSummary])
@cache(expire=ds.get_sync_int("data.cache_ttl_registry", 30), namespace="registry")
async def list_skills(
    response: Response,
    task_type: str | None = Query(None),
    target_agent: str | None = Query(None),
    search: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_current_user),
):
    optic.debug("listing skills (task_type={}, search={})", task_type, search)
    stmt = (
        select(SkillListing)
        .join(SkillVersion, SkillListing.latest_version_id == SkillVersion.id)
        .where(SkillVersion.status == ListingStatus.approved)
    )
    if task_type:
        stmt = stmt.where(SkillVersion.task_type == task_type)
    if target_agent:
        stmt = stmt.where(SkillVersion.target_agents.cast(str).ilike(f"%{escape_like(target_agent)}%"))
    if search:
        safe = escape_like(search)
        stmt = stmt.where(SkillListing.name.ilike(f"%{safe}%") | SkillVersion.description.ilike(f"%{safe}%"))
    stmt = apply_visibility_filter(stmt, SkillListing, current_user)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(stmt.order_by(SkillListing.created_at.desc()).limit(limit).offset(offset))
    listings = [SkillListingSummary.model_validate(r) for r in result.scalars().all()]
    response.headers["X-Total-Count"] = str(total or 0)
    return listings


@router.get("/my", response_model=list[SkillListingSummary])
async def my_skills(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.debug("my_skills called")
    stmt = (
        select(SkillListing)
        .where(SkillListing.submitted_by == current_user.id)
        .order_by(SkillListing.created_at.desc())
    )
    result = await db.execute(stmt)
    listings = [SkillListingSummary.model_validate(r) for r in result.scalars().all()]
    return listings


@router.get("/{listing_id}", response_model=SkillListingResponse)
async def get_skill(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_current_user),
):
    optic.debug("fetching skill {}", listing_id)
    listing = await resolve_listing(SkillListing, listing_id, db, require_status=ListingStatus.approved)
    if listing:
        resp = SkillListingResponse.model_validate(listing)
        resp.user_permission = get_effective_component_permission(listing, current_user)
        return resp

    listing = await resolve_listing(SkillListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    if check_listing_visibility(listing, current_user):
        resp = SkillListingResponse.model_validate(listing)
        resp.user_permission = get_effective_component_permission(listing, current_user)
        return resp

    raise HTTPException(status_code=404, detail="Listing not found")


@router.post("/{listing_id}/install", response_model=SkillInstallResponse)
async def install_skill(
    listing_id: str,
    req: SkillInstallRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.debug("installing skill {}", listing_id)
    listing = await resolve_listing(SkillListing, listing_id, db, require_status=ListingStatus.approved)
    if not listing:
        listing = await resolve_listing(SkillListing, listing_id, db)
        if not listing or get_effective_component_permission(listing, current_user) != "owner":
            raise HTTPException(status_code=404, detail="Listing not found or not approved")

    # Resolve specific version if requested
    version_override = None
    if req.version:
        from models.skill import SkillVersion

        ver_stmt = select(SkillVersion).where(
            SkillVersion.listing_id == listing.id,
            SkillVersion.version == req.version,
            SkillVersion.status == "approved",
        )
        ver_result = await db.execute(ver_stmt)
        version_override = ver_result.scalar_one_or_none()
        if not version_override:
            raise HTTPException(
                status_code=404,
                detail=f"Version {req.version!r} not found for this skill",
            )

    db.add(SkillDownload(listing_id=listing.id, user_id=current_user.id, ide=req.ide))
    await db.commit()

    from api.routes.config import derive_endpoints
    from services.skill_config_generator import generate_skill_config

    endpoints = await derive_endpoints(request)
    config = generate_skill_config(
        listing,
        req.ide,
        server_url=endpoints["api"],
        scope=req.scope,
        version_override=version_override,
    )
    return SkillInstallResponse(listing_id=listing.id, ide=req.ide, config_snippet=config)


@router.post("/draft", response_model=SkillListingResponse)
async def save_skill_draft(
    req: SkillDraftRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.trace("req={}", req)
    content_analysis = _validate_stored_skill_md(req.skill_md_content, req.slash_command)
    slash_command = content_analysis.slash_command

    listing = SkillListing(
        name=req.name,
        owner=req.owner or current_user.username or current_user.email,
        submitted_by=current_user.id,
        owner_org_id=current_user.org_id,
    )
    db.add(listing)
    await db.flush()

    version = SkillVersion(
        listing_id=listing.id,
        version=req.version,
        description=req.description,
        skill_path=req.skill_path,
        git_url=req.git_url,
        git_ref=req.git_ref,
        skill_md_content=req.skill_md_content,
        delivery_mode=req.delivery_mode or "git_fetch",
        script_content=req.script_content,
        script_filename=req.script_filename,
        target_agents=req.target_agents,
        task_type=req.task_type,
        slash_command=slash_command,
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
    return SkillListingResponse.model_validate(listing)


@router.put("/{listing_id}/draft", response_model=SkillListingResponse)
async def update_skill_draft(
    listing_id: str,
    req: SkillUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.trace("listing_id={}", listing_id)
    listing = await resolve_listing(SkillListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if get_effective_component_permission(listing, current_user) != "owner":
        raise HTTPException(status_code=403, detail="Not the listing owner")
    if listing.status not in (ListingStatus.draft, ListingStatus.rejected, ListingStatus.pending):
        raise HTTPException(status_code=400, detail="Only draft, rejected, or pending listings can be edited")

    ver = listing.latest_version
    if not ver:
        raise HTTPException(status_code=400, detail="Listing has no version to update")

    slash_command_should_update = "slash_command" in req.model_fields_set
    slash_command_explicit_clear = slash_command_should_update and req.slash_command is None
    slash_command = req.slash_command if slash_command_should_update else None
    if req.skill_md_content is not None:
        content_analysis = _validate_stored_skill_md(req.skill_md_content, slash_command)
        if content_analysis.slash_command is not None and not slash_command_explicit_clear:
            slash_command = content_analysis.slash_command
            slash_command_should_update = True
    elif slash_command_should_update:
        content_analysis = _validate_stored_skill_md(ver.skill_md_content, slash_command)
        if not slash_command_explicit_clear:
            slash_command = content_analysis.slash_command

    for field in (
        "version",
        "description",
        "skill_path",
        "git_url",
        "git_ref",
        "skill_md_content",
        "delivery_mode",
        "script_content",
        "script_filename",
        "target_agents",
        "task_type",
        "supported_ides",
    ):
        val = getattr(req, field)
        if val is not None:
            setattr(ver, field, val)

    if slash_command_should_update:
        ver.slash_command = slash_command

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
    return SkillListingResponse.model_validate(listing)


@router.post("/{listing_id}/start-edit")
async def start_edit_skill(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.trace("listing_id={}", listing_id)
    listing = await resolve_listing(SkillListing, listing_id, db)
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
    ver = (await db.execute(select(SkillVersion).where(SkillVersion.id == ver.id).with_for_update())).scalar_one()
    acquire_edit_lock(ver, current_user.id)
    await db.commit()
    return {"status": "locked"}


@router.post("/{listing_id}/cancel-edit")
async def cancel_edit_skill(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.trace("listing_id={}", listing_id)
    listing = await resolve_listing(SkillListing, listing_id, db)
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


@router.post("/{listing_id}/submit", response_model=SkillListingResponse)
async def submit_skill_draft(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.trace("listing_id={}", listing_id)
    listing = await resolve_listing(SkillListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if get_effective_component_permission(listing, current_user) != "owner":
        raise HTTPException(status_code=403, detail="Not the listing owner")
    if listing.status not in (ListingStatus.draft, ListingStatus.rejected):
        raise HTTPException(status_code=400, detail="Listing is not a draft")

    ver = listing.latest_version
    if not ver:
        raise HTTPException(status_code=400, detail="Listing has no version")
    content_analysis = _validate_stored_skill_md(ver.skill_md_content, ver.slash_command)
    if content_analysis.slash_command is not None:
        ver.slash_command = content_analysis.slash_command

    if not listing.description:
        raise HTTPException(status_code=400, detail="Description is required before submitting")

    listing.status = ListingStatus.pending
    await db.commit()
    await db.refresh(listing)
    return SkillListingResponse.model_validate(listing)


@router.delete("/{listing_id}")
async def delete_skill(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.debug("deleting skill {}", listing_id)
    listing = await resolve_listing(SkillListing, listing_id, db)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    is_admin = ROLE_HIERARCHY.get(current_user.role, 999) <= ROLE_HIERARCHY[UserRole.admin]
    if get_effective_component_permission(listing, current_user) != "owner":
        raise HTTPException(status_code=403, detail="Not authorized")
    if listing.status == ListingStatus.approved and not is_admin:
        raise HTTPException(status_code=400, detail="Cannot delete an approved listing. Contact an admin.")

    for r in (await db.execute(select(SkillDownload).where(SkillDownload.listing_id == listing.id))).scalars().all():
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
router.include_router(create_version_router("skill", SkillListing, SkillVersion))
