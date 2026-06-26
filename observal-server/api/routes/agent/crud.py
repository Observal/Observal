# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Agent CRUD routes: create, list, get, update, delete, archive, unarchive."""

import uuid  # noqa: TC003
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Query, Response
from loguru import logger as optic
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import (
    ROLE_HIERARCHY,
    get_db,
    get_effective_agent_permission,
    require_role,
)
from api.sanitize import escape_like
from models.agent import (
    Agent,
    AgentStatus,
    AgentVersion,
)
from models.agent_component import AgentComponent
from models.skill import SkillListing
from models.user import User, UserRole
from schemas.agent import (
    AgentCreateRequest,
    AgentResponse,
    AgentRestoreRequest,
    AgentSummary,
    AgentUpdateRequest,
)
from services.cache import invalidate_namespace
from services.config_generator import validate_mcp_command
from services.harness_capability_inference import compute_supported_harnesses, infer_required_features
from services.registry_telemetry import emit_registry_event

from ._router import router
from .helpers import (
    _agent_to_response,
    _load_agent,
    _resolve_component_names,
    _resolve_component_statuses,
    _validate_mcp_ids,
)


@router.post("", response_model=AgentResponse)
async def create_agent(
    req: AgentCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.debug("creating agent")
    if not req.description:
        raise HTTPException(status_code=422, detail="Description must not be empty")

    # If `components` is provided, it supersedes legacy `mcp_server_ids`
    if req.components:
        req.mcp_server_ids = []

    # Validate legacy mcp_server_ids
    mcp_listings = await _validate_mcp_ids(req.mcp_server_ids, db)

    # Validate new components field (component_type already validated by Pydantic Literal)
    if req.components:
        from services.agent_resolver import validate_component_ids

        errors = await validate_component_ids(
            [{"component_type": c.component_type, "component_id": c.component_id} for c in req.components],
            db,
            require_approved=False,
        )
        if errors:
            raise HTTPException(
                status_code=400,
                detail=[
                    {"component_type": e.component_type, "component_id": str(e.component_id), "reason": e.reason}
                    for e in errors
                ],
            )

    # Validate external MCP commands for shell safety

    for _mcp in req.external_mcps or []:
        _cmd = _mcp.get("command", "") if isinstance(_mcp, dict) else getattr(_mcp, "command", "")
        _args = _mcp.get("args", []) if isinstance(_mcp, dict) else getattr(_mcp, "args", [])
        try:
            validate_mcp_command(_cmd, _args or [])
        except ValueError as e:
            raise HTTPException(status_code=422, detail=f"Invalid MCP command: {e}")

    # Pre-check uniqueness before insert for a clean 409 (the DB constraint
    # remains the source of truth, but checking first avoids triggering an
    # IntegrityError mid-flush which would corrupt the savepoint state).
    existing = await db.execute(select(Agent.id).where(Agent.name == req.name, Agent.deleted_at.is_(None)))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail=f"An agent named '{req.name}' already exists. Pick a different name.",
        )

    agent = Agent(
        name=req.name,
        owner=req.owner or current_user.username or current_user.email,
        category=req.category,
        created_by=current_user.id,
        owner_org_id=current_user.org_id,
    )
    db.add(agent)
    await db.flush()

    version = AgentVersion(
        agent_id=agent.id,
        version=req.version,
        description=req.description,
        prompt=req.prompt,
        model_name=req.model_name,
        model_config_json=req.model_config_json,
        models_by_harness=req.models_by_harness,
        external_mcps=[m.model_dump() for m in req.external_mcps],
        supported_harnesses=req.supported_harnesses,
        status=AgentStatus.pending,
        released_by=current_user.id,
    )
    db.add(version)
    await db.flush()

    agent.latest_version_id = version.id

    # Legacy: mcp_server_ids → AgentComponent(type=mcp)
    order = 0
    for mid, listing in zip(req.mcp_server_ids, mcp_listings, strict=False):
        db.add(
            AgentComponent(
                agent_version_id=version.id,
                component_type="mcp",
                component_id=mid,
                component_name="",
                resolved_version=listing.version,
                order_index=order,
            )
        )
        order += 1

    # New: components list with all types
    for cref in req.components:
        db.add(
            AgentComponent(
                agent_version_id=version.id,
                component_type=cref.component_type,
                component_id=cref.component_id,
                component_name="",
                resolved_version="latest",
                order_index=order,
                config_override=cref.config_override,
            )
        )
        order += 1

    # Auto-infer harness feature requirements from the request data
    # (avoid accessing agent.components which would trigger a lazy load)
    all_crefs = list(req.components) + [
        type("_Ref", (), {"component_type": "mcp", "component_id": mid})() for mid in req.mcp_server_ids
    ]
    skill_comp_ids = [c.component_id for c in all_crefs if c.component_type == "skill"]
    skill_listings_map: dict = {}
    if skill_comp_ids:
        rows = (await db.execute(select(SkillListing).where(SkillListing.id.in_(skill_comp_ids)))).scalars().all()
        skill_listings_map = {row.id: row for row in rows}

    # Build a lightweight stand-in so the inference function can iterate components
    class _AgentProxy:
        components = all_crefs
        external_mcps = version.external_mcps

    version.required_capabilities = infer_required_features(_AgentProxy(), skill_listings=skill_listings_map)
    version.inferred_supported_harnesses = compute_supported_harnesses(version.required_capabilities)

    # Flush pending AgentComponent + goal rows so the snapshot builder picks
    # them up via its own SELECTs (the relationship cache is empty).
    await db.flush()
    from services.agent_snapshot import build_yaml_snapshot

    version.yaml_snapshot = await build_yaml_snapshot(version, db)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if "uq_agents_active_name" in str(exc.orig) or "uq_agents_name" in str(exc.orig):
            raise HTTPException(
                status_code=409,
                detail=f"An agent named '{req.name}' already exists. Pick a different name.",
            )
        raise

    agent = await _load_agent(db, str(agent.id))
    name_map = await _resolve_component_names(agent.components, db)

    emit_registry_event(
        action="agent.create",
        user_id=str(current_user.id),
        user_email=current_user.email,
        user_role=current_user.role.value,
        agent_id=str(agent.id),
        resource_name=req.name,
        metadata={"agent_name": req.name, "version": req.version, "component_count": str(len(req.components))},
    )

    return _agent_to_response(
        agent, name_map, created_by_email=current_user.email, created_by_username=current_user.username
    )


@router.get("", response_model=list[AgentSummary])
async def list_agents(
    response: Response,
    search: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200, description="Page size (1-200)"),
    offset: int = Query(0, ge=0, description="Items to skip"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.debug("listing agents")
    from models.feedback import Feedback

    base_filter = (AgentVersion.status == AgentStatus.approved) & (Agent.deleted_at.is_(None))
    search_filter = None
    if search:
        safe = escape_like(search)
        search_filter = Agent.name.ilike(f"%{safe}%") | AgentVersion.description.ilike(f"%{safe}%")

    # Org-scoping: when the caller belongs to an org, show agents owned by that org
    # or agents with no org set (legacy/bulk-created agents)
    org_filter = None
    if current_user.org_id is not None:
        org_filter = (Agent.owner_org_id == current_user.org_id) | (Agent.owner_org_id.is_(None))

    # Total count for pagination header
    count_stmt = (
        select(func.count(Agent.id)).join(AgentVersion, Agent.latest_version_id == AgentVersion.id).where(base_filter)
    )
    if search_filter is not None:
        count_stmt = count_stmt.where(search_filter)
    if org_filter is not None:
        count_stmt = count_stmt.where(org_filter)
    total = (await db.execute(count_stmt)).scalar_one()
    response.headers["X-Total-Count"] = str(total)

    stmt = select(Agent).join(AgentVersion, Agent.latest_version_id == AgentVersion.id).where(base_filter)
    if search_filter is not None:
        stmt = stmt.where(search_filter)
    if org_filter is not None:
        stmt = stmt.where(org_filter)
    result = await db.execute(stmt.order_by(Agent.created_at.desc()).offset(offset).limit(limit))
    agents = result.scalars().all()

    # Batch-fetch average ratings
    agent_ids = [a.id for a in agents]
    rating_map: dict[uuid.UUID, float] = {}
    if agent_ids:
        rows = await db.execute(
            select(Feedback.listing_id, func.avg(Feedback.rating))
            .where(Feedback.listing_id.in_(agent_ids), Feedback.listing_type == "agent")
            .group_by(Feedback.listing_id)
        )
        rating_map = {r[0]: round(float(r[1]), 2) for r in rows.all()}

    # Batch-fetch creator emails and usernames
    user_ids = {a.created_by for a in agents}
    email_map: dict[uuid.UUID, str] = {}
    username_map: dict[uuid.UUID, str | None] = {}
    if user_ids:
        rows = await db.execute(select(User.id, User.email, User.username).where(User.id.in_(user_ids)))
        for r in rows.all():
            email_map[r[0]] = r[1]
            username_map[r[0]] = r[2]

    return [
        AgentSummary(
            id=a.id,
            name=a.name,
            version=a.version,
            description=a.description,
            owner=a.owner,
            model_name=a.model_name,
            supported_harnesses=a.supported_harnesses,
            status=a.status,
            rejection_reason=a.rejection_reason,
            download_count=a.download_count,
            average_rating=rating_map.get(a.id),
            component_count=len(a.components),
            created_by=a.created_by,
            created_by_email=email_map.get(a.created_by, ""),
            created_by_username=username_map.get(a.created_by),
            created_at=a.created_at,
            updated_at=a.updated_at,
        )
        for a in agents
    ]


@router.get("/my", response_model=list[AgentSummary])
async def my_agents(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.debug("my_agents called")
    from models.feedback import Feedback

    stmt = (
        select(Agent)
        .where(Agent.created_by == current_user.id, Agent.deleted_at.is_(None))
        .order_by(Agent.created_at.desc())
    )
    agents = (await db.execute(stmt)).scalars().all()

    agent_ids = [a.id for a in agents]
    rating_map: dict[uuid.UUID, float] = {}
    if agent_ids:
        rows = await db.execute(
            select(Feedback.listing_id, func.avg(Feedback.rating))
            .where(Feedback.listing_id.in_(agent_ids), Feedback.listing_type == "agent")
            .group_by(Feedback.listing_id)
        )
        rating_map = {r[0]: round(float(r[1]), 2) for r in rows.all()}

    return [
        AgentSummary(
            id=a.id,
            name=a.name,
            version=a.version,
            description=a.description,
            owner=a.owner,
            model_name=a.model_name,
            supported_harnesses=a.supported_harnesses,
            status=a.status,
            rejection_reason=a.rejection_reason,
            download_count=a.download_count,
            average_rating=rating_map.get(a.id),
            component_count=len(a.components),
            created_by=a.created_by,
            created_by_email=current_user.email,
            created_by_username=current_user.username,
            created_at=a.created_at,
            updated_at=a.updated_at,
        )
        for a in agents
    ]


@router.get("/archived", response_model=list[AgentSummary])
async def archived_agents(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    optic.debug("archived_agents called")
    from models.feedback import Feedback

    stmt = (
        select(Agent)
        .join(AgentVersion, Agent.latest_version_id == AgentVersion.id)
        .where(AgentVersion.status == AgentStatus.archived, Agent.deleted_at.is_(None))
        .order_by(Agent.created_at.desc())
    )
    if current_user.org_id is not None:
        stmt = stmt.where(Agent.owner_org_id == current_user.org_id)

    agents = (await db.execute(stmt)).scalars().all()

    agent_ids = [a.id for a in agents]
    rating_map: dict[uuid.UUID, float] = {}
    if agent_ids:
        rows = await db.execute(
            select(Feedback.listing_id, func.avg(Feedback.rating))
            .where(Feedback.listing_id.in_(agent_ids), Feedback.listing_type == "agent")
            .group_by(Feedback.listing_id)
        )
        rating_map = {r[0]: round(float(r[1]), 2) for r in rows.all()}

    user_ids = {a.created_by for a in agents}
    email_map: dict[uuid.UUID, str] = {}
    username_map: dict[uuid.UUID, str | None] = {}
    if user_ids:
        rows = await db.execute(select(User.id, User.email, User.username).where(User.id.in_(user_ids)))
        for r in rows.all():
            email_map[r[0]] = r[1]
            username_map[r[0]] = r[2]

    return [
        AgentSummary(
            id=a.id,
            name=a.name,
            version=a.version,
            description=a.description,
            owner=a.owner,
            model_name=a.model_name,
            supported_harnesses=a.supported_harnesses,
            status=a.status,
            rejection_reason=a.rejection_reason,
            download_count=a.download_count,
            average_rating=rating_map.get(a.id),
            component_count=len(a.components),
            created_by=a.created_by,
            created_by_email=email_map.get(a.created_by, ""),
            created_by_username=username_map.get(a.created_by),
            created_at=a.created_at,
            updated_at=a.updated_at,
        )
        for a in agents
    ]


@router.get("/deleted", response_model=list[AgentSummary])
async def deleted_agents(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.debug("deleted_agents called")
    from models.feedback import Feedback

    is_admin = ROLE_HIERARCHY.get(current_user.role, 999) <= ROLE_HIERARCHY[UserRole.admin]
    stmt = select(Agent).where(Agent.deleted_at.is_not(None)).order_by(Agent.deleted_at.desc())
    if is_admin:
        if current_user.org_id is not None:
            stmt = stmt.where(Agent.owner_org_id == current_user.org_id)
    else:
        stmt = stmt.where(Agent.created_by == current_user.id)

    agents = (await db.execute(stmt)).scalars().all()

    agent_ids = [a.id for a in agents]
    rating_map: dict[uuid.UUID, float] = {}
    if agent_ids:
        rows = await db.execute(
            select(Feedback.listing_id, func.avg(Feedback.rating))
            .where(Feedback.listing_id.in_(agent_ids), Feedback.listing_type == "agent")
            .group_by(Feedback.listing_id)
        )
        rating_map = {r[0]: round(float(r[1]), 2) for r in rows.all()}

    user_ids = {a.created_by for a in agents}
    email_map: dict[uuid.UUID, str] = {}
    username_map: dict[uuid.UUID, str | None] = {}
    if user_ids:
        rows = await db.execute(select(User.id, User.email, User.username).where(User.id.in_(user_ids)))
        for r in rows.all():
            email_map[r[0]] = r[1]
            username_map[r[0]] = r[2]

    return [
        AgentSummary(
            id=a.id,
            name=a.name,
            version=a.version,
            description=a.description,
            owner=a.owner,
            model_name=a.model_name,
            supported_harnesses=a.supported_harnesses,
            status=a.status,
            rejection_reason=a.rejection_reason,
            download_count=a.download_count,
            average_rating=rating_map.get(a.id),
            component_count=len(a.components),
            created_by=a.created_by,
            created_by_email=email_map.get(a.created_by, ""),
            created_by_username=username_map.get(a.created_by),
            created_at=a.created_at,
            deleted_at=a.deleted_at,
            updated_at=a.updated_at,
        )
        for a in agents
    ]


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.debug("fetching agent details")
    agent = await _load_agent(
        db,
        agent_id,
        prefer_user_id=current_user.id,
        org_id=current_user.org_id,
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if current_user.org_id is not None and agent.owner_org_id != current_user.org_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    perm = get_effective_agent_permission(agent, current_user)
    if perm == "none":
        raise HTTPException(status_code=403, detail="Insufficient permissions to view this agent")
    name_map = await _resolve_component_names(agent.components, db)
    status_map = await _resolve_component_statuses(agent.components, db)
    user_row = (await db.execute(select(User.email, User.username).where(User.id == agent.created_by))).first()
    return _agent_to_response(
        agent,
        name_map,
        created_by_email=user_row[0] if user_row else "",
        created_by_username=user_row[1] if user_row else None,
        user_permission=perm,
        status_map=status_map,
    )


@router.get("/{agent_id}/version-suggestions")
async def version_suggestions(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.trace("agent_id={}", agent_id)
    agent = await _load_agent(
        db,
        agent_id,
        prefer_user_id=current_user.id,
        org_id=current_user.org_id,
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if current_user.org_id is not None and agent.owner_org_id != current_user.org_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    if get_effective_agent_permission(agent, current_user) == "none":
        raise HTTPException(status_code=403, detail="Insufficient permissions to view this agent")
    # Use the highest existing version (including pending) to avoid duplicate suggestions
    from models.agent import AgentVersion
    from services.versioning import suggest_versions

    all_versions_stmt = (
        select(AgentVersion.version).where(AgentVersion.agent_id == agent.id).order_by(AgentVersion.created_at.desc())
    )
    all_versions_result = await db.execute(all_versions_stmt)
    all_versions = [v for (v,) in all_versions_result.all()]

    # Find the highest semver among all existing versions
    from services.versioning import parse_semver

    highest = agent.version or "0.0.0"
    for v in all_versions:
        parsed = parse_semver(v)
        if parsed and parsed > (parse_semver(highest) or (0, 0, 0)):
            highest = v

    return {"current": highest, "suggestions": suggest_versions(highest)}


@router.put("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: str,
    req: AgentUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.trace("agent_id={}", agent_id)
    agent = await _load_agent(db, agent_id, prefer_user_id=current_user.id, org_id=current_user.org_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    is_admin = ROLE_HIERARCHY.get(current_user.role, 999) <= ROLE_HIERARCHY[UserRole.admin]
    if not is_admin and current_user.org_id is not None and agent.owner_org_id != current_user.org_id:
        raise HTTPException(status_code=404, detail="Agent not found")

    perm = get_effective_agent_permission(agent, current_user)
    if perm not in ("owner", "edit") and not is_admin:
        raise HTTPException(status_code=403, detail="Not the agent owner or editor")

    if req.version_bump_type and req.version is None:
        from services.versioning import bump_version

        req.version = bump_version(agent.version, req.version_bump_type)

    if req.name is not None and req.name != agent.name:
        existing = await db.execute(
            select(Agent.id).where(Agent.name == req.name, Agent.deleted_at.is_(None), Agent.id != agent.id)
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(status_code=409, detail=f"An active agent named '{req.name}' already exists.")

    for field in (
        "name",
        "version",
        "description",
        "category",
        "owner",
        "prompt",
        "model_name",
        "model_config_json",
        "models_by_harness",
        "supported_harnesses",
    ):
        val = getattr(req, field)
        if val is not None:
            setattr(agent, field, val)

    if req.external_mcps is not None:
        for _mcp in req.external_mcps:
            _cmd = getattr(_mcp, "command", "")
            _args = getattr(_mcp, "args", [])
            try:
                validate_mcp_command(_cmd, _args or [])
            except ValueError as e:
                raise HTTPException(status_code=422, detail=f"Invalid MCP command: {e}")
        agent.external_mcps = [m.model_dump() for m in req.external_mcps]

    if req.components is not None:
        # New components field replaces ALL components (type validated by Pydantic Literal)
        from services.agent_resolver import validate_component_ids

        if not agent.latest_version:
            raise HTTPException(status_code=400, detail="Agent has no version to update components on")

        errors = await validate_component_ids(
            [{"component_type": c.component_type, "component_id": c.component_id} for c in req.components],
            db,
            require_approved=False,
        )
        if errors:
            raise HTTPException(
                status_code=400,
                detail=[
                    {"component_type": e.component_type, "component_id": str(e.component_id), "reason": e.reason}
                    for e in errors
                ],
            )
        # Remove ALL old components on the latest version
        version_id = agent.latest_version.id
        old_comps = (
            (await db.execute(select(AgentComponent).where(AgentComponent.agent_version_id == version_id)))
            .scalars()
            .all()
        )
        for comp in old_comps:
            await db.delete(comp)
        for i, cref in enumerate(req.components):
            db.add(
                AgentComponent(
                    agent_version_id=version_id,
                    component_type=cref.component_type,
                    component_id=cref.component_id,
                    component_name="",
                    resolved_version="latest",
                    order_index=i,
                    config_override=cref.config_override,
                )
            )
    elif req.mcp_server_ids is not None:
        # Legacy: only update MCP components
        if not agent.latest_version:
            raise HTTPException(status_code=400, detail="Agent has no version to update components on")

        mcp_listings = await _validate_mcp_ids(req.mcp_server_ids, db)
        version_id = agent.latest_version.id
        old_comps = (
            (
                await db.execute(
                    select(AgentComponent).where(
                        AgentComponent.agent_version_id == version_id,
                        AgentComponent.component_type == "mcp",
                    )
                )
            )
            .scalars()
            .all()
        )
        for comp in old_comps:
            await db.delete(comp)
        for i, (mid, listing) in enumerate(zip(req.mcp_server_ids, mcp_listings, strict=False)):
            db.add(
                AgentComponent(
                    agent_version_id=version_id,
                    component_type="mcp",
                    component_id=mid,
                    component_name="",
                    resolved_version=listing.version,
                    order_index=i,
                )
            )

    # Re-infer harness features only when components or external_mcps changed
    if req.components is not None or req.mcp_server_ids is not None or req.external_mcps is not None:
        if not agent.latest_version:
            raise HTTPException(status_code=400, detail="Agent has no version to update features on")
        current_comps = (
            (await db.execute(select(AgentComponent).where(AgentComponent.agent_version_id == agent.latest_version.id)))
            .scalars()
            .all()
        )
        skill_comp_ids = [c.component_id for c in current_comps if c.component_type == "skill"]
        skill_listings_map_update: dict = {}
        if skill_comp_ids:
            rows = (await db.execute(select(SkillListing).where(SkillListing.id.in_(skill_comp_ids)))).scalars().all()
            skill_listings_map_update = {row.id: row for row in rows}

        class _AgentProxy:
            components = current_comps
            external_mcps = agent.external_mcps

        agent.required_capabilities = infer_required_features(_AgentProxy(), skill_listings=skill_listings_map_update)
        agent.inferred_supported_harnesses = compute_supported_harnesses(agent.required_capabilities)

    await db.commit()
    agent = await _load_agent(db, str(agent.id))
    name_map = await _resolve_component_names(agent.components, db)

    emit_registry_event(
        action="agent.update",
        user_id=str(current_user.id),
        user_email=current_user.email,
        user_role=current_user.role.value,
        agent_id=str(agent.id),
        resource_name=agent.name,
    )

    return _agent_to_response(
        agent, name_map, created_by_email=current_user.email, created_by_username=current_user.username
    )


@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.debug("soft deleting agent")

    agent = await _load_agent(
        db, agent_id, prefer_user_id=current_user.id, org_id=current_user.org_id, include_all_statuses=True
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    is_admin = ROLE_HIERARCHY.get(current_user.role, 999) <= ROLE_HIERARCHY[UserRole.admin]
    if not is_admin and current_user.org_id is not None and agent.owner_org_id != current_user.org_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    perm = get_effective_agent_permission(agent, current_user)
    if perm != "owner" and not is_admin:
        raise HTTPException(status_code=403, detail="Not authorized")

    agent.deleted_at = datetime.now(UTC)
    await db.commit()
    await invalidate_namespace("dashboard")

    emit_registry_event(
        action="agent.delete",
        user_id=str(current_user.id),
        user_email=current_user.email,
        user_role=current_user.role.value,
        agent_id=str(agent.id),
        resource_name=agent.name,
    )

    return {"deleted": str(agent.id), "name": agent.name, "deleted_at": agent.deleted_at.isoformat()}


@router.patch("/{agent_id}/restore")
async def restore_deleted_agent(
    agent_id: str,
    req: AgentRestoreRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.trace("agent_id={}", agent_id)
    agent = await _load_agent(
        db,
        agent_id,
        prefer_user_id=current_user.id,
        org_id=current_user.org_id,
        include_all_statuses=True,
        include_deleted=True,
    )
    if not agent or agent.deleted_at is None:
        raise HTTPException(status_code=404, detail="Deleted agent not found")
    is_admin = ROLE_HIERARCHY.get(current_user.role, 999) <= ROLE_HIERARCHY[UserRole.admin]
    if not is_admin and current_user.org_id is not None and agent.owner_org_id != current_user.org_id:
        raise HTTPException(status_code=404, detail="Deleted agent not found")
    perm = get_effective_agent_permission(agent, current_user)
    if perm != "owner" and not is_admin:
        raise HTTPException(status_code=403, detail="Not authorized")

    restore_name = req.name if req and req.name else agent.name
    existing = await db.execute(
        select(Agent.id).where(Agent.name == restore_name, Agent.deleted_at.is_(None), Agent.id != agent.id)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="An active agent already uses this name. Restore with a new name.")

    agent.name = restore_name
    agent.deleted_at = None
    await db.commit()
    await invalidate_namespace("dashboard")

    emit_registry_event(
        action="agent.restore",
        user_id=str(current_user.id),
        user_email=current_user.email,
        user_role=current_user.role.value,
        agent_id=str(agent.id),
        resource_name=agent.name,
    )

    return {"id": str(agent.id), "name": agent.name, "status": agent.status}


@router.patch("/{agent_id}/archive")
async def archive_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.trace("agent_id={}", agent_id)
    agent = await _load_agent(db, agent_id, prefer_user_id=current_user.id, org_id=current_user.org_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if current_user.org_id is not None and agent.owner_org_id != current_user.org_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    is_admin = ROLE_HIERARCHY.get(current_user.role, 999) <= ROLE_HIERARCHY[UserRole.admin]
    if agent.created_by != current_user.id and not is_admin:
        raise HTTPException(status_code=403, detail="Only the owner or an admin can archive this agent")
    if agent.status != AgentStatus.approved:
        raise HTTPException(status_code=400, detail="Only approved agents can be archived")
    if not agent.latest_version_id:
        raise HTTPException(status_code=400, detail="Agent has no version")
    await db.execute(
        update(AgentVersion).where(AgentVersion.id == agent.latest_version_id).values(status=AgentStatus.archived)
    )
    await db.commit()

    emit_registry_event(
        action="agent.archive",
        user_id=str(current_user.id),
        user_email=current_user.email,
        user_role=current_user.role.value,
        agent_id=str(agent.id),
        resource_name=agent.name,
    )

    return {"id": str(agent.id), "name": agent.name, "status": "archived"}


@router.patch("/{agent_id}/unarchive")
async def unarchive_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.trace("agent_id={}", agent_id)
    agent = await _load_agent(
        db, agent_id, prefer_user_id=current_user.id, org_id=current_user.org_id, include_all_statuses=True
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if current_user.org_id is not None and agent.owner_org_id != current_user.org_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    is_admin = ROLE_HIERARCHY.get(current_user.role, 999) <= ROLE_HIERARCHY[UserRole.admin]
    if agent.created_by != current_user.id and not is_admin:
        raise HTTPException(status_code=403, detail="Only the owner or an admin can unarchive this agent")
    if agent.status != AgentStatus.archived:
        raise HTTPException(status_code=400, detail="Agent is not archived")
    if not agent.latest_version_id:
        raise HTTPException(status_code=400, detail="Agent has no version")
    await db.execute(
        update(AgentVersion).where(AgentVersion.id == agent.latest_version_id).values(status=AgentStatus.approved)
    )
    await db.commit()

    emit_registry_event(
        action="agent.unarchive",
        user_id=str(current_user.id),
        user_email=current_user.email,
        user_role=current_user.role.value,
        agent_id=str(agent.id),
        resource_name=agent.name,
    )

    return {"id": str(agent.id), "name": agent.name, "status": "approved"}
