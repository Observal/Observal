# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 Shreem Seth <shreemseth26@gmail.com>
# SPDX-FileCopyrightText: 2026 tsitu0 <tomsitu0102@gmail.com>
# SPDX-License-Identifier: Apache-2.0

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from loguru import logger as optic
from sqlalchemy import String, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import (
    apply_registry_scope,
    commit_or_name_conflict,
    get_db,
    get_effective_component_permission,
    may_view_unapproved,
    optional_current_user,
    require_role,
    resolve_listing,
    resolve_visible_listing,
)
from api.routes._component_archive import archive_listing, archived_install_warning, unarchive_listing
from api.routes.component_versions import create_version_router
from api.sanitize import escape_like
from api.search import keyword_search
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
from services.registry_namespace import identity_exists
from services.skill_validator import SkillValidationError, validate_skill_md, validate_skill_md_content_frontmatter
from services.teamspace import publish_auto_approves_for_entity, resolve_publish_target

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

    target = await resolve_publish_target(
        db,
        current_user,
        name,
        team_id=req.team_id,
        visibility=req.visibility,
    )
    if await identity_exists(db, SkillListing, target.namespace, target.slug):
        raise HTTPException(status_code=409, detail=f"Skill '{target.namespace}/{target.slug}' already exists")

    listing = SkillListing(
        name=name,
        namespace=target.namespace,
        slug=target.slug,
        owner=target.owner if target.team_id else req.owner,
        submitted_by=current_user.id,
        team_id=target.team_id,
        is_private=target.visibility == "team",
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
        supported_harnesses=req.supported_harnesses,
        status=ListingStatus.approved if target.auto_approve else ListingStatus.pending,
        released_by=current_user.id,
        released_at=datetime.now(UTC),
        reviewed_by=current_user.id if target.auto_approve else None,
        reviewed_at=datetime.now(UTC) if target.auto_approve else None,
    )
    db.add(version)
    await db.flush()

    listing.latest_version_id = version.id
    await commit_or_name_conflict(db, "skill")
    await db.refresh(listing)
    return SkillListingResponse.model_validate(listing)


@router.get("", response_model=list[SkillListingSummary])
async def list_skills(
    response: Response,
    task_type: str | None = Query(None),
    target_agent: str | None = Query(None),
    harness: str | None = Query(None),
    namespace: str | None = Query(None),
    search: str | None = Query(None),
    team_id: uuid.UUID | None = Query(None, description="Only listings owned by this teamspace"),
    composable_for_team_id: uuid.UUID | None = Query(
        None, description="Public listings plus this teamspace's private ones, for agent composition"
    ),
    public_only: bool = Query(False),
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
    if harness:
        stmt = stmt.where(cast(SkillVersion.supported_harnesses, String).ilike(f'%"{escape_like(harness)}"%'))
    if namespace:
        stmt = stmt.where(SkillListing.namespace == namespace.strip().lower())
    target_agents_text = cast(SkillVersion.target_agents, String)
    if target_agent:
        target_filter, _ = keyword_search(target_agent, [target_agents_text])
        if target_filter is not None:
            stmt = stmt.where(target_filter)
    search_rank = None
    if search:
        search_filter, search_rank = keyword_search(
            search,
            [
                SkillListing.name,
                SkillListing.slug,
                SkillListing.namespace,
                SkillListing.owner,
                SkillVersion.description,
                SkillVersion.task_type,
                SkillVersion.skill_path,
                SkillVersion.slash_command,
                SkillVersion.git_url,
                SkillVersion.skill_md_content,
                SkillVersion.delivery_mode,
                target_agents_text,
                cast(SkillVersion.supported_harnesses, String),
            ],
            name_field=SkillListing.name,
        )
        if search_filter is not None:
            stmt = stmt.where(search_filter)
    stmt = apply_registry_scope(
        stmt,
        SkillListing,
        current_user,
        team_id=team_id,
        composable_for_team_id=composable_for_team_id,
        public_only=public_only,
    )
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    order_by = [SkillListing.created_at.desc()]
    if search_rank is not None:
        order_by.insert(0, search_rank.desc())
    result = await db.execute(stmt.order_by(*order_by).limit(limit).offset(offset))
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
    listing = await resolve_visible_listing(
        SkillListing, listing_id, db, current_user, require_status=ListingStatus.approved
    )
    if listing is None:
        listing = await resolve_visible_listing(SkillListing, listing_id, db, current_user)
        may_view = listing is not None and may_view_unapproved(
            get_effective_component_permission(listing, current_user), current_user
        )
        if not may_view:
            raise HTTPException(status_code=404, detail="Listing not found")
    resp = SkillListingResponse.model_validate(listing)
    resp.user_permission = get_effective_component_permission(listing, current_user)
    return resp


@router.post("/{listing_id}/install", response_model=SkillInstallResponse)
async def install_skill(
    listing_id: str,
    req: SkillInstallRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.debug("installing skill {}", listing_id)
    listing = await resolve_visible_listing(
        SkillListing, listing_id, db, current_user, require_status=ListingStatus.approved
    )
    if not listing:
        listing = await resolve_visible_listing(SkillListing, listing_id, db, current_user)
        if not listing:
            raise HTTPException(status_code=404, detail="Listing not found or not approved")
        if (
            listing.status != ListingStatus.archived
            and get_effective_component_permission(listing, current_user) != "owner"
        ):
            raise HTTPException(status_code=404, detail="Listing not found or not approved")

    warnings = []
    if listing.status == ListingStatus.archived:
        warnings.append(archived_install_warning("skill", listing.name))

    # Resolve specific version if requested
    version_override = None
    if req.version:
        from models.skill import SkillVersion

        ver_stmt = select(SkillVersion).where(
            SkillVersion.listing_id == listing.id,
            SkillVersion.version == req.version,
            SkillVersion.status.in_([ListingStatus.approved, listing.status]),
        )
        ver_result = await db.execute(ver_stmt)
        version_override = ver_result.scalar_one_or_none()
        if not version_override:
            raise HTTPException(
                status_code=404,
                detail=f"Version {req.version!r} not found for this skill",
            )

    db.add(SkillDownload(listing_id=listing.id, user_id=current_user.id, harness=req.harness))
    latest_version = getattr(listing, "latest_version", None)
    if latest_version:
        latest_version.download_count += 1
    await commit_or_name_conflict(db, "skill")

    from api.routes.config import derive_endpoints
    from services.skill_config_generator import generate_skill_config

    endpoints = await derive_endpoints(request)
    config = generate_skill_config(
        listing,
        req.harness,
        server_url=endpoints["api"],
        scope=req.scope,
        version_override=version_override,
        local_name=req.local_name,
    )
    return SkillInstallResponse(listing_id=listing.id, harness=req.harness, config_snippet=config, warnings=warnings)


@router.post("/draft", response_model=SkillListingResponse)
async def save_skill_draft(
    req: SkillDraftRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.trace("req={}", req)
    content_analysis = _validate_stored_skill_md(req.skill_md_content, req.slash_command)
    slash_command = content_analysis.slash_command

    target = await resolve_publish_target(
        db,
        current_user,
        req.name,
        team_id=req.team_id,
        visibility=req.visibility,
    )
    if await identity_exists(db, SkillListing, target.namespace, target.slug):
        raise HTTPException(status_code=409, detail=f"Skill '{target.namespace}/{target.slug}' already exists")
    listing = SkillListing(
        name=req.name,
        namespace=target.namespace,
        slug=target.slug,
        owner=target.owner if target.team_id else (req.owner or current_user.username or current_user.email),
        submitted_by=current_user.id,
        team_id=target.team_id,
        is_private=target.visibility == "team",
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
        supported_harnesses=req.supported_harnesses,
        status=ListingStatus.draft,
        released_by=current_user.id,
        released_at=datetime.now(UTC),
    )
    db.add(version)
    await db.flush()

    listing.latest_version_id = version.id
    await commit_or_name_conflict(db, "skill")
    await db.refresh(listing)
    return SkillListingResponse.model_validate(listing)


def _reject_visibility_edits(listing, req) -> None:
    """Refuse teamspace or visibility changes sent to the draft update route.

    Visibility has exactly one authoritative path, PATCH /api/v1/registry/skill/{listing_id}/visibility,
    which authorizes team owners and reviewers, writes audit metadata, and blocks privatizing a
    component that an approved public agent depends on. Accepting these fields here would either
    silently discard them or fork that policy into a weaker second implementation, so a real change
    is rejected. A request that repeats the values the listing already holds changes nothing and passes.
    """
    if req.team_id is not None and req.team_id != listing.team_id:
        raise HTTPException(
            status_code=400,
            detail="team_id cannot be changed here. A listing stays in the teamspace it was created under.",
        )
    if req.visibility is not None and req.visibility != listing.visibility:
        raise HTTPException(
            status_code=400,
            detail=f"visibility cannot be changed here. Use PATCH /api/v1/registry/skill/{listing.id}/visibility.",
        )


@router.put("/{listing_id}/draft", response_model=SkillListingResponse)
async def update_skill_draft(
    listing_id: str,
    req: SkillUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.trace("listing_id={}", listing_id)
    listing = await resolve_listing(SkillListing, listing_id, db, current_user=current_user)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if get_effective_component_permission(listing, current_user) != "owner":
        raise HTTPException(status_code=403, detail="Not the listing owner")
    if listing.status not in (ListingStatus.draft, ListingStatus.rejected, ListingStatus.pending):
        raise HTTPException(status_code=400, detail="Only draft, rejected, or pending listings can be edited")
    _reject_visibility_edits(listing, req)

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
        "supported_harnesses",
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

    await commit_or_name_conflict(db, "skill")
    await db.refresh(listing)
    return SkillListingResponse.model_validate(listing)


@router.post("/{listing_id}/start-edit")
async def start_edit_skill(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.trace("listing_id={}", listing_id)
    listing = await resolve_listing(SkillListing, listing_id, db, current_user=current_user)
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
    await commit_or_name_conflict(db, "skill")
    return {"status": "locked"}


@router.post("/{listing_id}/cancel-edit")
async def cancel_edit_skill(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.trace("listing_id={}", listing_id)
    listing = await resolve_listing(SkillListing, listing_id, db, current_user=current_user)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if get_effective_component_permission(listing, current_user) != "owner":
        raise HTTPException(status_code=403, detail="Not the listing owner")
    ver = listing.latest_version
    if not ver:
        raise HTTPException(status_code=400, detail="Listing has no version")
    release_edit_lock(ver, current_user.id)
    await commit_or_name_conflict(db, "skill")
    return {"status": "unlocked"}


@router.post("/{listing_id}/submit", response_model=SkillListingResponse)
async def submit_skill_draft(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.trace("listing_id={}", listing_id)
    listing = await resolve_listing(SkillListing, listing_id, db, current_user=current_user)
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

    if await publish_auto_approves_for_entity(listing, current_user, db):
        listing.status = ListingStatus.approved
        listing.latest_version.reviewed_by = current_user.id
        listing.latest_version.reviewed_at = datetime.now(UTC)
    else:
        listing.status = ListingStatus.pending
    await commit_or_name_conflict(db, "skill")
    await db.refresh(listing)
    return SkillListingResponse.model_validate(listing)


@router.patch("/{listing_id}/archive")
async def archive_skill(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    return await archive_listing(SkillListing, listing_id, db, current_user, "skill")


@router.patch("/{listing_id}/unarchive")
async def unarchive_skill(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    return await unarchive_listing(SkillListing, listing_id, db, current_user, "skill")


# --- Version sub-routes ---
router.include_router(create_version_router("skill", SkillListing, SkillVersion))
