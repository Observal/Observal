# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
#
# SPDX-License-Identifier: AGPL-3.0-only

"""CheckResult — the universal scoring atom.

Every layer in the eval pipeline produces CheckResult[]. The scorecard is
aggregate(CheckResult[]). Nothing in the system produces a numeric score
by any other path.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class CheckType(str, Enum):
    # Spec alignment (Layer 3)
    MATCHED = "MATCHED"
    WRONG_PARAMS = "WRONG_PARAMS"
    MISSING = "MISSING"
    ORDER_RESPECTED = "ORDER_RESPECTED"
    ORDER_VIOLATED = "ORDER_VIOLATED"
    UNEXPECTED_ACTION = "UNEXPECTED_ACTION"
    FORBIDDEN_ACTION = "FORBIDDEN_ACTION"
    # Council evidence (Layer 4)
    EVIDENCE_GROUNDED = "EVIDENCE_GROUNDED"
    EVIDENCE_MISSING = "EVIDENCE_MISSING"
    # Adversarial (Layer 5)
    INPUT_SANITIZED = "INPUT_SANITIZED"
    INPUT_TAMPERED = "INPUT_TAMPERED"
    CANARY_RESPECTED = "CANARY_RESPECTED"
    CANARY_TRIPPED = "CANARY_TRIPPED"
    # Waste (Layer 6)
    WASTE_REVERT = "WASTE_REVERT"
    WASTE_CYCLE = "WASTE_CYCLE"
    WASTE_REDUNDANT_READ = "WASTE_REDUNDANT_READ"
    WASTE_DEAD_END = "WASTE_DEAD_END"
    # Longitudinal (Layer 8)
    REGRESSION_DETECTED = "REGRESSION_DETECTED"
    CROSS_SESSION_CONTAMINATION = "CROSS_SESSION_CONTAMINATION"


class Status(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"


class Category(str, Enum):
    CORRECTNESS = "correctness"
    EFFICIENCY = "efficiency"
    SAFETY = "safety"
    ADVERSARIAL = "adversarial"
    WASTE = "waste"


class SpanRef(BaseModel):
    span_id: str
    trace_id: str | None = None


class CheckResult(BaseModel):
    check_type: CheckType
    status: Status
    weight: float
    points_earned: float
    points_possible: float
    evidence: list[SpanRef] = Field(default_factory=list)
    category: Category
    meta: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        if self.points_earned < 0 or self.points_possible < 0:
            raise ValueError("points must be non-negative")
        if self.points_earned > self.points_possible:
            raise ValueError("points_earned cannot exceed points_possible")
