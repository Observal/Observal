"""Shared helpers used by all session JSONL parsers."""

from __future__ import annotations

_EPOCH_SENTINEL = "1970-01-01"


def pick_timestamp(jsonl_ts: str | None, row_ts: str, ingested_at: str) -> str:
    """Return the best available timestamp string.

    Priority:
    1. JSONL-level timestamp (ISO-8601) converted to ClickHouse format
    2. Row timestamp, if it is not the 1970 epoch sentinel
    3. ingested_at fallback
    """
    if jsonl_ts:
        # Convert "2025-01-01T12:00:00.000Z" -> "2025-01-01 12:00:00.000"
        ts = jsonl_ts.replace("T", " ").replace("Z", "")
        if ts.endswith("+00:00"):
            ts = ts[:-6]
        if _EPOCH_SENTINEL not in ts:
            return ts
    if _EPOCH_SENTINEL not in row_ts:
        return row_ts
    return ingested_at


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
        "service_name": row.get("ide", ""),
    }
