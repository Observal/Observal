"""Batch insight report generation — discovers agents needing reports and queues jobs.

This module stays in the main repo because it directly interacts with
PostgreSQL models (Agent, InsightReport) and Redis job queues.
"""

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select

from config import settings
from database import async_session
from models.agent import Agent, AgentStatus, AgentVersion
from models.insight_report import InsightReport, InsightReportStatus
from services.clickhouse import _query
from services.redis import _get_arq_pool

logger = structlog.get_logger(__name__)


async def _load_agent_config(db, agent_id) -> dict | None:
    """Load the agent's latest approved version and its components.

    Returns a dict summarizing the agent configuration, or None if no
    approved version exists.
    """
    stmt = (
        select(AgentVersion)
        .where(
            AgentVersion.agent_id == agent_id,
            AgentVersion.status == AgentStatus.approved,
        )
        .order_by(AgentVersion.released_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    version = result.scalar_one_or_none()
    if not version:
        return None

    # Build a summary of configured MCPs
    mcp_names = []
    skill_names = []
    for comp in version.components or []:
        if comp.component_type == "mcp":
            mcp_names.append(comp.component_name or str(comp.component_id)[:8])
        elif comp.component_type == "skill":
            skill_names.append(comp.component_name or str(comp.component_id)[:8])

    # Also include external MCPs from the version config
    for ext_mcp in version.external_mcps or []:
        name = ext_mcp.get("name") or ext_mcp.get("server_name", "")
        if name and name not in mcp_names:
            mcp_names.append(name)

    config: dict = {
        "version": version.version,
        "model": version.model_name,
        "supported_ides": version.supported_ides or [],
    }

    if version.prompt:
        # Include a truncated system prompt (first 2000 chars) for context
        config["system_prompt_excerpt"] = version.prompt[:2000]
        config["system_prompt_length"] = len(version.prompt)

    if mcp_names:
        config["configured_mcps"] = mcp_names
    if skill_names:
        config["configured_skills"] = skill_names
    if version.model_config_json:
        config["model_config"] = version.model_config_json

    return config


async def _load_registry_catalog(db) -> dict:
    """Load a summary of available MCPs and skills from the registry.

    Returns a compact catalog for the LLM to reference when suggesting
    new components the agent could benefit from.
    """
    from models.mcp import McpListing, McpVersion
    from models.skill import SkillListing, SkillVersion

    catalog: dict = {"mcps": [], "skills": []}

    # Public MCPs with their latest version description
    mcp_stmt = (
        select(McpListing.id, McpListing.name, McpListing.category, McpVersion.description)
        .join(McpVersion, McpListing.latest_version_id == McpVersion.id, isouter=True)
        .where(McpListing.is_private == False)  # noqa: E712 — SQLAlchemy requires ==
    )
    mcp_result = await db.execute(mcp_stmt)
    for row in mcp_result.all():
        catalog["mcps"].append(
            {
                "id": str(row[0]),
                "name": row[1],
                "category": row[2],
                "description": (row[3] or "")[:120],
            }
        )

    # Public skills with their latest version description
    skill_stmt = (
        select(SkillListing.id, SkillListing.name, SkillVersion.description)
        .join(SkillVersion, SkillListing.latest_version_id == SkillVersion.id, isouter=True)
        .where(SkillListing.is_private == False)  # noqa: E712
    )
    skill_result = await db.execute(skill_stmt)
    for row in skill_result.all():
        catalog["skills"].append(
            {
                "id": str(row[0]),
                "name": row[1],
                "description": (row[2] or "")[:120],
            }
        )

    return catalog


async def run_single_report(report_id: str) -> None:
    """Generate an insight report: load from DB, run pipeline, save results.

    This replaces the old generator.generate_report() — orchestration stays
    here in the main repo, computation is delegated to the observal-insights package.
    """
    from services.insights import generate_report_content

    async with async_session() as db:
        stmt = select(InsightReport).where(InsightReport.id == report_id)
        result = await db.execute(stmt)
        report = result.scalar_one_or_none()
        if not report:
            logger.error("insight_report_not_found", report_id=report_id)
            return

        # Mark as running
        report.status = InsightReportStatus.running
        report.started_at = datetime.now(UTC)
        await db.commit()

        try:
            # Load agent
            agent_stmt = select(Agent).where(Agent.id == report.agent_id)
            agent_result = await db.execute(agent_stmt)
            agent = agent_result.scalar_one_or_none()
            agent_name = agent.name if agent else "Unknown Agent"

            # Load latest approved version with components for context-aware suggestions
            agent_config = await _load_agent_config(db, report.agent_id)

            start_str = report.period_start.strftime("%Y-%m-%d %H:%M:%S")
            end_str = report.period_end.strftime("%Y-%m-%d %H:%M:%S")

            # Load previous metrics for regression detection
            previous_metrics = None
            if report.previous_report_id:
                prev_stmt = select(InsightReport).where(InsightReport.id == report.previous_report_id)
                prev_result = await db.execute(prev_stmt)
                prev_report = prev_result.scalar_one_or_none()
                if prev_report and prev_report.aggregated_data:
                    previous_metrics = prev_report.aggregated_data

            # Load registry catalog for component-aware suggestions
            registry_catalog = await _load_registry_catalog(db)

            # Run the insights pipeline
            content = await generate_report_content(
                agent_name=agent_name,
                agent_id=str(report.agent_id),
                period_start=start_str,
                period_end=end_str,
                previous_metrics=previous_metrics,
                agent_config=agent_config,
                registry_catalog=registry_catalog,
                db=db,
            )

            # Persist results
            report.metrics = content.get("metrics")
            report.narrative = content.get("narrative")
            report.sessions_analyzed = content.get("sessions_analyzed", 0)
            report.aggregated_data = {
                "metrics": content.get("metrics"),
                "facets_summary": content.get("facets_summary"),
                "regressions": content.get("regressions"),
                "cross_user_patterns": content.get("cross_user_patterns"),
            }
            report.report_version = 3

            models_used = content.get("models_used", [])
            report.llm_model_used = ", ".join(models_used) if models_used else None

            report.status = InsightReportStatus.completed
            report.completed_at = datetime.now(UTC)
            await db.commit()

            logger.info(
                "insight_report_completed",
                report_id=report_id,
                sessions=content.get("sessions_analyzed", 0),
                has_narrative=content.get("narrative") is not None,
            )

        except Exception as e:
            report.status = InsightReportStatus.failed
            report.error_message = str(e)
            report.completed_at = datetime.now(UTC)
            await db.commit()
            logger.exception("insight_report_failed", report_id=report_id, error=str(e))


async def _count_agent_sessions(agent_name: str, since: str) -> int:
    """Count sessions in otel_logs for an agent since a given timestamp."""
    sql = """
        SELECT count(DISTINCT LogAttributes['session.id']) AS cnt
        FROM otel_logs
        WHERE (LogAttributes['agent_type'] = {aname:String}
               OR LogAttributes['agent_name'] = {aname:String})
          AND Timestamp >= {t_start:String}
          AND LogAttributes['session.id'] != ''
        FORMAT JSON
    """
    params = {"param_aname": agent_name, "param_t_start": since}
    try:
        r = await _query(sql, params)
        r.raise_for_status()
        data = r.json().get("data", [])
        return int(data[0]["cnt"]) if data else 0
    except Exception as e:
        logger.warning("insight_batch_count_failed", agent_name=agent_name, error=str(e))
        return 0


async def discover_and_queue_reports() -> int:
    """Find agents with enough new sessions and queue insight reports.

    Returns the number of reports queued.
    """
    if not settings.INSIGHT_BATCH_ENABLED:
        return 0

    period_days = settings.INSIGHT_BATCH_PERIOD_DAYS
    min_sessions = settings.INSIGHT_MIN_SESSIONS
    now = datetime.now(UTC)
    period_start = now - timedelta(days=period_days)

    queued = 0

    async with async_session() as db:
        # Get all approved agents
        agents_stmt = select(Agent).where(Agent.status == AgentStatus.approved)
        result = await db.execute(agents_stmt)
        agents = result.scalars().all()

        if not agents:
            logger.debug("insight_batch_no_agents")
            return 0

        for agent in agents:
            try:
                # Check if there's already a recent report (completed or in-progress)
                latest_report_stmt = (
                    select(InsightReport)
                    .where(
                        InsightReport.agent_id == agent.id,
                        InsightReport.status.in_(
                            [
                                InsightReportStatus.completed,
                                InsightReportStatus.running,
                                InsightReportStatus.pending,
                            ]
                        ),
                    )
                    .order_by(InsightReport.created_at.desc())
                    .limit(1)
                )
                latest_result = await db.execute(latest_report_stmt)
                latest_report = latest_result.scalar_one_or_none()

                # Skip if a report was generated within the last period
                if latest_report and latest_report.created_at > period_start:
                    continue

                # Count new sessions for this agent
                since_str = period_start.strftime("%Y-%m-%d %H:%M:%S")
                session_count = await _count_agent_sessions(agent.name, since_str)

                if session_count < min_sessions:
                    logger.debug(
                        "insight_batch_skip_insufficient",
                        agent=agent.name,
                        sessions=session_count,
                        min_required=min_sessions,
                    )
                    continue

                # Find the most recent completed report for regression linking
                prev_report_stmt = (
                    select(InsightReport)
                    .where(
                        InsightReport.agent_id == agent.id,
                        InsightReport.status == InsightReportStatus.completed,
                    )
                    .order_by(InsightReport.created_at.desc())
                    .limit(1)
                )
                prev_result = await db.execute(prev_report_stmt)
                prev_report = prev_result.scalar_one_or_none()

                # Create a new report record
                report = InsightReport(
                    agent_id=agent.id,
                    triggered_by=None,  # Cron-triggered
                    status=InsightReportStatus.pending,
                    period_start=period_start,
                    period_end=now,
                    started_at=now,
                    created_at=now,
                    previous_report_id=prev_report.id if prev_report else None,
                )
                db.add(report)
                await db.flush()

                # Enqueue the generation job
                pool = await _get_arq_pool()
                await pool.enqueue_job("generate_insight_report", str(report.id))

                await db.commit()
                queued += 1

                logger.info(
                    "insight_batch_queued",
                    agent=agent.name,
                    agent_id=str(agent.id),
                    report_id=str(report.id),
                    sessions=session_count,
                )

            except Exception as e:
                logger.error(
                    "insight_batch_agent_error",
                    agent=agent.name,
                    error=str(e),
                )
                await db.rollback()
                continue

    logger.info("insight_batch_complete", queued=queued, agents_checked=len(agents))
    return queued
