# SPDX-FileCopyrightText: 2026 Subramania Raja <dhanpraja231@gmail.com>
# SPDX-FileCopyrightText: 2026 Hemalatha Madeswaran <hemalathamadeswaran@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Insights plugin loader.

Delegates to the enterprise insights engine (ee/observal_insights/) when
a valid OBSERVAL_LICENSE_KEY with the "insights" feature is present.

Feature availability is derived entirely from the license — no env var needed.
"""

import json

import httpx
import structlog

from config import settings

logger = structlog.get_logger(__name__)

_generate = None
_render = None
_run_single_report = None
_discover_and_queue = None

# Derive INSIGHTS_AVAILABLE purely from license
INSIGHTS_AVAILABLE: bool = False

try:
    from ee.license import is_feature_licensed

    if is_feature_licensed("insights"):
        from ee.observal_insights import generate_report_content as _generate  # type: ignore[assignment]
        from ee.observal_insights import render_report_html as _render  # type: ignore[assignment]
        from ee.observal_insights.batch import (
            discover_and_queue_reports as _discover_and_queue,  # type: ignore[assignment]  # noqa: F401
        )
        from ee.observal_insights.batch import (
            run_single_report as _run_single_report,  # type: ignore[assignment]  # noqa: F401
        )

        INSIGHTS_AVAILABLE = True
except (ImportError, RuntimeError):
    # ee/ not present or license invalid — degrade gracefully
    pass


def _not_available():
    raise RuntimeError(
        "Insights requires a valid Observal Enterprise license. Set OBSERVAL_LICENSE_KEY or contact team@observal.dev."
    )


async def generate_report_content(*args, **kwargs):
    if not INSIGHTS_AVAILABLE or _generate is None:
        _not_available()
    return await _generate(*args, **kwargs)


def render_report_html(*args, **kwargs):
    if not INSIGHTS_AVAILABLE or _render is None:
        _not_available()
    return _render(*args, **kwargs)


# ---------------------------------------------------------------------------
# Generic LLM caller (Bedrock / OpenAI-compatible / Moonshot)
# ---------------------------------------------------------------------------


def _build_openai_body(model: str, prompt: str, provider: str = "", extra: dict | None = None) -> dict:
    body: dict = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.1}
    if provider == "moonshot":
        body["thinking"] = {"type": "disabled"}
        body["temperature"] = 0.6
    if extra:
        body.update(extra)
    return body


def _openai_url_and_headers(provider: str = "", url_override: str = "", key_override: str = "") -> tuple[str, dict]:
    default_url = "https://api.moonshot.ai/v1" if provider == "moonshot" else "http://localhost:11434/v1"
    url = url_override or default_url
    key = key_override or ""
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return url, headers


async def _call_bedrock(prompt: str, model_id: str, max_tokens: int = 16384) -> dict:
    """Call AWS Bedrock Converse API."""
    import asyncio

    import services.dynamic_settings as ds

    aws_region = await ds.get("insights.aws_region")
    aws_access_key = await ds.get("insights.aws_access_key_id")
    aws_secret_key = await ds.get("insights.aws_secret_access_key")
    aws_session_token = await ds.get("insights.aws_session_token")

    def _sync_call():
        import boto3
        from botocore.config import Config as _BotoConfig

        client_kwargs: dict = {"region_name": aws_region or "us-east-1"}
        if aws_access_key and aws_secret_key:
            client_kwargs["aws_access_key_id"] = aws_access_key
            client_kwargs["aws_secret_access_key"] = aws_secret_key
            if aws_session_token:
                client_kwargs["aws_session_token"] = aws_session_token

        client = boto3.client(
            "bedrock-runtime",
            config=_BotoConfig(read_timeout=300, retries={"max_attempts": 2}),
            **client_kwargs,
        )
        response = client.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"temperature": 0.1, "maxTokens": max_tokens},
        )
        text = response["output"]["message"]["content"][0]["text"]
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        return json.loads(text.strip())

    try:
        return await asyncio.get_event_loop().run_in_executor(None, _sync_call)
    except Exception as e:
        error_str = str(e)
        if "UnrecognizedClientException" in error_str or "security token" in error_str:
            raise RuntimeError(f"AWS credentials invalid: {error_str}") from e
        if "AccessDeniedException" in error_str:
            raise RuntimeError(f"AWS access denied for model '{model_id}': {error_str}") from e
        if "ModelNotReadyException" in error_str or "not found" in error_str.lower():
            raise RuntimeError(f"Model '{model_id}' not available in region '{aws_region}': {error_str}") from e
        if "ExpiredTokenException" in error_str:
            raise RuntimeError(f"AWS credentials expired: {error_str}") from e
        # JSON parse errors (truncated output) are non-fatal, return empty
        if "JSONDecodeError" in type(e).__name__ or "Unterminated string" in error_str:
            logger.warning("bedrock_truncated_response", error=error_str, model=model_id)
            return {}
        logger.error("bedrock_call_failed", error=error_str, model=model_id)
        raise RuntimeError(f"Bedrock call failed: {error_str}") from e


async def _call_openai_compatible(prompt: str, model: str, provider: str = "") -> dict:
    """Call an OpenAI-compatible API."""
    import services.dynamic_settings as ds

    model_url = await ds.get("insights.model_url")
    model_key = await ds.get("insights.model_api_key")
    url, headers = _openai_url_and_headers(provider, url_override=model_url, key_override=model_key)
    body = _build_openai_body(model, prompt, provider, extra={"response_format": {"type": "json_object"}})

    async with httpx.AsyncClient(timeout=120) as client:
        try:
            r = await client.post(f"{url}/chat/completions", headers=headers, json=body)
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            return json.loads(content)
        except Exception as e:
            logger.error("llm_call_failed", error=str(e))
            return {}


async def call_model(prompt: str, model_override: str | None = None, max_tokens: int = 16384) -> dict:
    """Call the configured LLM for insights generation.

    Provider is auto-detected from the model ID:
    - Contains 'anthropic' -> Bedrock
    - Contains 'kimi' -> Moonshot (OpenAI-compatible)
    - Otherwise -> generic OpenAI-compatible

    Args:
        prompt: The prompt to send to the model.
        model_override: Optional model ID to use instead of the default.
        max_tokens: Maximum output tokens (default 16384).
    """
    import services.dynamic_settings as ds

    # Use override, or fall back to sections model as the default
    model = model_override or await ds.get("insights.model_sections")

    if not model:
        return {}

    # Auto-detect provider from model ID
    if "anthropic" in model:
        return await _call_bedrock(prompt, model, max_tokens=max_tokens)
    if "kimi" in model.lower():
        return await _call_openai_compatible(prompt, model, provider="moonshot")
    return await _call_openai_compatible(prompt, model)


# ---------------------------------------------------------------------------
# Insights engine configuration
# ---------------------------------------------------------------------------


def configure_insights():
    """Wire up dependencies from the host app into the insights package.

    Called once at server startup. No-op if not licensed/available.
    """
    if not INSIGHTS_AVAILABLE:
        return

    from database import async_session
    from ee.observal_insights import configure
    from models.insight_meta_cache import InsightMetaCache
    from models.insight_session_facets import InsightSessionFacets
    from models.insight_session_meta import InsightSessionMeta
    from services.clickhouse import _query

    configure(
        settings=settings,
        query_fn=_query,
        call_model_fn=call_model,
        db_session_factory=async_session,
        meta_model=InsightSessionMeta,
        facets_model=InsightSessionFacets,
        meta_cache_model=InsightMetaCache,
    )


def licensed_features() -> list[str]:
    """Return licensed feature list via the gate — never import ee/ directly."""
    if not INSIGHTS_AVAILABLE:
        return []
    try:
        from ee.license import licensed_features as _lf

        return _lf()
    except (ImportError, RuntimeError):
        return []
