# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Spec DAG (v2) — outcome-oriented task specification.

The principle: don't spec the path, spec what success looks like. The agent
can take whatever path it wants. We check whether the result is correct,
whether the path was safe, and whether it was efficient. Three concerns,
three sections — outcome assertions, step constraints, domain invariants.

JSON-serializable. The Postgres `eval_spec_dags.dag_json` column stores the
full Pydantic dump. v1 (path-oriented) specs are detected by the absence of
``schema_version >= 2`` and rejected by ``registry.load_spec_dag``.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class OutcomeCheckType(str, Enum):
    RESPONSE_CONTAINS = "response_contains"
    RESPONSE_SCHEMA = "response_schema"
    STATE_EQUALS = "state_equals"
    STATE_CHANGED = "state_changed"
    TOOL_WAS_CALLED = "tool_was_called"
    TOOL_RESULT_CONTAINS = "tool_result_contains"
    ARTIFACT_EXISTS = "artifact_exists"
    CUSTOM_PYTHON = "custom_python"


# OutcomeCheck.params schemas, by check_type:
#
# RESPONSE_CONTAINS — does the agent's final response contain expected content?
#   params: {"pattern": str, "match_type": "exact"|"substring"|"regex"|"semantic",
#            "threshold": float (semantic only, default 0.85)}
#   Evaluated against the output of the last agent-to-user span in the trace.
#
# RESPONSE_SCHEMA — does the final response validate against a JSON schema?
#   params: {"schema": dict (valid JSON Schema)}
#
# STATE_EQUALS — does a state field equal an expected value at trace end?
#   params: {"namespace": str, "key": str, "expected_value": Any}
#   Primary path today: scan tool outputs / output_excerpt for the value
#   (state_writes is not yet captured by the SDK; when it lands, that becomes
#   the authoritative source).
#
# STATE_CHANGED — did a state field change from X to Y during the trace?
#   params: {"namespace": str, "key": str, "from_value": Any, "to_value": Any}
#
# TOOL_WAS_CALLED — was a specific tool called at least once?
#   params: {"tool_name": str, "min_count": int (default 1),
#            "param_constraints": dict|None (loose: only checks listed keys)}
#
# TOOL_RESULT_CONTAINS — did a specific tool's output contain expected content?
#   params: {"tool_name": str, "pattern": str,
#            "match_type": "exact"|"substring"|"regex"|"semantic"}
#
# ARTIFACT_EXISTS — was a file created or modified?
#   params: {"path_pattern": str (glob or regex over files_written),
#            "content_pattern": str | None (optional, against output_excerpt)}
#
# CUSTOM_PYTHON — reserved for a future sandboxed/registered implementation.
#   In-process dotted imports are intentionally disabled.


class OutcomeCheck(BaseModel):
    check_type: OutcomeCheckType
    params: dict[str, Any] = Field(default_factory=dict)


class OutcomeAssertion(BaseModel):
    """The primary building block. Asserts something about what happened, not how."""

    assertion_id: str
    description: str = ""
    check: OutcomeCheck
    weight: float = 1.0
    required: bool = True  # if True, failure here means the task objectively failed


class StepConstraint(BaseModel):
    """Safety-critical ordering only. Most specs should have zero of these."""

    constraint_id: str
    description: str = ""
    before_tool: str
    after_tool: str
    weight: float = 1.0
    severity: Literal["hard", "soft"] = "soft"


class DomainInvariant(BaseModel):
    """Domain-level safety rules. Shared across task types, hand-authored."""

    invariant_id: str
    description: str = ""
    check: OutcomeCheck
    severity: Literal["critical", "major"] = "major"


class SpecSource(str, Enum):
    HAND_AUTHORED = "hand_authored"
    MINED = "mined"
    LLM_INFERRED = "llm_inferred"


class SpecDAG(BaseModel):
    """Outcome-oriented task specification (schema_version=2)."""

    schema_version: int = 2
    task_type: str
    version: str = "1"
    source: SpecSource = SpecSource.HAND_AUTHORED
    created_at: str | None = None
    created_by: str | None = None

    outcome_assertions: list[OutcomeAssertion] = Field(default_factory=list)
    step_constraints: list[StepConstraint] = Field(default_factory=list)
    domain_invariants: list[DomainInvariant] = Field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> SpecDAG:
        return cls.model_validate(data)


__all__ = [
    "DomainInvariant",
    "OutcomeAssertion",
    "OutcomeCheck",
    "OutcomeCheckType",
    "SpecDAG",
    "SpecSource",
    "StepConstraint",
]
