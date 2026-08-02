# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Deployment-wide data retention purge service."""

from datetime import UTC, datetime, timedelta

from loguru import logger as optic
from sqlalchemy import delete, select

import services.dynamic_settings as ds
from database import async_session
from models.insight_report import InsightReport, InsightReportStatus
from observal_shared.migration.constants import DEFAULT_PROJECT_ID

TIME_PURGE_TABLES = {"session_events": "timestamp"}


async def _delete_batch(table: str, time_col: str, project_id: str, cutoff_str: str) -> int:
    """Execute a lightweight delete and return one on success."""
    from services.clickhouse import _query

    sql = (
        f"DELETE FROM {table} "
        f"WHERE project_id = {{pid:String}} AND {time_col} < {{cutoff:String}} "
        "SETTINGS lightweight_deletes_sync = 0"
    )
    response = await _query(sql, {"param_pid": project_id, "param_cutoff": cutoff_str})
    if response.status_code != 200:
        optic.warning(
            "retention delete failed on table {} (status={}): {}", table, response.status_code, response.text[:200]
        )
        return 0
    return 1


async def _has_data(project_id: str) -> bool:
    from services.clickhouse import _query

    response = await _query(
        "SELECT 1 FROM session_events WHERE project_id = {pid:String} LIMIT 1 FORMAT JSON",
        {"param_pid": project_id},
    )
    if response.status_code != 200:
        return False
    return bool(response.json().get("data", []))


async def _has_inflight_insights() -> bool:
    async with async_session() as db:
        report_id = (
            await db.execute(
                select(InsightReport.id)
                .where(InsightReport.status.in_([InsightReportStatus.pending, InsightReportStatus.running]))
                .limit(1)
            )
        ).scalar_one_or_none()
    return report_id is not None


async def _purge_time_based(project_id: str, cutoff_str: str, tables: dict[str, str]) -> dict[str, int]:
    stats: dict[str, int] = {}
    for table, time_col in tables.items():
        stats[table] = await _delete_batch(table, time_col, project_id, cutoff_str)
    return stats


async def _purge_session_stats_orphans(project_id: str) -> int:
    from services.clickhouse import _query

    sql = (
        "DELETE FROM session_stats_agg "
        "WHERE project_id = {pid:String} "
        "AND session_id NOT IN ("
        "  SELECT DISTINCT session_id FROM session_events WHERE project_id = {pid2:String}"
        ") SETTINGS lightweight_deletes_sync = 0"
    )
    response = await _query(sql, {"param_pid": project_id, "param_pid2": project_id})
    return 1 if response.status_code == 200 else 0


async def _purge_insight_reports(score_cutoff: datetime) -> int:
    async with async_session() as db:
        completed = await db.execute(
            delete(InsightReport).where(
                InsightReport.completed_at < score_cutoff,
                InsightReport.status == InsightReportStatus.completed,
            )
        )
        stuck = await db.execute(
            delete(InsightReport).where(
                InsightReport.created_at < score_cutoff,
                InsightReport.status.in_([InsightReportStatus.failed, InsightReportStatus.pending]),
            )
        )
        await db.commit()
    return int(completed.rowcount or 0) + int(stuck.rowcount or 0)


async def _purge_count_based(project_id: str, max_trace_count: int) -> int:
    from services.clickhouse import _query

    sql = (
        "SELECT toDate(timestamp) AS day, count(DISTINCT session_id) AS cnt "
        "FROM session_events WHERE project_id = {pid:String} "
        "AND timestamp >= now() - INTERVAL 730 DAY "
        "GROUP BY day ORDER BY day DESC LIMIT 730 FORMAT JSON"
    )
    response = await _query(sql, {"param_pid": project_id})
    if response.status_code != 200:
        return 0
    data = response.json().get("data", [])
    running_total = 0
    cutoff_day = None
    for row in data:
        running_total += int(row["cnt"])
        if running_total > max_trace_count:
            cutoff_day = row["day"]
            break
    if cutoff_day is None:
        return 0

    await _delete_batch("session_events", "timestamp", project_id, f"{cutoff_day} 00:00:00.000")
    await _purge_session_stats_orphans(project_id)
    return 1


async def run_retention_purge(ctx: dict | None = None):
    """Run the configured retention policy for the deployment."""
    del ctx
    if not await ds.get_bool("retention.enabled"):
        return

    trace_days = await ds.get_int("retention.trace_days", default=0)
    score_days = await ds.get_int("retention.score_days", default=0)
    max_trace_count = await ds.get_int("retention.max_trace_count", default=0)
    if not trace_days and not score_days and not max_trace_count:
        return
    if await _has_data(DEFAULT_PROJECT_ID) is False:
        return
    if await _has_inflight_insights():
        optic.info("skipping retention purge while insights are in flight")
        return

    now = datetime.now(UTC)
    stats: dict[str, object] = {}
    if trace_days:
        cutoff = (now - timedelta(days=trace_days)).strftime("%Y-%m-%d %H:%M:%S.000")
        stats["time"] = await _purge_time_based(DEFAULT_PROJECT_ID, cutoff, TIME_PURGE_TABLES)
        await _purge_session_stats_orphans(DEFAULT_PROJECT_ID)

    score_days = score_days or (trace_days * 2 if trace_days else 0)
    if score_days:
        stats["insight_reports"] = await _purge_insight_reports(now - timedelta(days=max(score_days, 30)))
    if max_trace_count:
        stats["count_purge"] = await _purge_count_based(DEFAULT_PROJECT_ID, max_trace_count)

    optic.info("retention purge complete: {}", stats)
