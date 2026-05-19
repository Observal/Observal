# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for SEC-021: secrets redacted before sending content to LLM providers."""

from unittest.mock import AsyncMock, MagicMock, patch


class TestLLMJudgeBackendRedaction:
    async def test_secret_in_trace_not_sent_to_llm(self):
        """LLMJudgeBackend.score must redact secrets via secrets_redactor before building the prompt."""
        from services.eval.eval_engine import LLMJudgeBackend

        captured: dict = {}

        async def _mock_call_model(prompt: str) -> dict:
            captured["prompt"] = prompt
            return {"score": 0.9, "reason": "ok"}

        template = {"prompt": "Trace: {trace}\nSpan: {span}", "id": "tpl-test", "name": "Test"}
        trace = {"tool_response": "Authorization: Bearer ghp_abc123def456ghi789jkl0123456789"}
        span = {"error": "DATABASE_URL=postgres://user:s3cr3t@db.example.com/prod"}

        with patch("services.eval.eval_engine._call_model", side_effect=_mock_call_model):
            await LLMJudgeBackend().score(template, trace, span)

        assert "ghp_abc123def456ghi789jkl0123456789" not in captured["prompt"]
        assert "s3cr3t" not in captured["prompt"]

    async def test_clean_trace_passes_through(self):
        """Content without secrets is passed through unchanged."""
        from services.eval.eval_engine import LLMJudgeBackend

        captured: dict = {}

        async def _mock_call_model(prompt: str) -> dict:
            captured["prompt"] = prompt
            return {"score": 0.8, "reason": "ok"}

        template = {"prompt": "Trace: {trace}\nSpan: {span}", "id": "tpl-test", "name": "Test"}
        trace = {"tool_name": "read_file", "status": "success"}
        span = {"latency_ms": 42}

        with patch("services.eval.eval_engine._call_model", side_effect=_mock_call_model):
            await LLMJudgeBackend().score(template, trace, span)

        assert "read_file" in captured["prompt"]
        assert "42" in captured["prompt"]


class TestRagasRedaction:
    """redact_secrets() is applied to all four RAGAS metric helpers."""

    async def _call_with_secret(self, fn, **kwargs) -> str:
        """Call a ragas helper with a mock model, return the captured prompt."""
        captured: dict = {}

        async def _mock(prompt: str) -> dict:
            captured["prompt"] = prompt
            return {"score": 0.5, "reason": "ok"}

        with patch("services.eval.ragas_eval._call_model", side_effect=_mock):
            await fn(**kwargs)

        return captured.get("prompt", "")

    async def test_faithfulness_redacts_secret(self):
        from services.eval.ragas_eval import _eval_faithfulness

        prompt = await self._call_with_secret(
            _eval_faithfulness,
            answer="The key is sk-ant-api03-abc123def456",
            context="Some context",
        )
        assert "sk-ant-api03-abc123def456" not in prompt

    async def test_answer_relevancy_redacts_secret(self):
        from services.eval.ragas_eval import _eval_answer_relevancy

        prompt = await self._call_with_secret(
            _eval_answer_relevancy,
            question="What is the API key?",
            answer="api_key=AKIAIOSFODNN7EXAMPLE",
        )
        assert "AKIAIOSFODNN7EXAMPLE" not in prompt

    async def test_context_precision_redacts_secret(self):
        from services.eval.ragas_eval import _eval_context_precision

        prompt = await self._call_with_secret(
            _eval_context_precision,
            question="How to connect?",
            chunks="Use postgres://admin:hunter2@db.host/prod",
        )
        assert "hunter2" not in prompt

    async def test_context_recall_redacts_secret(self):
        from services.eval.ragas_eval import _eval_context_recall

        prompt = await self._call_with_secret(
            _eval_context_recall,
            ground_truth="Use the secret token",
            context="token=ghp_realtoken123456789012345678901234567890",
        )
        assert "ghp_realtoken123456789012345678901234567890" not in prompt


class TestInsightsBatchRedaction:
    """redact_secrets() is applied to system_prompt_excerpt in _load_agent_config."""

    async def test_system_prompt_secret_redacted(self):
        from ee.observal_insights.batch import _load_agent_config

        mock_version = MagicMock()
        mock_version.version = "1.0.0"
        mock_version.model_name = "claude-3"
        mock_version.supported_ides = []
        mock_version.prompt = "System key: sk-proj-abc123def456ghi789jkl0123456789xyz"
        mock_version.components = []
        mock_version.external_mcps = []
        mock_version.model_config_json = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_version)

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        config = await _load_agent_config(mock_db, "agent-id-123")

        assert config is not None
        assert "sk-proj-abc123def456ghi789jkl0123456789xyz" not in config["system_prompt_excerpt"]
        assert "**REDACTED**" in config["system_prompt_excerpt"]
