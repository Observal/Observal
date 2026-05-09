"""8+1 parallel section prompts for Agent Insights V3 narrative generation.

Produces structured, actionable report sections modeled after professional
developer experience reports — clear narratives with evidence, not bullet slop.

V3 changes:
- Replaced `token_optimization` with IDE-aware `usage_cost_analysis`
- Replaced `user_experience` with project-centric `what_they_work_on`
- Enhanced `suggestions` with fix_type field
- Enhanced `regression_detection` with likely_cause field
- Enhanced `at_a_glance` synthesis with ambitious_workflows field
"""

from __future__ import annotations

import asyncio
import json

import structlog

from ._deps import get_call_model, get_settings

logger = structlog.get_logger(__name__)


def _get_section_model() -> str | None:
    """Get the model for detailed section prompts (Opus by default)."""
    settings = get_settings()
    return getattr(settings, "INSIGHT_MODEL_SECTIONS", "") or None


def _get_synthesis_model() -> str | None:
    """Get the model for synthesis/aggregation (Sonnet by default)."""
    settings = get_settings()
    return getattr(settings, "INSIGHT_MODEL_SYNTHESIS", "") or None


# ──────────────────────────────────────────────────────────────────────────────
# Section prompt templates — designed to produce structured JSON output
# ──────────────────────────────────────────────────────────────────────────────

SECTION_PREAMBLE = """You are writing part of a developer insights report — like Claude Insights, but for AI coding agents.

Your reader is an engineering manager or team lead who wants to understand: Is this agent helping my team? Where? How could it be better?

Writing style:
- DIRECT and SPECIFIC. Every sentence must reference actual data or a concrete observation.
- CONCISE. Scale your output to the data: 1-3 sessions = brief (1-3 sentences per field). 10+ sessions = richer analysis.
- HONEST. If the agent failed tasks, couldn't follow instructions, or left work incomplete — say so clearly. Don't soften real problems.
- INSIGHTFUL. Surface patterns the reader wouldn't notice from raw numbers alone. Connect dots between metrics.
- NO FILLER. Never pad with "insufficient data" hedging, generic observations, or restating what metrics already show.
- BALANCED. Praise genuine strengths, call out real problems. But don't manufacture positives to balance negatives — if nothing worked well, say so.

A completeness score below 0.9 means the agent didn't finish the job. Repeated user instructions mean the agent failed to listen. These are real problems, not footnotes.

"""

SECTION_PROMPTS: dict[str, str] = {
    "what_they_work_on": """You are producing ONE section of a developer-facing insight report for an AI coding agent. This section shows WHAT the agent is used for.

{data_block}

Produce a JSON object with this EXACT structure:
{{
  "what_they_work_on": {{
    "areas": [
      {{
        "name": "<area name, e.g. 'Backend API development'>",
        "sessions": <number>,
        "description": "<one sentence describing the work>"
      }}
    ]
  }}
}}

Rules:
- Maximum 6 areas
- Derive areas from goal_categories in the facets data AND from file paths/tools used
- Each area must have a real session count
- Group related goals into logical work areas
- Order by session count descending""",
    "usage_patterns": """You are producing ONE section of a developer-facing insight report for an AI coding agent. Write for the agent's admin/owner.

{data_block}

Produce a JSON object with this EXACT structure:
{{
  "usage_patterns": {{
    "narrative": "<1-3 sentences describing HOW the agent is used. Scale length to data volume — 1 session = 1 sentence, 10+ sessions = 2-3 sentences. Be factual, not flowery.>",
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
      "session_type": "<most common type>"
    }}
  }}
}}

Rules:
- Base everything on actual data, don't invent numbers
- Top tools by invocation count (max 10)
- Session type from facets data if available
- With fewer than 5 sessions, keep the narrative to 1-2 sentences of pure facts
- Do NOT speculate about patterns from insufficient data""",
    "what_works": """You are producing ONE section of a developer-facing insight report for an AI coding agent. This section highlights genuine strengths.

{data_block}

Produce a JSON object with this EXACT structure:
{{
  "what_works": {{
    "intro": "<1 sentence summarizing where the agent delivers value>",
    "strengths": [
      {{
        "title": "<short title, 3-5 words>",
        "description": "<1-2 sentences with specific evidence from metrics>"
      }}
    ]
  }}
}}

Rules:
- Maximum 4 strengths, but an empty array is valid if nothing genuinely worked well
- Each MUST cite a specific metric or observation
- A strength must represent actual value delivered to users, not just technical baseline behavior
- "Zero crashes" or "no errors" are only strengths if the agent also completed its tasks successfully
- Focus on: tasks completed successfully, time saved, effective tool usage, good cost efficiency on productive work
- If sessions ended incomplete or users had to repeat themselves, the bar for "strength" is higher""",
    "friction_analysis": """You are producing ONE section of a developer-facing insight report for an AI coding agent. This section identifies problems and their impact.

{data_block}

Produce a JSON object with this EXACT structure:
{{
  "friction_analysis": {{
    "intro": "<1 sentence summarizing the primary problem>",
    "categories": [
      {{
        "title": "<friction category name>",
        "severity": "<high | medium | low>",
        "description": "<1-2 sentences explaining the problem>",
        "evidence": "<specific metrics as evidence>",
        "impact": "<what this costs users in concrete terms>"
      }}
    ]
  }}
}}

Rules:
- Rank by severity (high first)
- Maximum 4 categories, empty array is valid if nothing went wrong
- Each MUST include specific metrics as evidence
- Severity guide:
  - HIGH: agent failed to complete tasks, users had to repeat instructions, or sessions ended without resolving the request
  - MEDIUM: tool errors, slow responses, or inefficient patterns that didn't block completion
  - LOW: minor optimization opportunities
- Be direct about failures. "The agent could not complete the requested task" is clearer than "task completion was suboptimal"
- If no significant friction exists, return an empty categories array with intro: 'No significant friction detected in this period.'""",
    "suggestions": """You are producing ONE section of a developer-facing insight report for an AI coding agent. Provide SPECIFIC, IMPLEMENTABLE suggestions.

{data_block}

Produce a JSON object with this EXACT structure:
{{
  "suggestions": {{
    "intro": "<1 sentence framing the suggestions based on session count and period>",
    "items": [
      {{
        "title": "<short action title>",
        "action": "<Exactly what to do — specific enough to implement right now. For system_prompt_addition, include the exact text to add.>",
        "why": "<which metric this addresses and expected impact>",
        "priority": "<high | medium | low>",
        "fix_type": "<system_prompt_addition | tool_configuration | workflow_change | agent_upgrade | context_expansion | mcp_addition | mcp_removal | skill_addition | skill_removal>",
        "expected_impact": "<e.g. 'Reduce wrong_file_or_location friction by ~60%'>",
        "confidence": "<high | medium | low>"
      }}
    ]
  }}
}}

Rules:
- Maximum 5 suggestions, minimum 2
- Each must address a SPECIFIC metric or pattern
- fix_type categories:
  - system_prompt_addition: Add text to agent system prompt
  - tool_configuration: Change tool settings or permissions
  - workflow_change: Suggest different usage pattern to users
  - agent_upgrade: Model or capability upgrade needed
  - context_expansion: Need more context in system prompt
  - mcp_addition: Suggest adding an MCP server the agent lacks
  - mcp_removal: Suggest removing an MCP server that's never used or causing errors
  - skill_addition: Suggest adding a skill based on user request patterns
  - skill_removal: Suggest removing a skill that's never triggered
- HIGH priority: addresses >10% error rate or >20% cost waste
- MEDIUM: addresses known friction pattern
- LOW: optimization opportunity
- NEVER suggest vague improvements — say EXACTLY what to change
- For system_prompt_addition: include the exact prompt text in quotes

COMPONENT-AWARE ANALYSIS:
If "Agent Configuration" is present in the data, use it to ground your suggestions:
- If an MCP is configured but NEVER called in any session, suggest removing it (reduces startup cost and confusion)
- If users repeatedly attempt tasks the agent can't do, check whether an MCP or skill could enable it
- If the system prompt is missing guidance for common user requests (visible in facets), suggest specific prompt additions
- If a configured skill is never triggered, suggest removing it or improving its trigger conditions
- Compare configured MCPs against actual tool usage — mismatches indicate configuration drift
- If model_config has suboptimal settings given the usage pattern (e.g. low max_tokens but users need long outputs), flag it

REGISTRY COMPONENT RECOMMENDATIONS:
If "Available Components" section is present in the data:
- Cross-reference user behavior with available registry components
- If users do tasks that a registry MCP/skill could automate, suggest adding it
- For registry components, include the CLI command: `observal agent add mcp <id>` or `observal agent add skill <id>`
- For removal suggestions: edit `observal-agent.yaml` to remove the entry, then `observal agent publish`

EXTERNAL MCP RECOMMENDATIONS:
If the agent's usage patterns would benefit from a well-known MCP server NOT in the registry, suggest adding it as an external MCP. Common external MCPs to consider:
- GitHub (@modelcontextprotocol/server-github) — for PR/issue automation
- PostgreSQL (@modelcontextprotocol/server-postgres) — for database access
- Slack (@modelcontextprotocol/server-slack) — for team communication
- Memory (@modelcontextprotocol/server-memory) — for cross-session context persistence
- Sequential Thinking (@modelcontextprotocol/server-sequential-thinking) — for complex reasoning

For external MCPs, provide the YAML snippet to add under `external_mcps:` in `observal-agent.yaml`, then run `observal agent publish`.""",
    "usage_cost_analysis": """You are producing ONE section of a developer-facing insight report for an AI coding agent. Focus on cost efficiency.

{data_block}

Produce a JSON object with this EXACT structure:
{{
  "usage_cost_analysis": {{
    "summary": "<1-2 sentences: overall cost assessment>",
    "metrics": {{
      "total_cost_usd": <number or null if Kiro credits-only>,
      "cost_per_session": <number or null>,
      "cost_per_prompt": <number or null>,
      "cache_efficiency_pct": <number 0-100 or null if Kiro>,
      "most_expensive_model": "<model name or null>",
      "total_credits": <number or null if Claude Code>,
      "credits_per_session": <number or null>
    }},
    "model_breakdown": [
      {{"model": "<name>", "cost_usd": <number>}}
    ],
    "opportunities": [
      {{
        "title": "<opportunity>",
        "description": "<what to change>",
        "estimated_savings": "<e.g. '~30% reduction'>"
      }}
    ]
  }}
}}

Rules:
- IDE-aware: If the agent uses Kiro, report credits NOT tokens
- Only suggest model downgrades with clear evidence of waste
- Maximum 3 opportunities, empty array is fine if costs are reasonable
- If costs are reasonable and cache efficiency is good, keep this section brief — state the numbers and move on
- Only go deep on cost when there's a real problem (e.g. high cost per session with low output, or poor cache efficiency)""",
    "regression_detection": """You are comparing current and previous period metrics for an AI coding agent.

{data_block}

{previous_data_block}

Produce a JSON object with this EXACT structure:
{{
  "regression_detection": {{
    "has_previous_data": <true|false>,
    "summary": "<1-2 sentences: what changed>",
    "changes": [
      {{
        "metric": "<metric name>",
        "direction": "<improved | degraded | stable>",
        "previous_value": "<formatted value>",
        "current_value": "<formatted value>",
        "magnitude_pct": <number>,
        "significance": "<meaningful | minor | noise>",
        "likely_cause": "<hypothesis about what caused the change>"
      }}
    ]
  }}
}}

If no previous data: {{"regression_detection": {{"has_previous_data": false, "summary": "No previous period data available.", "changes": []}}}}""",
    "fun_ending": """You are producing the final section of an AI coding agent insight report. Find ONE genuinely interesting or memorable observation.

{data_block}

Produce a JSON object with this EXACT structure:
{{
  "fun_ending": {{
    "headline": "<punchy 5-10 word headline>",
    "detail": "<2-3 sentences that are genuinely interesting. Could be: an unusual stat, a notable achievement, or something that characterizes this agent's usage.>"
  }}
}}

Rules:
- Don't force humor
- Focus on genuinely notable data points
- Under 50 words for detail""",
}

SYNTHESIS_PROMPT = """You have analysis sections about an AI coding agent's recent performance. Write an executive summary a manager can read in 10 seconds.

## Section Outputs
{sections_json}

Write a JSON response with this EXACT structure:
{{
  "at_a_glance": {{
    "health": "<healthy | mixed | concerning>",
    "whats_working": "<1 sentence: the agent's primary value — what it's actually helping with>",
    "whats_hindering": "<1 sentence: the biggest problem, stated concretely>",
    "quick_win": "<1 sentence: single most impactful change to make right now>",
    "ambitious_workflows": "<1 sentence: what this agent could enable if working well>"
  }}
}}

Rules:
- Each field: ONE sentence, max 25 words. Be specific — name tools, error rates, actual patterns.
- Health assessment:
  - "healthy" = users get tasks done, low friction, reasonable costs
  - "mixed" = delivers value in some areas but has notable problems in others
  - "concerning" = agent regularly fails to complete tasks, users repeat themselves, or sessions end without resolution
- whats_working: if genuinely nothing is working, say so (e.g. "No clear value delivered in this period")
- whats_hindering: name the specific failure, not vague language
- quick_win: must be concrete and implementable, not "improve the agent"
- ambitious_workflows: forward-looking — what could the team automate if this agent were performing well"""


# ──────────────────────────────────────────────────────────────────────────────
# Execution
# ──────────────────────────────────────────────────────────────────────────────

# Sections that require deeper reasoning get the "deep" model (Opus).
# All others use the "fast" model (Sonnet) for cost efficiency.
_DEEP_SECTIONS = {"suggestions"}

# Output size varies by section — right-size to avoid wasting tokens.
_SECTION_MAX_TOKENS: dict[str, int] = {
    "suggestions": 4096,
    "usage_patterns": 3000,
    "friction_analysis": 2500,
    "what_works": 2000,
    "usage_cost_analysis": 2000,
    "user_experience": 2000,
    "regression_detection": 2000,
    "fun_ending": 512,
}


async def _call_section(section_name: str, prompt: str, model: str | None = None) -> tuple[str, dict]:
    """Call the eval model for a single section, return (name, result)."""
    call_model = get_call_model()
    max_tokens = _SECTION_MAX_TOKENS.get(section_name, 4096)
    try:
        result = await call_model(prompt, model_override=model, max_tokens=max_tokens)
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
    registry_catalog: dict | None = None,
) -> dict:
    """Run 8 parallel section prompts + 1 synthesis, return combined narrative.

    Args:
        data_block: Formatted string with all metrics, facets, and session data.
        previous_report: Previous report's aggregated_data for regression comparison.
        registry_catalog: Filtered catalog of available components (only for suggestions).

    Returns:
        Dict with structured section outputs for each narrative section.
    """
    call_model = get_call_model()

    # Build previous data block for regression section
    previous_data_block = ""
    if previous_report:
        previous_data_block = f"## Previous Period Metrics\n{json.dumps(previous_report, indent=2, default=str)}"
    else:
        previous_data_block = "## Previous Period Metrics\nNo previous period data available."

    # Build catalog block — only injected into the suggestions prompt to save tokens
    catalog_block = ""
    if registry_catalog:
        catalog_block = (
            "\n\n## Available Components (registry catalog — NOT yet configured on this agent)\n"
            + json.dumps(registry_catalog, indent=2)
        )

    # Resolve models: deep (Opus) for complex sections, synthesis (Sonnet) for the rest
    deep_model = _get_section_model()
    fast_model = _get_synthesis_model()

    logger.info(
        "insight_sections_starting",
        deep_model=deep_model or "default",
        fast_model=fast_model or "default",
        catalog_items=(len(registry_catalog.get("mcps", [])) + len(registry_catalog.get("skills", [])))
        if registry_catalog
        else 0,
    )

    # Build prompts for all 8 sections
    section_prompts: dict[str, str] = {}
    for name, template in SECTION_PROMPTS.items():
        if name == "regression_detection":
            built = template.format(
                data_block=data_block,
                previous_data_block=previous_data_block,
            )
        elif name == "suggestions":
            # Append catalog only to suggestions to minimize token cost
            built = template.format(data_block=data_block + catalog_block)
        else:
            built = template.format(data_block=data_block)
        section_prompts[name] = SECTION_PREAMBLE + built

    # Route each section to the appropriate model tier
    tasks = [
        _call_section(
            name,
            prompt,
            model=deep_model if name in _DEEP_SECTIONS else fast_model,
        )
        for name, prompt in section_prompts.items()
    ]
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

    # Run synthesis with all section outputs using fast model (Sonnet)
    synthesis_prompt = SYNTHESIS_PROMPT.format(sections_json=json.dumps(narrative, indent=2, default=str))
    try:
        synthesis_result = await call_model(synthesis_prompt, model_override=fast_model, max_tokens=4096)
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
