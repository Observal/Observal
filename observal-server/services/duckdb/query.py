# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""DuckDB query functions for live session telemetry tables.

Direct ports of the legacy ClickHouse queries. ClickHouse FINAL is gone
(primary-key tables dedup at write time), countIf/minIf/maxIf become
FILTER clauses, and {name:Type} placeholders become $name parameters.
"""

import time

from loguru import logger as optic

import services.duckdb.client as _client


async def query_recent_events(minutes: int = 60) -> dict:
    """Get recent session activity counts from the session rollup table."""
    minutes = int(minutes)
    try:
        r = await _client._query(
            "SELECT coalesce(sum(tool_call_count), 0) AS tools, count(*) AS sessions "
            "FROM session_stats_agg "
            "WHERE last_event_time > now()::TIMESTAMP - ($minutes * INTERVAL '1 minute')",
            {"minutes": minutes},
        )
        r.raise_for_status()
        row = r.json().get("data", [{}])[0]
        return {
            "tool_call_events": int(row.get("tools") or 0),
            "agent_interaction_events": int(row.get("sessions") or 0),
        }
    except Exception as e:
        optic.warning("could not count recent session events: {}", e)
        return {"tool_call_events": 0, "agent_interaction_events": 0}


async def query_session_checkpoint(
    session_id: str,
    project_id: str,
    user_id: str,
    harness: str,
) -> tuple[int, int]:
    """Return the durable contiguous (source line, end byte) checkpoint."""
    sql = (
        "SELECT acknowledged_line, acknowledged_offset FROM session_checkpoints "
        "WHERE project_id = $pid AND user_id = $uid "
        "AND harness = $harness AND session_id = $sid LIMIT 1"
    )
    params = {"pid": project_id, "uid": user_id, "harness": harness, "sid": session_id}
    try:
        r = await _client._query(sql, params)
        r.raise_for_status()
        data = r.json().get("data", [])
        if not data:
            return -1, 0
        return int(data[0]["acknowledged_line"]), int(data[0].get("acknowledged_offset") or 0)
    except Exception as e:
        optic.error("failed to read checkpoint for session {}: {}", session_id, e)
        raise


async def query_source_records_after(
    session_id: str,
    project_id: str,
    user_id: str,
    harness: str,
    after_line: int,
    limit: int = 5000,
) -> list[tuple[int, int]]:
    """Return ordered source positions after a checkpoint for gap detection."""
    sql = (
        "SELECT line_offset, source_end_offset FROM session_events "
        "WHERE project_id = $pid AND user_id = $uid "
        "AND harness = $harness AND session_id = $sid "
        "AND is_source_record = 1 AND line_offset > $after "
        "ORDER BY line_offset LIMIT $limit"
    )
    params = {
        "pid": project_id,
        "uid": user_id,
        "harness": harness,
        "sid": session_id,
        "after": after_line,
        "limit": limit,
    }
    r = await _client._query(sql, params)
    r.raise_for_status()
    return [(int(row["line_offset"]), int(row.get("source_end_offset") or 0)) for row in r.json().get("data", [])]


async def query_session_source_manifest(
    session_id: str,
    project_id: str,
    user_id: str,
    harness: str,
) -> list[tuple[int, int, str]]:
    """Return canonical source positions for final integrity auditing."""
    sql = (
        "SELECT line_offset, source_end_offset, source_sha256 FROM session_events "
        "WHERE project_id = $pid AND user_id = $uid "
        "AND harness = $harness AND session_id = $sid "
        "AND is_source_record = 1 ORDER BY line_offset"
    )
    params = {"pid": project_id, "uid": user_id, "harness": harness, "sid": session_id}
    r = await _client._query(sql, params)
    r.raise_for_status()
    return [
        (int(row["line_offset"]), int(row.get("source_end_offset") or 0), str(row.get("source_sha256") or ""))
        for row in r.json().get("data", [])
    ]


async def query_existing_for_dedup(
    session_id: str,
    project_id: str,
    user_id: str,
    harness: str,
    min_offset: int,
    max_offset: int,
) -> dict[int, str]:
    """Return existing source line hashes by stable source index."""
    _t0 = time.perf_counter()
    if min_offset > max_offset:
        return {}
    sql = (
        "SELECT line_offset, line_hash FROM session_events "
        "WHERE project_id = $pid AND user_id = $uid "
        "AND harness = $harness AND session_id = $sid AND is_source_record = 1 "
        "AND line_offset >= $min_off AND line_offset <= $max_off"
    )
    params = {
        "pid": project_id,
        "uid": user_id,
        "harness": harness,
        "sid": session_id,
        "min_off": min_offset,
        "max_off": max_offset,
    }
    try:
        r = await _client._query(sql, params)
        r.raise_for_status()
        existing = {int(row["line_offset"]): str(row.get("line_hash") or "") for row in r.json().get("data", [])}
        _elapsed = (time.perf_counter() - _t0) * 1000
        optic.trace(
            "dedup check for session {}: {} offsets in range [{}, {}] ({:.0f}ms)",
            session_id,
            len(existing),
            min_offset,
            max_offset,
            _elapsed,
        )
        return existing
    except Exception as e:
        optic.error("dedup query failed for session {}: {}", session_id, e)
        raise
