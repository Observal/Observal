# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Agent install, download stats, traces, resolve, manifest, and validate routes."""

from fastapi import Depends, HTTPException, Query, Request
from loguru import logger as optic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import services.dynamic_settings as _ds
from api.deps import (
    get_db,
    get_effective_agent_permission,
    optional_current_user,
    require_role,
)
from api.routes._component_archive import archived_install_warning
from models.agent import AgentStatus
from models.hook import HookListing
from models.mcp import ListingStatus, McpListing
from models.prompt import PromptListing
from models.sandbox import SandboxListing
from models.skill import SkillListing
from models.user import User, UserRole
from schemas.agent import (
    AgentInstallRequest,
    AgentInstallResponse,
    AgentValidateRequest,
    ValidationIssue,
    ValidationResult,
)
from services.ide import generate_agent_config
from services.registry_telemetry import emit_registry_event

from ._router import router
from .helpers import _load_agent, _resolve_component_names


@router.post("/{agent_id}/install", response_model=AgentInstallResponse)
async def install_agent(
    agent_id: str,
    req: AgentInstallRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    optic.debug("installing agent")
    agent = await _load_agent(
        db,
        agent_id,
        prefer_user_id=current_user.id,
        org_id=current_user.org_id,
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.status != AgentStatus.approved and not (
        _ds.get_sync_bool("security.allow_draft_install") and agent.created_by == current_user.id
    ):
        raise HTTPException(status_code=404, detail="Agent not found or not approved for installation")
    if current_user.org_id is not None and agent.owner_org_id != current_user.org_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    if get_effective_agent_permission(agent, current_user) == "none":
        raise HTTPException(status_code=403, detail="Insufficient permissions to install this agent")

    # Resolve specific version if requested, otherwise use latest
    if req.version:
        from models.agent import AgentVersion

        version_stmt = select(AgentVersion).where(
            AgentVersion.agent_id == agent.id,
            AgentVersion.version == req.version,
            AgentVersion.status == AgentStatus.approved,
        )
        version_result = await db.execute(version_stmt)
        target_version = version_result.scalar_one_or_none()
        if not target_version:
            raise HTTPException(
                status_code=404,
                detail=f"Version {req.version!r} not found or not approved for this agent",
            )
        # Use the target version for config gen without mutating the ORM object
        # (dirtying agent would persist on db.commit and corrupt latest_version for all users)
        install_version = target_version  # noqa: F841
    elif not agent.latest_version:
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
        hook_rows = (
            (
                await db.execute(
                    select(HookListing)
                    .options(selectinload(HookListing.latest_version))
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
        prompt_rows = (
            (
                await db.execute(
                    select(PromptListing)
                    .options(selectinload(PromptListing.latest_version))
                    .where(PromptListing.id.in_(prompt_comp_ids))
                )
            )
            .scalars()
            .all()
        )
        prompt_listings_map = {row.id: row for row in prompt_rows}

    # Pre-load sandbox listings for rules content injection
    sandbox_comp_ids = [c.component_id for c in agent.components if c.component_type == "sandbox"]
    sandbox_listings_map = {}
    if sandbox_comp_ids:
        sandbox_rows = (
            (
                await db.execute(
                    select(SandboxListing)
                    .options(selectinload(SandboxListing.latest_version))
                    .where(SandboxListing.id.in_(sandbox_comp_ids))
                )
            )
            .scalars()
            .all()
        )
        sandbox_listings_map = {row.id: row for row in sandbox_rows}

    archived_warnings = []
    for item_type, rows in (
        ("MCP", mcp_listings_map.values()),
        ("skill", skill_listings_map.values()),
        ("hook", hook_listings_map.values()),
        ("prompt", prompt_listings_map.values()),
        ("sandbox", sandbox_listings_map.values()),
    ):
        for row in rows:
            if row.status == ListingStatus.archived:
                archived_warnings.append(archived_install_warning(item_type, row.name))

    # Resolve all component names for rules file content
    name_map = await _resolve_component_names(agent.components, db)

    from api.routes.config import derive_endpoints
    from services.model_resolver import resolve_model_for_ide

    endpoints = await derive_endpoints(request)

    install_options: dict = dict(req.options or {})
    raw_override = install_options.get("model") or None
    if isinstance(raw_override, str) and raw_override.strip().lower() == "inherit":
        raw_override = None
    resolved_model, model_warnings = await resolve_model_for_ide(
        req.ide,
        model_name=getattr(agent, "model_name", "") or "",
        models_by_ide=getattr(agent, "models_by_ide", {}) or {},
        override=raw_override,
    )
    install_options["_resolved_model"] = resolved_model
    install_options["_model_warnings"] = model_warnings

    snippet = generate_agent_config(
        agent,
        req.ide,
        observal_url=endpoints["api"],
        mcp_listings=mcp_listings_map,
        component_names=name_map,
        env_values=req.env_values,
        options=install_options,
        platform=req.platform,
        skill_listings=skill_listings_map,
        hook_listings=hook_listings_map,
        prompt_listings=prompt_listings_map,
        sandbox_listings=sandbox_listings_map,
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

    warnings = archived_warnings + snippet.pop("_warnings", [])
    return AgentInstallResponse(agent_id=resolved_agent_id, ide=req.ide, config_snippet=snippet, warnings=warnings)


@router.get("/{agent_id}/downloads")
async def agent_download_stats(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_current_user),
):
    optic.trace("agent_id={}", agent_id)
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
    optic.trace("agent_id={}, limit={}", agent_id, limit)
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
    return {"agent_id": str(agent.id), "traces": traces, "count": len(traces)}


@router.get("/{agent_id}/resolve")
async def resolve_agent_components(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    """Resolve all components for an agent - validates they exist and are approved."""
    optic.trace("agent_id={}", agent_id)
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

    return build_composition_summary(resolved)


@router.get("/{agent_id}/manifest")
async def get_agent_manifest(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    """Generate a portable agent manifest with all resolved components."""
    optic.trace("agent_id={}", agent_id)
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

    return build_agent_manifest(resolved)


@router.post("/validate", response_model=ValidationResult)
async def validate_agent_composition(
    req: AgentValidateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    """Validate a set of components for compatibility before publishing an agent."""
    optic.trace("req={}", req)
    if not req.components:
        return ValidationResult(valid=True, issues=[])

    from services.agent_resolver import validate_component_ids

    errors = await validate_component_ids(
        [{"component_type": c.component_type, "component_id": c.component_id} for c in req.components],
        db,
        require_approved=False,
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
