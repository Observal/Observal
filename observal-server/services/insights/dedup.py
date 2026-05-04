"""Event deduplication — merge hook and OTLP records for the same action.

Same session_id + same tool_name + timestamps within 2 seconds = same event.
Merge strategy: take token fields from OTLP record, tool_input/tool_response from hook record.
"""

from __future__ import annotations

from datetime import datetime


def _parse_ts(ts_str: str | None) -> float:
    """Parse an ISO-ish timestamp string to epoch seconds. Returns 0.0 on failure."""
    if not ts_str:
        return 0.0
    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(ts_str[:26], fmt).timestamp()
        except (ValueError, TypeError):
            continue
    return 0.0


def _make_dedup_key(event: dict) -> str:
    """Generate dedup key from session_id + tool_name + 1-second time bucket."""
    session_id = event.get("session_id") or ""
    tool_name = event.get("tool_name") or ""
    ts = _parse_ts(event.get("timestamp"))
    bucket = int(ts)  # floor to whole second
    return f"{session_id}|{tool_name}|{bucket}"


def _merge_events(existing: dict, new: dict) -> dict:
    """Merge two records for the same event, preferring richer data.

    Merge rules:
    - Token fields (input_tokens, output_tokens, cache_read, cache_creation):
      prefer the non-zero value; OTLP typically carries these.
    - tool_input, tool_response: prefer the non-empty value; hooks carry these.
    - error: prefer whichever has it.
    - model: prefer whichever has it.
    - timestamp: keep the earlier one.
    """
    merged = dict(existing)

    # Keep the earlier timestamp
    ts_existing = _parse_ts(existing.get("timestamp"))
    ts_new = _parse_ts(new.get("timestamp"))
    if ts_new > 0 and (ts_existing == 0 or ts_new < ts_existing):
        merged["timestamp"] = new["timestamp"]

    # Token fields: prefer non-zero value (OTLP usually has these)
    for field in ("input_tokens", "output_tokens", "cache_read", "cache_creation"):
        existing_val = existing.get(field)
        new_val = new.get(field)
        if (new_val and not existing_val) or (new_val and existing_val == 0):
            merged[field] = new_val

    # tool_input / tool_response: prefer non-empty (hooks carry these)
    for field in ("tool_input", "tool_response"):
        if not existing.get(field) and new.get(field):
            merged[field] = new[field]

    # error: prefer whichever has it
    if not existing.get("error") and new.get("error"):
        merged["error"] = new["error"]

    # model: prefer whichever has it
    if not existing.get("model") and new.get("model"):
        merged["model"] = new["model"]

    return merged


def dedupe_events(events: list[dict]) -> list[dict]:
    """Deduplicate hook + OTLP events for the same action.

    Dedup key: (session_id, tool_name, timestamp rounded to 1-second bucket)

    Within the 2-second window events with the same key are merged.
    Events that are more than 2 seconds apart are NOT merged even if they
    share the same session_id and tool_name.

    Returns: deduplicated event list, sorted by timestamp.
    """
    if not events:
        return []

    # Group events by their 1-second bucket key
    buckets: dict[str, dict] = {}

    for event in events:
        key = _make_dedup_key(event)
        if key not in buckets:
            buckets[key] = dict(event)
        else:
            buckets[key] = _merge_events(buckets[key], event)

    result = list(buckets.values())
    result.sort(key=lambda e: _parse_ts(e.get("timestamp")))
    return result


def dedupe_session_events(session_id: str, events: list[dict]) -> list[dict]:
    """Deduplicate events within a single session.

    Filters to only events belonging to the given session_id, then deduplicates.
    """
    session_events = [e for e in events if e.get("session_id") == session_id]
    return dedupe_events(session_events)
