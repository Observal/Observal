"""Kiro JSONL session parser.

Handles the Kiro CLI transcript format where each line has:
  { "version": "v1", "kind": "Prompt"|"AssistantMessage"|"ToolResults", "data": {...} }

Key differences from the Claude Code format:
- Top-level discriminator is ``kind`` (not ``type``)
- All payload lives under ``data``
- Content items use ``{kind, data}`` instead of ``{type, text/id/name/...}``
- Timestamps come from ``data.meta.timestamp`` (unix epoch *seconds*, integer) and
  are only present on ``Prompt`` lines -- subsequent lines inherit the same ts
- No token-usage data in the JSONL
- Tool inputs carry a Kiro-internal ``__tool_use_purpose`` key that is stripped
- ToolResults carries both a simple ``content`` array and a richer ``results`` map;
  we read from ``content`` so we never need the ``results`` map
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from .base import basic_event, pick_timestamp


def parse_rows(rows: list[dict]) -> list[dict]:
    """Parse raw_line Kiro JSONL rows into normalised frontend events.

    Each ClickHouse row contains a ``raw_line`` field holding one line of the
    Kiro CLI session transcript.  This function expands each row into one or
    more virtual events that the frontend trace viewer understands.

    Merging: ``ToolResults`` rows are merged back into the preceding
    ``AssistantMessage`` tool-use events keyed by ``toolUseId``.
    """
    events: list[dict] = []
    # Maps toolUseId -> index in events list for merge-on-result
    tool_use_index: dict[str, int] = {}

    for row in rows:
        raw_line = row.get("raw_line", "")
        ingested_at = row.get("ingested_at", "")
        row_ts = row.get("timestamp", "")
        ide = row.get("ide", "kiro")

        if not raw_line:
            events.append(basic_event(row))
            continue

        try:
            line = json.loads(raw_line)
        except (json.JSONDecodeError, ValueError):
            events.append(basic_event(row))
            continue

        kind = line.get("kind", "")
        data = line.get("data", {})
        if not isinstance(data, dict):
            events.append(basic_event(row))
            continue

        # Timestamps only exist on Prompt lines (meta.timestamp = unix epoch seconds).
        # For everything else we fall back to the row ts / ingested_at via pick_timestamp.
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        epoch_s = meta.get("timestamp") if meta else None
        jsonl_ts = _epoch_to_clickhouse(epoch_s) if epoch_s else None
        ts = pick_timestamp(jsonl_ts, row_ts, ingested_at)

        if kind == "KiroCredits":
            # Synthetic row written by kiro_session_push with lifetime credits.
            row_credits = row.get("credits") or data.get("credits")
            if row_credits:
                events.append(
                    {
                        "timestamp": ts,
                        "event_name": "kiro_credits",
                        "body": f"{float(row_credits):.4f} credits",
                        "attributes": {"credits": str(row_credits), "model": "Kiro Auto"},
                        "service_name": ide,
                    }
                )
        elif kind == "Prompt":
            _handle_prompt(data, ts, ide, events)
        elif kind == "AssistantMessage":
            _handle_assistant_message(data, ts, ide, events, tool_use_index)
        elif kind == "ToolResults":
            _handle_tool_results(data, ts, ide, events, tool_use_index)
        else:
            events.append(basic_event(row))

    return events


# ---------------------------------------------------------------------------
# Timestamp helper
# ---------------------------------------------------------------------------


def _epoch_to_clickhouse(epoch_s: int | float) -> str:
    """Convert unix epoch seconds to ClickHouse datetime string."""
    dt = datetime.fromtimestamp(epoch_s, tz=UTC)
    return dt.strftime("%Y-%m-%d %H:%M:%S.000")


# ---------------------------------------------------------------------------
# Internal handlers
# ---------------------------------------------------------------------------


def _handle_prompt(data: dict, ts: str, ide: str, events: list[dict]) -> None:
    content = data.get("content", [])
    text_parts = [
        item.get("data", "")
        for item in content
        if isinstance(item, dict) and item.get("kind") == "text" and isinstance(item.get("data"), str)
    ]
    full_text = "\n".join(text_parts)
    if full_text:
        events.append(
            {
                "timestamp": ts,
                "event_name": "hook_userpromptsubmit",
                "body": full_text[:100],
                "attributes": {"tool_input": full_text},
                "service_name": ide,
            }
        )


def _handle_assistant_message(
    data: dict,
    ts: str,
    ide: str,
    events: list[dict],
    tool_use_index: dict[str, int],
) -> None:
    content = data.get("content", [])

    for item in content:
        if not isinstance(item, dict):
            continue
        item_kind = item.get("kind", "")
        item_data = item.get("data", "")

        if item_kind == "text":
            text = item_data if isinstance(item_data, str) else ""
            if not text.strip():
                continue  # skip empty filler blocks Kiro emits between tool calls
            events.append(
                {
                    "timestamp": ts,
                    "event_name": "hook_assistant_response",
                    "body": text[:100],
                    "attributes": {"tool_response": text},
                    "service_name": ide,
                }
            )

        elif item_kind == "toolUse":
            if not isinstance(item_data, dict):
                continue
            tool_use_id = item_data.get("toolUseId", "")
            tool_name = item_data.get("name", "")
            tool_input = item_data.get("input", {})
            # Strip Kiro-internal annotation key
            clean_input = {k: v for k, v in tool_input.items() if not k.startswith("__")}
            idx = len(events)
            events.append(
                {
                    "timestamp": ts,
                    "event_name": "hook_posttooluse",
                    "body": tool_name,
                    "attributes": {
                        "tool_name": tool_name,
                        "tool_input": json.dumps(clean_input),
                        "tool_use_id": tool_use_id,
                    },
                    "service_name": ide,
                }
            )
            if tool_use_id:
                tool_use_index[tool_use_id] = idx


def _handle_tool_results(
    data: dict,
    ts: str,
    ide: str,
    events: list[dict],
    tool_use_index: dict[str, int],
) -> None:
    content = data.get("content", [])

    for item in content:
        if not isinstance(item, dict) or item.get("kind") != "toolResult":
            continue
        item_data = item.get("data", {})
        if not isinstance(item_data, dict):
            continue

        tool_use_id = item_data.get("toolUseId", "")
        status = item_data.get("status", "success")
        result_content = item_data.get("content", [])

        result_text = _extract_result_text(result_content)
        if status == "error":
            result_text = f"[error] {result_text}" if result_text else "[error]"

        if tool_use_id and tool_use_id in tool_use_index:
            existing = events[tool_use_index[tool_use_id]]
            existing["attributes"]["tool_response"] = result_text
            if status == "error":
                existing["attributes"]["tool_status"] = "error"
        # else: orphan tool result -- skip


def _extract_result_text(result_content: list) -> str:
    """Extract plain text from a Kiro tool-result content array.

    Each item is ``{kind: "text"|"json", data: str|{content:[{type,text}]}}``.
    """
    parts: list[str] = []
    for c in result_content:
        if not isinstance(c, dict):
            continue
        c_kind = c.get("kind", "")
        c_data = c.get("data", "")
        if c_kind == "text" and isinstance(c_data, str):
            parts.append(c_data)
        elif c_kind == "json" and isinstance(c_data, dict):
            # Nested Claude-style content array: [{type:"text", text:"..."}]
            for sub in c_data.get("content", []):
                if isinstance(sub, dict) and sub.get("type") == "text":
                    parts.append(sub.get("text", ""))
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Write-path extras — called by ingest_classify.get_extra_rows()
# ---------------------------------------------------------------------------


def extra_ingest_rows(
    session_id: str,
    project_id: str,
    user_id: str,
    agent_id: str | None,
    agent_version: str | None,
    ide: str,
    total_credits: float | None,
) -> list[dict]:
    """Return Kiro-specific extra rows to write after the main ingest loop.

    Stores a single ``kiro_credits`` row at line_offset=0xFFFFFFFF so the
    sessions list query can aggregate ``sum(credits)`` per session.
    ReplacingMergeTree deduplication makes repeated inserts idempotent.
    Returns an empty list when no credits are available.
    """
    if total_credits is None or total_credits <= 0:
        return []
    return [
        {
            "session_id": session_id,
            "project_id": project_id,
            "user_id": user_id,
            "agent_id": agent_id,
            "agent_version": agent_version,
            "ide": ide,
            "line_offset": 0xFFFFFFFF,
            "line_hash": "",
            "layer_hash": None,
            "event_type": "kiro_credits",
            "timestamp": "2099-12-31 00:00:00.000",
            "uuid": None,
            "parent_uuid": None,
            "tool_name": None,
            "tool_id": None,
            "content_preview": f"{total_credits:.6f} credits",
            "content_length": 0,
            "raw_line": json.dumps({"kind": "KiroCredits", "credits": total_credits, "model": "Kiro Auto"}),
            "credits": total_credits,
        }
    ]
