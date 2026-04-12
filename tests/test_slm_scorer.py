"""Unit tests for the SLM scorer (LLM-assisted)."""

from unittest.mock import AsyncMock, patch

import pytest

from services.slm_scorer import SLMScorer, _extract_reasoning_trace, _extract_tool_results


def _make_backend(response: dict):
    """Create a mock backend that returns the given response from _call_model_direct."""
    backend = AsyncMock()
    backend.score.side_effect = Exception("force direct call")
    return backend


def _tool_span(name="tool_a", output="result", span_id="s1", status="success", input_data=""):
    return {
        "type": "tool_call",
        "name": name,
        "output": output,
        "span_id": span_id,
        "status": status,
        "input": input_data,
    }


def _reasoning_span(input_data="thinking...", span_id="r1"):
    return {"type": "reasoning_step", "name": "think", "input": input_data, "output": "", "span_id": span_id}


class TestExtractToolResults:
    def test_extracts_tool_calls(self):
        spans = [_tool_span(name="read_file", output="file content", span_id="s1")]
        result = _extract_tool_results(spans)
        assert "read_file" in result
        assert "file content" in result
        assert "s1" in result

    def test_skips_non_tool_spans(self):
        spans = [_reasoning_span(), _tool_span()]
        result = _extract_tool_results(spans)
        assert "think" not in result

    def test_empty_spans(self):
        assert _extract_tool_results([]) == ""


class TestExtractReasoningTrace:
    def test_formats_reasoning_and_actions(self):
        spans = [
            _reasoning_span(input_data="I should read the file"),
            _tool_span(name="read_file", input_data="/path", output="content"),
        ]
        result = _extract_reasoning_trace(spans)
        assert "THOUGHT" in result
        assert "ACTION" in result
        assert "read_file" in result

    def test_empty_spans(self):
        assert _extract_reasoning_trace([]) == ""


class TestGoalCompletion:
    @pytest.mark.asyncio
    async def test_missing_section(self):
        backend = _make_backend({})
        scorer = SLMScorer(backend)
        llm_response = {
            "sections": [{"section_name": "Summary", "status": "missing", "evidence_span_id": None, "confidence": 0.9}]
        }
        with patch.object(scorer, "_call_model_direct", new_callable=AsyncMock, return_value=llm_response):
            penalties = await scorer.score_goal_completion(
                trace={"output": "some output"},
                spans=[],
                goal_description="Test goal",
                required_sections=[{"name": "Summary", "grounding_required": True}],
            )
        assert len(penalties) == 1
        assert penalties[0]["event_name"] == "missing_required_section"

    @pytest.mark.asyncio
    async def test_stub_section(self):
        backend = _make_backend({})
        scorer = SLMScorer(backend)
        llm_response = {
            "sections": [{"section_name": "Analysis", "status": "stub", "evidence_span_id": None, "confidence": 0.85}]
        }
        with patch.object(scorer, "_call_model_direct", new_callable=AsyncMock, return_value=llm_response):
            penalties = await scorer.score_goal_completion(
                trace={"output": "Analysis: TODO"},
                spans=[],
                goal_description="Test",
                required_sections=[{"name": "Analysis"}],
            )
        assert len(penalties) == 1
        assert penalties[0]["event_name"] == "empty_stub_section"

    @pytest.mark.asyncio
    async def test_ungrounded_section(self):
        backend = _make_backend({})
        scorer = SLMScorer(backend)
        llm_response = {
            "sections": [{"section_name": "Data", "status": "ungrounded", "evidence_span_id": None, "confidence": 0.8}]
        }
        with patch.object(scorer, "_call_model_direct", new_callable=AsyncMock, return_value=llm_response):
            penalties = await scorer.score_goal_completion(
                trace={"output": "Data: some data"},
                spans=[],
                goal_description="Test",
                required_sections=[{"name": "Data", "grounding_required": True}],
            )
        assert len(penalties) == 1
        assert penalties[0]["event_name"] == "ungrounded_section"

    @pytest.mark.asyncio
    async def test_present_section_no_penalty(self):
        backend = _make_backend({})
        scorer = SLMScorer(backend)
        llm_response = {
            "sections": [{"section_name": "Summary", "status": "present", "evidence_span_id": "s1", "confidence": 0.95}]
        }
        with patch.object(scorer, "_call_model_direct", new_callable=AsyncMock, return_value=llm_response):
            penalties = await scorer.score_goal_completion(
                trace={"output": "Summary: good content"},
                spans=[],
                goal_description="Test",
                required_sections=[{"name": "Summary"}],
            )
        assert len(penalties) == 0

    @pytest.mark.asyncio
    async def test_no_sections_returns_empty(self):
        backend = _make_backend({})
        scorer = SLMScorer(backend)
        penalties = await scorer.score_goal_completion(trace={"output": "output"}, spans=[], required_sections=[])
        assert penalties == []


class TestFactualGrounding:
    @pytest.mark.asyncio
    async def test_ungrounded_claim(self):
        backend = _make_backend({})
        scorer = SLMScorer(backend)
        llm_response = {
            "claims": [
                {
                    "claim_text": "Revenue is $10M",
                    "status": "ungrounded",
                    "evidence_quote": "No data source",
                    "source_span_id": None,
                }
            ]
        }
        with patch.object(scorer, "_call_model_direct", new_callable=AsyncMock, return_value=llm_response):
            penalties = await scorer.score_factual_grounding(
                trace={"output": "Revenue is $10M"},
                spans=[_tool_span(output="some data")],
            )
        assert len(penalties) == 1
        assert penalties[0]["event_name"] == "ungrounded_claim"

    @pytest.mark.asyncio
    async def test_contradicts_source(self):
        backend = _make_backend({})
        scorer = SLMScorer(backend)
        llm_response = {
            "claims": [
                {
                    "claim_text": "Revenue is $10M",
                    "status": "contradicted",
                    "evidence_quote": "Source says $5M",
                    "source_span_id": "s1",
                }
            ]
        }
        with patch.object(scorer, "_call_model_direct", new_callable=AsyncMock, return_value=llm_response):
            penalties = await scorer.score_factual_grounding(
                trace={"output": "Revenue is $10M"},
                spans=[_tool_span(output="Revenue: $5M", span_id="s1")],
            )
        assert len(penalties) == 1
        assert penalties[0]["event_name"] == "contradicts_source"

    @pytest.mark.asyncio
    async def test_grounded_no_penalty(self):
        backend = _make_backend({})
        scorer = SLMScorer(backend)
        llm_response = {
            "claims": [
                {
                    "claim_text": "Revenue is $10M",
                    "status": "grounded",
                    "evidence_quote": "Matches source",
                    "source_span_id": "s1",
                }
            ]
        }
        with patch.object(scorer, "_call_model_direct", new_callable=AsyncMock, return_value=llm_response):
            penalties = await scorer.score_factual_grounding(
                trace={"output": "Revenue is $10M"},
                spans=[_tool_span(output="Revenue: $10M")],
            )
        assert len(penalties) == 0

    @pytest.mark.asyncio
    async def test_empty_output_returns_empty(self):
        backend = _make_backend({})
        scorer = SLMScorer(backend)
        penalties = await scorer.score_factual_grounding(trace={"output": ""}, spans=[])
        assert penalties == []


class TestThoughtProcess:
    @pytest.mark.asyncio
    async def test_blind_tool_use(self):
        backend = _make_backend({})
        scorer = SLMScorer(backend)
        llm_response = {
            "findings": [
                {"finding_type": "blind_tool_use", "span_id": "s1", "explanation": "No reasoning before tool call"}
            ]
        }
        with patch.object(scorer, "_call_model_direct", new_callable=AsyncMock, return_value=llm_response):
            penalties = await scorer.score_thought_process(
                spans=[_tool_span(name="read_file")],
            )
        assert len(penalties) == 1
        assert penalties[0]["event_name"] == "blind_tool_use"

    @pytest.mark.asyncio
    async def test_invalid_finding_type_rejected(self):
        """Invalid finding types are now rejected by schema validation."""
        backend = _make_backend({})
        scorer = SLMScorer(backend)
        llm_response = {"findings": [{"finding_type": "unknown_type", "span_id": "s1", "explanation": "Something"}]}
        with patch.object(scorer, "_call_model_direct", new_callable=AsyncMock, return_value=llm_response):
            penalties = await scorer.score_thought_process(
                spans=[_tool_span()],
            )
        assert len(penalties) == 0

    @pytest.mark.asyncio
    async def test_empty_reasoning_returns_empty(self):
        backend = _make_backend({})
        scorer = SLMScorer(backend)
        penalties = await scorer.score_thought_process(spans=[])
        assert penalties == []
