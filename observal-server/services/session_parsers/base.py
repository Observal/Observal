# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 RAWx18 <rawx18.dev@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Shared helpers used by all session JSONL parsers."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

# ANSI escape sequence pattern (CSI sequences + OSC + simple escapes)
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\][^\x07]*\x07|\x1b[^\[]")


def load_line(raw_line: str) -> dict | None:
    """Decode one stored JSONL line, or return None when it is not a JSON object.

    ``session_events`` keeps ``raw_line`` verbatim even for lines the ingest path
    rejected, so the read path also sees malformed text and bare JSON scalars.
    Callers fall back to ``basic_event`` when this returns None.
    """
    try:
        parsed = json.loads(raw_line)
    except (json.JSONDecodeError, RecursionError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def str_field(parsed: dict, key: str) -> str:
    """Return a discriminator field as a string, or "" when it is any other type.

    Transcript records are untrusted, so a list or object where a tag is expected
    must never reach a set-membership test or a dict lookup.
    """
    value = parsed.get(key)
    return value if isinstance(value, str) else ""


def dict_field(parsed: dict, key: str) -> dict:
    """Return a nested field as a mapping, or {} when it is any other type.

    Same reasoning as :func:`str_field`: a transcript may carry a scalar where
    the format expects an object, and a bare ``.get(key, {}).get(...)`` chain
    would raise ``AttributeError`` on it.
    """
    value = parsed.get(key)
    return value if isinstance(value, dict) else {}


def list_field(parsed: dict, key: str) -> list:
    """Return a content field as a list, or [] when it is any other type.

    Iterating a scalar raises, and iterating a string silently yields characters,
    so content arrays are normalised before any parser walks them.
    """
    value = parsed.get(key)
    return value if isinstance(value, list) else []


def strip_ansi(text: str) -> str:
    """Remove ANSI terminal escape codes from text for clean web display."""
    return _ANSI_RE.sub("", text) if "\x1b" in text else text


def strip_cursor_xml_tags(text: str) -> str:
    """Remove Cursor's XML wrapper tags from user prompts for clean display."""
    text = re.sub(r"<timestamp>.*?</timestamp>\s*", "", text, flags=re.DOTALL)
    text = re.sub(r"</?user_query>\s*", "", text)
    text = re.sub(r"</?system_reminder>\s*", "", text)
    text = re.sub(r"</?attached_files>\s*", "", text)
    return text.strip()


_EPOCH_SENTINEL = "1970-01-01"


def pick_timestamp(jsonl_ts: str | None, row_ts: str, ingested_at: str) -> str:
    """Return the best available timestamp string.

    Priority:
    1. JSONL-level timestamp (ISO-8601) converted to ClickHouse format
    2. Row timestamp, if it is not the 1970 epoch sentinel
    3. ingested_at fallback

    ``jsonl_ts`` comes straight from an untrusted transcript, so anything that
    is not a string falls through to the row timestamp.
    """
    if isinstance(jsonl_ts, str) and jsonl_ts:
        # Convert "2025-01-01T12:00:00.000Z" -> "2025-01-01 12:00:00.000"
        ts = jsonl_ts.replace("T", " ").replace("Z", "")
        if ts.endswith("+00:00"):
            ts = ts[:-6]
        if _EPOCH_SENTINEL not in ts:
            return ts
    if _EPOCH_SENTINEL not in row_ts:
        return row_ts
    return ingested_at


# ---------------------------------------------------------------------------
# DeepSeek v4 record extraction (shared by the read parser and the ingest path)
# ---------------------------------------------------------------------------


def epoch_ms_timestamp(value: object) -> str | None:
    """Convert a nonnegative Unix-millisecond timestamp to ClickHouse UTC format."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    try:
        return (
            datetime.fromtimestamp(value // 1000, tz=UTC)
            .replace(microsecond=value % 1000 * 1000)
            .strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        )
    except (OverflowError, OSError, ValueError):
        return None


def extract_v4_text(message: dict) -> tuple[str, str]:
    """Committed text and reasoning of a DeepSeek v4 message content block list."""
    text: list[str] = []
    reasoning: list[str] = []
    for block in list_field(message, "content"):
        if not isinstance(block, dict):
            continue
        kind = str_field(block, "type")
        if kind == "text":
            text.append(str_field(block, "text"))
        elif kind == "reasoning":
            reasoning.append(str_field(block, "text"))
    return strip_ansi("\n".join(text)), strip_ansi("\n".join(reasoning))


def extract_v4_stream_chunk(data: dict, chunk_type: str) -> dict:
    """The first committed stream chunk payload of a DeepSeek v4 attempt, or {}."""
    for record in list_field(data, "stream"):
        if not isinstance(record, dict) or str_field(record, "type") != "chunk":
            continue
        chunk = dict_field(record, "chunk")
        if str_field(chunk, "type") == chunk_type:
            return chunk
    return {}


def extract_v4_attempt_failure(data: dict) -> dict:
    """The finish reason of a failed DeepSeek v4 assistant attempt, or {}."""
    reason = dict_field(extract_v4_stream_chunk(data, "finish"), "reason")
    return reason if str_field(reason, "kind") in ("error", "aborted") else {}


def basic_event(row: dict) -> dict:
    """Fallback: build a minimal event from stored columns when raw_line is unusable."""
    return {
        "timestamp": row.get("timestamp", ""),
        "event_name": row.get("event_type", ""),
        "body": row.get("content_preview", ""),
        "attributes": {
            "tool_name": row.get("tool_name") or "",
            "tool_id": row.get("tool_id") or "",
            "uuid": row.get("uuid") or "",
            "parent_uuid": row.get("parent_uuid") or "",
            "content_length": str(row.get("content_length", 0)),
            **({"credits": str(row["credits"])} if row.get("credits") else {}),
        },
        "service_name": row.get("harness", ""),
    }
