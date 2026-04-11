import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, model_validator

from models.eval import EvalRunStatus


class ScorecardDimensionResponse(BaseModel):
    dimension: str
    score: float
    grade: str
    notes: str | None
    model_config = {"from_attributes": True}


class InjectionAttemptResponse(BaseModel):
    pattern_matched: str
    location: str
    severity: str


class AdversarialFindings(BaseModel):
    injection_attempts_detected: int = 0
    injection_attempts: list[InjectionAttemptResponse] = []
    items_sanitized: int = 0
    adversarial_score: float = 100.0


class CanaryReportResponse(BaseModel):
    trace_id: str
    canary_id: str
    canary_type: str
    canary_value: str
    injection_point: str
    agent_behavior: str
    penalty_applied: bool
    evidence: str


class PenaltySummary(BaseModel):
    event_name: str
    dimension: str
    amount: int
    evidence: str


class ScorecardResponse(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    eval_run_id: uuid.UUID
    trace_id: str
    version: str
    overall_score: float
    overall_grade: str
    recommendations: str | None
    bottleneck: str | None
    evaluated_at: datetime
    dimensions: list[ScorecardDimensionResponse] = []
    # Structured scoring fields
    dimension_scores: dict | None = None
    composite_score: float | None = None
    display_score: float | None = None
    grade: str | None = None
    scoring_recommendations: list[str] | None = None
    penalty_count: int = 0
    # BenchJack-hardened fields
    warnings: list[str] | None = None
    partial_evaluation: bool = False
    dimensions_skipped: list[str] | None = None
    adversarial_findings: AdversarialFindings | None = None
    canary_report: CanaryReportResponse | None = None
    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def _extract_adversarial_from_raw(cls, data: Any) -> Any:
        """Extract adversarial_findings and canary_report from raw_output if present."""
        if isinstance(data, dict):
            raw = data.get("raw_output")
        else:
            raw = getattr(data, "raw_output", None)

        if not isinstance(raw, dict):
            return data

        if isinstance(data, dict):
            if not data.get("adversarial_findings") and "adversarial_findings" in raw:
                data["adversarial_findings"] = raw["adversarial_findings"]
            if not data.get("canary_report") and raw.get("canary_report"):
                data["canary_report"] = raw["canary_report"]
        else:
            # ORM object — set on the dict that model_validate produces
            # We can't mutate the ORM object, but Pydantic will use the dict
            pass

        return data


class EvalRunResponse(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    triggered_by: uuid.UUID
    status: EvalRunStatus
    traces_evaluated: int
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None
    model_config = {"from_attributes": True}


class EvalRunDetailResponse(EvalRunResponse):
    scorecards: list[ScorecardResponse] = []


class EvalRequest(BaseModel):
    trace_id: str | None = None  # Evaluate specific trace, or all recent if None
