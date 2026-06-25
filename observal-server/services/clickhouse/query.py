# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only
"""ClickHouse query functions for live session telemetry tables."""

import time

from loguru import logger as optic

import services.clickhouse.client as _client


async def query_recent_events(minutes: int = 60) -> dict:
    """Get recent session activity counts from JSONL session tables."""
    minutes = int(minutes)
    try:
        r = await _client._query(
            "SELECT sum(tool_call_count) AS tools, count() AS sessions "
            "FROM session_stats_agg "
            "WHERE last_event_time > now() - INTERVAL {minutes:UInt32} MINUTE "
            "FORMAT JSON",
            {"param_minutes": str(minutes)},
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


async def query_session_event_count(session_id: str, project_id: str) -> tuple[int, int]:
    """Return (count, max_offset) for a session's stored events.

    Uses FINAL so ReplacingMergeTree dedup is applied before counting.
    Returns (0, -1) when no rows exist.
    """
    _t0 = time.perf_counter()
    sql = (
        "SELECT count() AS cnt, max(line_offset) AS max_off "
        "FROM session_events FINAL "
        "WHERE session_id = {sid:String} AND project_id = {pid:String} "
        "FORMAT JSON"
    )
    params = {"param_sid": session_id, "param_pid": project_id}
    try:
        r = await _client._query(sql, params)
        r.raise_for_status()
        data = r.json().get("data", [{}])
        row = data[0] if data else {}
        count = int(row.get("cnt", 0))
        max_off = int(row.get("max_off", -1)) if count > 0 else -1
        _elapsed = (time.perf_counter() - _t0) * 1000
        optic.trace("session {} has {} events, max_offset={} ({:.0f}ms)", session_id, count, max_off, _elapsed)
        return count, max_off
    except Exception as e:
        optic.error("failed to count events for session {}: {}", session_id, e)
        return 0, -1


async def query_existing_for_dedup(
    session_id: str,
    project_id: str,
    min_offset: int,
    max_offset: int,
) -> tuple[frozenset[int], frozenset[str]]:
    """Return (existing_offsets, existing_hashes) for dedup.  Fail-open on errors."""
    _t0 = time.perf_counter()
    if min_offset > max_offset:
        return frozenset(), frozenset()
    sql = (
        "SELECT line_offset, line_hash "
        "FROM session_events FINAL "
        "WHERE project_id = {pid:String} AND session_id = {sid:String} "
        "AND line_offset >= {min_off:UInt32} AND line_offset <= {max_off:UInt32} "
        "FORMAT JSON"
    )
    params = {
        "param_pid": project_id,
        "param_sid": session_id,
        "param_min_off": str(min_offset),
        "param_max_off": str(max_offset),
    }
    try:
        r = await _client._query(sql, params)
        r.raise_for_status()
        data = r.json().get("data", [])
        existing_offsets = frozenset(int(row["line_offset"]) for row in data)
        existing_hashes = frozenset(row["line_hash"] for row in data if row.get("line_hash"))
        _elapsed = (time.perf_counter() - _t0) * 1000
        optic.trace(
            "dedup check for session {}: {} existing offsets, {} hashes in range [{}, {}] ({:.0f}ms)",
            session_id,
            len(existing_offsets),
            len(existing_hashes),
            min_offset,
            max_offset,
            _elapsed,
        )
        return existing_offsets, existing_hashes
    except Exception as e:
        optic.warning(
            "dedup query failed for session {} (fail-open, will re-insert): {}",
            session_id,
            e,
        )
        return frozenset(), frozenset()
