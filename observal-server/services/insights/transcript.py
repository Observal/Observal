# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Build readable session transcripts from ClickHouse session_events.

Reads raw JSONL lines stored in session_events and formats them into a
human-readable transcript suitable for LLM facet extraction.
"""

from __future__ import annotations

import json

import structlog

from ._deps import get_query

logger = structlog.get_logger(__name__)

MAX_TRANSCRIPT_CHARS = 30000
MAX_PROMPT_CHARS = 500
MAX_ASSISTANT_CHARS = 300
MAX_TOOL_INPUT_CHARS = 200
MAX_TOOL_OUTPUT_CHARS = 200


async def build_session_transcript(session_id: str) -> str:
    """Build a readable transcript for a session from session_events."""
    query = get_query()

    sql = """
        SELECT line_offset, event_type, tool_name, raw_line
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
        logger.warning("transcript_query_failed", session_id=session_id, error=str(e))
        return ""

    if not rows:
        return ""

    return _format_rows(rows)


def _format_rows(rows: list[dict]) -> str:
    """Parse raw_line JSONL rows and format as readable transcript."""
    lines: list[str] = []
    total_chars = 0

    for row in rows:
        event_type = row.get("event_type", "")
        raw = row.get("raw_line", "")
        tool_name = row.get("tool_name", "")

        if not raw:
            continue

        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            continue

        line = _format_event(event_type, tool_name, parsed)
        if not line:
            continue

        if total_chars + len(line) > MAX_TRANSCRIPT_CHARS:
            lines.append("[...truncated...]")
            break
        lines.append(line)
        total_chars += len(line) + 1

    return "\n".join(lines)


def _format_event(event_type: str, tool_name: str, parsed: dict) -> str:
    """Format a single parsed JSONL event into a transcript line."""
    if event_type == "user_prompt":
        text = _extract_text(parsed)
        if text:
            return f"[User]: {text[:MAX_PROMPT_CHARS]}"

    elif event_type == "assistant_text":
        text = _extract_assistant_text(parsed)
        if text:
            return f"[Assistant]: {text[:MAX_ASSISTANT_CHARS]}"

    elif event_type == "tool_call":
        name = tool_name or _extract_tool_name(parsed) or "unknown"
        input_summary = _extract_tool_input(parsed)
        return f"[Tool: {name}] {input_summary[:MAX_TOOL_INPUT_CHARS]}"

    elif event_type == "tool_result":
        name = tool_name or "unknown"
        is_error = parsed.get("is_error", False) or parsed.get("isError", False)
        content = _extract_tool_result(parsed)
        if is_error:
            return f"[Tool Result: {name}] ERROR: {content[:MAX_TOOL_OUTPUT_CHARS]}"
        # Skip non-error tool results to keep transcript focused
        return ""

    return ""


def _extract_text(parsed: dict) -> str:
    """Extract text from a message content."""
    msg = parsed.get("message", parsed)
    content = msg.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return " ".join(parts)
    return ""


def _extract_assistant_text(parsed: dict) -> str:
    """Extract assistant text (skip tool_use blocks)."""
    msg = parsed.get("message", parsed)
    content = msg.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return " ".join(parts)
    return ""


def _extract_tool_name(parsed: dict) -> str:
    """Extract tool name from parsed event."""
    if "name" in parsed:
        return parsed["name"]
    msg = parsed.get("message", {})
    content = msg.get("content", [])
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") in ("tool_use", "toolCall"):
                return block.get("name", "")
    return ""


def _extract_tool_input(parsed: dict) -> str:
    """Extract a summary of tool input."""
    # Direct format
    if "input" in parsed:
        inp = parsed["input"]
        if isinstance(inp, dict):
            if "command" in inp:
                return inp["command"]
            if "file_path" in inp or "path" in inp:
                return f"file: {inp.get('file_path') or inp.get('path')}"
            return json.dumps(inp)[:MAX_TOOL_INPUT_CHARS]
        return str(inp)[:MAX_TOOL_INPUT_CHARS]

    # Content array format
    msg = parsed.get("message", parsed)
    content = msg.get("content", [])
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") in ("tool_use", "toolCall"):
                inp = block.get("input", block.get("arguments", {}))
                if isinstance(inp, dict):
                    if "command" in inp:
                        return inp["command"]
                    if "path" in inp:
                        return f"file: {inp['path']}"
                    return json.dumps(inp)[:MAX_TOOL_INPUT_CHARS]
    return ""


def _extract_tool_result(parsed: dict) -> str:
    """Extract content from a tool result."""
    content = parsed.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return " ".join(parts)
    return str(content)[:200]
