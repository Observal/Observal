"""Deterministic metrics computation from ClickHouse telemetry.

V3: Dual-source approach — primary path queries `session_events` table
using `agent_id`; fallback path queries `otel_logs` using `agent_name`.
"""

from __future__ import annotations

import asyncio
import re

import structlog

from ._deps import get_query
from .pricing import compute_cost_summary

logger = structlog.get_logger(__name__)


# ===========================================================================
# Language detection map
# ===========================================================================

EXTENSION_MAP = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".rs": "Rust",
    ".go": "Go",
    ".java": "Java",
    ".rb": "Ruby",
    ".sql": "SQL",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".json": "JSON",
    ".md": "Markdown",
    ".html": "HTML",
    ".css": "CSS",
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".c": "C",
    ".cpp": "C++",
    ".h": "C/C++",
    ".swift": "Swift",
    ".kt": "Kotlin",
}


# ===========================================================================
# Error categorization (shared by both paths)
# ===========================================================================


def categorize_error(error_text: str) -> str:
    """Categorize a tool error into a high-level bucket."""
    lower = error_text.lower()
    if "exit code" in lower:
        return "command_failed"
    if "permission" in lower:
        return "permission_denied"
    if "rejected" in lower or "doesn't want" in lower or "denied" in lower:
        return "user_rejected"
    if "string to replace not found" in lower or "not unique" in lower:
        return "edit_failed"
    if "modified since read" in lower:
        return "file_changed"
    if "exceeds maximum" in lower or "too large" in lower:
        return "file_too_large"
    if "file not found" in lower or "does not exist" in lower or "no such file" in lower:
        return "file_not_found"
    if "timeout" in lower or "timed out" in lower:
        return "timeout"
    return "other"


# ===========================================================================
# Helper: Git stats parsing
# ===========================================================================


def parse_git_stats(rows: list[dict]) -> dict:
    """Parse git activity from Bash tool call/result events."""
    commits = 0
    pushes = 0
    lines_added = 0
    lines_removed = 0
    files_modified: set[str] = set()

    for row in rows:
        raw = row.get("raw_line", "")
        event_type = row.get("event_type", "")

        if event_type == "tool_call":
            # Look for git commit in Bash input
            if "git commit" in raw:
                commits += 1
            if "git push" in raw:
                pushes += 1
        elif event_type == "tool_result":
            # Parse diff stats: "N files changed, N insertions(+), N deletions(-)"
            match = re.search(r"(\d+) files? changed", raw)
            if match:
                files_modified.add(f"batch_{len(files_modified)}")
            ins_match = re.search(r"(\d+) insertions?\(\+\)", raw)
            if ins_match:
                lines_added += int(ins_match.group(1))
            del_match = re.search(r"(\d+) deletions?\(-\)", raw)
            if del_match:
                lines_removed += int(del_match.group(1))

    return {
        "commits": commits,
        "pushes": pushes,
        "lines_added": lines_added,
        "lines_removed": lines_removed,
        "files_modified": len(files_modified),
    }


# ===========================================================================
# Helper: Language detection
# ===========================================================================


def detect_languages(file_paths: list[str]) -> dict[str, float]:
    """Map file paths to language distribution percentages."""
    counts: dict[str, int] = {}
    for path in file_paths:
        if not path:
            continue
        ext = "." + path.rsplit(".", 1)[-1] if "." in path else ""
        lang = EXTENSION_MAP.get(ext, "Other")
        counts[lang] = counts.get(lang, 0) + 1
    total = sum(counts.values()) or 1
    return {lang: round(count / total, 3) for lang, count in sorted(counts.items(), key=lambda x: -x[1])}


# ===========================================================================
# Helper: Multi-session detection
# ===========================================================================


def detect_multi_session(sessions: list[dict]) -> dict:
    """Detect overlapping sessions (user working in multiple sessions simultaneously).

    From session metas, find sessions whose time ranges overlap within a
    30-minute sliding window.
    """
    if not sessions:
        return {"detected": False, "concurrent_windows": 0, "max_concurrent": 0}

    # Parse session time ranges
    parsed = []
    for s in sessions:
        start = s.get("start_time", "")
        end = s.get("end_time", "")
        if start and end:
            parsed.append({"session_id": s.get("session_id", ""), "start": start, "end": end})

    # Sort by start time
    parsed.sort(key=lambda x: x["start"])

    concurrent_windows = 0
    max_concurrent = 1

    for i, a in enumerate(parsed):
        concurrent = 1
        for j in range(i + 1, len(parsed)):
            b = parsed[j]
            # If b starts before a ends, they overlap
            if b["start"] < a["end"]:
                concurrent += 1
            else:
                break
        if concurrent > 1:
            concurrent_windows += 1
        max_concurrent = max(max_concurrent, concurrent)

    return {
        "detected": concurrent_windows > 0,
        "concurrent_windows": concurrent_windows,
        "max_concurrent": max_concurrent,
    }


# ===========================================================================
# V3 Primary Path: session_events queries
# ===========================================================================


async def _count_sessions_in_events(agent_id: str, start: str, end: str) -> int:
    """Quick count to determine if session_stats_agg has data for this agent.

    Reads from the pre-aggregated AggregatingMergeTree table instead of
    scanning session_events FINAL — one tiny row per session vs N event rows.
    """
    _query = get_query()
    sql = """
        SELECT count(DISTINCT session_id) AS cnt
        FROM session_stats_agg
        WHERE agent_id = {agent_id:String}
          AND last_event_time >= {t_start:String}
          AND last_event_time <= {t_end:String}
          AND last_event_time < '2099-01-01 00:00:00'
        FORMAT JSON
    """
    params = {
        "param_agent_id": agent_id,
        "param_t_start": start,
        "param_t_end": end,
    }
    try:
        r = await _query(sql, params)
        r.raise_for_status()
        data = r.json().get("data", [])
        return int(data[0]["cnt"]) if data else 0
    except Exception as e:
        logger.warning("count_sessions_in_events_failed", error=str(e))
        return 0


async def _ev_session_overview(agent_id: str, start: str, end: str) -> dict:
    """Session overview from session_stats_agg.

    Uses the pre-aggregated AggregatingMergeTree table: no FINAL, no event-row scan.
    first_event_time / last_event_time are SimpleAggregateFunction(min/max) columns
    that merge automatically on GROUP BY.
    """
    _query = get_query()
    sql = """
        SELECT
            count()                   AS total_sessions,
            count(DISTINCT user_id)   AS unique_users,
            min(first_event_time)     AS first_session,
            max(last_event_time)      AS last_session
        FROM (
            SELECT session_id, user_id,
                   min(first_event_time) AS first_event_time,
                   max(last_event_time)  AS last_event_time
            FROM (
                SELECT * FROM session_stats_agg
                WHERE agent_id = {agent_id:String}
                  AND last_event_time >= {t_start:String}
                  AND last_event_time <= {t_end:String}
                  AND last_event_time < '2099-01-01 00:00:00'
            )
            GROUP BY session_id, user_id
        )
        FORMAT JSON
    """
    params = {
        "param_agent_id": agent_id,
        "param_t_start": start,
        "param_t_end": end,
    }
    try:
        r = await _query(sql, params)
        r.raise_for_status()
        data = r.json().get("data", [])
        return data[0] if data else {}
    except Exception as e:
        logger.error("ev_session_overview_failed", error=str(e))
        return {}


async def _ev_token_aggregates(agent_id: str, start: str, end: str) -> dict:
    """Token aggregates from session_stats_agg pre-aggregated columns.

    session_stats_agg stores per-session sums via SimpleAggregateFunction(sum, Int64);
    GROUP BY session_id merges partial aggregates, then we sum over all sessions.
    Eliminates the per-event-row scan + FINAL on session_events.
    """
    _query = get_query()
    sql = """
        SELECT
            sum(input_tokens)       AS total_input_tokens,
            sum(output_tokens)      AS total_output_tokens,
            sum(cache_read_tokens)  AS total_cache_read_tokens,
            sum(cache_write_tokens) AS total_cache_write_tokens
        FROM (
            SELECT session_id,
                   sum(input_tokens)       AS input_tokens,
                   sum(output_tokens)      AS output_tokens,
                   sum(cache_read_tokens)  AS cache_read_tokens,
                   sum(cache_write_tokens) AS cache_write_tokens
            FROM (
                SELECT * FROM session_stats_agg
                WHERE agent_id = {agent_id:String}
                  AND last_event_time >= {t_start:String}
                  AND last_event_time <= {t_end:String}
                  AND last_event_time < '2099-01-01 00:00:00'
            )
            GROUP BY session_id
        )
        FORMAT JSON
    """
    params = {
        "param_agent_id": agent_id,
        "param_t_start": start,
        "param_t_end": end,
    }
    try:
        r = await _query(sql, params)
        r.raise_for_status()
        data = r.json().get("data", [])
        row = data[0] if data else {}
        # Add computed total
        inp = int(row.get("total_input_tokens") or 0)
        out = int(row.get("total_output_tokens") or 0)
        row["total_tokens"] = inp + out
        return row
    except Exception as e:
        logger.error("ev_token_aggregates_failed", error=str(e))
        return {}


async def _ev_credit_aggregates(agent_id: str, start: str, end: str) -> dict:
    """Credit aggregates from session_stats_agg (Kiro only).

    Filters by ide = 'kiro' at the per-session level; total_credits in the MV
    is the sum of all credits for that session (Kiro is the only IDE that emits
    non-zero credits so the filter is equivalent to the original event-level filter).
    """
    _query = get_query()
    sql = """
        SELECT
            sum(session_credits)              AS total_credits,
            countIf(session_credits > 0)      AS sessions_with_credits
        FROM (
            SELECT session_id,
                   sum(total_credits) AS session_credits
            FROM (
                SELECT * FROM session_stats_agg
                WHERE agent_id = {agent_id:String}
                  AND ide = 'kiro'
                  AND last_event_time >= {t_start:String}
                  AND last_event_time <= {t_end:String}
                  AND last_event_time < '2099-01-01 00:00:00'
            )
            GROUP BY session_id
        )
        FORMAT JSON
    """
    params = {
        "param_agent_id": agent_id,
        "param_t_start": start,
        "param_t_end": end,
    }
    try:
        r = await _query(sql, params)
        r.raise_for_status()
        data = r.json().get("data", [])
        return data[0] if data else {}
    except Exception as e:
        logger.error("ev_credit_aggregates_failed", error=str(e))
        return {}


async def _ev_duration_stats(agent_id: str, start: str, end: str) -> dict:
    """Duration percentiles from session_stats_agg.

    first_event_time / last_event_time are materialized min/max per session,
    so dateDiff can be computed per-session row without scanning individual events.
    """
    _query = get_query()
    sql = """
        SELECT
            avg(duration_s) AS avg_duration_seconds,
            quantile(0.5)(duration_s) AS p50_duration_seconds,
            quantile(0.9)(duration_s) AS p90_duration_seconds,
            quantile(0.99)(duration_s) AS p99_duration_seconds
        FROM (
            SELECT dateDiff(
                'second',
                min(first_event_time),
                max(last_event_time)
            ) AS duration_s
            FROM (
                SELECT * FROM session_stats_agg
                WHERE agent_id = {agent_id:String}
                  AND last_event_time >= {t_start:String}
                  AND last_event_time <= {t_end:String}
                  AND last_event_time < '2099-01-01 00:00:00'
            )
            GROUP BY session_id
        )
        FORMAT JSON
    """
    params = {
        "param_agent_id": agent_id,
        "param_t_start": start,
        "param_t_end": end,
    }
    try:
        r = await _query(sql, params)
        r.raise_for_status()
        data = r.json().get("data", [])
        return data[0] if data else {}
    except Exception as e:
        logger.error("ev_duration_stats_failed", error=str(e))
        return {}


async def _ev_tool_usage(agent_id: str, start: str, end: str) -> list[dict]:
    """Top tools by invocation count from session_events."""
    _query = get_query()
    sql = """
        SELECT
            tool_name AS name,
            count() AS invocations,
            countIf(event_type = 'tool_result' AND JSONExtractBool(raw_line, 'is_error')) AS errors
        FROM session_events FINAL
        WHERE agent_id = {agent_id:String}
          AND timestamp BETWEEN {t_start:String} AND {t_end:String}
          AND event_type IN ('tool_call', 'tool_result')
          AND tool_name != ''
        GROUP BY name
        ORDER BY invocations DESC
        LIMIT 20
        SETTINGS max_final_threads = 4, do_not_merge_across_partitions_select_final = 1
        FORMAT JSON
    """
    params = {
        "param_agent_id": agent_id,
        "param_t_start": start,
        "param_t_end": end,
    }
    try:
        r = await _query(sql, params)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception as e:
        logger.error("ev_tool_usage_failed", error=str(e))
        return []


async def _ev_tool_error_categories(agent_id: str, start: str, end: str) -> dict:
    """Get tool errors with categorization from session_events."""
    _query = get_query()
    sql = """
        SELECT
            tool_name,
            content_preview AS error_text
        FROM session_events FINAL
        WHERE agent_id = {agent_id:String}
          AND timestamp BETWEEN {t_start:String} AND {t_end:String}
          AND event_type = 'tool_result'
          AND JSONExtractBool(raw_line, 'is_error') = 1
        LIMIT 500
        SETTINGS max_final_threads = 4, do_not_merge_across_partitions_select_final = 1
        FORMAT JSON
    """
    params = {
        "param_agent_id": agent_id,
        "param_t_start": start,
        "param_t_end": end,
    }
    try:
        r = await _query(sql, params)
        r.raise_for_status()
        rows = r.json().get("data", [])

        categories: dict[str, int] = {}
        by_tool: dict[str, dict[str, int]] = {}
        for row in rows:
            cat = categorize_error(row.get("error_text", ""))
            categories[cat] = categories.get(cat, 0) + 1
            tool = row.get("tool_name", "unknown")
            if tool not in by_tool:
                by_tool[tool] = {}
            by_tool[tool][cat] = by_tool[tool].get(cat, 0) + 1

        return {
            "total_categorized": len(rows),
            "categories": categories,
            "by_tool": by_tool,
        }
    except Exception as e:
        logger.error("ev_tool_error_categories_failed", error=str(e))
        return {"total_categorized": 0, "categories": {}, "by_tool": {}}


async def _ev_interruption_metrics(agent_id: str, start: str, end: str) -> dict:
    """Interruption metrics from session_events."""
    _query = get_query()
    sql = """
        SELECT
            countIf(content_preview LIKE '%Request interrupted by user%') AS user_interruptions,
            count(DISTINCT session_id) AS total_sessions_with_stops
        FROM session_events FINAL
        WHERE agent_id = {agent_id:String}
          AND timestamp BETWEEN {t_start:String} AND {t_end:String}
          AND event_type IN ('assistant_text', 'user_prompt')
        SETTINGS max_final_threads = 4, do_not_merge_across_partitions_select_final = 1
        FORMAT JSON
    """
    params = {
        "param_agent_id": agent_id,
        "param_t_start": start,
        "param_t_end": end,
    }
    try:
        r = await _query(sql, params)
        r.raise_for_status()
        data = r.json().get("data", [])
        row = data[0] if data else {}
        return {
            "user_interruptions": int(row.get("user_interruptions", 0)),
            "total_sessions_with_stops": int(row.get("total_sessions_with_stops", 0)),
        }
    except Exception as e:
        logger.error("ev_interruption_metrics_failed", error=str(e))
        return {"user_interruptions": 0, "total_sessions_with_stops": 0}


async def _ev_git_stats(agent_id: str, start: str, end: str) -> dict:
    """Parse git activity from Bash tool calls in session_events."""
    _query = get_query()
    sql = """
        SELECT raw_line, event_type
        FROM session_events FINAL
        WHERE agent_id = {agent_id:String}
          AND timestamp BETWEEN {t_start:String} AND {t_end:String}
          AND event_type IN ('tool_call', 'tool_result')
          AND tool_name = 'Bash'
        LIMIT 1000
        SETTINGS max_final_threads = 4, do_not_merge_across_partitions_select_final = 1
        FORMAT JSON
    """
    params = {
        "param_agent_id": agent_id,
        "param_t_start": start,
        "param_t_end": end,
    }
    try:
        r = await _query(sql, params)
        r.raise_for_status()
        rows = r.json().get("data", [])
        return parse_git_stats(rows)
    except Exception as e:
        logger.error("ev_git_stats_failed", error=str(e))
        return {"commits": 0, "pushes": 0, "lines_added": 0, "lines_removed": 0, "files_modified": 0}


async def _ev_language_detection(agent_id: str, start: str, end: str) -> dict[str, float]:
    """Detect languages from file operations in session_events."""
    _query = get_query()
    sql = """
        SELECT
            tool_name,
            JSONExtractString(raw_line, 'message', 'content', 'input', 'file_path') AS file_path
        FROM session_events FINAL
        WHERE agent_id = {agent_id:String}
          AND timestamp BETWEEN {t_start:String} AND {t_end:String}
          AND event_type = 'tool_call'
          AND tool_name IN ('Read', 'Edit', 'Write', 'Glob', 'Grep')
        LIMIT 2000
        SETTINGS max_final_threads = 4, do_not_merge_across_partitions_select_final = 1
        FORMAT JSON
    """
    params = {
        "param_agent_id": agent_id,
        "param_t_start": start,
        "param_t_end": end,
    }
    try:
        r = await _query(sql, params)
        r.raise_for_status()
        rows = r.json().get("data", [])
        file_paths = [row.get("file_path", "") for row in rows]
        return detect_languages(file_paths)
    except Exception as e:
        logger.error("ev_language_detection_failed", error=str(e))
        return {}


async def _ev_subagent_stats(agent_id: str, start: str, end: str) -> dict:
    """Subagent statistics from session_stats_agg.

    parent_session_id != '' identifies subagent sessions in the MV.
    output_tokens is already summed per session; event_count serves as the
    subagent event proxy (individual event rows are not needed).
    """
    _query = get_query()
    sql = """
        SELECT
            count()                    AS total_subagent_sessions,
            sum(event_count)           AS subagent_events,
            sum(output_tokens)         AS subagent_output_tokens
        FROM (
            SELECT session_id,
                   sum(event_count)   AS event_count,
                   sum(output_tokens) AS output_tokens
            FROM (
                SELECT * FROM session_stats_agg
                WHERE agent_id = {agent_id:String}
                  AND last_event_time >= {t_start:String}
                  AND last_event_time <= {t_end:String}
                  AND last_event_time < '2099-01-01 00:00:00'
            )
            GROUP BY session_id
            HAVING anyLast(parent_session_id) != ''
        )
        FORMAT JSON
    """
    params = {
        "param_agent_id": agent_id,
        "param_t_start": start,
        "param_t_end": end,
    }
    try:
        r = await _query(sql, params)
        r.raise_for_status()
        data = r.json().get("data", [])
        row = data[0] if data else {}
        return {
            "total_subagent_sessions": int(row.get("total_subagent_sessions", 0)),
            "subagent_events": int(row.get("subagent_events", 0)),
            "subagent_output_tokens": int(row.get("subagent_output_tokens", 0)),
        }
    except Exception as e:
        logger.error("ev_subagent_stats_failed", error=str(e))
        return {"total_subagent_sessions": 0, "subagent_events": 0, "subagent_output_tokens": 0}


async def _ev_time_of_day(agent_id: str, start: str, end: str) -> dict:
    """Hourly distribution of user prompts from session_events."""
    _query = get_query()
    sql = """
        SELECT
            toHour(timestamp) AS hour,
            count() AS event_count
        FROM session_events FINAL
        WHERE agent_id = {agent_id:String}
          AND timestamp BETWEEN {t_start:String} AND {t_end:String}
          AND event_type = 'user_prompt'
        GROUP BY hour
        ORDER BY hour
        SETTINGS max_final_threads = 4, do_not_merge_across_partitions_select_final = 1
        FORMAT JSON
    """
    params = {
        "param_agent_id": agent_id,
        "param_t_start": start,
        "param_t_end": end,
    }
    try:
        r = await _query(sql, params)
        r.raise_for_status()
        rows = r.json().get("data", [])
        # Convert to dict format expected by HTML export
        hourly_counts = {int(row["hour"]): int(row["event_count"]) for row in rows}
        total = sum(hourly_counts.values())
        peak_hours = sorted(hourly_counts, key=lambda h: -hourly_counts.get(h, 0))[:3]
        work_count = sum(hourly_counts.get(h, 0) for h in range(9, 17))
        return {
            "hourly_counts": hourly_counts,
            "peak_hours": peak_hours,
            "work_hours_pct": round(work_count / total * 100, 1) if total else 0.0,
        }
    except Exception as e:
        logger.error("ev_time_of_day_failed", error=str(e))
        return {}


async def _ev_per_session_tokens(agent_id: str, start: str, end: str) -> list[dict]:
    """Per-session token breakdown from session_stats_agg.

    token columns are SimpleAggregateFunction(sum) in the MV — GROUP BY session_id
    merges partial aggregates.  model is anyLast(String) so no JSONExtract needed.
    """
    _query = get_query()
    sql = """
        SELECT
            session_id,
            sum(input_tokens)       AS input_tokens,
            sum(output_tokens)      AS output_tokens,
            sum(cache_read_tokens)  AS cache_read,
            sum(cache_write_tokens) AS cache_write,
            sum(total_credits)      AS credits,
            anyLast(ide)            AS session_ide,
            anyLastIf(model, model != '') AS model
        FROM (
            SELECT * FROM session_stats_agg
            WHERE agent_id = {agent_id:String}
              AND last_event_time >= {t_start:String}
              AND last_event_time <= {t_end:String}
              AND last_event_time < '2099-01-01 00:00:00'
        )
        GROUP BY session_id
        FORMAT JSON
    """
    params = {
        "param_agent_id": agent_id,
        "param_t_start": start,
        "param_t_end": end,
    }
    try:
        r = await _query(sql, params)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception as e:
        logger.error("ev_per_session_tokens_failed", error=str(e))
        return []


async def _ev_session_details(agent_id: str, start: str, end: str) -> list[dict]:
    """Per-session details from session_stats_agg.

    prompt_count / tool_call_count are materialized sums in the MV;
    duration_seconds is computed from first_event_time / last_event_time.
    No FINAL scan on session_events needed.
    """
    _query = get_query()
    sql = """
        SELECT
            session_id,
            dateDiff(
                'second',
                min(first_event_time),
                max(last_event_time)
            )                          AS duration_seconds,
            sum(prompt_count)          AS prompt_count,
            sum(tool_call_count)       AS tool_call_count,
            sum(input_tokens)          AS input_tokens,
            sum(output_tokens)         AS output_tokens,
            anyLast(ide)               AS session_ide,
            anyLast(parent_session_id) AS session_parent_id
        FROM (
            SELECT * FROM session_stats_agg
            WHERE agent_id = {agent_id:String}
              AND last_event_time >= {t_start:String}
              AND last_event_time <= {t_end:String}
              AND last_event_time < '2099-01-01 00:00:00'
        )
        GROUP BY session_id
        ORDER BY min(first_event_time) DESC
        LIMIT 200
        FORMAT JSON
    """
    params = {
        "param_agent_id": agent_id,
        "param_t_start": start,
        "param_t_end": end,
    }
    try:
        r = await _query(sql, params)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception as e:
        logger.error("ev_session_details_failed", error=str(e))
        return []


# ===========================================================================
# V3 compute_all_metrics_from_events
# ===========================================================================


async def _ev_response_times(agent_id: str, start: str, end: str) -> dict:
    """Compute response time distribution from session event timestamps.

    Response time = gap between an assistant response and the next user prompt.
    """
    _query = get_query()
    sql = """
        SELECT session_id, event_type, timestamp
        FROM session_events FINAL
        WHERE agent_id = {agent_id:String}
          AND timestamp BETWEEN {t_start:String} AND {t_end:String}
          AND event_type IN ('assistant_text', 'user_prompt')
        ORDER BY session_id, timestamp
        LIMIT 10000
        SETTINGS max_final_threads = 4, do_not_merge_across_partitions_select_final = 1
        FORMAT JSON
    """
    params = {
        "param_agent_id": agent_id,
        "param_t_start": start,
        "param_t_end": end,
    }
    try:
        r = await _query(sql, params)
        r.raise_for_status()
        rows = r.json().get("data", [])
    except Exception as e:
        logger.error("ev_response_times_failed", error=str(e))
        return {}

    if not rows:
        return {}

    from datetime import datetime

    # Group by session and compute gaps
    buckets = {"<2s": 0, "2-10s": 0, "10-30s": 0, "30s-1m": 0, "1-2m": 0, "2-5m": 0, "5-15m": 0, ">15m": 0}
    gaps: list[float] = []

    prev_event = None
    for row in rows:
        if (
            prev_event
            and prev_event.get("session_id") == row.get("session_id")
            and prev_event.get("event_type") == "assistant_text"
            and row.get("event_type") == "user_prompt"
        ):
            try:
                t1 = datetime.fromisoformat(str(prev_event["timestamp"]).replace("Z", "+00:00"))
                t2 = datetime.fromisoformat(str(row["timestamp"]).replace("Z", "+00:00"))
                gap = (t2 - t1).total_seconds()
                if 2 < gap < 3600:  # Filter noise
                    gaps.append(gap)
                    if gap < 2:
                        buckets["<2s"] += 1
                    elif gap < 10:
                        buckets["2-10s"] += 1
                    elif gap < 30:
                        buckets["10-30s"] += 1
                    elif gap < 60:
                        buckets["30s-1m"] += 1
                    elif gap < 120:
                        buckets["1-2m"] += 1
                    elif gap < 300:
                        buckets["2-5m"] += 1
                    elif gap < 900:
                        buckets["5-15m"] += 1
                    else:
                        buckets[">15m"] += 1
            except (ValueError, TypeError):
                pass
        prev_event = row

    median_seconds = sorted(gaps)[len(gaps) // 2] if gaps else 0.0

    return {
        "buckets": buckets,
        "median_seconds": round(median_seconds, 1),
        "total_measured": len(gaps),
    }


async def compute_all_metrics_from_events(agent_id: str, start: str, end: str) -> dict:
    """Run all metric queries against session_events in parallel."""
    (
        overview,
        tokens,
        credits,
        duration,
        tools,
        tool_errors,
        interruptions,
        git,
        languages,
        subagents,
        time_of_day,
        per_session_tokens,
        sessions,
        response_times,
    ) = await asyncio.gather(
        _ev_session_overview(agent_id, start, end),
        _ev_token_aggregates(agent_id, start, end),
        _ev_credit_aggregates(agent_id, start, end),
        _ev_duration_stats(agent_id, start, end),
        _ev_tool_usage(agent_id, start, end),
        _ev_tool_error_categories(agent_id, start, end),
        _ev_interruption_metrics(agent_id, start, end),
        _ev_git_stats(agent_id, start, end),
        _ev_language_detection(agent_id, start, end),
        _ev_subagent_stats(agent_id, start, end),
        _ev_time_of_day(agent_id, start, end),
        _ev_per_session_tokens(agent_id, start, end),
        _ev_session_details(agent_id, start, end),
        _ev_response_times(agent_id, start, end),
    )

    # Compute cost summary from per-session token data
    cost = compute_cost_summary(per_session_tokens)

    # Multi-session detection from session details
    multi_session = detect_multi_session(sessions)

    # Compute error breakdown from tool usage data
    total_tool_calls = sum(int(t.get("invocations", 0)) for t in tools)
    total_tool_errors = sum(int(t.get("errors", 0)) for t in tools)
    errors = {
        "total_events": 0,
        "total_tool_calls": total_tool_calls,
        "error_events": total_tool_errors,
        "error_rate": round(total_tool_errors / total_tool_calls, 4) if total_tool_calls > 0 else 0,
    }

    # Compute derived metrics
    total_sessions = int(overview.get("total_sessions", 0))
    first_session = overview.get("first_session", "")
    last_session = overview.get("last_session", "")

    # days_active and sessions_per_day
    days_active = 1
    if first_session and last_session:
        try:
            from datetime import datetime

            t1 = datetime.fromisoformat(str(first_session).replace("Z", "+00:00"))
            t2 = datetime.fromisoformat(str(last_session).replace("Z", "+00:00"))
            days_active = max(1, (t2 - t1).days + 1)
        except (ValueError, TypeError):
            pass

    overview["days_active"] = days_active
    overview["sessions_per_day"] = round(total_sessions / days_active, 1) if days_active > 0 else 0

    # tokens_per_session
    total_tokens = int(tokens.get("total_tokens", 0))
    if total_sessions > 0 and total_tokens > 0:
        tokens["tokens_per_session"] = round(total_tokens / total_sessions)

    # credits_per_session
    total_credits = int(credits.get("total_credits", 0))
    sessions_with_credits = int(credits.get("sessions_with_credits", 0))
    if sessions_with_credits > 0:
        credits["credits_per_session"] = round(total_credits / sessions_with_credits, 2)

    # total_hours
    avg_dur = float(duration.get("avg_duration_seconds", 0))
    duration["total_hours"] = round((avg_dur * total_sessions) / 3600, 1) if total_sessions > 0 else 0

    # interruption_rate
    user_interruptions = int(interruptions.get("user_interruptions", 0))
    total_stops = int(interruptions.get("total_sessions_with_stops", 0))
    interruptions["total_stops"] = total_stops
    interruptions["interruption_rate"] = round(user_interruptions / total_sessions, 3) if total_sessions > 0 else 0

    # Add error_rate to tool usage
    for t in tools:
        inv = int(t.get("invocations", 0))
        err = int(t.get("errors", 0))
        t["error_rate"] = round(err / inv, 4) if inv > 0 else 0.0

    return {
        "overview": overview,
        "tokens": tokens,
        "credits": credits,
        "duration": duration,
        "errors": errors,
        "tools": tools,
        "sessions": sessions,
        "cost": cost,
        "tool_errors": tool_errors,
        "interruptions": interruptions,
        "git": git,
        "languages": languages,
        "response_times": response_times,
        "time_of_day": time_of_day,
        "multi_session": multi_session,
        "subagents": subagents,
        "reconciliation": {"available": False},
        "mcp": {
            "total_mcp_calls": 0,
            "latency_p50_ms": 0,
            "latency_p95_ms": 0,
            "latency_p99_ms": 0,
            "schema_violations": 0,
            "schema_violation_rate": 0.0,
            "tools_available_count": 0,
            "slowest_tools": [],
            "error_tools": [],
        },
    }


# ===========================================================================
# Legacy Fallback Path: otel_logs queries
# ===========================================================================

# Subquery to find all session IDs belonging to an agent.
# Matches sessions where either agent_type or agent_name equals the registry name.
_SESSIONS_SUBQUERY = """
    SELECT DISTINCT LogAttributes['session.id']
    FROM otel_logs
    WHERE (LogAttributes['agent_type'] = {aname:String}
           OR LogAttributes['agent_name'] = {aname:String})
      AND Timestamp >= {t_start:String}
      AND Timestamp <= {t_end:String}
      AND LogAttributes['session.id'] != ''
"""


async def get_session_overview(agent_name: str, start: str, end: str) -> dict:
    """Count sessions and unique users for the agent in the time window."""
    _query = get_query()
    sql = f"""
        SELECT
            count(DISTINCT LogAttributes['session.id']) AS total_sessions,
            count(DISTINCT LogAttributes['user.id']) AS unique_users,
            min(Timestamp) AS first_session,
            max(Timestamp) AS last_session
        FROM otel_logs
        WHERE LogAttributes['session.id'] IN ({_SESSIONS_SUBQUERY})
          AND Timestamp >= {{t_start:String}}
          AND Timestamp <= {{t_end:String}}
        FORMAT JSON
    """
    params = {
        "param_aname": agent_name,
        "param_t_start": start,
        "param_t_end": end,
    }
    try:
        r = await _query(sql, params)
        r.raise_for_status()
        data = r.json().get("data", [])
        return data[0] if data else {}
    except Exception as e:
        logger.error("insight_session_overview_failed", error=str(e))
        return {}


async def get_token_aggregates(agent_name: str, start: str, end: str) -> dict:
    """Aggregate token counts from otel_logs for this agent's sessions."""
    _query = get_query()
    sql = f"""
        SELECT
            sum(toUInt64OrZero(LogAttributes['input_tokens'])) AS total_input_tokens,
            sum(toUInt64OrZero(LogAttributes['output_tokens'])) AS total_output_tokens,
            sum(toUInt64OrZero(LogAttributes['input_tokens'])) + sum(toUInt64OrZero(LogAttributes['output_tokens'])) AS total_tokens,
            sum(toUInt64OrZero(LogAttributes['cache_read_tokens'])) AS total_cache_read_tokens,
            sum(toUInt64OrZero(LogAttributes['cache_creation_tokens'])) AS total_cache_write_tokens
        FROM otel_logs
        WHERE LogAttributes['session.id'] IN ({_SESSIONS_SUBQUERY})
          AND Timestamp >= {{t_start:String}}
          AND Timestamp <= {{t_end:String}}
        FORMAT JSON
    """
    params = {
        "param_aname": agent_name,
        "param_t_start": start,
        "param_t_end": end,
    }
    try:
        r = await _query(sql, params)
        r.raise_for_status()
        data = r.json().get("data", [])
        return data[0] if data else {}
    except Exception as e:
        logger.error("insight_token_aggregates_failed", error=str(e))
        return {}


async def get_latency_and_duration(agent_name: str, start: str, end: str) -> dict:
    """Compute session duration stats from otel_logs timestamps."""
    _query = get_query()
    sql = f"""
        SELECT
            count() AS session_count,
            avg(duration_s) AS avg_duration_seconds,
            quantile(0.5)(duration_s) AS p50_duration_seconds,
            quantile(0.9)(duration_s) AS p90_duration_seconds
        FROM (
            SELECT
                dateDiff('second', min(Timestamp), max(Timestamp)) AS duration_s
            FROM otel_logs
            WHERE LogAttributes['session.id'] IN ({_SESSIONS_SUBQUERY})
              AND Timestamp >= {{t_start:String}}
              AND Timestamp <= {{t_end:String}}
            GROUP BY LogAttributes['session.id']
        )
        FORMAT JSON
    """
    params = {
        "param_aname": agent_name,
        "param_t_start": start,
        "param_t_end": end,
    }
    try:
        r = await _query(sql, params)
        r.raise_for_status()
        data = r.json().get("data", [])
        return data[0] if data else {}
    except Exception as e:
        logger.error("insight_latency_failed", error=str(e))
        return {}


async def get_error_breakdown(agent_name: str, start: str, end: str) -> dict:
    """Get tool call success/error rates from otel_logs."""
    _query = get_query()
    sql = f"""
        SELECT
            count() AS total_events,
            countIf(LogAttributes['event.name'] = 'hook_posttooluse') AS total_tool_calls,
            countIf(LogAttributes['event.name'] = 'hook_stopfailure') AS failure_stops,
            countIf(LogAttributes['error'] != '') AS error_events
        FROM otel_logs
        WHERE LogAttributes['session.id'] IN ({_SESSIONS_SUBQUERY})
          AND Timestamp >= {{t_start:String}}
          AND Timestamp <= {{t_end:String}}
        FORMAT JSON
    """
    params = {
        "param_aname": agent_name,
        "param_t_start": start,
        "param_t_end": end,
    }
    try:
        r = await _query(sql, params)
        r.raise_for_status()
        data = r.json().get("data", [])
        row = data[0] if data else {}
        total = int(row.get("total_tool_calls", 0))
        errors = int(row.get("error_events", 0))
        row["error_rate"] = round(errors / total, 4) if total > 0 else 0
        return row
    except Exception as e:
        logger.error("insight_error_breakdown_failed", error=str(e))
        return {}


async def get_tool_usage(agent_name: str, start: str, end: str) -> list[dict]:
    """Get top tools by invocation count from otel_logs."""
    _query = get_query()
    sql = f"""
        SELECT
            LogAttributes['tool_name'] AS name,
            count() AS invocations,
            countIf(LogAttributes['error'] != '') AS errors
        FROM otel_logs
        WHERE LogAttributes['session.id'] IN ({_SESSIONS_SUBQUERY})
          AND Timestamp >= {{t_start:String}}
          AND Timestamp <= {{t_end:String}}
          AND LogAttributes['event.name'] IN ('hook_posttooluse', 'tool_result')
          AND LogAttributes['tool_name'] != ''
        GROUP BY name
        ORDER BY invocations DESC
        LIMIT 20
        FORMAT JSON
    """
    params = {
        "param_aname": agent_name,
        "param_t_start": start,
        "param_t_end": end,
    }
    try:
        r = await _query(sql, params)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception as e:
        logger.error("insight_tool_usage_failed", error=str(e))
        return []


async def get_session_details(agent_name: str, start: str, end: str) -> list[dict]:
    """Get per-session stats from otel_logs."""
    _query = get_query()
    sql = f"""
        SELECT
            LogAttributes['session.id'] AS session_id,
            dateDiff('second', min(Timestamp), max(Timestamp)) AS duration_seconds,
            greatest(
                countIf(LogAttributes['event.name'] = 'user_prompt'),
                countIf(LogAttributes['event.name'] = 'hook_userpromptsubmit')
            ) AS prompt_count,
            greatest(
                countIf(LogAttributes['event.name'] = 'tool_result'),
                countIf(LogAttributes['event.name'] = 'hook_posttooluse')
            ) AS tool_call_count,
            sum(toUInt64OrZero(LogAttributes['input_tokens'])) AS input_tokens,
            sum(toUInt64OrZero(LogAttributes['output_tokens'])) AS output_tokens
        FROM otel_logs
        WHERE LogAttributes['session.id'] IN ({_SESSIONS_SUBQUERY})
          AND Timestamp >= {{t_start:String}}
          AND Timestamp <= {{t_end:String}}
        GROUP BY session_id
        ORDER BY min(Timestamp) DESC
        LIMIT 200
        FORMAT JSON
    """
    params = {
        "param_aname": agent_name,
        "param_t_start": start,
        "param_t_end": end,
    }
    try:
        r = await _query(sql, params)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception as e:
        logger.error("insight_session_details_failed", error=str(e))
        return []


async def get_per_session_tokens(agent_name: str, start: str, end: str) -> list[dict]:
    """Get per-session token breakdown with model name for cost computation."""
    _query = get_query()
    sql = f"""
        SELECT
            LogAttributes['session.id'] AS session_id,
            sum(toUInt64OrZero(LogAttributes['input_tokens'])) AS input_tokens,
            sum(toUInt64OrZero(LogAttributes['output_tokens'])) AS output_tokens,
            sum(toUInt64OrZero(LogAttributes['cache_read_tokens'])) AS cache_read,
            sum(toUInt64OrZero(LogAttributes['cache_creation_tokens'])) AS cache_write,
            anyIf(LogAttributes['model'], LogAttributes['model'] != '') AS model
        FROM otel_logs
        WHERE LogAttributes['session.id'] IN ({_SESSIONS_SUBQUERY})
          AND Timestamp >= {{t_start:String}}
          AND Timestamp <= {{t_end:String}}
        GROUP BY session_id
        FORMAT JSON
    """
    params = {
        "param_aname": agent_name,
        "param_t_start": start,
        "param_t_end": end,
    }
    try:
        r = await _query(sql, params)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception as e:
        logger.error("insight_per_session_tokens_failed", error=str(e))
        return []


async def get_tool_error_categories(agent_name: str, start: str, end: str) -> dict:
    """Get tool errors with their text for categorization in Python."""
    _query = get_query()
    sql = f"""
        SELECT
            LogAttributes['tool_name'] AS tool_name,
            LogAttributes['error'] AS error_text
        FROM otel_logs
        WHERE LogAttributes['session.id'] IN ({_SESSIONS_SUBQUERY})
          AND Timestamp >= {{t_start:String}}
          AND Timestamp <= {{t_end:String}}
          AND LogAttributes['error'] != ''
        LIMIT 500
        FORMAT JSON
    """
    params = {
        "param_aname": agent_name,
        "param_t_start": start,
        "param_t_end": end,
    }
    try:
        r = await _query(sql, params)
        r.raise_for_status()
        rows = r.json().get("data", [])

        # Categorize errors
        categories: dict[str, int] = {}
        by_tool: dict[str, dict[str, int]] = {}
        for row in rows:
            cat = categorize_error(row.get("error_text", ""))
            categories[cat] = categories.get(cat, 0) + 1
            tool = row.get("tool_name", "unknown")
            if tool not in by_tool:
                by_tool[tool] = {}
            by_tool[tool][cat] = by_tool[tool].get(cat, 0) + 1

        return {
            "total_categorized": len(rows),
            "categories": categories,
            "by_tool": by_tool,
        }
    except Exception as e:
        logger.error("insight_tool_error_categories_failed", error=str(e))
        return {"total_categorized": 0, "categories": {}, "by_tool": {}}


async def get_interruption_metrics(agent_name: str, start: str, end: str) -> dict:
    """Get stop reason counts and user interruption metrics."""
    _query = get_query()
    sql = f"""
        SELECT
            LogAttributes['stop_reason'] AS stop_reason,
            count() AS cnt
        FROM otel_logs
        WHERE LogAttributes['session.id'] IN ({_SESSIONS_SUBQUERY})
          AND Timestamp >= {{t_start:String}}
          AND Timestamp <= {{t_end:String}}
          AND LogAttributes['stop_reason'] != ''
        GROUP BY stop_reason
        ORDER BY cnt DESC
        FORMAT JSON
    """
    params = {
        "param_aname": agent_name,
        "param_t_start": start,
        "param_t_end": end,
    }
    try:
        r = await _query(sql, params)
        r.raise_for_status()
        rows = r.json().get("data", [])
        stop_reasons = {row["stop_reason"]: int(row["cnt"]) for row in rows}
        user_interruptions = stop_reasons.get("user_interrupt", 0) + stop_reasons.get("interrupted", 0)
        return {
            "stop_reasons": stop_reasons,
            "user_interruptions": user_interruptions,
            "total_stops": sum(stop_reasons.values()),
        }
    except Exception as e:
        logger.error("insight_interruption_metrics_failed", error=str(e))
        return {"stop_reasons": {}, "user_interruptions": 0, "total_stops": 0}


async def get_reconciliation_data(agent_name: str, start: str, end: str) -> dict:
    """Check if any sessions have reconciliation enrichment data."""
    _query = get_query()
    sql = f"""
        SELECT
            count(DISTINCT LogAttributes['session.id']) AS reconciled_sessions,
            sum(toUInt64OrZero(LogAttributes['input_tokens'])) AS total_input,
            sum(toUInt64OrZero(LogAttributes['output_tokens'])) AS total_output,
            sum(toUInt64OrZero(LogAttributes['cache_read_tokens'])) AS cache_read,
            sum(toUInt64OrZero(LogAttributes['cache_creation_tokens'])) AS cache_creation,
            sum(toUInt64OrZero(LogAttributes['thinking_turns'])) AS thinking_turns,
            sum(toUInt64OrZero(LogAttributes['tool_use_count'])) AS tool_uses
        FROM otel_logs
        WHERE LogAttributes['session.id'] IN ({_SESSIONS_SUBQUERY})
          AND LogAttributes['event.name'] = 'reconcile_enrichment'
          AND Timestamp >= {{t_start:String}}
          AND Timestamp <= {{t_end:String}}
        FORMAT JSON
    """
    params = {
        "param_aname": agent_name,
        "param_t_start": start,
        "param_t_end": end,
    }
    try:
        r = await _query(sql, params)
        r.raise_for_status()
        data = r.json().get("data", [])
        if data and int(data[0].get("reconciled_sessions", 0)) > 0:
            row = data[0]
            return {
                "available": True,
                "reconciled_sessions": int(row["reconciled_sessions"]),
                "total_input_tokens": int(row["total_input"]),
                "total_output_tokens": int(row["total_output"]),
                "cache_read_tokens": int(row["cache_read"]),
                "cache_creation_tokens": int(row["cache_creation"]),
                "thinking_turns": int(row["thinking_turns"]),
                "tool_uses": int(row["tool_uses"]),
            }
        return {"available": False}
    except Exception as e:
        logger.warning("reconciliation_data_query_failed", error=str(e))
        return {"available": False}


# ===========================================================================
# Legacy compute_all_metrics (otel_logs path)
# ===========================================================================


async def _compute_all_metrics_from_otel_logs(agent_name: str, start: str, end: str) -> dict:
    """Run all metric queries against otel_logs in parallel (legacy path)."""
    from .shim_enrichment import compute_mcp_metrics

    (
        overview,
        tokens,
        duration,
        errors,
        tools,
        sessions,
        per_session_tokens,
        tool_errors,
        interruptions,
        mcp_metrics,
    ) = await asyncio.gather(
        get_session_overview(agent_name, start, end),
        get_token_aggregates(agent_name, start, end),
        get_latency_and_duration(agent_name, start, end),
        get_error_breakdown(agent_name, start, end),
        get_tool_usage(agent_name, start, end),
        get_session_details(agent_name, start, end),
        get_per_session_tokens(agent_name, start, end),
        get_tool_error_categories(agent_name, start, end),
        get_interruption_metrics(agent_name, start, end),
        compute_mcp_metrics(agent_name, start, end),
    )

    # Compute cost summary from per-session token data
    cost = compute_cost_summary(per_session_tokens)

    # Check for reconciliation enrichment data
    reconciliation = await get_reconciliation_data(agent_name, start, end)

    return {
        "overview": overview,
        "tokens": tokens,
        "credits": {},
        "duration": duration,
        "errors": errors,
        "tools": tools,
        "sessions": sessions,
        "cost": cost,
        "tool_errors": tool_errors,
        "interruptions": interruptions,
        "git": {"commits": 0, "pushes": 0, "lines_added": 0, "lines_removed": 0, "files_modified": 0},
        "languages": {},
        "response_times": {},
        "time_of_day": [],
        "multi_session": {"overlapping_count": 0, "max_concurrent": 0, "overlapping_pairs": []},
        "subagents": {"total_subagent_sessions": 0, "subagent_events": 0, "subagent_output_tokens": 0},
        "reconciliation": reconciliation,
        "mcp": mcp_metrics,
    }


# ===========================================================================
# Main entry point: dual-source with fallback
# ===========================================================================


async def compute_all_metrics(agent_name: str, start: str, end: str, agent_id: str = "") -> dict:
    """Run all metric queries. Uses session_events if agent_id provided and data exists.

    Args:
        agent_name: The agent registry name (used for otel_logs fallback).
        start: ISO timestamp for period start.
        end: ISO timestamp for period end.
        agent_id: The agent UUID (used for session_events primary path).

    Returns:
        Combined metrics dict with all keys populated.
    """
    if agent_id:
        # Try session_events first
        count = await _count_sessions_in_events(agent_id, start, end)
        if count > 0:
            logger.info(
                "metrics_using_session_events",
                agent_id=agent_id,
                session_count=count,
            )
            return await compute_all_metrics_from_events(agent_id, start, end)

    # Fallback to otel_logs
    logger.info(
        "metrics_using_otel_logs_fallback",
        agent_name=agent_name,
        agent_id=agent_id,
    )
    return await _compute_all_metrics_from_otel_logs(agent_name, start, end)
