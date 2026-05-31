# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for the LiteLLM integration in the insights module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_warning_state():
    """Reset module-level deprecation warning flags between tests."""
    import sys

    if "litellm" not in sys.modules:
        sys.modules["litellm"] = MagicMock()
    import services.insights as mod

    mod._warned_model_format.clear()
    yield
    mod._warned_model_format.clear()


# ---------------------------------------------------------------------------
# _normalize_model_id tests
# ---------------------------------------------------------------------------


class TestNormalizeModelId:
    """Test legacy model ID normalization to LiteLLM format."""

    def _normalize(self, model: str) -> str:
        """Import and call _normalize_model_id."""
        from services.insights import _normalize_model_id

        return _normalize_model_id(model)

    def test_already_prefixed_anthropic(self):
        """Model with provider prefix passes through unchanged."""
        assert self._normalize("anthropic/claude-sonnet-4-20250514") == "anthropic/claude-sonnet-4-20250514"

    def test_already_prefixed_bedrock(self):
        """Bedrock-prefixed model passes through unchanged."""
        assert self._normalize("bedrock/us.anthropic.claude-opus-4-6-v1") == "bedrock/us.anthropic.claude-opus-4-6-v1"

    def test_already_prefixed_openai(self):
        """OpenAI-prefixed model passes through unchanged."""
        assert self._normalize("openai/gpt-4o") == "openai/gpt-4o"

    def test_already_prefixed_ollama(self):
        """Ollama-prefixed model passes through unchanged."""
        assert self._normalize("ollama/llama3") == "ollama/llama3"

    def test_bare_bedrock_anthropic_us(self):
        """Bare Bedrock Anthropic model (us region) gets bedrock/ prefix."""
        assert self._normalize("us.anthropic.claude-opus-4-6-v1") == "bedrock/us.anthropic.claude-opus-4-6-v1"

    def test_bare_bedrock_anthropic_eu(self):
        """Bare Bedrock Anthropic model (eu region) gets bedrock/ prefix."""
        assert self._normalize("eu.anthropic.claude-sonnet-4-6-v1") == "bedrock/eu.anthropic.claude-sonnet-4-6-v1"

    def test_bare_bedrock_anthropic_ap(self):
        """Bare Bedrock Anthropic model (ap region) gets bedrock/ prefix."""
        assert self._normalize("ap.anthropic.claude-sonnet-4-6-v1") == "bedrock/ap.anthropic.claude-sonnet-4-6-v1"

    def test_bare_bedrock_anthropic_haiku(self):
        """Bare Bedrock Haiku model gets bedrock/ prefix."""
        result = self._normalize("us.anthropic.claude-haiku-4-5-20251001-v1:0")
        assert result == "bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0"

    def test_bare_kimi_model(self):
        """Bare kimi model gets openai/ prefix."""
        assert self._normalize("kimi-v2") == "openai/kimi-v2"

    def test_bare_moonshot_model(self):
        """Bare moonshot model gets openai/ prefix."""
        assert self._normalize("moonshot-v1-8k") == "openai/moonshot-v1-8k"

    def test_bare_kimi_uppercase(self):
        """Case-insensitive kimi detection."""
        assert self._normalize("Kimi-v2") == "openai/Kimi-v2"

    def test_bare_unknown_model(self):
        """Unknown bare model passes through unchanged (user expected to use LiteLLM format)."""
        assert self._normalize("gpt-4o") == "gpt-4o"

    def test_empty_string(self):
        """Empty model string passes through."""
        assert self._normalize("") == ""


# ---------------------------------------------------------------------------
# _strip_json_fences tests
# ---------------------------------------------------------------------------


class TestStripJsonFences:
    """Test markdown fence stripping."""

    def _strip(self, text: str) -> str:
        from services.insights import _strip_json_fences

        return _strip_json_fences(text)

    def test_no_fences(self):
        """Plain JSON passes through."""
        assert self._strip('{"key": "value"}') == '{"key": "value"}'

    def test_json_fence(self):
        """Strips ```json fences."""
        text = '```json\n{"key": "value"}\n```'
        assert self._strip(text) == '{"key": "value"}'

    def test_generic_fence(self):
        """Strips generic ``` fences."""
        text = '```\n{"key": "value"}\n```'
        assert self._strip(text) == '{"key": "value"}'

    def test_text_before_fence(self):
        """Strips fences with leading text."""
        text = 'Here is the JSON:\n```json\n{"key": "value"}\n```\nDone.'
        assert self._strip(text) == '{"key": "value"}'


# ---------------------------------------------------------------------------
# _call_litellm tests
# ---------------------------------------------------------------------------


@pytest.fixture
def ds_settings():
    """Mock dynamic_settings.get to return empty strings by default."""
    settings = {}

    async def mock_get(key, default=None):
        return settings.get(key, default or "")

    return settings, mock_get


class TestCallLitellm:
    """Test _call_litellm function with mocked litellm."""

    @pytest.mark.asyncio
    async def test_success_json_response(self, ds_settings):
        """Successful call returns parsed JSON."""
        settings, mock_get = ds_settings
        settings["insights.api_key"] = "test-key"

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"sections": ["intro", "analysis"]}'

        with (
            patch("services.dynamic_settings.get", side_effect=mock_get),
            patch("litellm.acompletion", new_callable=AsyncMock, return_value=mock_response),
        ):
            from services.insights import _call_litellm

            result = await _call_litellm("test prompt", "anthropic/claude-sonnet-4-20250514")

        assert result == {"sections": ["intro", "analysis"]}

    @pytest.mark.asyncio
    async def test_success_with_json_fences(self, ds_settings):
        """Strips JSON fences from response before parsing."""
        settings, mock_get = ds_settings

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '```json\n{"key": "value"}\n```'

        with (
            patch("services.dynamic_settings.get", side_effect=mock_get),
            patch("litellm.acompletion", new_callable=AsyncMock, return_value=mock_response),
        ):
            from services.insights import _call_litellm

            result = await _call_litellm("test prompt", "openai/gpt-4o")

        assert result == {"key": "value"}

    @pytest.mark.asyncio
    async def test_empty_response_returns_empty_dict(self, ds_settings):
        """Empty content from model returns {}."""
        settings, mock_get = ds_settings

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = ""

        with (
            patch("services.dynamic_settings.get", side_effect=mock_get),
            patch("litellm.acompletion", new_callable=AsyncMock, return_value=mock_response),
        ):
            from services.insights import _call_litellm

            result = await _call_litellm("test prompt", "openai/gpt-4o")

        assert result == {}

    @pytest.mark.asyncio
    async def test_exception_returns_empty_dict(self, ds_settings):
        """LiteLLM exception returns {} without propagating."""
        settings, mock_get = ds_settings

        with (
            patch("services.dynamic_settings.get", side_effect=mock_get),
            patch("litellm.acompletion", new_callable=AsyncMock, side_effect=Exception("rate limited")),
        ):
            from services.insights import _call_litellm

            result = await _call_litellm("test prompt", "anthropic/claude-sonnet-4-20250514")

        assert result == {}

    @pytest.mark.asyncio
    async def test_json_parse_error_returns_empty_dict(self, ds_settings):
        """Invalid JSON in response returns {}."""
        settings, mock_get = ds_settings

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "not valid json at all"

        with (
            patch("services.dynamic_settings.get", side_effect=mock_get),
            patch("litellm.acompletion", new_callable=AsyncMock, return_value=mock_response),
        ):
            from services.insights import _call_litellm

            result = await _call_litellm("test prompt", "openai/gpt-4o")

        assert result == {}

    @pytest.mark.asyncio
    async def test_api_key_and_base_passed_to_litellm(self, ds_settings):
        """API key and base URL from settings are passed to litellm."""
        settings, mock_get = ds_settings
        settings["insights.api_key"] = "sk-ant-test123"
        settings["insights.api_base"] = "https://bedrock-runtime.us-east-1.amazonaws.com"

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"ok": true}'

        with (
            patch("services.dynamic_settings.get", side_effect=mock_get),
            patch("litellm.acompletion", new_callable=AsyncMock, return_value=mock_response) as mock_acompletion,
        ):
            from services.insights import _call_litellm

            await _call_litellm("test", "bedrock/us.anthropic.claude-opus-4-6-v1")

        call_kwargs = mock_acompletion.call_args.kwargs
        assert call_kwargs["api_key"] == "sk-ant-test123"
        assert call_kwargs["api_base"] == "https://bedrock-runtime.us-east-1.amazonaws.com"
        assert call_kwargs["model"] == "bedrock/us.anthropic.claude-opus-4-6-v1"

    @pytest.mark.asyncio
    async def test_no_api_key_omits_kwarg(self, ds_settings):
        """When api_key is empty, it's not passed to litellm (falls back to env vars)."""
        settings, mock_get = ds_settings

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"ok": true}'

        with (
            patch("services.dynamic_settings.get", side_effect=mock_get),
            patch("litellm.acompletion", new_callable=AsyncMock, return_value=mock_response) as mock_acompletion,
        ):
            from services.insights import _call_litellm

            await _call_litellm("test", "bedrock/us.anthropic.claude-opus-4-6-v1")

        call_kwargs = mock_acompletion.call_args.kwargs
        assert "api_key" not in call_kwargs
        assert "api_base" not in call_kwargs

    @pytest.mark.asyncio
    async def test_passes_correct_litellm_params(self, ds_settings):
        """Verifies num_retries, timeout, drop_params, response_format are passed."""
        settings, mock_get = ds_settings

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"ok": true}'

        with (
            patch("services.dynamic_settings.get", side_effect=mock_get),
            patch("litellm.acompletion", new_callable=AsyncMock, return_value=mock_response) as mock_acompletion,
        ):
            from services.insights import _call_litellm

            await _call_litellm("test prompt", "openai/gpt-4o", max_tokens=2048)

        call_kwargs = mock_acompletion.call_args.kwargs
        assert call_kwargs["num_retries"] == 2
        assert call_kwargs["timeout"] == 120
        assert call_kwargs["drop_params"] is True
        assert call_kwargs["response_format"] == {"type": "json_object"}
        assert call_kwargs["max_tokens"] == 2048
        assert call_kwargs["temperature"] == 0.1


# ---------------------------------------------------------------------------
# call_model tests
# ---------------------------------------------------------------------------


class TestCallModel:
    """Test the public call_model function."""

    @pytest.mark.asyncio
    async def test_empty_model_returns_empty_dict(self):
        """No model configured returns {}."""

        async def mock_get(key, default=None):
            return ""

        with patch("services.dynamic_settings.get", side_effect=mock_get):
            from services.insights import call_model

            result = await call_model("test prompt")

        assert result == {}

    @pytest.mark.asyncio
    async def test_model_override_takes_precedence(self):
        """model_override is used instead of dynamic setting."""

        async def mock_get(key, default=None):
            if key == "insights.model_sections":
                return "bedrock/default-model"
            return ""

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"ok": true}'

        with (
            patch("services.dynamic_settings.get", side_effect=mock_get),
            patch("litellm.acompletion", new_callable=AsyncMock, return_value=mock_response) as mock_acompletion,
        ):
            from services.insights import call_model

            await call_model("test", model_override="anthropic/claude-sonnet-4-20250514")

        call_kwargs = mock_acompletion.call_args.kwargs
        assert call_kwargs["model"] == "anthropic/claude-sonnet-4-20250514"

    @pytest.mark.asyncio
    async def test_normalizes_legacy_model_id(self):
        """Legacy bare model IDs are normalized before calling LiteLLM."""

        async def mock_get(key, default=None):
            if key == "insights.model_sections":
                return "us.anthropic.claude-opus-4-6-v1"
            return ""

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"ok": true}'

        with (
            patch("services.dynamic_settings.get", side_effect=mock_get),
            patch("litellm.acompletion", new_callable=AsyncMock, return_value=mock_response) as mock_acompletion,
        ):
            from services.insights import call_model

            await call_model("test")

        call_kwargs = mock_acompletion.call_args.kwargs
        assert call_kwargs["model"] == "bedrock/us.anthropic.claude-opus-4-6-v1"
