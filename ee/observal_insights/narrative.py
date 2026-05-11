# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""LLM narrative generation for Agent Insights reports (V1 fallback)."""

import json

import structlog

from ._deps import get_call_model, get_settings

logger = structlog.get_logger(__name__)

INSIGHT_PROMPT = """You are an AI agent performance analyst. Given the following deterministic metrics about an AI coding agent's performance over a time window, generate an actionable insight report.

## Agent: {agent_name}
## Period: {period_start} to {period_end}
## Sessions Analyzed: {session_count}

## Raw Metrics

### Session Overview
{overview_json}

### Token Usage (input + output + cache)
{tokens_json}

### Cost Analysis (USD)
{cost_json}

### Session Duration
{duration_json}

### Error Rates
{errors_json}

### Tool Error Categories
{tool_errors_json}

### Interruptions & Stop Reasons
{interruptions_json}

### Top Tools (by invocation count)
{tools_json}

### Per-Session Breakdown
{sessions_json}

## Instructions

Analyze these metrics and produce a structured JSON report with exactly 4 sections:

1. "at_a_glance": A 2-3 sentence executive summary. State the most important finding, whether things look healthy or concerning, and one specific number that stands out. Include cost if notable.

2. "usage_patterns": 3-5 bullet points about how the agent is being used. Which tools dominate? What do session durations suggest? How many tokens are consumed? Comment on cache efficiency and cost patterns.

3. "friction_analysis": 3-5 bullet points identifying where users encounter problems. Use the error categories (command_failed, edit_failed, user_rejected, etc.) to be specific. Note any high interrupt rates. Rank by severity.

4. "suggestions": 3-5 concrete, actionable recommendations the agent author should implement. Be specific (e.g., "Add retry logic for tool X which fails 15% of the time", "Improve cache utilization — current efficiency is only 23%") not vague ("improve reliability"). Include cost optimization suggestions if relevant.

Respond ONLY with valid JSON matching this exact structure:
{{"at_a_glance": "<string>", "usage_patterns": ["<bullet>", ...], "friction_analysis": ["<bullet>", ...], "suggestions": ["<suggestion>", ...]}}"""


async def generate_narrative(
    agent_name: str,
    metrics: dict,
    period_start: str,
    period_end: str,
    session_count: int,
) -> dict | None:
    """Generate narrative sections from aggregated metrics via LLM.

    Returns a dict with keys: at_a_glance, usage_patterns, friction_analysis, suggestions.
    Returns None if no eval model is configured or on failure.
    """
    settings = get_settings()
    eval_model = getattr(settings, "EVAL_MODEL_NAME", "") or ""
    if not eval_model:
        logger.info("insight_narrative_skipped", reason="no eval model configured")
        return None

    call_model = get_call_model()

    prompt = INSIGHT_PROMPT.format(
        agent_name=agent_name,
        period_start=period_start,
        period_end=period_end,
        session_count=session_count,
        overview_json=json.dumps(metrics.get("overview", {}), indent=2),
        tokens_json=json.dumps(metrics.get("tokens", {}), indent=2),
        cost_json=json.dumps(metrics.get("cost", {}), indent=2),
        duration_json=json.dumps(metrics.get("duration", {}), indent=2),
        errors_json=json.dumps(metrics.get("errors", {}), indent=2),
        tool_errors_json=json.dumps(metrics.get("tool_errors", {}), indent=2),
        interruptions_json=json.dumps(metrics.get("interruptions", {}), indent=2),
        tools_json=json.dumps(metrics.get("tools", [])[:10], indent=2),
        sessions_json=json.dumps(metrics.get("sessions", [])[:5], indent=2),
    )

    try:
        result = await call_model(prompt)
        if not result:
            logger.warning("insight_narrative_empty_response")
            return None

        # Validate expected keys
        expected_keys = {"at_a_glance", "usage_patterns", "friction_analysis", "suggestions"}
        if not expected_keys.issubset(result.keys()):
            logger.warning("insight_narrative_missing_keys", keys=list(result.keys()))
            return result  # Return partial result anyway

        return result
    except Exception as e:
        logger.error("insight_narrative_failed", error=str(e))
        return None
