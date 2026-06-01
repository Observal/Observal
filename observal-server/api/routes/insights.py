# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Hemalatha Madeswaran <hemalathamadeswaran@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Agent Insights API endpoints."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from loguru import logger as optic
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db, require_role, resolve_prefix_id
from models.agent import Agent
from models.insight_meta_cache import InsightMetaCache
from models.insight_report import InsightReport, InsightReportStatus
from models.insight_session_facets import InsightSessionFacets
from models.user import User, UserRole
from schemas.insights import (
    ApplySuggestionsRequest,
    GenerateInsightRequest,
    InsightReportListItem,
    InsightReportResponse,
)
from services.insights import INSIGHTS_AVAILABLE, render_report_html
from services.redis import _get_arq_pool

router = APIRouter(prefix="/api/v1/insights", tags=["insights"])


def _require_insights():
    """Raise 402 if the insights package is not installed."""
    if not INSIGHTS_AVAILABLE:
        raise HTTPException(
            status_code=402,
            detail="Insights is an enterprise feature. Contact sales for access.",
        )


@router.get("/status")
async def insights_status(current_user: User = Depends(require_role(UserRole.admin))):
    """Return whether insights is available and properly configured."""
    import services.dynamic_settings as ds

    if not INSIGHTS_AVAILABLE:
        return {"available": False, "reason": "Insights requires an enterprise license."}

    model = await ds.get("insights.model_sections")
    if not model:
        return {"available": False, "reason": "No model configured. Set insights.model_sections in admin settings."}

    # If a direct API key is configured, skip AWS credential checks
    api_key = await ds.get("insights.api_key")

    # Check if AWS credentials are set and valid (for Bedrock models)
    if "anthropic" in model and not api_key:
        aws_key = await ds.get("insights.aws_access_key_id")
        aws_secret = await ds.get("insights.aws_secret_access_key")
        if not aws_key:
            return {
                "available": False,
                "reason": "AWS access key not configured. Set insights.aws_access_key_id in admin settings.",
            }
        if not aws_secret:
            return {
                "available": False,
                "reason": "AWS secret key not configured. Set insights.aws_secret_access_key in admin settings.",
            }

        # Validate credentials with a lightweight STS call
        try:
            import boto3

            region = await ds.get("insights.aws_region") or "us-east-1"
            sts = boto3.client(
                "sts",
                region_name=region,
                aws_access_key_id=aws_key,
                aws_secret_access_key=aws_secret,
            )
            sts.get_caller_identity()
        except Exception as e:
            error_str = str(e)
            if "InvalidClientTokenId" in error_str or "security token" in error_str:
                return {
                    "available": False,
                    "reason": "AWS access key is invalid. Update insights.aws_access_key_id in admin settings.",
                }
            if "SignatureDoesNotMatch" in error_str:
                return {
                    "available": False,
                    "reason": "AWS secret key is invalid. Update insights.aws_secret_access_key in admin settings.",
                }
            if "ExpiredToken" in error_str:
                return {
                    "available": False,
                    "reason": "AWS credentials have expired. Update credentials in admin settings.",
                }
            return {
                "available": False,
                "reason": "AWS credential check failed. Verify your access key and secret in admin settings.",
            }

    return {"available": True, "reason": None}


@router.get("/agents/{agent_id}/session-count")
async def agent_session_count(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Return the number of sessions available for insight generation."""
    from services.clickhouse import _query

    agent = await resolve_prefix_id(Agent, agent_id, db)
    now = datetime.now(UTC)
    period_start = now - timedelta(days=14)

    count_sql = (
        "SELECT count() AS cnt FROM session_stats_agg FINAL "
        "WHERE (agent_id = {agent_id:String} OR agent_id = {agent_name:String}) "
        "AND last_event_time >= {t_start:String} "
        "AND last_event_time <= {t_end:String} "
        "FORMAT JSON"
    )
    try:
        r = await _query(
            count_sql,
            {
                "param_agent_id": str(agent.id),
                "param_agent_name": agent.name,
                "param_t_start": period_start.strftime("%Y-%m-%d %H:%M:%S"),
                "param_t_end": now.strftime("%Y-%m-%d %H:%M:%S"),
            },
        )
        count_data = r.json().get("data", []) if r.status_code == 200 else []
        count = int(count_data[0]["cnt"]) if count_data else 0
    except Exception:
        count = 0

    return {"session_count": count}


@router.post("/agents/{agent_id}/generate", response_model=InsightReportListItem)
async def generate_insight(
    agent_id: str,
    req: GenerateInsightRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Trigger generation of an insight report for an agent."""
    optic.trace("agent_id={}, req={}", agent_id, req)
    _require_insights()
    agent = await resolve_prefix_id(Agent, agent_id, db)

    if current_user.org_id is not None and agent.owner_org_id != current_user.org_id:
        raise HTTPException(status_code=403, detail="Agent does not belong to your organization")

    period_days = req.period_days if req else 14
    now = datetime.now(UTC)
    period_start = now - timedelta(days=period_days)

    # Check if there are any sessions for this agent in the period
    from services.clickhouse import _query

    count_sql = (
        "SELECT count() AS cnt FROM session_stats_agg FINAL "
        "WHERE (agent_id = {agent_id:String} OR agent_id = {agent_name:String}) "
        "AND last_event_time >= {t_start:String} "
        "AND last_event_time <= {t_end:String} "
        "FORMAT JSON"
    )
    try:
        r = await _query(
            count_sql,
            {
                "param_agent_id": str(agent.id),
                "param_agent_name": agent.name,
                "param_t_start": period_start.strftime("%Y-%m-%d %H:%M:%S"),
                "param_t_end": now.strftime("%Y-%m-%d %H:%M:%S"),
            },
        )
        count_data = r.json().get("data", []) if r.status_code == 200 else []
        session_count = int(count_data[0]["cnt"]) if count_data else 0
    except Exception:
        session_count = 0

    if session_count == 0:
        raise HTTPException(
            status_code=422,
            detail=f"No sessions found for this agent in the last {period_days} days. Cannot generate a report.",
        )

    # Find previous completed report for regression linking
    prev_stmt = (
        select(InsightReport)
        .where(
            InsightReport.agent_id == agent.id,
            InsightReport.status == InsightReportStatus.completed,
        )
        .order_by(InsightReport.created_at.desc())
        .limit(1)
    )
    prev_result = await db.execute(prev_stmt)
    prev_report = prev_result.scalar_one_or_none()

    report = InsightReport(
        agent_id=agent.id,
        triggered_by=current_user.id,
        status=InsightReportStatus.pending,
        period_start=period_start,
        period_end=now,
        started_at=now,
        previous_report_id=prev_report.id if prev_report else None,
    )
    db.add(report)
    await db.flush()

    # Enqueue background job
    pool = await _get_arq_pool()
    await pool.enqueue_job("generate_insight_report", str(report.id))
    await db.commit()

    return InsightReportListItem.model_validate(report)


@router.get("/agents/{agent_id}/reports", response_model=list[InsightReportListItem])
async def list_reports(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """List insight reports for an agent, newest first."""
    optic.trace("agent_id={}", agent_id)
    _require_insights()
    agent = await resolve_prefix_id(Agent, agent_id, db)

    if current_user.org_id is not None and agent.owner_org_id != current_user.org_id:
        raise HTTPException(status_code=403, detail="Agent does not belong to your organization")

    stmt = (
        select(InsightReport)
        .where(InsightReport.agent_id == agent.id)
        .order_by(InsightReport.created_at.desc())
        .limit(20)
    )
    result = await db.execute(stmt)
    reports = result.scalars().all()
    return [InsightReportListItem.model_validate(r) for r in reports]


@router.get("/reports/{report_id}", response_model=InsightReportResponse)
async def get_report(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Get a single insight report by ID."""
    optic.trace("report_id={}", report_id)
    _require_insights()
    stmt = select(InsightReport).where(InsightReport.id == report_id)
    result = await db.execute(stmt)
    report = result.scalar_one_or_none()

    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    # Org-scope check via agent
    agent_stmt = select(Agent).where(Agent.id == report.agent_id)
    agent_result = await db.execute(agent_stmt)
    agent = agent_result.scalar_one_or_none()
    if agent and current_user.org_id is not None and agent.owner_org_id != current_user.org_id:
        raise HTTPException(status_code=403, detail="Agent does not belong to your organization")

    return InsightReportResponse.model_validate(report)


@router.get("/reports/{report_id}/export/html", response_class=HTMLResponse)
async def export_report_html(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Export an insight report as a self-contained HTML document."""
    optic.trace("report_id={}", report_id)
    _require_insights()
    stmt = select(InsightReport).where(InsightReport.id == report_id)
    result = await db.execute(stmt)
    report = result.scalar_one_or_none()

    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    if report.status != InsightReportStatus.completed:
        raise HTTPException(status_code=400, detail="Report is not yet completed")

    # Org-scope check
    agent_stmt = select(Agent).where(Agent.id == report.agent_id)
    agent_result = await db.execute(agent_stmt)
    agent = agent_result.scalar_one_or_none()
    if agent and current_user.org_id is not None and agent.owner_org_id != current_user.org_id:
        raise HTTPException(status_code=403, detail="Agent does not belong to your organization")

    # Build report dict for the renderer
    report_data = {
        "id": str(report.id),
        "agent_id": str(report.agent_id),
        "status": report.status.value if hasattr(report.status, "value") else str(report.status),
        "period_start": report.period_start,
        "period_end": report.period_end,
        "metrics": report.metrics,
        "narrative": report.narrative,
        "sessions_analyzed": report.sessions_analyzed,
    }

    html_content = render_report_html(report_data)

    return HTMLResponse(
        content=html_content,
        headers={
            "Content-Disposition": f'attachment; filename="insight-report-{report_id[:8]}.html"',
        },
    )


@router.delete("/agents/{agent_id}/reports")
async def clear_agent_reports(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Delete all insight reports and cached data for an agent."""
    optic.trace("agent_id={}", agent_id)
    _require_insights()
    agent = await resolve_prefix_id(Agent, agent_id, db)

    if current_user.org_id is not None and agent.owner_org_id != current_user.org_id:
        raise HTTPException(status_code=403, detail="Agent does not belong to your organization")

    # Delete reports
    report_result = await db.execute(delete(InsightReport).where(InsightReport.agent_id == agent.id))

    # Delete cached session facets
    facets_result = await db.execute(delete(InsightSessionFacets).where(InsightSessionFacets.agent_id == agent.id))

    # Delete meta cache
    cache_result = await db.execute(delete(InsightMetaCache).where(InsightMetaCache.agent_id == agent.id))
    await db.commit()

    return {
        "deleted_reports": report_result.rowcount,
        "deleted_facets": facets_result.rowcount,
        "deleted_cache": cache_result.rowcount,
    }


@router.delete("/reports/{report_id}")
async def delete_report(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Delete a single insight report."""
    optic.trace("report_id={}", report_id)
    _require_insights()
    stmt = select(InsightReport).where(InsightReport.id == report_id)
    result = await db.execute(stmt)
    report = result.scalar_one_or_none()

    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    # Org-scope check
    agent_stmt = select(Agent).where(Agent.id == report.agent_id)
    agent_result = await db.execute(agent_stmt)
    agent = agent_result.scalar_one_or_none()
    if agent and current_user.org_id is not None and agent.owner_org_id != current_user.org_id:
        raise HTTPException(status_code=403, detail="Agent does not belong to your organization")

    await db.delete(report)
    await db.commit()

    return {"deleted": True, "report_id": report_id}


@router.post("/reports/{report_id}/apply")
async def apply_report_suggestions(
    report_id: str,
    body: ApplySuggestionsRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Apply selected insight suggestions as pending registry items.

    Pass index arrays to select specific suggestions. Omit or pass null
    to skip a category entirely. Pass an empty body to apply all.
    """
    optic.trace("report_id={}", report_id)
    _require_insights()

    # Check feature toggle
    import services.dynamic_settings as ds

    enabled = await ds.get_bool("insights.self_learn_enabled", default=True)
    if not enabled:
        raise HTTPException(
            status_code=403,
            detail="Self-learning is disabled. Enable via settings: insights.self_learn_enabled",
        )

    # Org-scope check
    stmt = select(InsightReport).where(InsightReport.id == report_id)
    result = await db.execute(stmt)
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    agent_stmt = select(Agent).where(Agent.id == report.agent_id)
    agent_result = await db.execute(agent_stmt)
    agent = agent_result.scalar_one_or_none()
    if agent and current_user.org_id is not None and agent.owner_org_id != current_user.org_id:
        raise HTTPException(status_code=403, detail="Agent does not belong to your organization")

    # Run the self-learn pipeline
    from services.insights.self_learn import apply_insight_suggestions

    selection = None
    if body and (
        body.config_indices is not None or body.feature_indices is not None or body.pattern_indices is not None
    ):
        selection = {
            "config_indices": body.config_indices,
            "feature_indices": body.feature_indices,
            "pattern_indices": body.pattern_indices,
        }

    try:
        applied = await apply_insight_suggestions(
            report_id=report_id,
            db=db,
            triggered_by=current_user.id,
            selection=selection,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "applied": True,
        "report_id": report_id,
        "items": applied,
    }
