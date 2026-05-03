"""8+1 parallel section prompts for Agent Insights V2 narrative generation.

Produces structured, actionable report sections modeled after professional
developer experience reports — clear narratives with evidence, not bullet slop.
"""

from __future__ import annotations

import asyncio
import json

import structlog

from config import settings
from services.eval.eval_service import call_eval_model

logger = structlog.get_logger(__name__)


def _get_section_model() -> str | None:
    """Get the model for detailed section prompts (Opus by default)."""
    return getattr(settings, "INSIGHT_MODEL_SECTIONS", "") or None


def _get_synthesis_model() -> str | None:
    """Get the model for synthesis/aggregation (Sonnet by default)."""
    return getattr(settings, "INSIGHT_MODEL_SYNTHESIS", "") or None

# ──────────────────────────────────────────────────────────────────────────────
# Section prompt templates — designed to produce structured JSON output
# ──────────────────────────────────────────────────────────────────────────────

SECTION_PROMPTS: dict[str, str] = {
    "usage_patterns": """You are producing ONE section of a developer-facing insight report for an AI coding agent. Write for the agent's admin/owner — someone who wants to understand how their team uses this agent.

{data_block}

Produce a JSON object with this EXACT structure:
{{
  "usage_patterns": {{
    "narrative": "<2-3 paragraph narrative describing HOW the agent is used. Write in 2nd person ('your agent', 'your users'). Be specific: name numbers, tools, and patterns. Don't be generic. Reference the actual metrics. Example: 'Your agent handled 42 sessions over 14 days, averaging 6 minutes per session. Bash dominates tool usage at 64% of all calls, suggesting users primarily delegate command execution rather than file editing.'",
    "top_tasks": [
      {{"name": "<task type>", "count": <number>, "description": "<one sentence>"}}
    ],
    "tool_distribution": [
      {{"tool": "<name>", "calls": <number>, "error_rate": <percent as float>}}
    ],
    "session_profile": {{
      "avg_duration_minutes": <number>,
      "avg_tool_calls": <number>,
      "avg_prompts": <number>,
      "session_type": "<most common: single_task | multi_task | iterative_refinement | exploration>"
    }}
  }}
}}

Base everything on the actual data. Do not invent numbers. If data is limited, say so in the narrative.""",

    "what_works": """You are producing ONE section of a developer-facing insight report for an AI coding agent. This section highlights genuine strengths.

{data_block}

Produce a JSON object with this EXACT structure:
{{
  "what_works": {{
    "intro": "<1 sentence summarizing overall agent effectiveness>",
    "strengths": [
      {{
        "title": "<short title, 3-5 words>",
        "description": "<2-3 sentences explaining WHY this is a strength, with specific evidence from the metrics. Example: 'Agent and Write tools have 0% error rate across 4 invocations, providing reliable file operations without retry loops.'>"
      }}
    ]
  }}
}}

Rules:
- Maximum 4 strengths
- Each must be backed by a specific metric (name the number)
- Don't stretch thin data — if you only have 1 session, you can only have 1-2 strengths
- Focus on what would matter to the agent owner (reliability, cost efficiency, user satisfaction)""",

    "friction_analysis": """You are producing ONE section of a developer-facing insight report for an AI coding agent. This section identifies WHERE things go wrong.

{data_block}

Produce a JSON object with this EXACT structure:
{{
  "friction_analysis": {{
    "intro": "<1 sentence summarizing the primary friction pattern>",
    "categories": [
      {{
        "title": "<friction category name>",
        "severity": "<high | medium | low>",
        "description": "<1-2 sentences explaining the problem>",
        "evidence": "<specific metrics: e.g. 'Bash tool: 1 command_failed error in 7 invocations (14% error rate)'>",
        "impact": "<what this costs users: time, retries, abandoned sessions>"
      }}
    ]
  }}
}}

Rules:
- Rank by severity (high first)
- Maximum 4 categories
- Each MUST include a specific metric as evidence
- Focus on patterns that actually hurt users, not one-off errors in tiny samples
- If error counts are very low (1-2 total), note that statistical confidence is low""",

    "suggestions": """You are producing ONE section of a developer-facing insight report for an AI coding agent. This section provides SPECIFIC, IMPLEMENTABLE suggestions.

{data_block}

Produce a JSON object with this EXACT structure:
{{
  "suggestions": {{
    "intro": "<1 sentence framing these as next steps>",
    "items": [
      {{
        "title": "<short action title>",
        "action": "<Exactly what to do — specific enough that someone could implement it right now. Not vague. Example: 'Add to your agent system prompt: Before running any Bash command, verify the target file exists with a Read call first.'>",
        "why": "<1 sentence explaining which metric this addresses and expected impact>",
        "priority": "<high | medium | low>"
      }}
    ]
  }}
}}

Rules:
- Maximum 5 suggestions, minimum 2
- Each must address a SPECIFIC metric or pattern from the data
- Prioritize by expected impact
- HIGH priority: addresses >10% error rate or >20% cost waste
- MEDIUM priority: addresses known friction pattern
- LOW priority: optimization opportunity
- NEVER suggest "improve reliability" — say EXACTLY what to change
- Suggestions should be things the agent OWNER can do (system prompt changes, tool config, workflow adjustments)""",

    "token_optimization": """You are producing ONE section of a developer-facing insight report for an AI coding agent. Focus on cost and token efficiency.

{data_block}

Produce a JSON object with this EXACT structure:
{{
  "token_optimization": {{
    "summary": "<1-2 sentences: overall cost assessment — is this agent expensive, cheap, efficient?>",
    "metrics": {{
      "total_cost_usd": <number>,
      "cost_per_session": <number>,
      "cache_efficiency_pct": <number 0-100>,
      "most_expensive_model": "<model name or null>"
    }},
    "opportunities": [
      {{
        "title": "<opportunity name>",
        "description": "<what to change>",
        "estimated_savings": "<e.g. '~30% reduction in per-session cost'>"
      }}
    ]
  }}
}}

Rules:
- Be honest: if costs are already low, say so
- If cache efficiency is >70%, acknowledge it's good
- Only suggest model downgrades if there's clear evidence simpler tasks don't need the expensive model
- Maximum 3 opportunities""",

    "user_experience": """You are producing ONE section of a developer-facing insight report for an AI coding agent. Focus on the end-user experience.

{data_block}

Produce a JSON object with this EXACT structure:
{{
  "user_experience": {{
    "narrative": "<2-3 sentences describing the overall user experience. Are users satisfied? Do they interrupt frequently? Do sessions complete successfully? Reference specific metrics.>",
    "signals": [
      {{
        "signal": "<what was observed>",
        "interpretation": "<what it means for user satisfaction>"
      }}
    ],
    "satisfaction_indicators": {{
      "completion_rate": "<percentage or 'N/A'>",
      "interruption_rate": "<percentage or 'N/A'>",
      "retry_patterns": "<description or 'none observed'>"
    }}
  }}
}}

Rules:
- Maximum 4 signals
- Base satisfaction assessment on actual data (stop reasons, error rates, session completion)
- Don't assume user satisfaction from limited data — say confidence is low if sample is small""",

    "regression_detection": """You are comparing current and previous period metrics for an AI coding agent.

{data_block}

{previous_data_block}

Produce a JSON object with this EXACT structure:
{{
  "regression_detection": {{
    "has_previous_data": <true|false>,
    "summary": "<1-2 sentences: what changed between periods>",
    "changes": [
      {{
        "metric": "<metric name>",
        "direction": "<improved | degraded | stable>",
        "previous_value": "<formatted value>",
        "current_value": "<formatted value>",
        "magnitude_pct": <number>,
        "significance": "<meaningful | minor | noise>"
      }}
    ]
  }}
}}

If no previous period data is available, return:
{{"regression_detection": {{"has_previous_data": false, "summary": "No previous period data available for comparison.", "changes": []}}}}""",

    "fun_ending": """You are producing the final section of a developer-facing insight report for an AI coding agent. Find ONE genuinely interesting or memorable observation from the data.

{data_block}

Produce a JSON object with this EXACT structure:
{{
  "fun_ending": {{
    "headline": "<punchy 5-10 word headline>",
    "detail": "<2-3 sentence observation that's genuinely interesting, not forced. Could be: an unusual stat, a contrast, a notable achievement, or something that characterizes this agent's personality. Keep it light.>"
  }}
}}

Rules:
- Don't force humor if there's nothing funny
- Focus on what's genuinely notable or surprising in the data
- Keep it SHORT (under 50 words for the detail)""",
}

SYNTHESIS_PROMPT = """You have analysis sections about an AI coding agent's recent performance. Write a concise executive summary.

## Section Outputs
{sections_json}

Write a JSON response with this EXACT structure:
{{
  "at_a_glance": {{
    "whats_working": "<1 sentence: the primary strength or positive pattern>",
    "whats_hindering": "<1 sentence: the primary friction or concern>",
    "quick_win": "<1 sentence: the single most impactful quick improvement>",
    "health": "<healthy | mixed | concerning>"
  }}
}}

Rules:
- Each field must be ONE sentence, under 30 words
- Be specific — name tools, error rates, or patterns by name
- "healthy" = error rates low, costs reasonable, users satisfied
- "mixed" = some friction but generally functional
- "concerning" = high error rates, cost issues, or user dissatisfaction"""


# ──────────────────────────────────────────────────────────────────────────────
# Execution
# ──────────────────────────────────────────────────────────────────────────────


async def _call_section(section_name: str, prompt: str, model: str | None = None) -> tuple[str, dict]:
    """Call the eval model for a single section, return (name, result)."""
    try:
        result = await call_eval_model(prompt, model_override=model, max_tokens=8192)
        if result and isinstance(result, dict):
            return section_name, result
        logger.warning("section_empty_response", section=section_name)
        return section_name, {}
    except Exception as e:
        logger.error("section_call_failed", section=section_name, error=str(e))
        return section_name, {}


async def generate_sections(
    data_block: str,
    previous_report: dict | None = None,
) -> dict:
    """Run 8 parallel section prompts + 1 synthesis, return combined narrative.

    Args:
        data_block: Formatted string with all metrics, facets, and session data.
        previous_report: Previous report's aggregated_data for regression comparison.

    Returns:
        Dict with structured section outputs for each narrative section.
    """
    # Build previous data block for regression section
    previous_data_block = ""
    if previous_report:
        previous_data_block = f"## Previous Period Metrics\n{json.dumps(previous_report, indent=2, default=str)}"
    else:
        previous_data_block = "## Previous Period Metrics\nNo previous period data available."

    # Resolve models for this pipeline
    section_model = _get_section_model()
    synthesis_model = _get_synthesis_model()

    logger.info(
        "insight_sections_starting",
        section_model=section_model or "default",
        synthesis_model=synthesis_model or "default",
    )

    # Build prompts for all 8 sections
    section_prompts: dict[str, str] = {}
    for name, template in SECTION_PROMPTS.items():
        if name == "regression_detection":
            section_prompts[name] = template.format(
                data_block=data_block,
                previous_data_block=previous_data_block,
            )
        else:
            section_prompts[name] = template.format(data_block=data_block)

    # Run all 8 in parallel using the section model (Opus)
    tasks = [_call_section(name, prompt, model=section_model) for name, prompt in section_prompts.items()]
    results = await asyncio.gather(*tasks)

    # Collect results
    narrative: dict = {}
    for name, result in results:
        # Extract the section content from the JSON response
        if name in result:
            narrative[name] = result[name]
        elif result:
            # Model may have returned with a different key structure
            first_value = next(iter(result.values()), None)
            narrative[name] = first_value
        else:
            narrative[name] = {} if name != "fun_ending" else {"headline": "", "detail": ""}

    # Run synthesis with all section outputs using synthesis model (Sonnet)
    synthesis_prompt = SYNTHESIS_PROMPT.format(
        sections_json=json.dumps(narrative, indent=2, default=str)
    )
    try:
        synthesis_result = await call_eval_model(
            synthesis_prompt, model_override=synthesis_model, max_tokens=4096
        )
        if synthesis_result and "at_a_glance" in synthesis_result:
            narrative["at_a_glance"] = synthesis_result["at_a_glance"]
        elif synthesis_result:
            narrative["at_a_glance"] = next(iter(synthesis_result.values()), {})
        else:
            narrative["at_a_glance"] = {}
    except Exception as e:
        logger.error("synthesis_failed", error=str(e))
        narrative["at_a_glance"] = {}

    return narrative
