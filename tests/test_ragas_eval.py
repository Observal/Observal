"""Unit tests for RAGAS evaluation service."""

from unittest.mock import AsyncMock, patch

import pytest

from services.ragas_eval import (
    RAGAS_DIMENSIONS,
    _eval_answer_relevancy,
    _eval_context_precision,
    _eval_context_recall,
    _eval_faithfulness,
    _safe_score,
    run_ragas_on_span,
)


class TestSafeScore:
    def test_normal(self):
        assert _safe_score({"score": 0.85}) == 0.85

    def test_clamp_high(self):
        assert _safe_score({"score": 1.5}) == 1.0

    def test_clamp_low(self):
        assert _safe_score({"score": -0.3}) == 0.0

    def test_missing(self):
        assert _safe_score({}) == 0.0

    def test_invalid(self):
        assert _safe_score({"score": "bad"}) == 0.0


class TestDimensions:
    def test_four_dimensions(self):
        assert len(RAGAS_DIMENSIONS) == 4
        assert "faithfulness" in RAGAS_DIMENSIONS
        assert "answer_relevancy" in RAGAS_DIMENSIONS
        assert "context_precision" in RAGAS_DIMENSIONS
        assert "context_recall" in RAGAS_DIMENSIONS


class TestFaithfulness:
    @pytest.mark.asyncio
    @patch("services.ragas_eval._call_model", new_callable=AsyncMock)
    async def test_returns_score(self, mock_call):
        mock_call.return_value = {"claims_total": 3, "claims_supported": 2, "score": 0.67, "reason": "1 unsupported"}
        result = await _eval_faithfulness("answer text", "context text")
        assert result["score"] == 0.67
        assert "unsupported" in result["reason"]

    @pytest.mark.asyncio
    @patch("services.ragas_eval._call_model", new_callable=AsyncMock)
    async def test_invalid_response(self, mock_call):
        mock_call.return_value = {}
        result = await _eval_faithfulness("answer", "context")
        assert result["score"] == 0.0


class TestAnswerRelevancy:
    @pytest.mark.asyncio
    @patch("services.ragas_eval._call_model", new_callable=AsyncMock)
    async def test_returns_score(self, mock_call):
        mock_call.return_value = {"score": 0.9, "reason": "directly addresses question"}
        result = await _eval_answer_relevancy("what is X?", "X is a thing")
        assert result["score"] == 0.9

    @pytest.mark.asyncio
    @patch("services.ragas_eval._call_model", new_callable=AsyncMock)
    async def test_invalid_response(self, mock_call):
        mock_call.return_value = {"error": "bad"}
        result = await _eval_answer_relevancy("q", "a")
        assert result["score"] == 0.0


class TestContextPrecision:
    @pytest.mark.asyncio
    @patch("services.ragas_eval._call_model", new_callable=AsyncMock)
    async def test_returns_score(self, mock_call):
        mock_call.return_value = {"chunks_total": 5, "chunks_relevant": 4, "score": 0.8, "reason": "1 noisy chunk"}
        result = await _eval_context_precision("question", "chunks")
        assert result["score"] == 0.8


class TestContextRecall:
    @pytest.mark.asyncio
    @patch("services.ragas_eval._call_model", new_callable=AsyncMock)
    async def test_returns_score(self, mock_call):
        mock_call.return_value = {
            "statements_total": 4,
            "statements_attributed": 3,
            "score": 0.75,
            "reason": "1 missing",
        }
        result = await _eval_context_recall("ground truth", "context")
        assert result["score"] == 0.75


class TestRunRagasOnSpan:
    @pytest.mark.asyncio
    @patch("services.ragas_eval._call_model", new_callable=AsyncMock)
    async def test_all_dimensions(self, mock_call):
        mock_call.return_value = {"score": 0.8, "reason": "good"}
        span = {"input": "what is X?", "output": "X is a thing that does Y"}
        result = await run_ragas_on_span(span, ground_truth="X does Y and Z")
        assert "faithfulness" in result
        assert "answer_relevancy" in result
        assert "context_precision" in result
        assert "context_recall" in result
        for dim in RAGAS_DIMENSIONS:
            assert result[dim]["score"] == 0.8

    @pytest.mark.asyncio
    @patch("services.ragas_eval._call_model", new_callable=AsyncMock)
    async def test_no_question(self, mock_call):
        mock_call.return_value = {"score": 0.8, "reason": "good"}
        span = {"input": "", "output": "some output"}
        result = await run_ragas_on_span(span)
        assert result["answer_relevancy"]["score"] == 0.0
        assert result["context_precision"]["score"] == 0.0

    @pytest.mark.asyncio
    @patch("services.ragas_eval._call_model", new_callable=AsyncMock)
    async def test_no_ground_truth(self, mock_call):
        mock_call.return_value = {"score": 0.8, "reason": "good"}
        span = {"input": "question", "output": "answer"}
        result = await run_ragas_on_span(span)
        assert result["context_recall"]["score"] == 0.0
        assert "ground truth" in result["context_recall"]["reason"].lower()
