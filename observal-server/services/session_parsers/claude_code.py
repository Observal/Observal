# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Claude Code JSONL session parser.

Handles the Claude Code transcript format where each line has:
  { "type": "user"|"assistant"|"system"|"attachment"|..., "message": {...}, ... }
"""

from __future__ import annotations

import json

from .base import basic_event, pick_timestamp, strip_ansi

_META_TYPES = {
    "agent-setting",
    "debug",
    "file-history-snapshot",
    "last-prompt",
    "meta",
    "mode",
    "permission-mode",
    "pr-link",
    "queue-operation",
    "worktree-state",
}


def parse_rows(rows: list[dict]) -> list[dict]:
    """Parse raw_line Claude Code JSONL rows into normalised frontend events.

    Each ClickHouse row contains a ``raw_line`` field holding one line of the
    Claude Code session transcript.  This function expands each row into one
    or more virtual events that the frontend trace viewer understands.

    Merging: ``tool_result`` blocks are merged back into the preceding
    ``tool_use`` event keyed by ``tool_use_id`` rather than emitting a
    separate event.
    """
    events: list[dict] = []
    # Maps tool_use_id -> index in events for merge-on-result
    tool_use_index: dict[str, int] = {}

    for row in rows:
        raw_line = row.get("raw_line", "")
        ingested_at = row.get("ingested_at", "")
        row_ts = row.get("timestamp", "")
        harness = row.get("harness", "")

        if not raw_line:
            events.append(basic_event(row))
            continue

        try:
            line = json.loads(raw_line)
        except (json.JSONDecodeError, ValueError):
            events.append(basic_event(row))
            continue

        msg_type = line.get("type", "")

        if msg_type in _META_TYPES:
            continue

        ts = pick_timestamp(line.get("timestamp"), row_ts, ingested_at)

        if msg_type == "user":
            _handle_user(line, ts, harness, events, tool_use_index)

        elif msg_type == "assistant":
            _handle_assistant(line, ts, harness, events, tool_use_index)

        elif msg_type == "system":
            system_text = line.get("content", "")
            events.append(
                {
                    "timestamp": ts,
                    "event_name": "hook_sessionstart",
                    "body": system_text[:100],
                    "attributes": {},
                    "service_name": harness,
                }
            )

        elif msg_type == "attachment":
            attachment = line.get("attachment", {})
            attach_name = attachment.get("name", "")
            events.append(
                {
                    "timestamp": ts,
                    "event_name": "attachment",
                    "body": attach_name[:100],
                    "attributes": {
                        "attachment_type": attachment.get("type", ""),
                        "attachment_name": attach_name,
                    },
                    "service_name": harness,
                }
            )

        else:
            events.append(basic_event(row))

    return events


# ---------------------------------------------------------------------------
# Internal handlers
# ---------------------------------------------------------------------------


def _handle_user(
    line: dict,
    ts: str,
    harness: str,
    events: list[dict],
    tool_use_index: dict[str, int],
) -> None:
    content = line.get("message", {}).get("content", [])

    if isinstance(content, str):
        events.append(
            {
                "timestamp": ts,
                "event_name": "hook_userpromptsubmit",
                "body": content[:100],
                "attributes": {"tool_input": content},
                "service_name": harness,
            }
        )
        return

    if not isinstance(content, list):
        return

    text_blocks = [b for b in content if isinstance(b, dict) and b.get("type") == "text"]
    result_blocks = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"]

    if text_blocks:
        full_text = "\n".join(b.get("text", "") for b in text_blocks)
        events.append(
            {
                "timestamp": ts,
                "event_name": "hook_userpromptsubmit",
                "body": full_text[:100],
                "attributes": {"tool_input": full_text},
                "service_name": harness,
            }
        )

    for block in result_blocks:
        tool_use_id = block.get("tool_use_id", "")
        result_content = block.get("content", "")
        if isinstance(result_content, str):
            result_text = result_content
        elif isinstance(result_content, list):
            result_text = "\n".join(
                c.get("text", "") for c in result_content if isinstance(c, dict) and c.get("type") == "text"
            )
        else:
            result_text = str(result_content)
        if tool_use_id and tool_use_id in tool_use_index:
            existing = events[tool_use_index[tool_use_id]]
            existing["attributes"]["tool_response"] = result_text
        # else: orphan tool_result -- skip


def _handle_assistant(
    line: dict,
    ts: str,
    harness: str,
    events: list[dict],
    tool_use_index: dict[str, int],
) -> None:
    message = line.get("message", {})
    content = message.get("content", [])

    usage = message.get("usage") or {}
    token_attrs: dict = {}
    if usage:
        if usage.get("input_tokens"):
            token_attrs["input_tokens"] = str(usage["input_tokens"])
        if usage.get("output_tokens"):
            token_attrs["output_tokens"] = str(usage["output_tokens"])
        if usage.get("cache_read_input_tokens"):
            token_attrs["cache_read_tokens"] = str(usage["cache_read_input_tokens"])
        if usage.get("cache_creation_input_tokens"):
            token_attrs["cache_creation_tokens"] = str(usage["cache_creation_input_tokens"])
        if message.get("model"):
            token_attrs["model"] = message["model"]
        if message.get("stop_reason"):
            token_attrs["stop_reason"] = message["stop_reason"]

    if not isinstance(content, list):
        return

    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type", "")

        if block_type == "thinking":
            thinking_text = strip_ansi(block.get("thinking", ""))
            events.append(
                {
                    "timestamp": ts,
                    "event_name": "hook_assistant_thinking",
                    "body": thinking_text[:100],
                    "attributes": {"tool_response": thinking_text},
                    "service_name": harness,
                }
            )

        elif block_type == "text":
            response_text = block.get("text", "")
            attrs: dict = {"tool_response": response_text}
            if token_attrs:
                attrs.update(token_attrs)
                token_attrs = {}  # consumed -- only on first text block
            events.append(
                {
                    "timestamp": ts,
                    "event_name": "hook_assistant_response",
                    "body": response_text[:100],
                    "attributes": attrs,
                    "service_name": harness,
                }
            )

        elif block_type == "tool_use":
            tool_use_id = block.get("id", "")
            tool_name = block.get("name", "")
            tool_input = block.get("input", {})
            idx = len(events)
            events.append(
                {
                    "timestamp": ts,
                    "event_name": "hook_posttooluse",
                    "body": tool_name,
                    "attributes": {
                        "tool_name": tool_name,
                        "tool_input": json.dumps(tool_input),
                        "tool_use_id": tool_use_id,
                    },
                    "service_name": harness,
                }
            )
            if tool_use_id:
                tool_use_index[tool_use_id] = idx

    # If token_attrs were not consumed by a text block (tool-only turn),
    # emit a standalone token_usage event so the UI can show token counts.
    if token_attrs:
        events.append(
            {
                "timestamp": ts,
                "event_name": "hook_token_usage",
                "body": "",
                "attributes": token_attrs,
                "service_name": harness,
            }
        )
