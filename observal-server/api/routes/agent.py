import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.deps import (
    ROLE_HIERARCHY,
    get_db,
    get_effective_agent_permission,
    get_user_groups,
    optional_current_user,
    require_role,
    resolve_prefix_id,
)
from api.sanitize import escape_like
from config import settings
from models.agent import (
    Agent,
    AgentGoalSection,
    AgentGoalTemplate,
    AgentStatus,
    AgentTeamAccess,
    AgentVersion,
    AgentVisibility,
)
from models.agent_component import AgentComponent
from models.download import AgentDownloadRecord
from models.hook import HookListing
from models.mcp import ListingStatus, McpListing, McpVersion
from models.skill import SkillListing
from models.user import User, UserRole
from schemas.agent import (
    AgentCreateRequest,
    AgentInstallRequest,
    AgentInstallResponse,
    AgentResponse,
    AgentSummary,
    AgentUpdateRequest,
    AgentValidateRequest,
    ComponentLinkResponse,
    GoalSectionResponse,
    GoalTemplateResponse,
    McpLinkResponse,
    ValidationIssue,
    ValidationResult,
)
from services.agent_config_generator import generate_agent_config
from services.audit_helpers import audit
from services.editing_lock import _is_lock_expired, acquire_edit_lock, release_edit_lock
from services.ide_feature_inference import compute_supported_ides, infer_required_features
from services.registry_telemetry import emit_registry_event

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])

# Eager-load options for Agent queries to avoid MissingGreenlet in async.
# Agent.latest_version (selectin) auto-loads AgentVersion.components and .goal_template.
_agent_load_options = [
    selectinload(Agent.team_accesses),
]


async def _load_agent(
    db: AsyncSession,
    agent_id: str,
    extra_conditions=None,
    *,
    prefer_user_id: uuid.UUID | None = None,
    org_id: uuid.UUID | None = None,
    include_all_statuses: bool = False,
) -> Agent | None:
    """Load an agent by UUID, prefix, or name with eager loading.

    When *prefer_user_id* is provided and resolution is by name, prefer the
    caller's own agent over agents created by other users with the same name.
    The global name fallback is restricted to active agents and, when *org_id*
    is set, to agents within the same organisation.

    Set *include_all_statuses* to find agents regardless of version status
    (needed for unarchive, delete, etc.).
    """
    try:
        return await resolve_prefix_id(
            Agent, agent_id, db, load_options=_agent_load_options, extra_conditions=extra_conditions
        )
    except HTTPException:
        pass

    # Try the caller's own agent first
    if prefer_user_id is not None:
        stmt = (
            select(Agent)
            .where(Agent.name == agent_id, Agent.created_by == prefer_user_id)
            .options(*_agent_load_options)
        )
        if extra_conditions:
            stmt = stmt.where(*extra_conditions)
        mine = (await db.execute(stmt)).scalar_one_or_none()
        if mine:
            return mine

    # Fall back to global name lookup
    stmt = (
        select(Agent)
        .join(AgentVersion, Agent.latest_version_id == AgentVersion.id)
        .where(Agent.name == agent_id)
        .options(*_agent_load_options)
    )
    if not include_all_statuses:
        stmt = stmt.where(AgentVersion.status == AgentStatus.approved)
    if extra_conditions:
        stmt = stmt.where(*extra_conditions)
    if org_id is not None:
        stmt = stmt.where(Agent.owner_org_id == org_id)
    results = (await db.execute(stmt)).scalars().all()
    if len(results) == 1:
        return results[0]

    return None


def _agent_to_response(
    agent: Agent,
    name_map: dict[str, str] | None = None,
    *,
    created_by_email: str = "",
    created_by_username: str | None = None,
    user_permission: str | None = None,
) -> AgentResponse:
    name_map = name_map or {}
    # Build mcp_links from components with component_type='mcp' (backwards compat)
    mcp_components = [c for c in agent.components if c.component_type == "mcp"]
    mcp_links = [
        McpLinkResponse(
            mcp_listing_id=comp.component_id,
            mcp_name=name_map.get(str(comp.component_id), "(component)"),
            order=comp.order_index,
        )
        for comp in mcp_components
    ]
    # Build full component_links for all types
    component_links = [
        ComponentLinkResponse(
            component_type=comp.component_type,
            component_id=comp.component_id,
            component_name=name_map.get(str(comp.component_id), ""),
            version_ref=comp.resolved_version,
            order=comp.order_index,
            config_override=comp.config_override,
        )
        for comp in agent.components
    ]
    goal_template = None
    if agent.goal_template:
        sections = [
            GoalSectionResponse(
                name=s.name, description=s.description, grounding_required=s.grounding_required, order=s.order
            )
            for s in agent.goal_template.sections
        ]
        goal_template = GoalTemplateResponse(description=agent.goal_template.description, sections=sections)

    # Build agent_dict from table columns (identity fields) plus version-delegate properties.
    agent_dict = {c.key: getattr(agent, c.key) for c in Agent.__table__.columns}
    for field in (
        "version",
        "description",
        "prompt",
        "model_name",
        "model_config_json",
        "external_mcps",
        "supported_ides",
        "required_ide_features",
        "inferred_supported_ides",
        "status",
        "rejection_reason",
    ):
        agent_dict[field] = getattr(agent, field)
    agent_dict["mcp_links"] = mcp_links
    agent_dict["component_links"] = component_links
    agent_dict["goal_template"] = goal_template
    agent_dict["visibility"] = agent.visibility
    agent_dict["team_accesses"] = [
        {"group_name": acc.group_name, "permission": acc.permission} for acc in getattr(agent, "team_accesses", [])
    ]
    agent_dict["created_by_email"] = created_by_email
    agent_dict["created_by_username"] = created_by_username
    agent_dict["user_permission"] = user_permission
    # Populate version fields for CLI pull resolution
    approved_versions = [
        v for v in getattr(agent, "versions", []) if getattr(v, "status", None) == AgentStatus.approved
    ]
    latest_approved = max(approved_versions, key=lambda v: v.created_at) if approved_versions else None
    agent_dict["latest_approved_version"] = latest_approved.version if latest_approved else None
    agent_dict["latest_version"] = agent.version if agent.version != "0.0.0" else None
    return AgentResponse(**agent_dict)


async def _resolve_component_names(components: list, db: AsyncSession) -> dict[str, str]:
    """Batch-resolve component_id → name for all component types."""
    if not components:
        return {}
    from services.agent_resolver import _LISTING_MODELS

    # Group component_ids by type
    by_type: dict[str, list[uuid.UUID]] = {}
    for comp in components:
        by_type.setdefault(comp.component_type, []).append(comp.component_id)

    name_map: dict[str, str] = {}
    for comp_type, ids in by_type.items():
        model = _LISTING_MODELS.get(comp_type)
        if not model:
            continue
        rows = (await db.execute(select(model.id, model.name).where(model.id.in_(ids)))).all()
        for row in rows:
            name_map[str(row[0])] = row[1]
    return name_map


async def _validate_mcp_ids(mcp_ids: list[uuid.UUID], db: AsyncSession) -> list[McpListing]:
    listings = []
    for mid in mcp_ids:
        result = await db.execute(
            select(McpListing)
            .join(McpVersion, McpListing.latest_version_id == McpVersion.id)
            .where(McpListing.id == mid, McpVersion.status == ListingStatus.approved)
        )
        listing = result.scalar_one_or_none()
        if not listing:
            raise HTTPException(status_code=400, detail=f"MCP server {mid} not found or not approved")
        listings.append(listing)
    return listings


@router.post("", response_model=AgentResponse)
async def create_agent(
    req: AgentCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
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
        )
        if errors:
            raise HTTPException(
                status_code=400,
                detail=[
                    {"component_type": e.component_type, "component_id": str(e.component_id), "reason": e.reason}
                    for e in errors
                ],
            )

    # Pre-check uniqueness before insert for a clean 409 (the DB constraint
    # remains the source of truth, but checking first avoids triggering an
    # IntegrityError mid-flush which would corrupt the savepoint state).
    existing = await db.execute(select(Agent.id).where(Agent.name == req.name, Agent.created_by == current_user.id))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail=f"You already have an agent named '{req.name}'. Pick a different name or delete the existing one.",
        )

    agent = Agent(
        name=req.name,
        owner=req.owner or current_user.username or current_user.email,
        visibility=req.visibility,
        created_by=current_user.id,
        owner_org_id=current_user.org_id,
    )
    db.add(agent)
    await db.flush()

    for acc in req.team_accesses:
        db.add(AgentTeamAccess(agent_id=agent.id, group_name=acc.group_name, permission=acc.permission))

    version = AgentVersion(
        agent_id=agent.id,
        version=req.version,
        description=req.description,
        prompt=req.prompt,
        model_name=req.model_name,
        model_config_json=req.model_config_json,
        external_mcps=[m.model_dump() for m in req.external_mcps],
        supported_ides=req.supported_ides,
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

    goal = AgentGoalTemplate(agent_version_id=version.id, description=req.goal_template.description)
    db.add(goal)
    await db.flush()

    for i, sec in enumerate(req.goal_template.sections):
        db.add(
            AgentGoalSection(
                goal_template_id=goal.id,
                name=sec.name,
                description=sec.description,
                grounding_required=sec.grounding_required,
                order=i,
            )
        )

    # Auto-infer IDE feature requirements from the request data
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

    version.required_ide_features = infer_required_features(_AgentProxy(), skill_listings=skill_listings_map)
    version.inferred_supported_ides = compute_supported_ides(version.required_ide_features)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if "uq_agents_name_created_by" in str(exc.orig):
            raise HTTPException(
                status_code=409,
                detail=f"You already have an agent named '{req.name}'. Pick a different name or delete the existing one.",
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

    await audit(
        current_user, "agent.create", resource_type="agent", resource_id=str(agent.id), resource_name=agent.name
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
    current_user: User | None = Depends(optional_current_user),
):
    from models.feedback import Feedback

    is_admin = False
    skip_visibility = settings.DEPLOYMENT_MODE == "local"
    if current_user:
        user_role_level = ROLE_HIERARCHY.get(current_user.role, 999)
        if user_role_level <= ROLE_HIERARCHY[UserRole.admin]:
            is_admin = True

    base_filter = AgentVersion.status == AgentStatus.approved
    if not is_admin and not skip_visibility:
        visibility_filter = Agent.visibility == AgentVisibility.public
        if current_user:
            user_groups = get_user_groups(current_user)
            visibility_filter = visibility_filter | (Agent.created_by == current_user.id)
            if current_user.org_id is not None:
                visibility_filter = visibility_filter | (Agent.owner_org_id == current_user.org_id)
            if user_groups:
                visibility_filter = visibility_filter | Agent.team_accesses.any(
                    AgentTeamAccess.group_name.in_(user_groups)
                )
        base_filter = base_filter & visibility_filter
    search_filter = None
    if search:
        safe = escape_like(search)
        search_filter = Agent.name.ilike(f"%{safe}%") | AgentVersion.description.ilike(f"%{safe}%")

    # Org-scoping: when the caller belongs to an org, only show agents owned by that org
    org_filter = None
    if current_user is not None and current_user.org_id is not None:
        org_filter = Agent.owner_org_id == current_user.org_id

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

    stmt = (
        select(Agent)
        .join(AgentVersion, Agent.latest_version_id == AgentVersion.id)
        .where(base_filter)
        .options(*_agent_load_options)
    )
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

    await audit(current_user, "agent.list", resource_type="agent")

    return [
        AgentSummary(
            id=a.id,
            name=a.name,
            version=a.version,
            description=a.description,
            owner=a.owner,
            model_name=a.model_name,
            supported_ides=a.supported_ides,
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
            visibility=a.visibility,
        )
        for a in agents
    ]


@router.get("/my", response_model=list[AgentSummary])
async def my_agents(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    from models.feedback import Feedback

    stmt = (
        select(Agent)
        .where(Agent.created_by == current_user.id)
        .options(*_agent_load_options)
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

    await audit(current_user, "agent.my_list", resource_type="agent")

    return [
        AgentSummary(
            id=a.id,
            name=a.name,
            version=a.version,
            description=a.description,
            owner=a.owner,
            model_name=a.model_name,
            supported_ides=a.supported_ides,
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
            visibility=a.visibility,
        )
        for a in agents
    ]


@router.get("/archived", response_model=list[AgentSummary])
async def archived_agents(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    from models.feedback import Feedback

    stmt = (
        select(Agent)
        .join(AgentVersion, Agent.latest_version_id == AgentVersion.id)
        .where(AgentVersion.status == AgentStatus.archived)
        .options(*_agent_load_options)
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
            supported_ides=a.supported_ides,
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
            visibility=a.visibility,
        )
        for a in agents
    ]


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_current_user),
):
    agent = await _load_agent(
        db,
        agent_id,
        prefer_user_id=current_user.id if current_user else None,
        org_id=current_user.org_id if current_user else None,
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if current_user is not None and current_user.org_id is not None and agent.owner_org_id != current_user.org_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    perm = get_effective_agent_permission(agent, current_user)
    if perm == "none":
        raise HTTPException(status_code=403, detail="Insufficient permissions to view this agent")
    name_map = await _resolve_component_names(agent.components, db)
    user_row = (await db.execute(select(User.email, User.username).where(User.id == agent.created_by))).first()
    await audit(current_user, "agent.view", resource_type="agent", resource_id=str(agent.id), resource_name=agent.name)
    return _agent_to_response(
        agent,
        name_map,
        created_by_email=user_row[0] if user_row else "",
        created_by_username=user_row[1] if user_row else None,
        user_permission=perm,
    )


@router.get("/{agent_id}/version-suggestions")
async def version_suggestions(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_current_user),
):
    agent = await _load_agent(
        db,
        agent_id,
        prefer_user_id=current_user.id if current_user else None,
        org_id=current_user.org_id if current_user else None,
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if current_user is not None and current_user.org_id is not None and agent.owner_org_id != current_user.org_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    if get_effective_agent_permission(agent, current_user) == "none":
        raise HTTPException(status_code=403, detail="Insufficient permissions to view this agent")
    from services.versioning import suggest_versions

    await audit(
        current_user,
        "agent.version_suggestions",
        resource_type="agent",
        resource_id=str(agent.id),
        resource_name=agent.name,
    )
    return {"current": agent.version, "suggestions": suggest_versions(agent.version)}


@router.put("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: str,
    req: AgentUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    agent = await _load_agent(db, agent_id, prefer_user_id=current_user.id, org_id=current_user.org_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if current_user.org_id is not None and agent.owner_org_id != current_user.org_id:
        raise HTTPException(status_code=404, detail="Agent not found")

    perm = get_effective_agent_permission(agent, current_user)
    if perm not in ("owner", "edit"):
        raise HTTPException(status_code=403, detail="Not the agent owner or editor")

    if req.version_bump_type and req.version is None:
        from services.versioning import bump_version

        req.version = bump_version(agent.version, req.version_bump_type)

    for field in (
        "name",
        "version",
        "description",
        "owner",
        "prompt",
        "model_name",
        "model_config_json",
        "supported_ides",
        "visibility",
    ):
        val = getattr(req, field)
        if val is not None:
            setattr(agent, field, val)

    if req.team_accesses is not None:
        old_accesses = (
            (await db.execute(select(AgentTeamAccess).where(AgentTeamAccess.agent_id == agent.id))).scalars().all()
        )
        for old_acc in old_accesses:
            await db.delete(old_acc)
        for acc in req.team_accesses:
            db.add(AgentTeamAccess(agent_id=agent.id, group_name=acc.group_name, permission=acc.permission))

    if req.external_mcps is not None:
        agent.external_mcps = [m.model_dump() for m in req.external_mcps]

    if req.components is not None:
        # New components field replaces ALL components (type validated by Pydantic Literal)
        from services.agent_resolver import validate_component_ids

        if not agent.latest_version:
            raise HTTPException(status_code=400, detail="Agent has no version to update components on")

        errors = await validate_component_ids(
            [{"component_type": c.component_type, "component_id": c.component_id} for c in req.components],
            db,
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

    if req.goal_template is not None:
        if not agent.latest_version:
            raise HTTPException(status_code=400, detail="Agent has no version to update goal template on")
        version_id = agent.latest_version.id
        if agent.goal_template:
            old_sections = (
                (
                    await db.execute(
                        select(AgentGoalSection).where(AgentGoalSection.goal_template_id == agent.goal_template.id)
                    )
                )
                .scalars()
                .all()
            )
            for sec in old_sections:
                await db.delete(sec)
            await db.delete(agent.goal_template)
            await db.flush()
        goal = AgentGoalTemplate(agent_version_id=version_id, description=req.goal_template.description)
        db.add(goal)
        await db.flush()
        for i, sec in enumerate(req.goal_template.sections):
            db.add(
                AgentGoalSection(
                    goal_template_id=goal.id,
                    name=sec.name,
                    description=sec.description,
                    grounding_required=sec.grounding_required,
                    order=i,
                )
            )

    # Re-infer IDE features only when components or external_mcps changed
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

        agent.required_ide_features = infer_required_features(_AgentProxy(), skill_listings=skill_listings_map_update)
        agent.inferred_supported_ides = compute_supported_ides(agent.required_ide_features)

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

    await audit(
        current_user, "agent.update", resource_type="agent", resource_id=str(agent.id), resource_name=agent.name
    )

    return _agent_to_response(
        agent, name_map, created_by_email=current_user.email, created_by_username=current_user.username
    )


@router.post("/{agent_id}/install", response_model=AgentInstallResponse)
async def install_agent(
    agent_id: str,
    req: AgentInstallRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    agent = await _load_agent(
        db,
        agent_id,
        prefer_user_id=current_user.id,
        org_id=current_user.org_id,
    )
    if not agent or (agent.status != AgentStatus.approved and agent.created_by != current_user.id):
        raise HTTPException(status_code=404, detail="Agent not found or not active")
    if current_user.org_id is not None and agent.owner_org_id != current_user.org_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    if get_effective_agent_permission(agent, current_user) == "none":
        raise HTTPException(status_code=403, detail="Insufficient permissions to install this agent")
    if not agent.latest_version:
        raise HTTPException(status_code=400, detail="Agent has no published version available for install")

    # Pre-load MCP listings for config generation
    mcp_comp_ids = [c.component_id for c in agent.components if c.component_type == "mcp"]
    mcp_listings_map = {}
    if mcp_comp_ids:
        mcp_rows = (await db.execute(select(McpListing).where(McpListing.id.in_(mcp_comp_ids)))).scalars().all()
        mcp_listings_map = {row.id: row for row in mcp_rows}

    # Pre-load skill listings for skill file generation
    skill_comp_ids = [c.component_id for c in agent.components if c.component_type == "skill"]
    skill_listings_map = {}
    if skill_comp_ids:
        skill_rows = (await db.execute(select(SkillListing).where(SkillListing.id.in_(skill_comp_ids)))).scalars().all()
        skill_listings_map = {row.id: row for row in skill_rows}

    # Pre-load hook listings for hook config generation
    hook_comp_ids = [c.component_id for c in agent.components if c.component_type == "hook"]
    hook_listings_map = {}
    if hook_comp_ids:
        from sqlalchemy.orm import selectinload as _sel

        hook_rows = (
            (
                await db.execute(
                    select(HookListing)
                    .options(_sel(HookListing.latest_version))
                    .where(HookListing.id.in_(hook_comp_ids))
                )
            )
            .scalars()
            .all()
        )
        hook_listings_map = {row.id: row for row in hook_rows}

    # Pre-load prompt listings for template injection
    prompt_comp_ids = [c.component_id for c in agent.components if c.component_type == "prompt"]
    prompt_listings_map = {}
    if prompt_comp_ids:
        from sqlalchemy.orm import selectinload as _sel2

        from models.prompt import PromptListing

        prompt_rows = (
            (
                await db.execute(
                    select(PromptListing)
                    .options(_sel2(PromptListing.latest_version))
                    .where(PromptListing.id.in_(prompt_comp_ids))
                )
            )
            .scalars()
            .all()
        )
        prompt_listings_map = {row.id: row for row in prompt_rows}

    # Resolve all component names for rules file content
    name_map = await _resolve_component_names(agent.components, db)

    from api.routes.config import derive_endpoints

    endpoints = derive_endpoints(request)
    snippet = generate_agent_config(
        agent,
        req.ide,
        observal_url=endpoints["api"],
        mcp_listings=mcp_listings_map,
        component_names=name_map,
        env_values=req.env_values,
        options=req.options,
        platform=req.platform,
        skill_listings=skill_listings_map,
        hook_listings=hook_listings_map,
        otlp_http_url=endpoints["otlp_http"],
        prompt_listings=prompt_listings_map,
    )

    # Capture agent.id before any DB operations that might expire the ORM
    # instance (e.g. savepoint rollback on duplicate download).
    resolved_agent_id = agent.id

    from services.download_tracker import record_agent_download

    await record_agent_download(
        agent_id=resolved_agent_id,
        user_id=current_user.id,
        source="api",
        ide=req.ide,
        request=request,
        db=db,
    )
    await db.commit()

    emit_registry_event(
        action="agent.install",
        user_id=str(current_user.id),
        user_email=current_user.email,
        user_role=current_user.role.value,
        agent_id=str(resolved_agent_id),
        resource_name=agent.name,
        metadata={"ide": req.ide},
    )

    await audit(
        current_user,
        "agent.install",
        resource_type="agent",
        resource_id=str(resolved_agent_id),
        resource_name=agent.name,
    )

    warnings = snippet.pop("_warnings", [])
    return AgentInstallResponse(agent_id=resolved_agent_id, ide=req.ide, config_snippet=snippet, warnings=warnings)


@router.get("/{agent_id}/downloads")
async def agent_download_stats(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_current_user),
):
    agent = await _load_agent(
        db,
        agent_id,
        prefer_user_id=current_user.id if current_user else None,
        org_id=current_user.org_id if current_user else None,
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if current_user is not None and current_user.org_id is not None and agent.owner_org_id != current_user.org_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    if get_effective_agent_permission(agent, current_user) == "none":
        raise HTTPException(status_code=403, detail="Insufficient permissions to view stats for this agent")
    from services.download_tracker import get_download_stats

    stats = await get_download_stats(agent.id, db)
    await audit(
        current_user, "agent.download_stats", resource_type="agent", resource_id=str(agent.id), resource_name=agent.name
    )
    return stats


@router.get("/{agent_id}/traces")
async def get_agent_traces(
    agent_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_current_user),
):
    """Return all traces where this agent participated."""
    agent = await _load_agent(
        db,
        agent_id,
        prefer_user_id=current_user.id if current_user else None,
        org_id=current_user.org_id if current_user else None,
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if current_user is not None and current_user.org_id is not None and agent.owner_org_id != current_user.org_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    if get_effective_agent_permission(agent, current_user) == "none":
        raise HTTPException(status_code=403, detail="Insufficient permissions to view this agent")
    from services.clickhouse import query_traces

    uid = None
    if current_user and current_user.role not in (UserRole.admin, UserRole.super_admin):
        uid = str(current_user.id)
    traces = await query_traces(
        project_id="default",
        agent_id=str(agent.id),
        user_id=uid,
        limit=limit,
        offset=offset,
    )
    await audit(
        current_user, "agent.traces", resource_type="agent", resource_id=str(agent.id), resource_name=agent.name
    )
    return {"agent_id": str(agent.id), "traces": traces, "count": len(traces)}


@router.get("/{agent_id}/resolve")
async def resolve_agent_components(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    """Resolve all components for an agent — validates they exist and are approved."""
    agent = await _load_agent(db, agent_id, prefer_user_id=current_user.id, org_id=current_user.org_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if current_user.org_id is not None and agent.owner_org_id != current_user.org_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    if get_effective_agent_permission(agent, current_user) == "none":
        raise HTTPException(status_code=403, detail="Insufficient permissions to resolve this agent")
    from services.agent_resolver import resolve_agent

    resolved = await resolve_agent(agent, db)
    from services.agent_builder import build_composition_summary

    await audit(
        current_user, "agent.resolve", resource_type="agent", resource_id=str(agent.id), resource_name=agent.name
    )
    return build_composition_summary(resolved)


@router.get("/{agent_id}/manifest")
async def get_agent_manifest(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    """Generate a portable agent manifest with all resolved components."""
    agent = await _load_agent(db, agent_id, prefer_user_id=current_user.id, org_id=current_user.org_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if current_user.org_id is not None and agent.owner_org_id != current_user.org_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    if get_effective_agent_permission(agent, current_user) == "none":
        raise HTTPException(status_code=403, detail="Insufficient permissions to view this agent's manifest")
    from services.agent_resolver import resolve_agent

    resolved = await resolve_agent(agent, db)
    if not resolved.ok:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Agent has unresolvable components",
                "errors": [
                    {"component_type": e.component_type, "component_id": str(e.component_id), "reason": e.reason}
                    for e in resolved.errors
                ],
            },
        )
    from services.agent_builder import build_agent_manifest

    await audit(
        current_user, "agent.manifest", resource_type="agent", resource_id=str(agent.id), resource_name=agent.name
    )
    return build_agent_manifest(resolved)


@router.post("/validate", response_model=ValidationResult)
async def validate_agent_composition(
    req: AgentValidateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    """Validate a set of components for compatibility before publishing an agent."""
    if not req.components:
        return ValidationResult(valid=True, issues=[])

    from services.agent_resolver import validate_component_ids

    errors = await validate_component_ids(
        [{"component_type": c.component_type, "component_id": c.component_id} for c in req.components],
        db,
    )
    issues = [
        ValidationIssue(
            severity="error",
            component_type=e.component_type,
            component_id=e.component_id,
            message=e.reason,
        )
        for e in errors
    ]
    await audit(current_user, "agent.validate", resource_type="agent")
    return ValidationResult(valid=len(issues) == 0, issues=issues)


@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    from models.eval import EvalRun, Scorecard
    from models.feedback import Feedback

    agent = await _load_agent(
        db, agent_id, prefer_user_id=current_user.id, org_id=current_user.org_id, include_all_statuses=True
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if current_user.org_id is not None and agent.owner_org_id != current_user.org_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    is_admin = ROLE_HIERARCHY.get(current_user.role, 999) <= ROLE_HIERARCHY[UserRole.admin]
    perm = get_effective_agent_permission(agent, current_user)
    if perm != "owner" and not is_admin:
        raise HTTPException(status_code=403, detail="Not authorized")
    if agent.status == AgentStatus.approved and not is_admin:
        raise HTTPException(status_code=400, detail="Cannot delete an approved listing. Contact an admin.")

    # Delete related records with correct type filters
    for r in (
        (await db.execute(select(Feedback).where(Feedback.listing_id == agent.id, Feedback.listing_type == "agent")))
        .scalars()
        .all()
    ):
        await db.delete(r)
    for r in (
        (
            await db.execute(
                select(Scorecard).where(Scorecard.agent_id == agent.id).options(selectinload(Scorecard.penalties))
            )
        )
        .scalars()
        .all()
    ):
        await db.delete(r)
    for r in (
        (
            await db.execute(
                select(EvalRun)
                .where(EvalRun.agent_id == agent.id)
                .options(selectinload(EvalRun.scorecards).selectinload(Scorecard.penalties))
            )
        )
        .scalars()
        .all()
    ):
        await db.delete(r)
    for r in (
        (await db.execute(select(AgentDownloadRecord).where(AgentDownloadRecord.agent_id == agent.id))).scalars().all()
    ):
        await db.delete(r)
    # Break circular FK (Agent.latest_version_id ↔ AgentVersion.agent_id)
    # then delete via raw SQL to avoid ORM cascade circular dependency.
    from sqlalchemy import delete as sql_delete

    agent_id_str = str(agent.id)
    agent_name = agent.name

    # Null out the self-referential FK first
    agent.latest_version_id = None
    await db.flush()

    # Delete versions via SQL (DB-level CASCADE handles children: components, goals)
    await db.execute(sql_delete(AgentVersion).where(AgentVersion.agent_id == agent.id))
    # Delete agent via SQL (avoids ORM cascade re-triggering on stale identity map)
    await db.execute(sql_delete(Agent).where(Agent.id == agent.id))
    await db.commit()

    emit_registry_event(
        action="agent.delete",
        user_id=str(current_user.id),
        user_email=current_user.email,
        user_role=current_user.role.value,
        agent_id=agent_id_str,
        resource_name=agent_name,
    )

    await audit(current_user, "agent.delete", resource_type="agent", resource_id=agent_id_str, resource_name=agent_name)

    return {"deleted": agent_id_str}


@router.patch("/{agent_id}/archive")
async def archive_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
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

    await audit(
        current_user, "agent.archive", resource_type="agent", resource_id=str(agent.id), resource_name=agent.name
    )

    return {"id": str(agent.id), "name": agent.name, "status": "archived"}


@router.patch("/{agent_id}/unarchive")
async def unarchive_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
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

    await audit(
        current_user, "agent.unarchive", resource_type="agent", resource_id=str(agent.id), resource_name=agent.name
    )

    return {"id": str(agent.id), "name": agent.name, "status": "approved"}


# ---------------------------------------------------------------------------
# Draft workflow
# ---------------------------------------------------------------------------


@router.post("/draft", response_model=AgentResponse)
async def save_draft(
    req: AgentCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    """Create an agent as a draft (relaxed validation, not submitted for review)."""
    agent = Agent(
        name=req.name,
        owner=req.owner or current_user.username or current_user.email,
        visibility=req.visibility,
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
        external_mcps=[m.model_dump() for m in req.external_mcps],
        supported_ides=req.supported_ides,
        status=AgentStatus.draft,
        released_by=current_user.id,
    )
    db.add(version)
    await db.flush()

    agent.latest_version_id = version.id

    # Legacy: mcp_server_ids -> AgentComponent(type=mcp)
    order = 0
    if not req.components and req.mcp_server_ids:
        for mid in req.mcp_server_ids:
            db.add(
                AgentComponent(
                    agent_version_id=version.id,
                    component_type="mcp",
                    component_id=mid,
                    component_name="",
                    resolved_version="latest",
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
    goal = AgentGoalTemplate(agent_version_id=version.id, description=req.goal_template.description)
    db.add(goal)
    await db.flush()
    for i, sec in enumerate(req.goal_template.sections):
        db.add(
            AgentGoalSection(
                goal_template_id=goal.id,
                name=sec.name,
                description=sec.description,
                grounding_required=sec.grounding_required,
                order=i,
            )
        )

    # Auto-infer IDE features for draft (use request data, not ORM relationship)
    all_crefs_draft = list(req.components) + [
        type("_Ref", (), {"component_type": "mcp", "component_id": mid})() for mid in req.mcp_server_ids
    ]
    skill_comp_ids = [c.component_id for c in all_crefs_draft if c.component_type == "skill"]
    skill_listings_map_draft: dict = {}
    if skill_comp_ids:
        rows = (await db.execute(select(SkillListing).where(SkillListing.id.in_(skill_comp_ids)))).scalars().all()
        skill_listings_map_draft = {row.id: row for row in rows}

    class _DraftProxy:
        components = all_crefs_draft
        external_mcps = version.external_mcps

    version.required_ide_features = infer_required_features(_DraftProxy(), skill_listings=skill_listings_map_draft)
    version.inferred_supported_ides = compute_supported_ides(version.required_ide_features)

    await db.commit()
    agent = await _load_agent(db, str(agent.id))
    await audit(
        current_user, "agent.draft.create", resource_type="agent", resource_id=str(agent.id), resource_name=agent.name
    )
    return _agent_to_response(agent, created_by_email=current_user.email, created_by_username=current_user.username)


@router.put("/{agent_id}/draft", response_model=AgentResponse)
async def update_draft(
    agent_id: str,
    req: AgentUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    """Update a draft agent."""
    agent = await _load_agent(db, agent_id, prefer_user_id=current_user.id, org_id=current_user.org_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if current_user.org_id is not None and agent.owner_org_id != current_user.org_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    perm = get_effective_agent_permission(agent, current_user)
    if perm not in ("owner", "edit"):
        raise HTTPException(status_code=403, detail="Not the agent owner or editor")
    if agent.status not in (AgentStatus.draft, AgentStatus.rejected, AgentStatus.pending):
        raise HTTPException(status_code=400, detail="Only draft, rejected, or pending agents can be edited")

    version = agent.latest_version
    if not version:
        raise HTTPException(status_code=400, detail="Agent has no version to update")

    for field in ("version", "description", "prompt", "model_name", "model_config_json", "supported_ides"):
        val = getattr(req, field)
        if val is not None:
            setattr(version, field, val)

    if req.external_mcps is not None:
        version.external_mcps = [m.model_dump() for m in req.external_mcps]

    if req.components is not None:
        version_id = version.id
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

    # Re-infer IDE features only when components or external_mcps changed
    if req.components is not None or req.external_mcps is not None:
        if not agent.latest_version:
            raise HTTPException(status_code=400, detail="Agent has no version to update features on")
        current_comps_draft = (
            (await db.execute(select(AgentComponent).where(AgentComponent.agent_version_id == version.id)))
            .scalars()
            .all()
        )
        skill_comp_ids = [c.component_id for c in current_comps_draft if c.component_type == "skill"]
        skill_listings_map_draft_update: dict = {}
        if skill_comp_ids:
            rows = (await db.execute(select(SkillListing).where(SkillListing.id.in_(skill_comp_ids)))).scalars().all()
            skill_listings_map_draft_update = {row.id: row for row in rows}

        class _DraftUpdateProxy:
            components = current_comps_draft
            external_mcps = version.external_mcps

        version.required_ide_features = infer_required_features(
            _DraftUpdateProxy(), skill_listings=skill_listings_map_draft_update
        )
        version.inferred_supported_ides = compute_supported_ides(version.required_ide_features)

    # Don't allow saving over another user's active lock
    if version.is_editing and version.editing_by != current_user.id and not _is_lock_expired(version.editing_since):
        raise HTTPException(
            status_code=409,
            detail="This item is currently being edited by another user. Please try again later.",
        )
    release_edit_lock(version, current_user.id, force=True)
    await db.flush()

    for field in ("name", "owner"):
        val = getattr(req, field)
        if val is not None:
            setattr(agent, field, val)

    await db.commit()
    agent = await _load_agent(db, str(agent.id))
    if agent.status == AgentStatus.pending:
        action = "agent.pending.update"
    elif agent.status == AgentStatus.rejected:
        action = "agent.rejected.update"
    else:
        action = "agent.draft.update"
    await audit(current_user, action, resource_type="agent", resource_id=str(agent.id), resource_name=agent.name)
    return _agent_to_response(agent, created_by_email=current_user.email, created_by_username=current_user.username)


@router.post("/{agent_id}/start-edit")
async def start_edit_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    agent = await _load_agent(db, agent_id, prefer_user_id=current_user.id, org_id=current_user.org_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    perm = get_effective_agent_permission(agent, current_user)
    if perm not in ("owner", "edit"):
        raise HTTPException(status_code=403, detail="Not the agent owner or editor")
    version = agent.latest_version
    if not version:
        raise HTTPException(status_code=400, detail="Agent has no version")
    if version.status not in (AgentStatus.pending, AgentStatus.draft, AgentStatus.rejected):
        raise HTTPException(status_code=400, detail=f"Cannot edit: agent version is '{version.status.value}'")
    # Re-fetch with row-level lock to prevent TOCTOU race
    version = (
        await db.execute(select(AgentVersion).where(AgentVersion.id == version.id).with_for_update())
    ).scalar_one()
    acquire_edit_lock(version, current_user.id)
    await db.commit()
    return {"status": "locked"}


@router.post("/{agent_id}/cancel-edit")
async def cancel_edit_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    agent = await _load_agent(db, agent_id, prefer_user_id=current_user.id, org_id=current_user.org_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    perm = get_effective_agent_permission(agent, current_user)
    if perm not in ("owner", "edit"):
        raise HTTPException(status_code=403, detail="Not the agent owner or editor")
    version = agent.latest_version
    if not version:
        raise HTTPException(status_code=400, detail="Agent has no version")
    release_edit_lock(version, current_user.id)
    await db.commit()
    return {"status": "unlocked"}


@router.post("/{agent_id}/submit", response_model=AgentResponse)
async def submit_draft(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    """Submit a draft agent for review (transitions draft -> pending)."""
    agent = await _load_agent(db, agent_id, prefer_user_id=current_user.id, org_id=current_user.org_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if current_user.org_id is not None and agent.owner_org_id != current_user.org_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    perm = get_effective_agent_permission(agent, current_user)
    if perm not in ("owner", "edit"):
        raise HTTPException(status_code=403, detail="Not the agent owner or editor")
    if agent.status not in (AgentStatus.draft, AgentStatus.rejected):
        raise HTTPException(status_code=400, detail="Agent is not a draft")
    if not agent.description:
        raise HTTPException(status_code=400, detail="Description is required before submitting")

    # Validate components exist
    if agent.components:
        from services.agent_resolver import validate_component_ids

        errors = await validate_component_ids(
            [{"component_type": c.component_type, "component_id": c.component_id} for c in agent.components],
            db,
        )
        if errors:
            raise HTTPException(
                status_code=400,
                detail=[
                    {"component_type": e.component_type, "component_id": str(e.component_id), "reason": e.reason}
                    for e in errors
                ],
            )

    agent.status = AgentStatus.pending
    await db.commit()
    agent = await _load_agent(db, str(agent.id))
    name_map = await _resolve_component_names(agent.components, db)

    emit_registry_event(
        action="agent.submit",
        user_id=str(current_user.id),
        user_email=current_user.email,
        user_role=current_user.role.value,
        agent_id=str(agent.id),
        resource_name=agent.name,
    )

    await audit(
        current_user, "agent.draft.submit", resource_type="agent", resource_id=str(agent.id), resource_name=agent.name
    )

    return _agent_to_response(
        agent, name_map, created_by_email=current_user.email, created_by_username=current_user.username
    )


from api.routes.agent_versions import agent_version_router  # noqa: E402

router.include_router(agent_version_router)
