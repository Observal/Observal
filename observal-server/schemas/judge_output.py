"""Structured output schemas for SLM judge responses.

Forces the judge to return structured JSON rather than free-text reasoning
that can be steered by prompt injection in agent output.
"""

from typing import Literal

from pydantic import BaseModel, Field


class SectionJudgment(BaseModel):
    """Judgment for a single required section."""

    section_name: str
    status: Literal["present", "missing", "stub", "ungrounded"]
    evidence_span_id: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class GoalCompletionJudgment(BaseModel):
    """Structured response for goal completion evaluation."""

    sections: list[SectionJudgment]


class ClaimJudgment(BaseModel):
    """Judgment for a single factual claim."""

    claim_text: str = Field(max_length=100)
    status: Literal["grounded", "ungrounded", "contradicted", "numeric_mismatch", "hallucinated_entity"]
    source_span_id: str | None = None
    evidence_quote: str = Field(max_length=100)


class FactualGroundingJudgment(BaseModel):
    """Structured response for factual grounding evaluation."""

    claims: list[ClaimJudgment]


class ThoughtFinding(BaseModel):
    """A single thought process finding."""

    finding_type: Literal[
        "blind_tool_use",
        "reasoning_contradicts_action",
        "no_conclusion_explanation",
        "ignores_relevant_data",
    ]
    span_id: str
    explanation: str = Field(max_length=150)


class ThoughtProcessJudgment(BaseModel):
    """Structured response for thought process evaluation."""

    findings: list[ThoughtFinding]


# JSON schema strings for embedding in prompts
GOAL_COMPLETION_SCHEMA = GoalCompletionJudgment.model_json_schema()
FACTUAL_GROUNDING_SCHEMA = FactualGroundingJudgment.model_json_schema()
THOUGHT_PROCESS_SCHEMA = ThoughtProcessJudgment.model_json_schema()
