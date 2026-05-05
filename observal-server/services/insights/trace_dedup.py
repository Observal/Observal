"""Trace-level deduplication for the UI trace viewer.

Ensures enriched/reconciled data merges INTO existing trace spans rather than
creating new duplicate entries that cause visual clutter.
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


def _enrich_event(event: dict, turn: dict) -> dict:
    """Merge turn enrichment fields into an existing event dict."""
    event = dict(event)

    for field in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens"):
        turn_val = turn.get(field)
        if turn_val and not event.get(field):
            event[field] = turn_val

    if not event.get("model") and turn.get("model"):
        event["model"] = turn["model"]

    if turn.get("has_thinking"):
        event["has_thinking"] = True

    if not event.get("stop_reason") and turn.get("stop_reason"):
        event["stop_reason"] = turn["stop_reason"]

    return event


def _make_synthetic_event(turn: dict) -> dict:
    """Create a synthetic (gap-fill) event from a turn with no matching span."""
    return {
        "span_id": f"synthetic-turn-{turn.get('turn_index', 0)}",
        "type": "reconcile_turn",
        "name": f"turn_{turn.get('turn_index', 0)}",
        "start_time": "",
        "status": "success",
        "synthetic": True,
        "turn_index": turn.get("turn_index"),
        "model": turn.get("model"),
        "input_tokens": turn.get("input_tokens", 0),
        "output_tokens": turn.get("output_tokens", 0),
        "cache_read_tokens": turn.get("cache_read_tokens", 0),
        "cache_creation_tokens": turn.get("cache_creation_tokens", 0),
        "has_thinking": turn.get("has_thinking", False),
        "stop_reason": turn.get("stop_reason"),
    }


def merge_enrichment_into_trace(
    existing_events: list[dict],
    enrichment_turns: list[dict],
) -> list[dict]:
    """Merge reconciliation enrichment data into existing trace events.

    Strategy:
    - Match enrichment turns to existing events by turn_index.
    - Add token counts, model info, thinking flags to the first matched span.
    - Do NOT create new events for turns that already match — only enrich.
    - If no matching event found for a turn, append as a synthetic gap-fill event.

    Returns: unified event list with no duplicates, enriched where possible.
    """
    if not enrichment_turns:
        return list(existing_events)

    turn_to_positions: dict[int, list[int]] = {}
    for idx, event in enumerate(existing_events):
        ti = event.get("turn_index")
        if ti is not None:
            turn_to_positions.setdefault(ti, []).append(idx)

    result = list(existing_events)
    matched_turn_indices: set[int] = set()

    for turn in enrichment_turns:
        ti = turn.get("turn_index")
        if ti is None:
            continue

        positions = turn_to_positions.get(ti, [])
        if positions:
            result[positions[0]] = _enrich_event(result[positions[0]], turn)
            matched_turn_indices.add(ti)

    for turn in enrichment_turns:
        ti = turn.get("turn_index")
        if ti is not None and ti not in matched_turn_indices:
            result.append(_make_synthetic_event(turn))

    return result


def _span_collapse_key(event: dict) -> tuple[str, int]:
    """Generate a collapse key: (tool_name, 1-second time bucket)."""
    name = event.get("name") or ""
    ts = _parse_ts(event.get("start_time"))
    return (name, int(ts))


def _merge_spans(base: dict, incoming: dict) -> dict:
    """Merge two span dicts, keeping richer fields from each."""
    merged = dict(base)

    for field in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens"):
        if (not merged.get(field) or merged.get(field) == 0) and incoming.get(field):
            merged[field] = incoming[field]

    for field in ("tool_input", "tool_response"):
        if not merged.get(field) and incoming.get(field):
            merged[field] = incoming[field]

    if not merged.get("error") and incoming.get("error"):
        merged["error"] = incoming["error"]

    if not merged.get("model") and incoming.get("model"):
        merged["model"] = incoming["model"]

    if incoming.get("has_thinking"):
        merged["has_thinking"] = True

    ts_base = _parse_ts(base.get("start_time"))
    ts_inc = _parse_ts(incoming.get("start_time"))
    if ts_inc > 0 and (ts_base == 0 or ts_inc < ts_base):
        merged["start_time"] = incoming["start_time"]

    return merged


def collapse_duplicate_tool_spans(events: list[dict]) -> list[dict]:
    """Collapse multiple spans for the same tool call into one.

    Non-tool-call events pass through unchanged. Only events within a 2-second
    window sharing the same tool name are collapsed.

    Returns: collapsed event list sorted by start_time.
    """
    if not events:
        return []

    tool_events: list[dict] = []
    other_events: list[dict] = []

    for event in events:
        if event.get("type") == "tool_call":
            tool_events.append(event)
        else:
            other_events.append(event)

    collapsed: dict[tuple[str, int], dict] = {}

    for event in tool_events:
        key = _span_collapse_key(event)
        if key not in collapsed:
            collapsed[key] = dict(event)
        else:
            collapsed[key] = _merge_spans(collapsed[key], event)

    all_events = list(collapsed.values()) + other_events
    all_events.sort(key=lambda e: _parse_ts(e.get("start_time")))
    return all_events
