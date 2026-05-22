# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Agent draft workflow routes: save, update, start/cancel edit, submit."""

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db, get_effective_agent_permission, require_role
from models.agent import Agent, AgentStatus, AgentVersion
from models.agent_component import AgentComponent
from models.skill import SkillListing
from models.user import User, UserRole
from schemas.agent import AgentCreateRequest, AgentResponse, AgentUpdateRequest
from services.audit_helpers import audit
from services.config_generator import validate_mcp_command
from services.editing_lock import _is_lock_expired, acquire_edit_lock, release_edit_lock
from services.ide_feature_inference import compute_supported_ides, infer_required_features
from services.registry_telemetry import emit_registry_event

from ._router import router
from .helpers import _agent_to_response, _load_agent, _resolve_component_names

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
        models_by_ide=req.models_by_ide,
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

    await db.flush()
    from services.agent_snapshot import build_yaml_snapshot

    version.yaml_snapshot = await build_yaml_snapshot(version, db)

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

    for field in (
        "version",
        "description",
        "prompt",
        "model_name",
        "model_config_json",
        "models_by_ide",
        "supported_ides",
    ):
        val = getattr(req, field)
        if val is not None:
            setattr(version, field, val)

    if req.external_mcps is not None:
        for _mcp in req.external_mcps:
            _cmd = getattr(_mcp, "command", "")
            _args = getattr(_mcp, "args", [])
            try:
                validate_mcp_command(_cmd, _args or [])
            except ValueError as e:
                raise HTTPException(status_code=422, detail=f"Invalid MCP command: {e}")
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

    # Always rebuild the snapshot so reviewers see the latest state including
    # per-IDE model overrides, prompt edits, and component swaps.
    from services.agent_snapshot import build_yaml_snapshot

    version.yaml_snapshot = await build_yaml_snapshot(version, db)

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

    # Scan for anti-gaming patterns before transitioning to pending
    from services.anti_gaming import scan_for_gaming, summarize_flags

    if agent.latest_version:
        flags = scan_for_gaming(agent.latest_version.prompt)
        agent.latest_version.gaming_flags = summarize_flags(flags)
        # Defensive refresh — covers older drafts created before snapshot
        # backfill landed and guarantees the reviewer sees current state.
        from services.agent_snapshot import build_yaml_snapshot

        agent.latest_version.yaml_snapshot = await build_yaml_snapshot(agent.latest_version, db)

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
