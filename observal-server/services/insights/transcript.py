"""Build readable session transcripts from ClickHouse otel_logs for facet extraction."""

from __future__ import annotations

import structlog

from services.clickhouse import _query

logger = structlog.get_logger(__name__)

MAX_TRANSCRIPT_CHARS = 4000
MAX_TOOL_INPUT_CHARS = 200
MAX_PROMPT_CHARS = 500


async def build_session_transcript(session_id: str, start: str, end: str) -> str:
    """Query otel_logs for a session and build a readable transcript.

    Includes: user prompts (truncated), tool calls (name + outcome),
    errors with context, stop event. Truncated to MAX_TRANSCRIPT_CHARS total.
    """
    sql = """
        SELECT
            LogAttributes['event.name'] AS event_name,
            LogAttributes['tool_name'] AS tool_name,
            LogAttributes['tool_input'] AS tool_input,
            LogAttributes['tool_response'] AS tool_response,
            LogAttributes['error'] AS error,
            LogAttributes['stop_reason'] AS stop_reason,
            LogAttributes['body'] AS body,
            Timestamp
        FROM otel_logs
        WHERE LogAttributes['session.id'] = {sid:String}
          AND Timestamp >= {t_start:String}
          AND Timestamp <= {t_end:String}
        ORDER BY Timestamp
        LIMIT 200
        FORMAT JSON
    """
    params = {
        "param_sid": session_id,
        "param_t_start": start,
        "param_t_end": end,
    }

    try:
        r = await _query(sql, params)
        r.raise_for_status()
        rows = r.json().get("data", [])
    except Exception as e:
        logger.warning("transcript_query_failed", session_id=session_id, error=str(e))
        return ""

    if not rows:
        return ""

    lines: list[str] = []
    total_chars = 0

    for row in rows:
        ev = row.get("event_name", "")
        line = ""

        if ev in ("user_prompt", "hook_userpromptsubmit"):
            body = (row.get("body") or "")[:MAX_PROMPT_CHARS]
            if body:
                line = f"[USER] {body}"

        elif ev in ("tool_result", "hook_posttooluse"):
            tool = row.get("tool_name", "unknown")
            error = row.get("error", "")
            if error:
                line = f"[TOOL:{tool}] ERROR: {error[:200]}"
            else:
                response = (row.get("tool_response") or "")[:100]
                line = f"[TOOL:{tool}] OK{' — ' + response if response else ''}"

        elif ev in ("hook_stopfailure", "hook_stopsuccess"):
            reason = row.get("stop_reason", "")
            line = f"[STOP:{reason}]"

        elif ev == "api_request":
            # Skip API requests — too noisy
            continue

        if line:
            if total_chars + len(line) > MAX_TRANSCRIPT_CHARS:
                lines.append("[...truncated...]")
                break
            lines.append(line)
            total_chars += len(line) + 1

    return "\n".join(lines)
