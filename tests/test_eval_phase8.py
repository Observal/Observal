"""Unit tests for eval engine v2: Phase 8."""

from unittest.mock import AsyncMock, patch

import pytest

from services.eval_engine import (
    EVAL_TEMPLATES,
    FallbackBackend,
    LLMJudgeBackend,
    _extract_json,
    get_backend,
    list_templates,
    run_eval_on_trace,
)


class TestEvalTemplates:
    def test_has_required_templates(self):
        for name in [
            "tool_selection_accuracy",
            "tool_output_utility",
            "reasoning_clarity",
            "response_quality",
            "graph_faithfulness",
            "recall_accuracy",
        ]:
            assert name in EVAL_TEMPLATES

    def test_templates_have_required_fields(self):
        for name, tpl in EVAL_TEMPLATES.items():
            assert "id" in tpl
            assert "name" in tpl
            assert "applies_to" in tpl
            assert "prompt" in tpl
            assert "{trace}" in tpl["prompt"]
            assert "{span}" in tpl["prompt"]

    def test_list_templates(self):
        result = list_templates()
        assert len(result) == len(EVAL_TEMPLATES)
        assert all("name" in t for t in result)


class TestExtractJson:
    def test_plain_json(self):
        assert _extract_json('{"score": 0.8}') == {"score": 0.8}

    def test_json_in_code_block(self):
        assert _extract_json('```json\n{"score": 0.9}\n```') == {"score": 0.9}

    def test_json_in_generic_block(self):
        assert _extract_json('```\n{"score": 0.7}\n```') == {"score": 0.7}

    def test_invalid(self):
        assert _extract_json("not json") == {}


class TestFallbackBackend:
    @pytest.mark.asyncio
    async def test_success_span(self):
        backend = FallbackBackend()
        result = await backend.score({}, {}, {"status": "success", "latency_ms": 100})
        assert result["score"] == 0.8
        assert "success" in result["reason"]

    @pytest.mark.asyncio
    async def test_error_span(self):
        backend = FallbackBackend()
        result = await backend.score({}, {}, {"status": "error", "latency_ms": 100})
        assert result["score"] == 0.2

    @pytest.mark.asyncio
    async def test_high_latency_penalty(self):
        backend = FallbackBackend()
        result = await backend.score({}, {}, {"status": "success", "latency_ms": 10000})
        assert result["score"] < 0.8


class TestGetBackend:
    def test_returns_fallback_when_no_model(self):
        with patch("services.eval_engine.settings") as mock_settings:
            mock_settings.EVAL_MODEL_NAME = ""
            assert isinstance(get_backend(), FallbackBackend)

    def test_returns_llm_when_model_set(self):
        with patch("services.eval_engine.settings") as mock_settings:
            mock_settings.EVAL_MODEL_NAME = "gpt-4"
            assert isinstance(get_backend(), LLMJudgeBackend)


class TestRunEvalOnTrace:
    @pytest.mark.asyncio
    async def test_no_trace_returns_empty(self):
        with patch("services.eval_engine.query_trace_by_id", new_callable=AsyncMock, return_value=None):
            result = await run_eval_on_trace("agent-1", "missing-trace")
            assert result == []

    @pytest.mark.asyncio
    async def test_no_spans_returns_empty(self):
        with (
            patch("services.eval_engine.query_trace_by_id", new_callable=AsyncMock, return_value={"trace_id": "t1"}),
            patch("services.eval_engine.query_spans", new_callable=AsyncMock, return_value=[]),
        ):
            result = await run_eval_on_trace("agent-1", "t1")
            assert result == []

    @pytest.mark.asyncio
    async def test_scores_tool_call_spans(self):
        trace = {"trace_id": "t1", "user_id": "u1"}
        spans = [
            {"span_id": "s1", "type": "tool_call", "status": "success", "latency_ms": 50},
            {"span_id": "s2", "type": "initialize", "status": "success"},  # no template
        ]
        with (
            patch("services.eval_engine.query_trace_by_id", new_callable=AsyncMock, return_value=trace),
            patch("services.eval_engine.query_spans", new_callable=AsyncMock, return_value=spans),
            patch("services.eval_engine.get_backend") as mock_get,
            patch("services.eval_engine.insert_scores", new_callable=AsyncMock) as mock_insert,
        ):
            mock_backend = AsyncMock()
            mock_backend.score.return_value = {"score": 0.9, "reason": "good"}
            mock_get.return_value = mock_backend

            result = await run_eval_on_trace("agent-1", "t1")

            # tool_call has 2 templates (tool_selection_accuracy, tool_output_utility)
            assert len(result) == 2
            assert all(s["source"] == "eval" for s in result)
            assert all(s["trace_id"] == "t1" for s in result)
            mock_insert.assert_called_once()

    @pytest.mark.asyncio
    async def test_scores_written_to_clickhouse(self):
        trace = {"trace_id": "t1", "user_id": "u1"}
        spans = [{"span_id": "s1", "type": "tool_call", "status": "success"}]
        with (
            patch("services.eval_engine.query_trace_by_id", new_callable=AsyncMock, return_value=trace),
            patch("services.eval_engine.query_spans", new_callable=AsyncMock, return_value=spans),
            patch("services.eval_engine.get_backend") as mock_get,
            patch("services.eval_engine.insert_scores", new_callable=AsyncMock) as mock_insert,
        ):
            mock_backend = AsyncMock()
            mock_backend.score.return_value = {"score": 0.85, "reason": "test"}
            mock_get.return_value = mock_backend

            await run_eval_on_trace("agent-1", "t1")

            scores = mock_insert.call_args[0][0]
            assert all(s["eval_template_id"].startswith("tpl-") for s in scores)
            assert all(s["data_type"] == "numeric" for s in scores)

    @pytest.mark.asyncio
    async def test_handles_backend_error(self):
        trace = {"trace_id": "t1", "user_id": "u1"}
        spans = [{"span_id": "s1", "type": "tool_call", "status": "success"}]
        with (
            patch("services.eval_engine.query_trace_by_id", new_callable=AsyncMock, return_value=trace),
            patch("services.eval_engine.query_spans", new_callable=AsyncMock, return_value=spans),
            patch("services.eval_engine.get_backend") as mock_get,
            patch("services.eval_engine.insert_scores", new_callable=AsyncMock),
        ):
            mock_backend = AsyncMock()
            mock_backend.score.side_effect = Exception("model down")
            mock_get.return_value = mock_backend

            result = await run_eval_on_trace("agent-1", "t1")
            assert result == []  # errors caught, no scores
