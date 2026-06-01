# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Antigravity CLI JSONL session parser.

Real transcript format (brain/<id>/.system_generated/logs/transcript.jsonl):
  {
    "step_index": 0,
    "source": "USER_EXPLICIT" | "MODEL" | "SYSTEM",
    "type": "USER_INPUT" | "PLANNER_RESPONSE" | "LIST_DIRECTORY" | "CONVERSATION_HISTORY" | ...,
    "status": "DONE" | "IN_PROGRESS" | "ERROR",
    "created_at": "2026-05-31T17:54:04Z",
    "content": "...",           # present on USER_INPUT and PLANNER_RESPONSE
    "tool_calls": [             # present on PLANNER_RESPONSE when tools are invoked
      {"name": "list_dir", "args": {...}}
    ]
  }

Tool results come as separate rows with type matching the tool name
(e.g. "LIST_DIRECTORY") and content holding the output.
"""

from __future__ import annotations

import json
import re

from .base import basic_event, pick_timestamp

# Types that represent user prompts
_USER_TYPES = {"USER_INPUT"}

# Types that represent model text responses (no tool calls)
_ASSISTANT_TYPES = {"PLANNER_RESPONSE"}

# Types that are tool results (source=MODEL, type != USER_INPUT/PLANNER_RESPONSE/SYSTEM types)
_SYSTEM_TYPES = {"CONVERSATION_HISTORY", "SYSTEM_PROMPT"}

_USER_REQUEST_RE = re.compile(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", re.DOTALL)


def _extract_user_text(content: str) -> str:
    """Strip XML wrapper tags agy injects around user prompts."""
    m = _USER_REQUEST_RE.search(content)
    return m.group(1).strip() if m else content.strip()


def parse_rows(rows: list[dict]) -> list[dict]:
    """Parse raw_line Antigravity transcript rows into normalised frontend events."""
    events: list[dict] = []
    # Maps step_index of a PLANNER_RESPONSE with tool_calls -> event index
    # so we can attach tool results back to the tool call event
    tool_step_index: dict[int, int] = {}

    for row in rows:
        raw_line = row.get("raw_line", "")
        ingested_at = row.get("ingested_at", "")
        row_ts = row.get("timestamp", "")
        ide = row.get("ide", "antigravity")

        if not raw_line:
            events.append(basic_event(row))
            continue

        try:
            line = json.loads(raw_line)
        except (json.JSONDecodeError, ValueError):
            events.append(basic_event(row))
            continue

        line_type = line.get("type", "")
        source = line.get("source", "")
        status = line.get("status", "")
        content = line.get("content", "")
        tool_calls = line.get("tool_calls", [])
        step_index = line.get("step_index", -1)
        jsonl_ts = line.get("created_at")
        ts = pick_timestamp(jsonl_ts, row_ts, ingested_at)

        # Skip system/history lines
        if line_type in _SYSTEM_TYPES or source == "SYSTEM":
            continue

        # User prompt
        if line_type in _USER_TYPES and source in ("USER_EXPLICIT", "USER_IMPLICIT"):
            text = _extract_user_text(content) if content else ""
            if text:
                events.append(
                    {
                        "timestamp": ts,
                        "event_name": "hook_userpromptsubmit",
                        "body": text[:120],
                        "attributes": {"tool_input": text},
                        "service_name": ide,
                    }
                )

        # Model response with tool calls
        elif line_type in _ASSISTANT_TYPES and tool_calls:
            for tc in tool_calls:
                tool_name = tc.get("name", "")
                args = tc.get("args", {})
                idx = len(events)
                events.append(
                    {
                        "timestamp": ts,
                        "event_name": "hook_posttooluse",
                        "body": tool_name,
                        "attributes": {
                            "tool_name": tool_name,
                            "tool_input": json.dumps(args) if isinstance(args, dict) else str(args),
                        },
                        "service_name": ide,
                    }
                )
                tool_step_index[step_index] = idx

        # Model text response (no tool calls)
        elif line_type in _ASSISTANT_TYPES and content and not tool_calls:
            events.append(
                {
                    "timestamp": ts,
                    "event_name": "hook_assistant_response",
                    "body": content[:120],
                    "attributes": {"tool_response": content},
                    "service_name": ide,
                }
            )

        # Tool result — type is the tool name (e.g. LIST_DIRECTORY)
        # source=MODEL, step_index follows the PLANNER_RESPONSE that called it
        elif source == "MODEL" and line_type not in _ASSISTANT_TYPES and content:
            # Find the preceding tool call event (step_index - 1 or step_index - 2)
            parent_idx = tool_step_index.get(step_index - 1) or tool_step_index.get(step_index - 2)
            if parent_idx is not None and parent_idx < len(events):
                events[parent_idx]["attributes"]["tool_response"] = content[:500]
                if status == "ERROR":
                    events[parent_idx]["attributes"]["tool_status"] = "error"
            else:
                # No matching tool call — emit as standalone result
                events.append(
                    {
                        "timestamp": ts,
                        "event_name": "hook_posttooluse",
                        "body": line_type,
                        "attributes": {
                            "tool_name": line_type,
                            "tool_response": content[:500],
                        },
                        "service_name": ide,
                    }
                )

        else:
            events.append(basic_event(row))

    return events
