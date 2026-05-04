"""MCP shim data enrichment — join spans table with hook events for richer insights.

The shim provides data hooks cannot:
- Precise latency (monotonic clock, not wall clock)
- Schema compliance (hallucinated tool detection)
- Full input/output (no 64KB truncation)
- tools_available count (how many tools were exposed)

Only Claude Code + the Observal shim produce this data.
Other IDEs will have no spans, and all functions handle that gracefully.
"""

from __future__ import annotations

from datetime import UTC

import structlog

from services.clickhouse import _query

logger = structlog.get_logger(__name__)

# Subquery to find sessions belonging to an agent (same pattern as metrics.py).
_SESSIONS_SUBQUERY = """
    SELECT DISTINCT LogAttributes['session.id']
    FROM otel_logs
    WHERE (LogAttributes['agent_type'] = {aname:String}
           OR LogAttributes['agent_name'] = {aname:String})
      AND Timestamp >= {t_start:String}
      AND Timestamp <= {t_end:String}
      AND LogAttributes['session.id'] != ''
"""


async def get_shim_spans_for_sessions(
    agent_name: str, session_ids: list[str], start: str, end: str
) -> dict[str, list[dict]]:
    """Query spans table for MCP tool calls matching the given sessions.

    Returns a dict of session_id -> list of span dicts.
    Each span has: tool_name, input, output, latency_ms, tool_schema_valid,
    start_time, mcp_id, session_id.
    """
    if not session_ids:
        return {}

    ids_str = ", ".join(f"'{sid}'" for sid in session_ids)
    sql = (
        "SELECT "
        "name AS tool_name, "
        "input, "
        "output, "
        "latency_ms, "
        "tool_schema_valid, "
        "toString(start_time) AS start_time, "
        "mcp_id, "
        "metadata['session.id'] AS session_id "
        "FROM spans FINAL "
        f"WHERE metadata['session.id'] IN ({ids_str}) "
        "AND type = 'tool_call' "
        "AND is_deleted = 0 "
        "AND start_time >= parseDateTimeBestEffort({t_start:String}) "
        "AND start_time <= parseDateTimeBestEffort({t_end:String}) "
        "ORDER BY start_time ASC "
        "LIMIT 5000 "
        "FORMAT JSON"
    )
    params = {"param_t_start": start, "param_t_end": end}

    try:
        r = await _query(sql, params)
        r.raise_for_status()
        rows = r.json().get("data", [])
    except Exception as e:
        logger.error("shim_spans_for_sessions_failed", error=str(e))
        return {}

    result: dict[str, list[dict]] = {}
    for row in rows:
        sid = row.get("session_id", "")
        if not sid:
            continue
        result.setdefault(sid, []).append(row)
    return result


def _parse_ts_ms(ts: str) -> float | None:
    """Parse an ISO-ish timestamp to milliseconds since epoch. Returns None on failure."""
    if not ts:
        return None
    from datetime import datetime

    fmts = [
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
    ]
    ts_trimmed = ts[:26]
    for fmt in fmts:
        try:
            dt = datetime.strptime(ts_trimmed, fmt).replace(tzinfo=UTC)
            return dt.timestamp() * 1000
        except ValueError:
            continue
    return None


async def enrich_session_with_shim(session_id: str, hook_events: list[dict], shim_spans: list[dict]) -> list[dict]:
    """Join shim spans with hook events for a single session.

    Match by: tool_name + timestamp proximity (within 2 seconds).

    Enrichment adds to hook events:
    - mcp_latency_ms: precise latency from shim
    - tool_schema_valid: 0/1 whether tool call matched schema
    - full_tool_input: complete input (no 64KB truncation)
    - full_tool_response: complete output (no truncation)

    Returns the enriched event list (events are modified in-place copies).
    """
    if not shim_spans:
        return hook_events

    used_span_indices: set[int] = set()
    result: list[dict] = []

    for event in hook_events:
        event = dict(event)  # shallow copy to avoid mutating input
        tool_name = event.get("tool_name", "")
        event_ts_ms = _parse_ts_ms(event.get("timestamp", ""))

        if tool_name and event_ts_ms is not None:
            best_idx: int | None = None
            best_diff = float("inf")

            for idx, span in enumerate(shim_spans):
                if idx in used_span_indices:
                    continue
                if span.get("tool_name", "") != tool_name:
                    continue
                span_ts_ms = _parse_ts_ms(span.get("start_time", ""))
                if span_ts_ms is None:
                    continue
                diff = abs(event_ts_ms - span_ts_ms)
                if diff <= 2000 and diff < best_diff:
                    best_diff = diff
                    best_idx = idx

            if best_idx is not None:
                span = shim_spans[best_idx]
                used_span_indices.add(best_idx)
                if span.get("latency_ms") is not None:
                    event["mcp_latency_ms"] = int(span["latency_ms"])
                if span.get("tool_schema_valid") is not None:
                    event["tool_schema_valid"] = int(span["tool_schema_valid"])
                if span.get("input"):
                    event["full_tool_input"] = span["input"]
                if span.get("output"):
                    event["full_tool_response"] = span["output"]

        result.append(event)

    return result


async def compute_mcp_metrics(agent_name: str, start: str, end: str) -> dict:
    """Compute MCP-specific metrics from the spans table.

    Returns:
        total_mcp_calls: int
        latency_p50_ms: int
        latency_p95_ms: int
        latency_p99_ms: int
        schema_violations: int (calls where tool_schema_valid = 0)
        schema_violation_rate: float
        tools_available_count: int (avg tools exposed per call)
        slowest_tools: list[dict] (top 5 by p95 latency)
        error_tools: list[dict] (tools with highest failure rate)
    """
    _default = {
        "total_mcp_calls": 0,
        "latency_p50_ms": 0,
        "latency_p95_ms": 0,
        "latency_p99_ms": 0,
        "schema_violations": 0,
        "schema_violation_rate": 0.0,
        "tools_available_count": 0,
        "slowest_tools": [],
        "error_tools": [],
    }

    # Aggregate query
    agg_sql = """
        SELECT
            count() AS total_mcp_calls,
            quantile(0.5)(latency_ms) AS latency_p50_ms,
            quantile(0.95)(latency_ms) AS latency_p95_ms,
            quantile(0.99)(latency_ms) AS latency_p99_ms,
            countIf(tool_schema_valid = 0) AS schema_violations,
            avg(tools_available) AS tools_available_count
        FROM spans FINAL
        WHERE is_deleted = 0
          AND type = 'tool_call'
          AND latency_ms IS NOT NULL
          AND metadata['agent_name'] IN (
              SELECT DISTINCT LogAttributes['agent_name']
              FROM otel_logs
              WHERE (LogAttributes['agent_type'] = {aname:String}
                     OR LogAttributes['agent_name'] = {aname:String})
                AND Timestamp >= {t_start:String}
                AND Timestamp <= {t_end:String}
          )
          AND start_time >= parseDateTimeBestEffort({t_start:String})
          AND start_time <= parseDateTimeBestEffort({t_end:String})
        FORMAT JSON
    """

    # Slowest tools by p95 latency
    slowest_sql = """
        SELECT
            name AS tool_name,
            count() AS call_count,
            quantile(0.95)(latency_ms) AS p95_latency_ms
        FROM spans FINAL
        WHERE is_deleted = 0
          AND type = 'tool_call'
          AND latency_ms IS NOT NULL
          AND metadata['agent_name'] IN (
              SELECT DISTINCT LogAttributes['agent_name']
              FROM otel_logs
              WHERE (LogAttributes['agent_type'] = {aname:String}
                     OR LogAttributes['agent_name'] = {aname:String})
                AND Timestamp >= {t_start:String}
                AND Timestamp <= {t_end:String}
          )
          AND start_time >= parseDateTimeBestEffort({t_start:String})
          AND start_time <= parseDateTimeBestEffort({t_end:String})
        GROUP BY name
        ORDER BY p95_latency_ms DESC
        LIMIT 5
        FORMAT JSON
    """

    # Tools with highest error rates
    error_tools_sql = """
        SELECT
            name AS tool_name,
            count() AS call_count,
            countIf(status = 'error') AS error_count,
            round(countIf(status = 'error') / count(), 4) AS error_rate
        FROM spans FINAL
        WHERE is_deleted = 0
          AND type = 'tool_call'
          AND metadata['agent_name'] IN (
              SELECT DISTINCT LogAttributes['agent_name']
              FROM otel_logs
              WHERE (LogAttributes['agent_type'] = {aname:String}
                     OR LogAttributes['agent_name'] = {aname:String})
                AND Timestamp >= {t_start:String}
                AND Timestamp <= {t_end:String}
          )
          AND start_time >= parseDateTimeBestEffort({t_start:String})
          AND start_time <= parseDateTimeBestEffort({t_end:String})
        GROUP BY name
        HAVING error_count > 0
        ORDER BY error_rate DESC
        LIMIT 10
        FORMAT JSON
    """

    params = {
        "param_aname": agent_name,
        "param_t_start": start,
        "param_t_end": end,
    }

    try:
        agg_resp = await _query(agg_sql, params)
        agg_resp.raise_for_status()
        agg_rows = agg_resp.json().get("data", [])
    except Exception as e:
        logger.error("mcp_metrics_agg_failed", error=str(e))
        return _default

    if not agg_rows:
        return _default

    row = agg_rows[0]
    total = int(row.get("total_mcp_calls", 0) or 0)
    violations = int(row.get("schema_violations", 0) or 0)
    violation_rate = round(violations / total, 4) if total > 0 else 0.0

    try:
        slowest_resp = await _query(slowest_sql, params)
        slowest_resp.raise_for_status()
        slowest_tools = [
            {
                "tool_name": r["tool_name"],
                "call_count": int(r["call_count"]),
                "p95_latency_ms": int(r["p95_latency_ms"] or 0),
            }
            for r in slowest_resp.json().get("data", [])
        ]
    except Exception as e:
        logger.warning("mcp_slowest_tools_failed", error=str(e))
        slowest_tools = []

    try:
        error_resp = await _query(error_tools_sql, params)
        error_resp.raise_for_status()
        error_tools = [
            {
                "tool_name": r["tool_name"],
                "call_count": int(r["call_count"]),
                "error_count": int(r["error_count"]),
                "error_rate": float(r["error_rate"]),
            }
            for r in error_resp.json().get("data", [])
        ]
    except Exception as e:
        logger.warning("mcp_error_tools_failed", error=str(e))
        error_tools = []

    tools_available_raw = row.get("tools_available_count")
    tools_available_count = int(float(tools_available_raw)) if tools_available_raw else 0

    return {
        "total_mcp_calls": total,
        "latency_p50_ms": int(row.get("latency_p50_ms") or 0),
        "latency_p95_ms": int(row.get("latency_p95_ms") or 0),
        "latency_p99_ms": int(row.get("latency_p99_ms") or 0),
        "schema_violations": violations,
        "schema_violation_rate": violation_rate,
        "tools_available_count": tools_available_count,
        "slowest_tools": slowest_tools,
        "error_tools": error_tools,
    }
