# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Pi session parser -- READ path (raw ClickHouse rows -> frontend events).

Pi's JSONL format uses entry-level ``type`` + ``message.role`` structure.
Tool calls use ``type: "toolCall"`` and tool results are ``role: "toolResult"``.
"""

from __future__ import annotations

import json

from .base import basic_event, pick_timestamp


def parse_rows(rows: list[dict]) -> list[dict]:
    """Parse Pi session rows into normalised frontend events."""
    events: list[dict] = []
    # Maps toolCallId -> index in events for merge-on-result
    tool_call_index: dict[str, int] = {}

    for row in rows:
        raw_line = row.get("raw_line", "")
        ingested_at = row.get("ingested_at", "")
        row_ts = row.get("timestamp", "")
        ide = row.get("ide", "pi")

        if not raw_line:
            events.append(basic_event(row))
            continue

        try:
            parsed = json.loads(raw_line)
        except (json.JSONDecodeError, ValueError):
            events.append(basic_event(row))
            continue

        line_type = parsed.get("type", "")
        ts = pick_timestamp(parsed.get("timestamp"), row_ts, ingested_at)

        if line_type == "message":
            _handle_message(parsed, ts, ide, events, tool_call_index)
        elif line_type == "model_change":
            events.append(
                {
                    "timestamp": ts,
                    "event_name": "hook_sessionstart",
                    "body": f"Model: {parsed.get('provider', '')}/{parsed.get('modelId', '')}",
                    "attributes": {
                        "provider": parsed.get("provider", ""),
                        "model": parsed.get("modelId", ""),
                    },
                    "service_name": ide,
                }
            )
        elif line_type == "thinking_level_change":
            events.append(
                {
                    "timestamp": ts,
                    "event_name": "hook_sessionstart",
                    "body": f"Thinking level: {parsed.get('thinkingLevel', '')}",
                    "attributes": {"thinking_level": parsed.get("thinkingLevel", "")},
                    "service_name": ide,
                }
            )
        elif line_type in ("compaction", "branch_summary"):
            events.append(
                {
                    "timestamp": ts,
                    "event_name": "hook_assistant_response",
                    "body": parsed.get("summary", "")[:100],
                    "attributes": {"tool_response": parsed.get("summary", "")},
                    "service_name": ide,
                }
            )
        elif line_type == "custom_message":
            content = parsed.get("content", "")
            if isinstance(content, list):
                content = "\n".join(
                    b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
                )
            events.append(
                {
                    "timestamp": ts,
                    "event_name": "hook_assistant_response",
                    "body": str(content)[:100],
                    "attributes": {"tool_response": str(content)},
                    "service_name": ide,
                }
            )

    return events


def _handle_message(
    parsed: dict,
    ts: str,
    ide: str,
    events: list[dict],
    tool_call_index: dict[str, int],
) -> None:
    msg = parsed.get("message", {})
    role = msg.get("role", "")

    if role == "user":
        _handle_user(msg, ts, ide, events)
    elif role == "assistant":
        _handle_assistant(msg, ts, ide, events, tool_call_index)
    elif role == "toolResult":
        _handle_tool_result(msg, ts, ide, events, tool_call_index)
    elif role == "bashExecution":
        _handle_bash(msg, ts, ide, events)


def _handle_user(msg: dict, ts: str, ide: str, events: list[dict]) -> None:
    content = msg.get("content", [])
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    else:
        text = str(content)

    if text.strip():
        events.append(
            {
                "timestamp": ts,
                "event_name": "hook_userpromptsubmit",
                "body": text[:100],
                "attributes": {"tool_input": text},
                "service_name": ide,
            }
        )


def _handle_assistant(
    msg: dict,
    ts: str,
    ide: str,
    events: list[dict],
    tool_call_index: dict[str, int],
) -> None:
    content = msg.get("content", [])
    if not isinstance(content, list):
        return

    usage = msg.get("usage") or {}
    token_attrs: dict = {}
    if usage:
        if usage.get("input"):
            token_attrs["input_tokens"] = str(usage["input"])
        if usage.get("output"):
            token_attrs["output_tokens"] = str(usage["output"])
        if usage.get("cacheRead"):
            token_attrs["cache_read_tokens"] = str(usage["cacheRead"])
        if usage.get("cacheWrite"):
            token_attrs["cache_creation_tokens"] = str(usage["cacheWrite"])
        if msg.get("model"):
            token_attrs["model"] = msg["model"]
        if msg.get("provider"):
            token_attrs["provider"] = msg["provider"]
        if msg.get("stopReason"):
            token_attrs["stop_reason"] = msg["stopReason"]
        # Pi-unique: cost data
        cost = usage.get("cost", {})
        if cost and cost.get("total"):
            token_attrs["cost_usd"] = str(cost["total"])

    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type", "")

        if block_type == "thinking":
            thinking_text = block.get("thinking", "")
            events.append(
                {
                    "timestamp": ts,
                    "event_name": "hook_assistant_thinking",
                    "body": thinking_text[:100],
                    "attributes": {"tool_response": thinking_text},
                    "service_name": ide,
                }
            )

        elif block_type == "text":
            response_text = block.get("text", "")
            attrs: dict = {"tool_response": response_text}
            if token_attrs:
                attrs.update(token_attrs)
                token_attrs = {}  # consumed
            events.append(
                {
                    "timestamp": ts,
                    "event_name": "hook_assistant_response",
                    "body": response_text[:100],
                    "attributes": attrs,
                    "service_name": ide,
                }
            )

        elif block_type == "toolCall":
            tool_call_id = block.get("id", "")
            tool_name = block.get("name", "")
            tool_input = block.get("arguments", {})
            idx = len(events)
            events.append(
                {
                    "timestamp": ts,
                    "event_name": "hook_posttooluse",
                    "body": tool_name,
                    "attributes": {
                        "tool_name": tool_name,
                        "tool_input": json.dumps(tool_input),
                        "tool_use_id": tool_call_id,
                    },
                    "service_name": ide,
                }
            )
            if tool_call_id:
                tool_call_index[tool_call_id] = idx

    # Emit standalone token usage if not consumed by text block
    if token_attrs:
        events.append(
            {
                "timestamp": ts,
                "event_name": "hook_token_usage",
                "body": "",
                "attributes": token_attrs,
                "service_name": ide,
            }
        )


def _handle_tool_result(
    msg: dict,
    ts: str,
    ide: str,
    events: list[dict],
    tool_call_index: dict[str, int],
) -> None:
    tool_call_id = msg.get("toolCallId", "")
    tool_name = msg.get("toolName", "")
    content = msg.get("content", [])
    is_error = msg.get("isError", False)

    if isinstance(content, list):
        result_text = "\n".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
    elif isinstance(content, str):
        result_text = content
    else:
        result_text = str(content)

    # Merge into preceding tool_call event if possible
    if tool_call_id and tool_call_id in tool_call_index:
        existing = events[tool_call_index[tool_call_id]]
        existing["attributes"]["tool_response"] = result_text
        if is_error:
            existing["attributes"]["is_error"] = "true"
    else:
        # Standalone tool result (orphan or no matching call)
        events.append(
            {
                "timestamp": ts,
                "event_name": "hook_posttooluse",
                "body": tool_name,
                "attributes": {
                    "tool_name": tool_name,
                    "tool_response": result_text,
                    "tool_use_id": tool_call_id,
                    **({"is_error": "true"} if is_error else {}),
                },
                "service_name": ide,
            }
        )


def _handle_bash(msg: dict, ts: str, ide: str, events: list[dict]) -> None:
    command = msg.get("command", "")
    output = msg.get("output", "")
    exit_code = msg.get("exitCode")

    events.append(
        {
            "timestamp": ts,
            "event_name": "hook_posttooluse",
            "body": "bash",
            "attributes": {
                "tool_name": "bash",
                "tool_input": command,
                "tool_response": output,
                **({"exit_code": str(exit_code)} if exit_code is not None else {}),
            },
            "service_name": ide,
        }
    )
