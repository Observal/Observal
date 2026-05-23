# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only
"""ClickHouse query functions for all telemetry tables."""

import structlog
from loguru import logger as optic

import services.clickhouse.client as _client

logger = structlog.get_logger(__name__)


async def query_recent_events(minutes: int = 60) -> dict:
    """Get event counts from the last N minutes from the active telemetry tables."""
    optic.debug("query_recent_events: minutes={}", minutes)
    minutes = int(minutes)
    tool_count = 0
    agent_count = 0

    try:
        r = await _client._query(
            "SELECT count() as cnt FROM spans "
            "WHERE start_time > now() - INTERVAL {minutes:UInt32} MINUTE "
            "AND is_deleted = 0 "
            "FORMAT JSON",
            {"param_minutes": str(minutes)},
        )
        if r.status_code == 200:
            tool_count = int(r.json().get("data", [{}])[0].get("cnt", 0))
    except Exception as e:
        logger.warning("clickhouse_query_spans_failed", error=str(e))

    try:
        r = await _client._query(
            "SELECT count() as cnt FROM traces "
            "WHERE start_time > now() - INTERVAL {minutes:UInt32} MINUTE "
            "AND is_deleted = 0 "
            "FORMAT JSON",
            {"param_minutes": str(minutes)},
        )
        if r.status_code == 200:
            agent_count = int(r.json().get("data", [{}])[0].get("cnt", 0))
    except Exception as e:
        logger.warning("clickhouse_query_traces_failed", error=str(e))

    return {"tool_call_events": tool_count, "agent_interaction_events": agent_count}


async def query_traces(
    project_id: str,
    *,
    trace_type: str | None = None,
    mcp_id: str | None = None,
    agent_id: str | None = None,
    user_id: str | None = None,
    agent_version: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Query traces with optional filters."""
    optic.debug("query_traces: project_id={}, trace_type={}, mcp_id={}", project_id, trace_type, mcp_id)
    conditions = ["project_id = {pid:String}", "is_deleted = 0"]
    params: dict[str, str] = {"param_pid": project_id}
    if trace_type:
        conditions.append("trace_type = {tt:String}")
        params["param_tt"] = trace_type
    if mcp_id:
        conditions.append("mcp_id = {mid:String}")
        params["param_mid"] = mcp_id
    if agent_id:
        conditions.append("agent_id = {aid:String}")
        params["param_aid"] = agent_id
    if user_id:
        conditions.append("user_id = {uid:String}")
        params["param_uid"] = user_id
    if agent_version:
        conditions.append("agent_version = {av:String}")
        params["param_av"] = agent_version
    where = " AND ".join(conditions)
    sql = (
        f"SELECT * FROM traces FINAL WHERE {where} "
        f"ORDER BY start_time DESC LIMIT {int(limit)} OFFSET {int(offset)} FORMAT JSON"
    )
    try:
        r = await _client._query(sql, params)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception as e:
        logger.error("clickhouse_query_traces_failed", error=str(e))
        return []


async def query_trace_by_id(project_id: str, trace_id: str, *, user_id: str | None = None) -> dict | None:
    """Get a single trace by ID, optionally scoped to a user."""
    optic.debug("query_trace_by_id: project_id={}, trace_id={}, user_id={}", project_id, trace_id, user_id)
    conditions = [
        "project_id = {pid:String}",
        "trace_id = {tid:String}",
        "is_deleted = 0",
    ]
    params: dict[str, str] = {"param_pid": project_id, "param_tid": trace_id}
    if user_id:
        conditions.append("user_id = {uid:String}")
        params["param_uid"] = user_id
    where = " AND ".join(conditions)
    sql = f"SELECT * FROM traces FINAL WHERE {where} LIMIT 1 FORMAT JSON"
    try:
        r = await _client._query(sql, params)
        r.raise_for_status()
        data = r.json().get("data", [])
        return data[0] if data else None
    except Exception as e:
        logger.error("clickhouse_query_trace_by_id_failed", error=str(e))
        return None


async def query_spans(
    project_id: str,
    trace_id: str,
    *,
    span_type: str | None = None,
    status: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """Query spans for a trace with optional filters."""
    optic.debug("query_spans: project_id={}, trace_id={}, span_type={}", project_id, trace_id, span_type)
    conditions = [
        "project_id = {pid:String}",
        "trace_id = {tid:String}",
        "is_deleted = 0",
    ]
    params: dict[str, str] = {"param_pid": project_id, "param_tid": trace_id}
    if span_type:
        conditions.append("type = {st:String}")
        params["param_st"] = span_type
    if status:
        conditions.append("status = {status:String}")
        params["param_status"] = status
    where = " AND ".join(conditions)
    sql = f"SELECT * FROM spans FINAL WHERE {where} ORDER BY start_time ASC LIMIT {int(limit)} FORMAT JSON"
    try:
        r = await _client._query(sql, params)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception as e:
        logger.error("clickhouse_query_spans_failed", error=str(e))
        return []


async def query_span_by_id(project_id: str, span_id: str, *, user_id: str | None = None) -> dict | None:
    """Get a single span by ID, optionally scoped to a user."""
    optic.debug("query_span_by_id: project_id={}, span_id={}, user_id={}", project_id, span_id, user_id)
    conditions = [
        "project_id = {pid:String}",
        "span_id = {sid:String}",
        "is_deleted = 0",
    ]
    params: dict[str, str] = {"param_pid": project_id, "param_sid": span_id}
    if user_id:
        conditions.append("user_id = {uid:String}")
        params["param_uid"] = user_id
    where = " AND ".join(conditions)
    sql = f"SELECT * FROM spans FINAL WHERE {where} LIMIT 1 FORMAT JSON"
    try:
        r = await _client._query(sql, params)
        r.raise_for_status()
        data = r.json().get("data", [])
        return data[0] if data else None
    except Exception as e:
        logger.error("clickhouse_query_span_by_id_failed", error=str(e))
        return None


async def query_shim_spans_for_window(
    user_id: str,
    start_time: str,
    end_time: str,
) -> list[dict]:
    """Fetch shim spans from the spans table that overlap a time window.

    Used for query-time side-load when shim data has no session_id.
    """
    optic.debug("query_shim_spans_for_window: user_id={}, start_time={}, end_time={}", user_id, start_time, end_time)
    sql = (
        "SELECT "
        "span_id, trace_id, name, type, method, "
        "input, output, error, "
        "start_time, latency_ms, status, "
        "tools_available, tool_schema_valid, "
        "mcp_id "
        "FROM spans FINAL "
        "WHERE user_id = {uid:String} "
        "AND is_deleted = 0 "
        "AND type IN ("
        "  'tool_call', 'tool_list', 'initialize', "
        "  'resource_read', 'resource_list', 'resource_subscribe', "
        "  'prompt_get', 'prompt_list', 'ping', 'completion', 'config', 'other'"
        ") "
        "AND start_time >= parseDateTimeBestEffort({t_start:String}) - INTERVAL 2 SECOND "
        "AND start_time <= parseDateTimeBestEffort({t_end:String}) + INTERVAL 2 SECOND "
        "ORDER BY start_time ASC "
        "LIMIT 500 "
        "FORMAT JSON"
    )
    params = {
        "param_uid": user_id,
        "param_t_start": start_time,
        "param_t_end": end_time,
    }
    try:
        r = await _client._query(sql, params)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception as e:
        logger.error("clickhouse_query_shim_spans_failed", error=str(e))
        return []


async def query_scores(
    project_id: str,
    *,
    trace_id: str | None = None,
    span_id: str | None = None,
    source: str | None = None,
    name: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Query scores with optional filters."""
    optic.debug("query_scores: project_id={}, trace_id={}, span_id={}", project_id, trace_id, span_id)
    conditions = ["project_id = {pid:String}", "is_deleted = 0"]
    params: dict[str, str] = {"param_pid": project_id}
    if trace_id:
        conditions.append("trace_id = {tid:String}")
        params["param_tid"] = trace_id
    if span_id:
        conditions.append("span_id = {sid:String}")
        params["param_sid"] = span_id
    if source:
        conditions.append("source = {src:String}")
        params["param_src"] = source
    if name:
        conditions.append("name = {name:String}")
        params["param_name"] = name
    where = " AND ".join(conditions)
    sql = f"SELECT * FROM scores FINAL WHERE {where} ORDER BY timestamp DESC LIMIT {int(limit)} FORMAT JSON"
    try:
        r = await _client._query(sql, params)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception as e:
        logger.error("clickhouse_query_scores_failed", error=str(e))
        return []


async def query_session_event_count(session_id: str, project_id: str) -> tuple[int, int]:
    """Return (count, max_offset) for a session's stored events.

    Uses FINAL so ReplacingMergeTree dedup is applied before counting.
    Returns (0, -1) when no rows exist.
    """
    optic.debug("query_session_event_count: session_id={}, project_id={}", session_id, project_id)
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
        return count, max_off
    except Exception as e:
        logger.error("clickhouse_query_session_event_count_failed", error=str(e))
        return 0, -1


async def query_existing_for_dedup(
    session_id: str,
    project_id: str,
    min_offset: int,
    max_offset: int,
) -> tuple[frozenset[int], frozenset[str]]:
    """Return (existing_offsets, existing_hashes) for the given session/range.

    Fail-open: returns (frozenset(), frozenset()) on any error.
    """
    optic.debug(
        "query_existing_for_dedup: session_id={}, project_id={}, min_offset={}", session_id, project_id, min_offset
    )
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
        return existing_offsets, existing_hashes
    except Exception as e:
        logger.warning("clickhouse_query_existing_for_dedup_failed", error=str(e))
        return frozenset(), frozenset()
