# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Per-organization data retention purge service.

Runs as a cron job every 6 hours. For each org with retention_enabled=True:
1. Time-based purge: DELETE rows older than data_retention_days
2. Score/insight purge: DELETE scores + insight reports older than score_retention_days
3. Count-based purge: If trace count exceeds max_trace_count, find cutoff and purge
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import structlog
from loguru import logger as optic
from sqlalchemy import select

from database import async_session
from models.organization import Organization

logger = structlog.get_logger(__name__)

INTER_ORG_DELAY = 2.0

TIME_PURGE_TABLES = {
    "spans": "start_time",
    "session_events": "timestamp",
}

SCORE_TABLE = {"scores": "timestamp"}


async def _delete_batch(table: str, time_col: str, project_id: str, cutoff_str: str) -> int:
    """Execute a lightweight DELETE. Returns 1 on success, 0 on failure."""
    optic.debug("_delete_batch: table={}, time_col={}", table, time_col)
    from services.clickhouse import _query

    sql = (
        f"DELETE FROM {table} "
        f"WHERE project_id = {{pid:String}} AND {time_col} < {{cutoff:String}} "
        f"SETTINGS lightweight_deletes_sync = 0"
    )
    resp = await _query(sql, {"param_pid": project_id, "param_cutoff": cutoff_str})
    if resp.status_code != 200:
        logger.warning("retention_delete_failed", table=table, status=resp.status_code, body=resp.text[:200])
        return 0
    return 1


async def _has_data(project_id: str) -> bool:
    """Quick existence check - does this org have any traces?"""
    optic.debug("_has_data: project_id={}", project_id)
    from services.clickhouse import _query

    resp = await _query(
        "SELECT 1 FROM traces WHERE project_id = {pid:String} LIMIT 1 FORMAT JSON",
        {"param_pid": project_id},
    )
    if resp.status_code == 200:
        data = resp.json().get("data", [])
        return len(data) > 0
    return False


async def _has_inflight_insights(org_id: uuid.UUID) -> bool:
    """Check if org has insight reports currently being generated."""
    optic.debug("_has_inflight_insights: org_id={}", org_id)
    from models.agent import Agent
    from models.insight_report import InsightReport, InsightReportStatus

    async with async_session() as db:
        agent_ids = (await db.execute(select(Agent.id).where(Agent.owner_org_id == org_id))).scalars().all()
        if not agent_ids:
            return False
        count = (
            await db.execute(
                select(InsightReport.id)
                .where(
                    InsightReport.agent_id.in_(agent_ids),
                    InsightReport.status.in_([InsightReportStatus.pending, InsightReportStatus.running]),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        return count is not None


async def _purge_time_based(project_id: str, cutoff_str: str, tables: dict[str, str]) -> dict[str, int]:
    """Delete rows older than cutoff from specified tables."""
    optic.debug("_purge_time_based: project_id={}, cutoff_str={}", project_id, cutoff_str)
    stats = {}
    for table, time_col in tables.items():
        try:
            stats[table] = await _delete_batch(table, time_col, project_id, cutoff_str)
        except Exception as e:
            logger.warning("retention_purge_table_error", table=table, error=str(e))
            stats[table] = 0
    return stats


async def _purge_session_stats_orphans(project_id: str) -> int:
    """Delete session_stats_agg entries whose sessions no longer have events."""
    optic.debug("_purge_session_stats_orphans: project_id={}", project_id)
    from services.clickhouse import _query

    sql = (
        "DELETE FROM session_stats_agg "
        "WHERE project_id = {pid:String} "
        "AND session_id NOT IN ("
        "  SELECT DISTINCT session_id FROM session_events WHERE project_id = {pid2:String}"
        ") "
        "SETTINGS lightweight_deletes_sync = 0"
    )
    resp = await _query(sql, {"param_pid": project_id, "param_pid2": project_id})
    if resp.status_code != 200:
        logger.warning("retention_session_stats_orphan_failed", status=resp.status_code)
        return 0
    return 1


async def _purge_insight_reports(org_id: uuid.UUID, score_cutoff: datetime) -> int:
    """Delete old insight reports from PostgreSQL."""
    optic.debug("_purge_insight_reports: org_id={}, score_cutoff={}", org_id, score_cutoff)
    from models.agent import Agent
    from models.insight_report import InsightReport, InsightReportStatus

    async with async_session() as db:
        agent_ids = (await db.execute(select(Agent.id).where(Agent.owner_org_id == org_id))).scalars().all()
        if not agent_ids:
            return 0

        # Delete completed reports older than score_cutoff
        from sqlalchemy import delete

        result = await db.execute(
            delete(InsightReport).where(
                InsightReport.agent_id.in_(agent_ids),
                InsightReport.completed_at < score_cutoff,
                InsightReport.status == InsightReportStatus.completed,
            )
        )
        completed_deleted = result.rowcount

        # Delete stuck reports (failed/pending) older than score_cutoff
        result = await db.execute(
            delete(InsightReport).where(
                InsightReport.agent_id.in_(agent_ids),
                InsightReport.created_at < score_cutoff,
                InsightReport.status.in_([InsightReportStatus.failed, InsightReportStatus.pending]),
            )
        )
        stuck_deleted = result.rowcount

        await db.commit()
        return completed_deleted + stuck_deleted


async def _purge_count_based(project_id: str, max_trace_count: int) -> int:
    """If trace count exceeds max, find cutoff day and purge oldest."""
    optic.debug("_purge_count_based: project_id={}, max_trace_count={}", project_id, max_trace_count)
    from services.clickhouse import _query

    # Get daily trace counts, capped at 2 years to bound query cost.
    # Count-based purge only needs to find the cutoff day; scanning beyond
    # 730 days offers no benefit and risks hitting the cron timeout on large orgs.
    sql = (
        "SELECT toDate(start_time) as day, count() as cnt "
        "FROM traces WHERE project_id = {pid:String} "
        "AND start_time >= now() - INTERVAL 730 DAY "
        "GROUP BY day ORDER BY day DESC LIMIT 730 FORMAT JSON"
    )
    resp = await _query(sql, {"param_pid": project_id})
    if resp.status_code != 200:
        return 0

    data = resp.json().get("data", [])
    if not data:
        return 0

    # Walk from newest to oldest summing counts
    running_total = 0
    cutoff_day = None
    for row in data:
        running_total += int(row["cnt"])
        if running_total > max_trace_count:
            cutoff_day = row["day"]
            break

    if cutoff_day is None:
        return 0

    # Purge everything older than cutoff_day (children first)
    cutoff_str = f"{cutoff_day} 00:00:00.000"
    for table, time_col in [("spans", "start_time"), ("session_events", "timestamp")]:
        await _delete_batch(table, time_col, project_id, cutoff_str)
    await _purge_session_stats_orphans(project_id)
    await _delete_batch("scores", "timestamp", project_id, cutoff_str)
    await _delete_batch("traces", "start_time", project_id, cutoff_str)
    return 1


async def run_retention_purge(ctx: dict | None = None):
    """Main entry point for the retention purge cron job."""
    optic.debug("retention: purge started")
    async with async_session() as db:
        result = await db.execute(select(Organization).where(Organization.retention_enabled.is_(True)))
        orgs = result.scalars().all()

    if not orgs:
        return

    logger.info("retention_purge_started", org_count=len(orgs))

    for org in orgs:
        project_id = str(org.id)

        # Skip if no data exists
        if not await _has_data(project_id):
            logger.debug("retention_purge_skip_empty", org=org.slug)
            await asyncio.sleep(INTER_ORG_DELAY)
            continue

        # Skip if insight reports are being generated
        if await _has_inflight_insights(org.id):
            logger.info("retention_purge_skip_inflight", org=org.slug)
            await asyncio.sleep(INTER_ORG_DELAY)
            continue

        org_stats: dict = {}
        now = datetime.now(UTC)

        # Time-based purge (traces, spans, session_events)
        if org.data_retention_days:
            data_cutoff = now - timedelta(days=org.data_retention_days)
            data_cutoff_str = data_cutoff.strftime("%Y-%m-%d %H:%M:%S.000")
            org_stats["time"] = await _purge_time_based(project_id, data_cutoff_str, TIME_PURGE_TABLES)
            await _purge_session_stats_orphans(project_id)

        # Score + insight purge (separate retention period)
        score_days = org.score_retention_days or ((org.data_retention_days * 2) if org.data_retention_days else None)
        if score_days:
            score_days = max(score_days, 30)
            score_cutoff = now - timedelta(days=score_days)
            score_cutoff_str = score_cutoff.strftime("%Y-%m-%d %H:%M:%S.000")
            org_stats["scores"] = await _purge_time_based(project_id, score_cutoff_str, SCORE_TABLE)
            org_stats["insight_reports"] = await _purge_insight_reports(org.id, score_cutoff)

        # Count-based purge
        if org.max_trace_count:
            org_stats["count_purge"] = await _purge_count_based(project_id, org.max_trace_count)

        # Delete traces last (time-based) - children already deleted above
        if org.data_retention_days:
            await _delete_batch("traces", "start_time", project_id, data_cutoff_str)

        logger.info("retention_purge_org_done", org=org.slug, stats=org_stats)
        await asyncio.sleep(INTER_ORG_DELAY)

    logger.info("retention_purge_completed")
