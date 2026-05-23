# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Admin data retention routes."""

import json

from fastapi import Depends, HTTPException
from loguru import logger as optic
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import services.dynamic_settings as ds
from api.deps import get_db, require_role
from models.user import User, UserRole
from schemas.retention import RetentionConfigResponse, RetentionConfigUpdate
from services.audit_helpers import audit
from services.security_events import EventType, SecurityEvent, Severity, emit_security_event

from ._router import router
from .helpers import _get_user_org

# ── Data Retention ─────────────────────────────────────────


@router.get("/org/retention")
async def get_retention_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
) -> RetentionConfigResponse:
    """Get the organization's data retention configuration."""
    optic.debug("admin retention get")
    org = await _get_user_org(db, current_user)
    global_days = await ds.get_int("retention.global_days")
    return RetentionConfigResponse(
        retention_enabled=org.retention_enabled,
        data_retention_days=org.data_retention_days,
        score_retention_days=org.score_retention_days,
        max_trace_count=org.max_trace_count,
        global_retention_days=global_days,
    )


@router.put("/org/retention")
async def update_retention_config(
    body: RetentionConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.super_admin)),
) -> RetentionConfigResponse:
    """Update the organization's data retention configuration. Super admin only."""
    optic.debug("update_retention_config: body={}", body)
    global_days = await ds.get_int("retention.global_days")
    if body.data_retention_days is not None and global_days > 0 and body.data_retention_days > global_days:
        raise HTTPException(
            status_code=422,
            detail=f"data_retention_days cannot exceed global ceiling of {global_days} days",
        )

    org = await _get_user_org(db, current_user)
    org.retention_enabled = body.retention_enabled
    org.data_retention_days = body.data_retention_days
    org.score_retention_days = body.score_retention_days
    org.max_trace_count = body.max_trace_count
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
            detail=f"Data retention {'enabled' if body.retention_enabled else 'disabled'}"
            f" (days={body.data_retention_days}, scores={body.score_retention_days}, max={body.max_trace_count})",
        )
    )
    await audit(
        current_user,
        "admin.retention.update",
        "retention",
        resource_id=str(org.id),
        detail=json.dumps(
            {
                "retention_enabled": body.retention_enabled,
                "data_retention_days": body.data_retention_days,
                "score_retention_days": body.score_retention_days,
                "max_trace_count": body.max_trace_count,
            }
        ),
    )

    return RetentionConfigResponse(
        retention_enabled=org.retention_enabled,
        data_retention_days=org.data_retention_days,
        score_retention_days=org.score_retention_days,
        max_trace_count=org.max_trace_count,
        global_retention_days=global_days,
    )


@router.get("/org/retention/preview")
async def preview_retention(
    days: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.super_admin)),
):
    """Preview approximate row counts that would be deleted for a given retention period."""
    optic.debug("preview_retention: days={}", days)
    if days < 7:
        raise HTTPException(status_code=422, detail="days must be >= 7")

    from services.clickhouse import _query

    org = await _get_user_org(db, current_user)
    project_id = str(org.id)

    counts = {}
    tables = {
        "traces": "SELECT count() as cnt FROM traces WHERE project_id = {pid:String} AND start_time < now() - INTERVAL {days:UInt32} DAY",
        "spans": "SELECT count() as cnt FROM spans WHERE project_id = {pid:String} AND start_time < now() - INTERVAL {days:UInt32} DAY",
        "scores": "SELECT count() as cnt FROM scores WHERE project_id = {pid:String} AND timestamp < now() - INTERVAL {days:UInt32} DAY",
        "session_events": "SELECT count() as cnt FROM session_events WHERE project_id = {pid:String} AND timestamp < now() - INTERVAL {days:UInt32} DAY",
    }

    for table_name, sql in tables.items():
        try:
            resp = await _query(sql + " FORMAT JSON", {"param_pid": project_id, "param_days": str(days)})
            if resp.status_code == 200:
                data = resp.json().get("data", [{}])
                counts[table_name] = int(data[0].get("cnt", 0)) if data else 0
            else:
                counts[table_name] = -1
        except Exception:
            counts[table_name] = -1

    # Count insight reports from PostgreSQL
    from datetime import UTC, datetime, timedelta

    from models.agent import Agent
    from models.insight_report import InsightReport, InsightReportStatus

    score_cutoff = datetime.now(UTC) - timedelta(days=days * 2)
    agent_ids = (await db.execute(select(Agent.id).where(Agent.owner_org_id == org.id))).scalars().all()
    if agent_ids:
        report_count = (
            await db.execute(
                select(func.count())
                .select_from(InsightReport)
                .where(
                    InsightReport.agent_id.in_(agent_ids),
                    InsightReport.completed_at < score_cutoff,
                    InsightReport.status == InsightReportStatus.completed,
                )
            )
        ).scalar() or 0
    else:
        report_count = 0

    counts["insight_reports"] = report_count
    counts["_note"] = "approximate; counts may be higher if a purge ran recently"
    return counts


@router.get("/org/retention/stats")
async def get_retention_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Get retention statistics for the dashboard widget."""
    optic.debug("get_retention_stats called")
    org = await _get_user_org(db, current_user)
    if not org.retention_enabled:
        return {
            "retention_enabled": False,
            "data_retention_days": org.data_retention_days,
            "score_retention_days": org.score_retention_days,
            "total_traces": 0,
            "oldest_trace_age_days": 0,
            "traces_expiring_7d": 0,
            "next_purge_approx": None,
        }

    from services.clickhouse import _query

    project_id = str(org.id)

    # Get total traces and oldest trace
    total_traces = 0
    oldest_age_days = 0
    try:
        resp = await _query(
            "SELECT count() as cnt, "
            "if(cnt > 0, dateDiff('day', min(start_time), now()), 0) as age "
            "FROM traces WHERE project_id = {pid:String} FORMAT JSON",
            {"param_pid": project_id},
        )
        if resp.status_code == 200:
            data = resp.json().get("data", [{}])
            if data:
                total_traces = int(data[0].get("cnt", 0))
                oldest_age_days = int(data[0].get("age", 0)) if total_traces > 0 else 0
    except Exception:
        pass

    # Get traces expiring in 7 days
    traces_expiring = 0
    if org.data_retention_days:
        try:
            cutoff_soon = org.data_retention_days - 7
            if cutoff_soon > 0:
                resp = await _query(
                    "SELECT count() as cnt FROM traces "
                    "WHERE project_id = {pid:String} "
                    "AND start_time < now() - INTERVAL {days:UInt32} DAY "
                    "FORMAT JSON",
                    {"param_pid": project_id, "param_days": str(cutoff_soon)},
                )
                if resp.status_code == 200:
                    data = resp.json().get("data", [{}])
                    if data:
                        traces_expiring = int(data[0].get("cnt", 0))
        except Exception:
            pass

    return {
        "retention_enabled": True,
        "data_retention_days": org.data_retention_days,
        "score_retention_days": org.score_retention_days,
        "total_traces": total_traces,
        "oldest_trace_age_days": oldest_age_days,
        "traces_expiring_7d": traces_expiring,
        "next_purge_approx": "Every 6 hours (01:30, 07:30, 13:30, 19:30 UTC)",
    }


@router.get("/org/retention/warnings")
async def get_retention_warnings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Get agents with unanalyzed traces approaching expiry."""
    optic.debug("get_retention_warnings called")
    org = await _get_user_org(db, current_user)
    if not org.retention_enabled or not org.data_retention_days:
        return {"warnings": [], "retention_days": org.data_retention_days, "retention_enabled": org.retention_enabled}

    from models.agent import Agent
    from models.insight_report import InsightReport, InsightReportStatus

    # Get all agents for this org
    agents_result = await db.execute(select(Agent.id, Agent.name).where(Agent.owner_org_id == org.id))
    agents = agents_result.all()
    if not agents:
        return {"warnings": [], "retention_days": org.data_retention_days, "retention_enabled": True}

    # Get latest completed report per agent
    latest_reports = {}
    for agent_id, _ in agents:
        report = (
            await db.execute(
                select(InsightReport.completed_at)
                .where(
                    InsightReport.agent_id == agent_id,
                    InsightReport.status == InsightReportStatus.completed,
                )
                .order_by(InsightReport.completed_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        latest_reports[agent_id] = report

    # Find agents without a recent report covering the retention window
    from datetime import UTC, datetime, timedelta

    retention_start = datetime.now(UTC) - timedelta(days=org.data_retention_days)
    warnings = []
    for agent_id, agent_name in agents:
        last_report = latest_reports.get(agent_id)
        if last_report is None or last_report < retention_start:
            warnings.append(
                {
                    "agent_id": str(agent_id),
                    "agent_name": agent_name or "Unnamed Agent",
                    "traces_expiring_soon": 0,
                    "last_insight_report": last_report.isoformat() if last_report else None,
                }
            )

    return {"warnings": warnings, "retention_days": org.data_retention_days, "retention_enabled": True}
