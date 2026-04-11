"""Unit tests for the structural scorer (rule-based, no LLM)."""

from services.structural_scorer import StructuralScorer, _span_dedup_key


def _tool_span(
    name="tool_a", input_data="input1", output="result", status="success", latency_ms=100, span_id="s1", error=None
):
    """Helper to create a mock tool call span."""
    return {
        "type": "tool_call",
        "name": name,
        "input": input_data,
        "output": output,
        "status": status,
        "latency_ms": latency_ms,
        "span_id": span_id,
        "error": error,
    }


def _reasoning_span(input_data="", span_id="r1"):
    """Helper to create a non-tool span."""
    return {"type": "reasoning_step", "name": "think", "input": input_data, "span_id": span_id}


class TestSpanDedupKey:
    def test_same_name_same_input(self):
        a = _tool_span(name="read_file", input_data='{"path": "/a"}')
        b = _tool_span(name="read_file", input_data='{"path": "/a"}')
        assert _span_dedup_key(a) == _span_dedup_key(b)

    def test_different_input(self):
        a = _tool_span(name="read_file", input_data='{"path": "/a"}')
        b = _tool_span(name="read_file", input_data='{"path": "/b"}')
        assert _span_dedup_key(a) != _span_dedup_key(b)

    def test_different_name(self):
        a = _tool_span(name="read_file", input_data="x")
        b = _tool_span(name="write_file", input_data="x")
        assert _span_dedup_key(a) != _span_dedup_key(b)


class TestToolEfficiency:
    def setup_method(self):
        self.scorer = StructuralScorer()

    def test_no_penalties_for_clean_trace(self):
        spans = [
            _tool_span(name="tool_a", input_data="i1", output="o1", span_id="s1"),
            _reasoning_span(input_data="o1"),  # references output
            _tool_span(name="tool_b", input_data="i2", output="o2", span_id="s2"),
        ]
        penalties = self.scorer.score_tool_efficiency(spans, "agent-1")
        assert len(penalties) == 0

    def test_duplicate_tool_call(self):
        spans = [
            _tool_span(name="tool_a", input_data="same", span_id="s1"),
            _tool_span(name="tool_a", input_data="same", span_id="s2"),
        ]
        penalties = self.scorer.score_tool_efficiency(spans, "agent-1")
        dup = [p for p in penalties if p["event_name"] == "duplicate_tool_call"]
        assert len(dup) == 1
        assert "Duplicate" in dup[0]["evidence"]

    def test_no_duplicate_for_different_inputs(self):
        spans = [
            _tool_span(name="tool_a", input_data="input1", span_id="s1"),
            _tool_span(name="tool_a", input_data="input2", span_id="s2"),
        ]
        penalties = self.scorer.score_tool_efficiency(spans, "agent-1")
        dup = [p for p in penalties if p["event_name"] == "duplicate_tool_call"]
        assert len(dup) == 0

    def test_unused_tool_result(self):
        spans = [
            _tool_span(name="tool_a", input_data="i1", output="unique_output_xyz", span_id="s1"),
            _tool_span(name="tool_b", input_data="unrelated", output="o2", span_id="s2"),
        ]
        penalties = self.scorer.score_tool_efficiency(spans, "agent-1")
        unused = [p for p in penalties if p["event_name"] == "unused_tool_result"]
        # Both outputs unused since neither is referenced later
        assert len(unused) >= 1

    def test_used_tool_result_no_penalty(self):
        output_text = "the result data"
        spans = [
            _tool_span(name="tool_a", input_data="i1", output=output_text, span_id="s1"),
            _reasoning_span(input_data=f"processing: {output_text}", span_id="r1"),
        ]
        penalties = self.scorer.score_tool_efficiency(spans, "agent-1")
        unused = [p for p in penalties if p["event_name"] == "unused_tool_result"]
        assert len(unused) == 0

    def test_ungrounded_claims_detected(self):
        """Agent makes assertions about external state with no tool calls."""
        spans = [_reasoning_span(input_data="the file contains a config block")]
        penalties = self.scorer.score_tool_efficiency(spans, "agent-1")
        ungrounded = [p for p in penalties if p["event_name"] == "ungrounded_claims"]
        assert len(ungrounded) == 1

    def test_no_ungrounded_claims_without_assertions(self):
        """Agent reasons without asserting external state — no penalty."""
        spans = [_reasoning_span(input_data="let me think about the approach")]
        penalties = self.scorer.score_tool_efficiency(spans, "agent-1")
        ungrounded = [p for p in penalties if p["event_name"] == "ungrounded_claims"]
        assert len(ungrounded) == 0

    def test_no_ungrounded_claims_when_tools_used(self):
        """Agent uses tools — even with assertion language, not penalized."""
        spans = [
            _tool_span(name="read_file", input_data="/a.py", output="content", span_id="s1"),
            _reasoning_span(input_data="the file contains content"),
        ]
        penalties = self.scorer.score_tool_efficiency(spans, "agent-1")
        ungrounded = [p for p in penalties if p["event_name"] == "ungrounded_claims"]
        assert len(ungrounded) == 0

    def test_many_unique_tool_calls_no_excessive_penalty(self):
        """Many tool calls should not be penalized if they are all unique."""
        spans = [_tool_span(name=f"tool_{i}", input_data=f"i{i}", span_id=f"s{i}") for i in range(25)]
        penalties = self.scorer.score_tool_efficiency(spans, "agent-1")
        excessive = [p for p in penalties if p["event_name"] == "excessive_tool_calls"]
        assert len(excessive) == 0


class TestToolFailures:
    def setup_method(self):
        self.scorer = StructuralScorer(timeout_ms=30000)

    def test_no_penalties_for_clean_trace(self):
        spans = [_tool_span(status="success", span_id="s1")]
        penalties = self.scorer.score_tool_failures(spans)
        assert len(penalties) == 0

    def test_tool_call_error(self):
        spans = [_tool_span(status="error", error="Connection refused", span_id="s1")]
        penalties = self.scorer.score_tool_failures(spans)
        errors = [p for p in penalties if p["event_name"] == "tool_call_error"]
        assert len(errors) == 1
        assert "Connection refused" in errors[0]["evidence"]

    def test_tool_call_timeout(self):
        spans = [_tool_span(latency_ms=35000, span_id="s1")]
        penalties = self.scorer.score_tool_failures(spans)
        timeouts = [p for p in penalties if p["event_name"] == "tool_call_timeout"]
        assert len(timeouts) == 1
        assert "35000ms" in timeouts[0]["evidence"]

    def test_no_timeout_under_threshold(self):
        spans = [_tool_span(latency_ms=25000, span_id="s1")]
        penalties = self.scorer.score_tool_failures(spans)
        timeouts = [p for p in penalties if p["event_name"] == "tool_call_timeout"]
        assert len(timeouts) == 0

    def test_retry_success(self):
        spans = [
            _tool_span(name="tool_a", input_data="x", status="error", error="fail", span_id="s1"),
            _tool_span(name="tool_a", input_data="x", status="success", span_id="s2"),
        ]
        penalties = self.scorer.score_tool_failures(spans)
        retries = [p for p in penalties if p["event_name"] == "tool_call_retry_success"]
        errors = [p for p in penalties if p["event_name"] == "tool_call_error"]
        assert len(retries) == 1
        assert len(errors) == 0

    def test_ignored_tool_failure(self):
        spans = [
            _tool_span(name="tool_a", input_data="x", status="error", error="fail", span_id="s1"),
            _reasoning_span(span_id="r1"),  # non-tool span follows
        ]
        penalties = self.scorer.score_tool_failures(spans)
        ignored = [p for p in penalties if p["event_name"] == "ignored_tool_failure"]
        assert len(ignored) == 1
        assert "SLM confirmation" in ignored[0]["evidence"]

    def test_error_with_error_field_only(self):
        """Error detected via error field even when status is not 'error'."""
        spans = [_tool_span(status="success", error="some error occurred", span_id="s1")]
        penalties = self.scorer.score_tool_failures(spans)
        errors = [p for p in penalties if p["event_name"] == "tool_call_error"]
        assert len(errors) == 1
