"""Batch insight report generation — discovers agents needing reports and queues jobs."""

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select

from config import settings
from database import async_session
from models.agent import Agent, AgentStatus
from models.insight_report import InsightReport, InsightReportStatus
from services.clickhouse import _query
from services.redis import _get_arq_pool

logger = structlog.get_logger(__name__)


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
