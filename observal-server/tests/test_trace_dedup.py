"""Tests for trace-level deduplication (enrichment merge + tool span collapse)."""


def _span(span_id, tool_name, start_time="2024-01-01 10:00:00.000", **extra) -> dict:
    s = {
        "span_id": span_id,
        "type": "tool_call",
        "name": tool_name,
        "start_time": start_time,
        "status": "success",
    }
    s.update(extra)
    return s


def _turn(turn_index, model="claude-sonnet-4", **extra) -> dict:
    t = {
        "turn_index": turn_index,
        "model": model,
        "input_tokens": 100,
        "output_tokens": 50,
        "has_thinking": False,
        "tool_uses": [],
    }
    t.update(extra)
    return t


# ---------------------------------------------------------------------------
# merge_enrichment_into_trace
# ---------------------------------------------------------------------------


def test_merge_adds_tokens_to_existing_event():
    from services.insights.trace_dedup import merge_enrichment_into_trace

    events = [_span("s1", "Bash", turn_index=1)]
    turns = [_turn(1, input_tokens=200, output_tokens=80)]

    result = merge_enrichment_into_trace(events, turns)
    assert len(result) == 1
    assert result[0]["input_tokens"] == 200
    assert result[0]["output_tokens"] == 80


def test_merge_adds_model_to_existing_event():
    from services.insights.trace_dedup import merge_enrichment_into_trace

    events = [_span("s1", "Bash", turn_index=1)]
    turns = [_turn(1, model="claude-opus-4")]

    result = merge_enrichment_into_trace(events, turns)
    assert result[0]["model"] == "claude-opus-4"


def test_merge_adds_thinking_flag():
    from services.insights.trace_dedup import merge_enrichment_into_trace

    events = [_span("s1", "Bash", turn_index=1)]
    turns = [_turn(1, has_thinking=True)]

    result = merge_enrichment_into_trace(events, turns)
    assert result[0]["has_thinking"] is True


def test_merge_does_not_create_duplicate_events():
    from services.insights.trace_dedup import merge_enrichment_into_trace

    events = [_span("s1", "Bash", turn_index=1)]
    turns = [_turn(1)]

    result = merge_enrichment_into_trace(events, turns)
    assert len(result) == 1


def test_merge_unmatched_turn_appended_as_synthetic():
    from services.insights.trace_dedup import merge_enrichment_into_trace

    events = [_span("s1", "Bash", turn_index=1)]
    turns = [_turn(1), _turn(99)]  # turn 99 has no matching event

    result = merge_enrichment_into_trace(events, turns)
    assert len(result) == 2
    synthetic = next(e for e in result if e.get("turn_index") == 99)
    assert synthetic.get("synthetic") is True


def test_merge_empty_events_all_synthetic():
    from services.insights.trace_dedup import merge_enrichment_into_trace

    events = []
    turns = [_turn(1), _turn(2)]

    result = merge_enrichment_into_trace(events, turns)
    assert len(result) == 2
    assert all(e.get("synthetic") is True for e in result)


def test_merge_empty_turns_returns_events_unchanged():
    from services.insights.trace_dedup import merge_enrichment_into_trace

    events = [_span("s1", "Bash"), _span("s2", "Read")]
    result = merge_enrichment_into_trace(events, [])
    assert result == events


def test_merge_does_not_overwrite_existing_tokens_with_zero():
    from services.insights.trace_dedup import merge_enrichment_into_trace

    events = [_span("s1", "Bash", turn_index=1, input_tokens=500)]
    turns = [_turn(1, input_tokens=0)]  # enrichment has zero — don't overwrite

    result = merge_enrichment_into_trace(events, turns)
    assert result[0]["input_tokens"] == 500


def test_merge_multiple_events_same_turn_index():
    """When multiple events share the same turn_index, only the first is enriched."""
    from services.insights.trace_dedup import merge_enrichment_into_trace

    events = [
        _span("s1", "Bash", turn_index=1),
        _span("s2", "Read", turn_index=1),
    ]
    turns = [_turn(1, model="claude-haiku-4")]

    result = merge_enrichment_into_trace(events, turns)
    # No duplicate synthetic entries — total count remains 2
    assert len(result) == 2
    # At least one event gets the model
    models = [e.get("model") for e in result]
    assert "claude-haiku-4" in models


# ---------------------------------------------------------------------------
# collapse_duplicate_tool_spans
# ---------------------------------------------------------------------------


def test_collapse_merges_same_name_and_time():
    from services.insights.trace_dedup import collapse_duplicate_tool_spans

    events = [
        _span("s1", "Bash", start_time="2024-01-01 10:00:00.100", tool_input="echo hi", source="hook"),
        _span("s2", "Bash", start_time="2024-01-01 10:00:00.800", input_tokens=30, source="otlp"),
    ]
    result = collapse_duplicate_tool_spans(events)
    assert len(result) == 1
    assert result[0]["tool_input"] == "echo hi"
    assert result[0]["input_tokens"] == 30


def test_collapse_different_tool_names_not_merged():
    from services.insights.trace_dedup import collapse_duplicate_tool_spans

    events = [
        _span("s1", "Bash", start_time="2024-01-01 10:00:00.100"),
        _span("s2", "Read", start_time="2024-01-01 10:00:00.200"),
    ]
    result = collapse_duplicate_tool_spans(events)
    assert len(result) == 2


def test_collapse_non_tool_events_pass_through():
    from services.insights.trace_dedup import collapse_duplicate_tool_spans

    events = [
        {"span_id": "s1", "type": "session_start", "name": "session_start", "start_time": "2024-01-01 10:00:00.000"},
        {"span_id": "s2", "type": "user_prompt", "name": "user_prompt", "start_time": "2024-01-01 10:00:01.000"},
    ]
    result = collapse_duplicate_tool_spans(events)
    assert len(result) == 2


def test_collapse_outside_2s_window_not_merged():
    from services.insights.trace_dedup import collapse_duplicate_tool_spans

    events = [
        _span("s1", "Bash", start_time="2024-01-01 10:00:00.000"),
        _span("s2", "Bash", start_time="2024-01-01 10:00:03.000"),
    ]
    result = collapse_duplicate_tool_spans(events)
    assert len(result) == 2


def test_collapse_preserves_order():
    from services.insights.trace_dedup import collapse_duplicate_tool_spans

    events = [
        _span("s1", "Bash", start_time="2024-01-01 10:00:03.000"),
        _span("s2", "Read", start_time="2024-01-01 10:00:01.000"),
        _span("s3", "Write", start_time="2024-01-01 10:00:02.000"),
    ]
    result = collapse_duplicate_tool_spans(events)
    names = [e["name"] for e in result]
    assert names == ["Read", "Write", "Bash"]


def test_collapse_empty_list():
    from services.insights.trace_dedup import collapse_duplicate_tool_spans

    assert collapse_duplicate_tool_spans([]) == []


def test_collapse_three_sources_same_tool():
    """Hook + OTLP + reconcile all recording the same tool call → one entry."""
    from services.insights.trace_dedup import collapse_duplicate_tool_spans

    events = [
        _span("s1", "Bash", start_time="2024-01-01 10:00:00.100", source="hook", tool_input="ls -la"),
        _span("s2", "Bash", start_time="2024-01-01 10:00:00.700", source="otlp", input_tokens=20),
        _span("s3", "Bash", start_time="2024-01-01 10:00:00.900", source="reconcile", model="claude-sonnet-4"),
    ]
    result = collapse_duplicate_tool_spans(events)
    assert len(result) == 1
    assert result[0]["tool_input"] == "ls -la"
    assert result[0]["input_tokens"] == 20
    assert result[0]["model"] == "claude-sonnet-4"
