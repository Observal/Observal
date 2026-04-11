import uuid
import uuid as _uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.deps import get_current_user, get_db
from models.agent import Agent, AgentGoalSection, AgentGoalTemplate, AgentStatus
from models.agent_component import AgentComponent
from models.download import AgentDownloadRecord
from models.mcp import ListingStatus, McpListing
from models.user import User
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

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])

# Eager-load options for Agent queries to avoid MissingGreenlet in async
_agent_load_options = [
    selectinload(Agent.components),
    selectinload(Agent.goal_template).selectinload(AgentGoalTemplate.sections),
]


def _agent_id_clause(agent_id: str):
    if isinstance(agent_id, _uuid.UUID):
        return Agent.id == agent_id
    try:
        uid = _uuid.UUID(agent_id)
        return Agent.id == uid
    except ValueError:
        return Agent.name == agent_id


async def _load_agent(db: AsyncSession, *where_clauses) -> Agent | None:
    stmt = select(Agent).where(*where_clauses).options(*_agent_load_options)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


def _agent_to_response(agent: Agent) -> AgentResponse:
    # Build mcp_links from components with component_type='mcp' (backwards compat)
    mcp_components = [c for c in agent.components if c.component_type == "mcp"]
    mcp_links = [
        McpLinkResponse(
            mcp_listing_id=comp.component_id,
            mcp_name="(component)",
            order=comp.order_index,
        )
        for comp in mcp_components
    ]
    # Build full component_links for all types
    component_links = [
        ComponentLinkResponse(
            component_type=comp.component_type,
            component_id=comp.component_id,
            version_ref=comp.version_ref,
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

    agent_dict = {c.key: getattr(agent, c.key) for c in Agent.__table__.columns}
    agent_dict["mcp_links"] = mcp_links
    agent_dict["component_links"] = component_links
    agent_dict["goal_template"] = goal_template
    return AgentResponse(**agent_dict)


async def _validate_mcp_ids(mcp_ids: list[uuid.UUID], db: AsyncSession) -> list[McpListing]:
    listings = []
    for mid in mcp_ids:
        result = await db.execute(
            select(McpListing).where(McpListing.id == mid, McpListing.status == ListingStatus.approved)
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
    current_user: User = Depends(get_current_user),
):
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

    agent = Agent(
        name=req.name,
        version=req.version,
        description=req.description,
        owner=req.owner,
        prompt=req.prompt,
        model_name=req.model_name,
        model_config_json=req.model_config_json,
        external_mcps=[m.model_dump() for m in req.external_mcps],
        supported_ides=req.supported_ides,
        created_by=current_user.id,
    )
    db.add(agent)
    await db.flush()

    # Legacy: mcp_server_ids → AgentComponent(type=mcp)
    order = 0
    for mid, listing in zip(req.mcp_server_ids, mcp_listings, strict=False):
        db.add(
            AgentComponent(
                agent_id=agent.id,
                component_type="mcp",
                component_id=mid,
                version_ref=listing.version,
                order_index=order,
            )
        )
        order += 1

    # New: components list with all types
    for cref in req.components:
        db.add(
            AgentComponent(
                agent_id=agent.id,
                component_type=cref.component_type,
                component_id=cref.component_id,
                version_ref="latest",
                order_index=order,
                config_override=cref.config_override,
            )
        )
        order += 1

    goal = AgentGoalTemplate(agent_id=agent.id, description=req.goal_template.description)
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

    await db.commit()
    agent = await _load_agent(db, Agent.id == agent.id)
    return _agent_to_response(agent)


@router.get("", response_model=list[AgentSummary])
async def list_agents(
    search: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    from models.feedback import Feedback

    stmt = select(Agent).where(Agent.status == AgentStatus.active).options(selectinload(Agent.components))
    if search:
        stmt = stmt.where(Agent.name.ilike(f"%{search}%") | Agent.description.ilike(f"%{search}%"))
    result = await db.execute(stmt.order_by(Agent.created_at.desc()))
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
            download_count=a.download_count,
            average_rating=rating_map.get(a.id),
            component_count=len(a.components),
            created_at=a.created_at,
            updated_at=a.updated_at,
        )
        for a in agents
    ]


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(agent_id: str, db: AsyncSession = Depends(get_db)):
    agent = await _load_agent(db, _agent_id_clause(agent_id))
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return _agent_to_response(agent)


@router.put("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: str,
    req: AgentUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    agent = await _load_agent(db, _agent_id_clause(agent_id))
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="Not the agent owner")

    for field in (
        "name",
        "version",
        "description",
        "owner",
        "prompt",
        "model_name",
        "model_config_json",
        "supported_ides",
    ):
        val = getattr(req, field)
        if val is not None:
            setattr(agent, field, val)

    if req.external_mcps is not None:
        agent.external_mcps = [m.model_dump() for m in req.external_mcps]

    if req.components is not None:
        # New components field replaces ALL components (type validated by Pydantic Literal)
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
        # Remove ALL old components
        old_comps = (
            (await db.execute(select(AgentComponent).where(AgentComponent.agent_id == agent.id))).scalars().all()
        )
        for comp in old_comps:
            await db.delete(comp)
        for i, cref in enumerate(req.components):
            db.add(
                AgentComponent(
                    agent_id=agent.id,
                    component_type=cref.component_type,
                    component_id=cref.component_id,
                    version_ref="latest",
                    order_index=i,
                    config_override=cref.config_override,
                )
            )
    elif req.mcp_server_ids is not None:
        # Legacy: only update MCP components
        mcp_listings = await _validate_mcp_ids(req.mcp_server_ids, db)
        old_comps = (
            (
                await db.execute(
                    select(AgentComponent).where(
                        AgentComponent.agent_id == agent.id,
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
                    agent_id=agent.id,
                    component_type="mcp",
                    component_id=mid,
                    version_ref=listing.version,
                    order_index=i,
                )
            )

    if req.goal_template is not None:
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
        goal = AgentGoalTemplate(agent_id=agent.id, description=req.goal_template.description)
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

    await db.commit()
    agent = await _load_agent(db, Agent.id == agent.id)
    return _agent_to_response(agent)


@router.post("/{agent_id}/install", response_model=AgentInstallResponse)
async def install_agent(
    agent_id: str,
    req: AgentInstallRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    agent = await _load_agent(db, _agent_id_clause(agent_id), Agent.status == AgentStatus.active)
    if not agent:
        agent = await _load_agent(db, _agent_id_clause(agent_id))
        if not agent or agent.created_by != current_user.id:
            raise HTTPException(status_code=404, detail="Agent not found or not active")

    # Pre-load MCP listings for config generation
    mcp_comp_ids = [c.component_id for c in agent.components if c.component_type == "mcp"]
    mcp_listings_map = {}
    if mcp_comp_ids:
        mcp_rows = (await db.execute(select(McpListing).where(McpListing.id.in_(mcp_comp_ids)))).scalars().all()
        mcp_listings_map = {row.id: row for row in mcp_rows}

    snippet = generate_agent_config(agent, req.ide, mcp_listings=mcp_listings_map)
    from services.download_tracker import record_agent_download

    await record_agent_download(
        agent_id=agent.id,
        user_id=current_user.id,
        source="api",
        ide=req.ide,
        request=request,
        db=db,
    )
    await db.commit()

    return AgentInstallResponse(agent_id=agent.id, ide=req.ide, config_snippet=snippet)


@router.get("/{agent_id}/downloads")
async def agent_download_stats(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
):
    agent = await _load_agent(db, _agent_id_clause(agent_id))
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    from services.download_tracker import get_download_stats

    stats = await get_download_stats(agent.id, db)
    return stats


@router.get("/{agent_id}/resolve")
async def resolve_agent_components(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Resolve all components for an agent — validates they exist and are approved."""
    agent = await _load_agent(db, _agent_id_clause(agent_id))
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    from services.agent_resolver import resolve_agent

    resolved = await resolve_agent(agent, db)
    from services.agent_builder import build_composition_summary

    return build_composition_summary(resolved)


@router.get("/{agent_id}/manifest")
async def get_agent_manifest(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate a portable agent manifest with all resolved components."""
    agent = await _load_agent(db, _agent_id_clause(agent_id))
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
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

    return build_agent_manifest(resolved)


@router.post("/validate", response_model=ValidationResult)
async def validate_agent_composition(
    req: AgentValidateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
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
    return ValidationResult(valid=len(issues) == 0, issues=issues)


@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from models.eval import EvalRun, Scorecard
    from models.feedback import Feedback

    agent = await _load_agent(db, _agent_id_clause(agent_id))
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.created_by != current_user.id and current_user.role.value != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    # Delete related records with correct type filters
    for r in (
        (await db.execute(select(Feedback).where(Feedback.listing_id == agent.id, Feedback.listing_type == "agent")))
        .scalars()
        .all()
    ):
        await db.delete(r)
    for r in (await db.execute(select(Scorecard).where(Scorecard.agent_id == agent.id))).scalars().all():
        await db.delete(r)
    for r in (await db.execute(select(EvalRun).where(EvalRun.agent_id == agent.id))).scalars().all():
        await db.delete(r)
    for r in (
        (await db.execute(select(AgentDownloadRecord).where(AgentDownloadRecord.agent_id == agent.id))).scalars().all()
    ):
        await db.delete(r)
    # AgentComponent, AgentGoalTemplate, AgentGoalSection handled by cascade="all, delete-orphan"

    await db.delete(agent)
    await db.commit()
    return {"deleted": str(agent.id)}
