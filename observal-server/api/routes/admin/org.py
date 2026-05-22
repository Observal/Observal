# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Admin organization settings routes: security events, trace privacy, registered agents, cache, resources."""

import json
import logging

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db, require_role
from models.organization import Organization
from models.user import User, UserRole
from services.audit_helpers import audit
from services.security_events import EventType, SecurityEvent, Severity, emit_security_event

from ._router import router

logger = logging.getLogger(__name__)


@router.get("/security-events")
async def get_security_events(
    event_type: str | None = None,
    severity: str | None = None,
    actor_email: str | None = None,
    limit: int = 100,
    offset: int = 0,
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Query the security events audit log from ClickHouse."""
    from services.clickhouse import _query

    conditions = ["1 = 1"]
    params: dict[str, str] = {}
    if event_type:
        conditions.append("event_type = {et:String}")
        params["param_et"] = event_type
    if severity:
        conditions.append("severity = {sev:String}")
        params["param_sev"] = severity
    if actor_email:
        conditions.append("actor_email = {ae:String}")
        params["param_ae"] = actor_email

    where = " AND ".join(conditions)
    limit = min(max(int(limit), 1), 1000)
    offset = max(int(offset), 0)
    sql = (
        f"SELECT * FROM security_events WHERE {where} ORDER BY timestamp DESC LIMIT {limit} OFFSET {offset} FORMAT JSON"
    )
    try:
        r = await _query(sql, params)
        r.raise_for_status()
        data = r.json()
        await audit(current_user, "admin.audit_log.view", "audit_log")
        return {"events": data.get("data", []), "total": data.get("rows", 0)}
    except Exception as e:
        logger.warning("Audit log query failed: %s", e)
        await audit(current_user, "admin.audit_log.view", "audit_log", detail="query_failed")
        return {"events": [], "total": 0}


# ── Trace Privacy ──────────────────────────────────────────


@router.get("/org/trace-privacy")
async def get_trace_privacy(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Get the trace privacy setting for the current user's organization."""
    if not current_user.org_id:
        await audit(current_user, "admin.trace_privacy.view", "trace_privacy")
        return {"trace_privacy": False}
    result = await db.execute(select(Organization).where(Organization.id == current_user.org_id))
    org = result.scalar_one_or_none()
    if not org:
        await audit(current_user, "admin.trace_privacy.view", "trace_privacy")
        return {"trace_privacy": False}
    await audit(current_user, "admin.trace_privacy.view", "trace_privacy", resource_id=str(org.id))
    return {"trace_privacy": org.trace_privacy}


@router.put("/org/trace-privacy")
async def set_trace_privacy(
    req: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Toggle trace privacy for the current user's organization.

    When enabled, all roles below super-admin can only see their own
    traces.  Super-admins always retain full visibility.
    """
    enabled = bool(req.get("trace_privacy", False))

    if not current_user.org_id:
        raise HTTPException(status_code=400, detail="User has no organization")

    result = await db.execute(select(Organization).where(Organization.id == current_user.org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    org.trace_privacy = enabled
    await db.commit()
    await db.refresh(org)
    await emit_security_event(
        SecurityEvent(
            event_type=EventType.SETTING_CHANGED,
            severity=Severity.WARNING,
            outcome="success",
            actor_id=str(current_user.id),
            actor_email=current_user.email,
            actor_role=current_user.role.value,
            target_id=str(org.id),
            target_type="organization",
            detail=f"Trace privacy {'enabled' if enabled else 'disabled'}",
        )
    )
    await audit(
        current_user,
        "admin.trace_privacy.update",
        "trace_privacy",
        resource_id=str(org.id),
        detail=json.dumps({"enabled": enabled}),
    )
    return {"trace_privacy": org.trace_privacy}


# ── Registered Agents Only ─────────────────────────────────


@router.get("/org/registered-agents-only")
async def get_registered_agents_only(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.user)),
):
    """Get the registered-agents-only setting for the current user's organization."""
    if not current_user.org_id:
        await audit(current_user, "admin.registered_agents_only.view", "registered_agents_only")
        return {"registered_agents_only": False}
    result = await db.execute(select(Organization).where(Organization.id == current_user.org_id))
    org = result.scalar_one_or_none()
    if not org:
        await audit(current_user, "admin.registered_agents_only.view", "registered_agents_only")
        return {"registered_agents_only": False}
    await audit(current_user, "admin.registered_agents_only.view", "registered_agents_only", resource_id=str(org.id))
    return {"registered_agents_only": org.registered_agents_only}


@router.put("/org/registered-agents-only")
async def set_registered_agents_only(
    req: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.super_admin)),
):
    """Toggle registered-agents-only mode for the current user's organization.

    When enabled, only registered (active) agents are traced.
    Unregistered agent telemetry is stored as metadata-only (no content).
    """
    enabled = bool(req.get("registered_agents_only", False))

    if not current_user.org_id:
        raise HTTPException(status_code=400, detail="User has no organization")

    result = await db.execute(select(Organization).where(Organization.id == current_user.org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    org.registered_agents_only = enabled
    await db.commit()
    await db.refresh(org)
    await emit_security_event(
        SecurityEvent(
            event_type=EventType.SETTING_CHANGED,
            severity=Severity.WARNING,
            outcome="success",
            actor_id=str(current_user.id),
            actor_email=current_user.email,
            actor_role=current_user.role.value,
            target_id=str(org.id),
            target_type="organization",
            detail=f"Registered-agents-only {'enabled' if enabled else 'disabled'}",
        )
    )
    await audit(
        current_user,
        "admin.registered_agents_only.update",
        "registered_agents_only",
        resource_id=str(org.id),
        detail=json.dumps({"enabled": enabled}),
    )
    # Invalidate registry cache so all server instances pick up the change immediately
    from services.agent_registry_cache import invalidate as invalidate_registry_cache

    await invalidate_registry_cache()
    return {"registered_agents_only": org.registered_agents_only}


@router.post("/cache/clear")
async def clear_cache(current_user: User = Depends(require_role(UserRole.admin))):
    """Clear all cached dashboard and OTEL responses."""
    from services.cache import invalidate_all

    deleted = await invalidate_all()
    await audit(current_user, "admin.cache.clear", "cache", detail=json.dumps({"cleared": deleted}))
    return {"cleared": deleted}


@router.post("/fix-agent-org")
async def fix_agent_org(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Fix agents missing owner_org_id by setting it from the creator's org."""
    from models.agent import Agent, AgentVisibility

    result = await db.execute(select(Agent).where(Agent.owner_org_id.is_(None)))
    agents = result.scalars().all()
    fixed = 0
    for agent in agents:
        creator = (await db.execute(select(User).where(User.id == agent.created_by))).scalar_one_or_none()
        if creator and creator.org_id:
            agent.owner_org_id = creator.org_id
            agent.visibility = AgentVisibility.public
            fixed += 1
    await db.commit()
    await audit(current_user, "admin.fix_agent_org", detail=json.dumps({"fixed": fixed}))
    return {"fixed": fixed, "total_checked": len(agents)}
