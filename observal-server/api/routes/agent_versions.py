"""Version-specific endpoints for agents.

Mounted on the /api/v1/agents router via::

    router.include_router(agent_version_router)

All paths are relative to /api/v1/agents (no extra prefix).
"""

from __future__ import annotations

import difflib
import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from api.deps import get_db, get_effective_agent_permission, require_role
from models.agent import (
    Agent,
    AgentGoalSection,
    AgentGoalTemplate,
    AgentStatus,
    AgentVersion,
)
from models.mcp import McpListing
from models.skill import SkillListing
from models.user import User, UserRole
from schemas.agent import (  # noqa: TC001
    AgentVersionCreateRequest,
    AgentVersionReviewRequest,
)
from services.agent_config_generator import generate_agent_config
from services.agent_resolver import validate_component_ids
from services.audit_helpers import audit
from services.ide_feature_inference import compute_supported_ides, infer_required_features
from services.versioning import parse_semver, validate_semver

logger = logging.getLogger(__name__)

agent_version_router = APIRouter()

# Import _load_agent from agent.py to avoid duplication.
# This is a late import done inside each function to avoid circular imports
# at module load time (agent.py imports from schemas.agent which we also import here).


def _version_to_summary(ver: AgentVersion) -> dict:
    """Serialize an AgentVersion to a list-view dict."""
    return {
        "id": str(ver.id),
        "agent_id": str(ver.agent_id),
        "version": ver.version,
        "description": ver.description,
        "status": ver.status.value if hasattr(ver.status, "value") else ver.status,
        "is_prerelease": ver.is_prerelease,
        "download_count": ver.download_count,
        "supported_ides": ver.supported_ides,
        "released_by": str(ver.released_by),
        "released_at": ver.released_at,
        "created_at": ver.created_at,
        "rejection_reason": ver.rejection_reason,
        "component_count": len(ver.components) if ver.components else 0,
    }


def _version_to_detail(ver: AgentVersion) -> dict:
    """Serialize an AgentVersion to a full-detail dict."""
    d = _version_to_summary(ver)
    d.update(
        {
            "prompt": ver.prompt,
            "model_name": ver.model_name,
            "model_config_json": ver.model_config_json,
            "external_mcps": ver.external_mcps,
            "yaml_snapshot": ver.yaml_snapshot,
            "ide_configs": ver.ide_configs,
            "required_ide_features": ver.required_ide_features,
            "inferred_supported_ides": ver.inferred_supported_ides,
        }
    )
    return d


# ---------------------------------------------------------------------------
# Standalone async functions — exposed for direct testing
# ---------------------------------------------------------------------------


async def _load_agent(db: AsyncSession, agent_id: str) -> Agent | None:
    """Thin wrapper that delegates to the route-level _load_agent."""
    from api.routes.agent import _load_agent as _base_load

    return await _base_load(db, agent_id)


async def _list_agent_versions(
    agent_id: str,
    page: int,
    page_size: int,
    db: AsyncSession,
    current_user: User,
) -> dict:
    agent = await _load_agent(db, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    perm = get_effective_agent_permission(agent, current_user)
    if perm == "none":
        raise HTTPException(status_code=403, detail="Insufficient permissions to view this agent")

    offset = (page - 1) * page_size
    stmt = (
        select(AgentVersion)
        .where(AgentVersion.agent_id == agent.id)
        .order_by(AgentVersion.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    versions = result.scalars().all()

    count_stmt = select(func.count(AgentVersion.id)).where(AgentVersion.agent_id == agent.id)
    total = (await db.execute(count_stmt)).scalar() or 0

    return {
        "items": [_version_to_summary(v) for v in versions],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def _get_agent_version(
    agent_id: str,
    version: str,
    db: AsyncSession,
    current_user: User,
) -> dict:
    agent = await _load_agent(db, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    perm = get_effective_agent_permission(agent, current_user)
    if perm == "none":
        raise HTTPException(status_code=403, detail="Insufficient permissions to view this agent")

    stmt = select(AgentVersion).where(
        AgentVersion.agent_id == agent.id,
        AgentVersion.version == version,
    )
    ver = (await db.execute(stmt)).scalar_one_or_none()
    if not ver:
        raise HTTPException(status_code=404, detail="Version not found")

    return _version_to_detail(ver)


async def _create_agent_version(
    agent_id: str,
    req: AgentVersionCreateRequest,
    db: AsyncSession,
    current_user: User,
) -> dict:
    # Validate semver (guard against mock objects in tests that bypass the schema validator)
    if not validate_semver(req.version):
        raise HTTPException(status_code=422, detail=f"Invalid semver string: {req.version!r}")

    agent = await _load_agent(db, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    is_owner = agent.created_by == current_user.id
    is_co_maintainer = str(current_user.id) in [str(uid) for uid in (agent.co_maintainers or [])]
    if not is_owner and not is_co_maintainer:
        raise HTTPException(status_code=403, detail="Not authorized to release versions")

    # Duplicate check
    dup_stmt = select(AgentVersion).where(
        AgentVersion.agent_id == agent.id,
        AgentVersion.version == req.version,
    )
    if (await db.execute(dup_stmt)).scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail=f"Version {req.version!r} already exists for this agent")

    # Validate components exist and are approved
    if req.components:
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

    # Check for existing pending versions to warn the caller
    pending_stmt = select(func.count(AgentVersion.id)).where(
        AgentVersion.agent_id == agent.id,
        AgentVersion.status == AgentStatus.pending,
    )
    pending_count = (await db.execute(pending_stmt)).scalar() or 0

    initial_status = AgentStatus.draft if req.save_as_draft else AgentStatus.pending
    now = datetime.now(UTC)
    ver = AgentVersion(
        agent_id=agent.id,
        version=req.version,
        description=req.description,
        prompt=req.prompt,
        model_name=req.model_name,
        model_config_json=req.model_config_json,
        external_mcps=[m.model_dump() for m in req.external_mcps] if req.external_mcps else [],
        supported_ides=req.supported_ides,
        yaml_snapshot=req.yaml_snapshot,
        is_prerelease=req.is_prerelease,
        status=initial_status,
        released_by=current_user.id,
        released_at=now,
    )
    db.add(ver)
    await db.flush()

    # Create AgentComponent records
    from models.agent_component import AgentComponent

    for order, cref in enumerate(req.components):
        db.add(
            AgentComponent(
                agent_version_id=ver.id,
                component_type=cref.component_type,
                component_id=cref.component_id,
                component_name="",
                resolved_version="latest",
                order_index=order,
                config_override=cref.config_override,
            )
        )

    # Create goal template if provided
    if req.goal_template is not None:
        goal = AgentGoalTemplate(agent_version_id=ver.id, description=req.goal_template.description)
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

    # Infer IDE features from components
    skill_comp_ids = [c.component_id for c in req.components if c.component_type == "skill"]
    skill_listings_map: dict = {}
    if skill_comp_ids:
        rows = (await db.execute(select(SkillListing).where(SkillListing.id.in_(skill_comp_ids)))).scalars().all()
        skill_listings_map = {row.id: row for row in rows}

    class _VersionProxy:
        components = req.components
        external_mcps = ver.external_mcps

    ver.required_ide_features = infer_required_features(_VersionProxy(), skill_listings=skill_listings_map)
    ver.inferred_supported_ides = compute_supported_ides(ver.required_ide_features)

    # Pre-generate IDE configs at release time (spec: no generation at request time)
    mcp_comp_ids = [c.component_id for c in req.components if c.component_type == "mcp"]
    mcp_listings_map: dict = {}
    if mcp_comp_ids:
        rows = (await db.execute(select(McpListing).where(McpListing.id.in_(mcp_comp_ids)))).scalars().all()
        mcp_listings_map = {row.id: row for row in rows}

    # Pre-generate IDE configs for supported_ides (the user-declared list).
    # inferred_supported_ides is a compatibility analysis result used for display/filtering,
    # but supported_ides is authoritative for which configs to generate.
    ide_configs: dict = {}
    failed_ides: list[str] = []
    for ide in ver.supported_ides or []:
        try:
            ide_configs[ide] = generate_agent_config(ver, ide, mcp_listings=mcp_listings_map)
        except Exception:
            logger.exception(
                "IDE config generation failed for agent=%s version=%s ide=%s", agent.name, req.version, ide
            )
            failed_ides.append(ide)
    ver.ide_configs = ide_configs or {}

    # Do NOT update latest_version_id — that happens on approval
    await db.commit()

    await audit(
        current_user,
        "agent.version.publish",
        resource_type="agent",
        resource_id=str(agent.id),
        resource_name=agent.name,
        detail=req.version,
    )

    warnings: list[str] = []
    if pending_count > 0:
        warnings.append(f"This agent already has {pending_count} pending version(s)")
    if failed_ides:
        warnings.append(
            f"IDE config generation failed for: {', '.join(failed_ides)}. These will 404 until regenerated."
        )

    result = {
        "id": str(ver.id),
        "agent_id": str(ver.agent_id),
        "version": ver.version,
        "status": ver.status.value,
        "description": ver.description,
        "model_name": ver.model_name,
        "supported_ides": ver.supported_ides,
        "released_by": str(ver.released_by),
        "released_at": ver.released_at,
        "created_at": ver.created_at,
    }
    if warnings:
        result["warnings"] = warnings
    return result


async def _review_agent_version(
    agent_id: str,
    version: str,
    req: AgentVersionReviewRequest,
    db: AsyncSession,
    current_user: User,
) -> dict:
    agent = await _load_agent(db, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    stmt = select(AgentVersion).where(
        AgentVersion.agent_id == agent.id,
        AgentVersion.version == version,
    )
    ver = (await db.execute(stmt)).scalar_one_or_none()
    if not ver:
        raise HTTPException(status_code=404, detail="Version not found")

    if ver.status != AgentStatus.pending:
        raise HTTPException(
            status_code=422, detail=f"Version is {ver.status.value!r}, only pending versions can be reviewed"
        )

    if req.action == "approve":
        ver.status = AgentStatus.approved
        ver.rejection_reason = None
        ver.reviewed_by = current_user.id
        ver.reviewed_at = datetime.now(UTC)
        # Flush version status change first to avoid CircularDependencyError
        # between Agent.latest_version (ManyToOne) and Agent.versions (OneToMany)
        await db.flush()
        # Update latest_version_id if this version is newer than (or equal to) the current latest
        current_latest = agent.latest_version
        new_parsed = parse_semver(ver.version)
        current_parsed = parse_semver(current_latest.version) if current_latest else None
        if not current_latest or (
            new_parsed is not None and current_parsed is not None and new_parsed >= current_parsed
        ):
            agent.latest_version_id = ver.id
    else:
        ver.status = AgentStatus.rejected
        ver.rejection_reason = req.reason
        ver.reviewed_by = current_user.id
        ver.reviewed_at = datetime.now(UTC)

    await db.commit()

    await audit(
        current_user,
        f"agent.version.{req.action}",
        resource_type="agent",
        resource_id=str(agent.id),
        resource_name=agent.name,
        detail=version,
    )

    return {
        "version": version,
        "new_status": ver.status.value,
        "reason": ver.rejection_reason,
    }


async def _get_agent_ide_config(
    agent_id: str,
    version: str,
    ide: str,
    db: AsyncSession,
    current_user: User,
) -> dict:
    agent = await _load_agent(db, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    perm = get_effective_agent_permission(agent, current_user)
    if perm == "none":
        raise HTTPException(status_code=403, detail="Insufficient permissions to view this agent")

    stmt = select(AgentVersion).where(
        AgentVersion.agent_id == agent.id,
        AgentVersion.version == version,
    )
    ver = (await db.execute(stmt)).scalar_one_or_none()
    if not ver:
        raise HTTPException(status_code=404, detail="Version not found")

    # Serve pre-generated config only — no generation at request time (spec requirement #8)
    if not ver.ide_configs or ide not in ver.ide_configs:
        raise HTTPException(
            status_code=404,
            detail=f"IDE '{ide}' not supported by this agent version. Available: {list(ver.ide_configs or {})}",
        )

    return ver.ide_configs[ide]


async def _get_version_diff(
    agent_id: str,
    v1: str,
    v2: str,
    db: AsyncSession,
    current_user: User,
) -> dict:
    agent = await _load_agent(db, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    perm = get_effective_agent_permission(agent, current_user)
    if perm == "none":
        raise HTTPException(status_code=403, detail="Insufficient permissions to view this agent")

    stmt1 = select(AgentVersion).where(AgentVersion.agent_id == agent.id, AgentVersion.version == v1)
    ver1 = (await db.execute(stmt1)).scalar_one_or_none()
    if not ver1:
        raise HTTPException(status_code=404, detail=f"Version {v1!r} not found")

    stmt2 = select(AgentVersion).where(AgentVersion.agent_id == agent.id, AgentVersion.version == v2)
    ver2 = (await db.execute(stmt2)).scalar_one_or_none()
    if not ver2:
        raise HTTPException(status_code=404, detail=f"Version {v2!r} not found")

    # Build YAML diff text
    def _structural_text(ver: AgentVersion) -> str:
        data = {
            "description": ver.description,
            "prompt": ver.prompt,
            "model_name": ver.model_name,
            "model_config_json": ver.model_config_json,
            "supported_ides": ver.supported_ides,
            "external_mcps": ver.external_mcps,
        }
        return json.dumps(data, indent=2, default=str)

    text1 = ver1.yaml_snapshot if ver1.yaml_snapshot is not None else _structural_text(ver1)
    text2 = ver2.yaml_snapshot if ver2.yaml_snapshot is not None else _structural_text(ver2)

    yaml_diff = "\n".join(
        line.rstrip("\n")
        for line in difflib.unified_diff(
            text1.splitlines(keepends=True),
            text2.splitlines(keepends=True),
            fromfile=f"v{v1}",
            tofile=f"v{v2}",
        )
    )

    # Compute component changes between versions
    comp1 = {(c.component_type, str(c.component_id)): c for c in (ver1.components or [])}
    comp2 = {(c.component_type, str(c.component_id)): c for c in (ver2.components or [])}
    component_changes = []
    for key, c in comp2.items():
        if key not in comp1:
            component_changes.append(
                {
                    "type": c.component_type,
                    "name": c.component_name or "",
                    "change": "added",
                    "version": c.resolved_version or "",
                }
            )
        elif comp1[key].resolved_version != c.resolved_version:
            component_changes.append(
                {
                    "type": c.component_type,
                    "name": c.component_name or "",
                    "change": "updated",
                    "from": comp1[key].resolved_version or "",
                    "to": c.resolved_version or "",
                }
            )
    for key, c in comp1.items():
        if key not in comp2:
            component_changes.append(
                {
                    "type": c.component_type,
                    "name": c.component_name or "",
                    "change": "removed",
                    "version": c.resolved_version or "",
                }
            )

    return {
        "agent_id": str(agent.id),
        "version_a": v1,
        "version_b": v2,
        "yaml_diff": yaml_diff,
        "component_changes": component_changes,
    }


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@agent_version_router.get("/{agent_id}/versions")
async def list_agent_versions(
    agent_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    return await _list_agent_versions(
        agent_id=agent_id,
        page=page,
        page_size=page_size,
        db=db,
        current_user=current_user,
    )


@agent_version_router.get("/{agent_id}/versions/{version}")
async def get_agent_version(
    agent_id: str,
    version: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    return await _get_agent_version(
        agent_id=agent_id,
        version=version,
        db=db,
        current_user=current_user,
    )


@agent_version_router.post("/{agent_id}/versions")
async def create_agent_version(
    agent_id: str,
    req: AgentVersionCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    return await _create_agent_version(
        agent_id=agent_id,
        req=req,
        db=db,
        current_user=current_user,
    )


@agent_version_router.post("/{agent_id}/versions/{version}/review")
async def review_agent_version(
    agent_id: str,
    version: str,
    req: AgentVersionReviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.reviewer)),
):
    return await _review_agent_version(
        agent_id=agent_id,
        version=version,
        req=req,
        db=db,
        current_user=current_user,
    )


@agent_version_router.get("/{agent_id}/versions/{version}/ide/{ide}")
async def get_agent_ide_config(
    agent_id: str,
    version: str,
    ide: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    return await _get_agent_ide_config(
        agent_id=agent_id,
        version=version,
        ide=ide,
        db=db,
        current_user=current_user,
    )


@agent_version_router.get("/{agent_id}/versions/{v1}/diff/{v2}")
async def get_version_diff(
    agent_id: str,
    v1: str,
    v2: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    return await _get_version_diff(
        agent_id=agent_id,
        v1=v1,
        v2=v2,
        db=db,
        current_user=current_user,
    )
