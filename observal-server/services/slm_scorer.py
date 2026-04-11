"""SLM scorer: LLM-assisted scoring for Goal Completion, Factual Grounding, Thought Process.

Uses the existing EvalBackend (LLMJudgeBackend/FallbackBackend) to evaluate trace quality.
"""

import logging

from models.scoring import ScoringDimension
from services.eval_engine import EvalBackend

logger = logging.getLogger(__name__)


# --- Prompt Templates ---

GOAL_COMPLETION_PROMPT = """You are an evaluation judge. Given an agent's output and its goal template with required sections, check each section.

## Goal Template
{goal_description}

## Required Sections
{sections}

## Agent Output (from trace)
{agent_output}

## Tool Call Results
{tool_results}

## Instructions
For each required section, determine:
1. Is it present in the agent output?
2. If present, is the content substantive (not a stub/placeholder)?
3. If present, is it grounded in tool call results?

Respond ONLY with valid JSON (no markdown):
{{"sections": [
  {{"section_name": "<name>", "status": "present|missing|stub|ungrounded", "evidence": "<quote or explanation>"}}
]}}"""

FACTUAL_GROUNDING_PROMPT = """You are an evaluation judge. Given an agent's final output and all tool call results, identify claims in the output and verify each against the tool results.

## Agent Output
{agent_output}

## Tool Call Results
{tool_results}

## Instructions
Extract key factual claims from the agent output. For each claim, check if it is supported by the tool call results.

Respond ONLY with valid JSON (no markdown):
{{"claims": [
  {{"claim": "<the claim>", "status": "grounded|ungrounded|contradicted|numeric_mismatch|hallucinated_entity", "evidence": "<supporting or contradicting evidence>", "source_span_id": "<span_id or null>"}}
]}}"""

THOUGHT_PROCESS_PROMPT = """You are an evaluation judge. Given an agent's reasoning trace (thought steps and actions), evaluate the quality of the thought process.

## Reasoning Trace
{reasoning_trace}

## Instructions
Check the following:
1. Does each tool call have preceding reasoning explaining why it's being made?
2. Does the reasoning match the subsequent action?
3. Is the final conclusion explained and justified?
4. Is relevant tool data incorporated into reasoning?

Respond ONLY with valid JSON (no markdown):
{{"findings": [
  {{"type": "blind_tool_use|reasoning_contradicts_action|no_conclusion_explanation|ignores_relevant_data", "description": "<what was found>", "evidence": "<specific quote or reference>"}}
]}}"""


class SLMScorer:
    """LLM-assisted scorer for goal_completion, factual_grounding, thought_process."""

    def __init__(self, backend: EvalBackend):
        self.backend = backend

    async def score_goal_completion(
        self,
        trace: dict,
        spans: list[dict],
        goal_description: str = "",
        required_sections: list[dict] | None = None,
    ) -> list[dict]:
        """Check goal completion by evaluating agent output against goal template sections."""
        if not required_sections:
            return []

        agent_output = trace.get("output") or ""
        tool_results = _extract_tool_results(spans)
        sections_text = "\n".join(
            f"- {s.get('name', 'Unknown')}" + (" [grounding required]" if s.get("grounding_required") else "")
            for s in required_sections
        )

        prompt = GOAL_COMPLETION_PROMPT.format(
            goal_description=goal_description,
            sections=sections_text,
            agent_output=agent_output[:3000],
            tool_results=tool_results[:3000],
        )

        result = await self._call_llm(prompt)
        penalties: list[dict] = []

        for section in result.get("sections", []):
            status = section.get("status", "present")
            evidence = section.get("evidence", "")
            section_name = section.get("section_name", "")

            if status == "missing":
                penalties.append(
                    {
                        "event_name": "missing_required_section",
                        "dimension": ScoringDimension.goal_completion,
                        "evidence": f"Section '{section_name}' is missing. {evidence}",
                        "trace_event_index": None,
                    }
                )
            elif status == "stub":
                penalties.append(
                    {
                        "event_name": "empty_stub_section",
                        "dimension": ScoringDimension.goal_completion,
                        "evidence": f"Section '{section_name}' contains only stub content. {evidence}",
                        "trace_event_index": None,
                    }
                )
            elif status == "ungrounded":
                penalties.append(
                    {
                        "event_name": "ungrounded_section",
                        "dimension": ScoringDimension.goal_completion,
                        "evidence": f"Section '{section_name}' is not grounded in tool results. {evidence}",
                        "trace_event_index": None,
                    }
                )

        return penalties

    async def score_factual_grounding(self, trace: dict, spans: list[dict]) -> list[dict]:
        """Check factual grounding of agent output against tool call results."""
        agent_output = trace.get("output") or ""
        if not agent_output:
            return []

        tool_results = _extract_tool_results(spans)
        if not tool_results:
            return []

        prompt = FACTUAL_GROUNDING_PROMPT.format(
            agent_output=agent_output[:3000],
            tool_results=tool_results[:3000],
        )

        result = await self._call_llm(prompt)
        penalties: list[dict] = []

        status_to_event = {
            "ungrounded": "ungrounded_claim",
            "contradicted": "contradicts_source",
            "numeric_mismatch": "numeric_mismatch",
            "hallucinated_entity": "hallucinated_entity",
        }

        for claim in result.get("claims", []):
            status = claim.get("status", "grounded")
            event_name = status_to_event.get(status)
            if event_name:
                penalties.append(
                    {
                        "event_name": event_name,
                        "dimension": ScoringDimension.factual_grounding,
                        "evidence": f"Claim: '{claim.get('claim', '')}'. {claim.get('evidence', '')}",
                        "trace_event_index": None,
                    }
                )

        return penalties

    async def score_thought_process(self, spans: list[dict]) -> list[dict]:
        """Evaluate the quality of the agent's reasoning/thought process."""
        reasoning_trace = _extract_reasoning_trace(spans)
        if not reasoning_trace:
            return []

        prompt = THOUGHT_PROCESS_PROMPT.format(
            reasoning_trace=reasoning_trace[:4000],
        )

        result = await self._call_llm(prompt)
        penalties: list[dict] = []

        valid_types = {
            "blind_tool_use",
            "reasoning_contradicts_action",
            "no_conclusion_explanation",
            "ignores_relevant_data",
        }

        for finding in result.get("findings", []):
            event_name = finding.get("type", "")
            if event_name in valid_types:
                penalties.append(
                    {
                        "event_name": event_name,
                        "dimension": ScoringDimension.thought_process,
                        "evidence": f"{finding.get('description', '')} Evidence: {finding.get('evidence', '')}",
                        "trace_event_index": None,
                    }
                )

        return penalties

    async def _call_llm(self, prompt: str) -> dict:
        """Call the LLM backend and parse JSON response."""
        try:
            # Use the backend's score method with a synthetic template
            template = {"prompt": "{trace}"}
            result = await self.backend.score(template, {"prompt": prompt}, {"prompt": prompt})
            # If backend returned score/reason format, the prompt wasn't processed correctly
            # Fall back to direct model calling
            if "score" in result and "reason" in result and "sections" not in result:
                return await self._call_model_direct(prompt)
            return result
        except Exception:
            return await self._call_model_direct(prompt)

    async def _call_model_direct(self, prompt: str) -> dict:
        """Direct model call for structured JSON responses."""
        from services.eval_service import call_eval_model

        try:
            result = await call_eval_model(prompt)
            if result:
                return result
        except Exception as e:
            logger.error(f"SLM scorer model call failed: {e}")
        return {}


def _extract_tool_results(spans: list[dict]) -> str:
    """Extract tool call results from spans as formatted text."""
    results = []
    for span in spans:
        if span.get("type") == "tool_call":
            name = span.get("name", "unknown")
            output = span.get("output") or ""
            status = span.get("status", "success")
            span_id = span.get("span_id", "")
            results.append(f"[{span_id}] {name} ({status}): {output[:500]}")
    return "\n".join(results)


def _extract_reasoning_trace(spans: list[dict]) -> str:
    """Extract reasoning steps and actions as formatted text."""
    steps = []
    for i, span in enumerate(spans):
        span_type = span.get("type", "")
        name = span.get("name", "")
        input_data = span.get("input") or ""
        output_data = span.get("output") or ""

        if span_type in ("reasoning_step", "thought", "agent_turn"):
            steps.append(f"[Step {i}] THOUGHT: {input_data[:300]}")
        elif span_type == "tool_call":
            steps.append(f"[Step {i}] ACTION: {name}({input_data[:200]}) -> {output_data[:200]}")
        elif span_type == "response":
            steps.append(f"[Step {i}] RESPONSE: {output_data[:300]}")

    return "\n".join(steps)
