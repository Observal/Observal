# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Build readable session transcripts from ClickHouse for facet extraction.

V3: Reads from session_events.raw_line (primary) with otel_logs fallback.
"""

from __future__ import annotations

import json

import structlog

from ._deps import get_query

logger = structlog.get_logger(__name__)

MAX_TRANSCRIPT_CHARS = 30000
MAX_TOOL_INPUT_CHARS = 200
MAX_PROMPT_CHARS = 500
MAX_ASSISTANT_CHARS = 300
MAX_TOOL_OUTPUT_CHARS = 200


async def build_session_transcript(
    session_id: str,
    start: str,
    end: str,
    use_session_events: bool = True,
) -> str:
    """Build a readable transcript for a session.

    Tries session_events first (V3), falls back to otel_logs (V2).
    """
    if use_session_events:
        transcript = await _build_from_session_events(session_id)
        if transcript:
            return transcript

    # Fallback to otel_logs
    return await _build_from_otel_logs(session_id, start, end)


async def _build_from_session_events(session_id: str) -> str:
    """Build transcript from session_events.raw_line."""
    query = get_query()

    sql = """
        SELECT line_offset, event_type, timestamp, tool_name, raw_line
        FROM session_events FINAL
        WHERE session_id = {sid:String}
        ORDER BY line_offset ASC
        LIMIT 500
        FORMAT JSON
    """
    params = {"param_sid": session_id}

    try:
        r = await query(sql, params)
        r.raise_for_status()
        rows = r.json().get("data", [])
    except Exception as e:
        logger.warning("transcript_session_events_failed", session_id=session_id, error=str(e))
        return ""

    if not rows:
        return ""

    return _format_transcript_from_raw(rows)


def _format_transcript_from_raw(rows: list[dict]) -> str:
    """Parse raw_line JSONL and format as readable transcript."""
    lines: list[str] = []
    total_chars = 0

    for row in rows:
        event_type = row.get("event_type", "")
        raw = row.get("raw_line", "")
        tool_name = row.get("tool_name", "")

        line = ""

        if not raw:
            # Fallback to metadata-only formatting
            line = _format_from_metadata(event_type, tool_name, row)
        else:
            try:
                parsed = json.loads(raw) if isinstance(raw, str) else raw
                line = _format_parsed_event(event_type, tool_name, parsed)
            except (json.JSONDecodeError, TypeError):
                line = _format_from_metadata(event_type, tool_name, row)

        if line:
            if total_chars + len(line) > MAX_TRANSCRIPT_CHARS:
                lines.append("[...truncated...]")
                break
            lines.append(line)
            total_chars += len(line) + 1

    return "\n".join(lines)


def _format_parsed_event(event_type: str, tool_name: str, parsed: dict) -> str:
    """Format a parsed JSONL event into a transcript line."""

    if event_type == "user_prompt":
        text = _extract_text_content(parsed)
        if text:
            return f"[USER] {text[:MAX_PROMPT_CHARS]}"

    elif event_type == "assistant_text":
        text = _extract_assistant_text(parsed)
        if text:
            return f"[ASSISTANT] {text[:MAX_ASSISTANT_CHARS]}"

    elif event_type == "tool_call":
        input_summary = _extract_tool_input(parsed)
        name = tool_name or _extract_tool_name(parsed) or "unknown"
        return f"[TOOL_CALL:{name}] {input_summary[:MAX_TOOL_INPUT_CHARS]}"

    elif event_type == "tool_result":
        is_error = parsed.get("is_error", False)
        content = _extract_tool_result_content(parsed)
        name = tool_name or "unknown"
        if is_error:
            return f"[TOOL_RESULT:{name}] ERROR: {content[:MAX_TOOL_OUTPUT_CHARS]}"
        else:
            return f"[TOOL_RESULT:{name}] OK: {content[:MAX_TOOL_OUTPUT_CHARS]}"

    return ""


def _extract_text_content(parsed: dict) -> str:
    """Extract text from a message's content array or string."""
    msg = parsed.get("message", parsed)
    content = msg.get("content", "")

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        texts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(block.get("text", ""))
            elif isinstance(block, str):
                texts.append(block)
        return " ".join(texts)

    return str(content)[:200] if content else ""


def _extract_assistant_text(parsed: dict) -> str:
    """Extract assistant text content (skip tool_use blocks)."""
    msg = parsed.get("message", parsed)
    content = msg.get("content", "")

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        texts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(block.get("text", ""))
        return " ".join(texts)

    return ""


def _extract_tool_input(parsed: dict) -> str:
    """Extract a summary of tool input."""
    msg = parsed.get("message", parsed)
    content = msg.get("content", "")

    # Direct tool call format
    if isinstance(parsed, dict) and "input" in parsed:
        inp = parsed["input"]
        if isinstance(inp, dict):
            # For Bash: show command
            if "command" in inp:
                return inp["command"]
            # For Edit: show file_path
            if "file_path" in inp:
                return f"file: {inp['file_path']}"
            return json.dumps(inp)[:MAX_TOOL_INPUT_CHARS]
        return str(inp)[:MAX_TOOL_INPUT_CHARS]

    # Content array format
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                inp = block.get("input", {})
                if isinstance(inp, dict):
                    if "command" in inp:
                        return inp["command"]
                    if "file_path" in inp:
                        return f"file: {inp['file_path']}"
                    return json.dumps(inp)[:MAX_TOOL_INPUT_CHARS]

    return ""


def _extract_tool_name(parsed: dict) -> str:
    """Extract tool name from parsed event."""
    if "name" in parsed:
        return parsed["name"]
    msg = parsed.get("message", {})
    content = msg.get("content", [])
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                return block.get("name", "")
    return ""


def _extract_tool_result_content(parsed: dict) -> str:
    """Extract content from a tool result."""
    content = parsed.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(block.get("text", ""))
            elif isinstance(block, str):
                texts.append(block)
        return " ".join(texts)
    return str(content)[:200]


def _format_from_metadata(event_type: str, tool_name: str, row: dict) -> str:
    """Fallback: format using only metadata columns when raw_line is unavailable."""
    if event_type == "user_prompt":
        preview = row.get("content_preview", "")
        return f"[USER] {preview[:MAX_PROMPT_CHARS]}" if preview else "[USER] <no content>"
    elif event_type == "assistant_text":
        preview = row.get("content_preview", "")
        return f"[ASSISTANT] {preview[:MAX_ASSISTANT_CHARS]}" if preview else ""
    elif event_type == "tool_call":
        return f"[TOOL_CALL:{tool_name or 'unknown'}]"
    elif event_type == "tool_result":
        preview = row.get("content_preview", "")
        return f"[TOOL_RESULT:{tool_name or 'unknown'}] {preview[:MAX_TOOL_OUTPUT_CHARS]}"
    return ""


# ---------------------------------------------------------------------------
# V2 fallback: otel_logs based transcript (kept for backward compatibility)
# ---------------------------------------------------------------------------

_V2_MAX_TRANSCRIPT_CHARS = 4000


async def _build_from_otel_logs(session_id: str, start: str, end: str) -> str:
    """Query otel_logs for a session and build a readable transcript (V2 path).

    Includes: user prompts (truncated), tool calls (name + outcome),
    errors with context, stop event. Truncated to 4000 chars total.
    """
    query = get_query()

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
        r = await query(sql, params)
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
            if total_chars + len(line) > _V2_MAX_TRANSCRIPT_CHARS:
                lines.append("[...truncated...]")
                break
            lines.append(line)
            total_chars += len(line) + 1

    return "\n".join(lines)
