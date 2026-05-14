# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Aggregation — CheckResult[] → Scorecard.

Two scoring modes, tagged on the scorecard:
- spec_dag_alignment: anchored ratio of points_earned / points_possible
- council_deductive:  100 - sum(penalty); used when no spec exists

Refusing cross-mode comparison is the comparator's job — this module
just labels the mode.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.eval.check_result.models import Category, CheckResult


class ScoringMode(str, Enum):
    SPEC_DAG_ALIGNMENT = "spec_dag_alignment"
    COUNCIL_DEDUCTIVE = "council_deductive"


@dataclass(frozen=True)
class Scorecard:
    score: float  # 0.0 - 1.0 for spec_dag_alignment; 0-100 for council_deductive
    scoring_mode: ScoringMode
    checks: list[CheckResult]
    points_earned: float
    points_possible: float
    per_category: dict[str, dict[str, float]] = field(default_factory=dict)
    spec_dag_version: str | None = None
    agent_version_hash: str | None = None
    council_model_snapshots: dict[str, str] = field(default_factory=dict)


def _per_category(checks: list[CheckResult]) -> dict[str, dict[str, float]]:
    by_cat: dict[Category, list[CheckResult]] = defaultdict(list)
    for c in checks:
        by_cat[c.category].append(c)
    out: dict[str, dict[str, float]] = {}
    for cat, items in by_cat.items():
        earned = sum(c.points_earned for c in items)
        possible = sum(c.points_possible for c in items)
        out[cat.value] = {
            "points_earned": earned,
            "points_possible": possible,
            "score": (earned / possible) if possible > 0 else 1.0,
            "count": float(len(items)),
        }
    return out


def spec_dag_alignment_score(checks: list[CheckResult]) -> tuple[float, float, float]:
    earned = sum(c.points_earned for c in checks)
    possible = sum(c.points_possible for c in checks)
    score = (earned / possible) if possible > 0 else 1.0
    return score, earned, possible


def council_deductive_score(checks: list[CheckResult]) -> tuple[float, float, float]:
    """Subtract deductions from 100. Each failing/warning check contributes its weight."""
    deduction = 0.0
    for c in checks:
        deduction += c.points_possible - c.points_earned
    score = max(0.0, 100.0 - deduction)
    return score, deduction, 100.0


def aggregate(
    checks: list[CheckResult],
    *,
    mode: ScoringMode,
    spec_dag_version: str | None = None,
    agent_version_hash: str | None = None,
    council_model_snapshots: dict[str, str] | None = None,
) -> Scorecard:
    if mode == ScoringMode.SPEC_DAG_ALIGNMENT:
        score, earned, possible = spec_dag_alignment_score(checks)
    else:
        score, earned, possible = council_deductive_score(checks)
    return Scorecard(
        score=score,
        scoring_mode=mode,
        checks=list(checks),
        points_earned=earned,
        points_possible=possible,
        per_category=_per_category(checks),
        spec_dag_version=spec_dag_version,
        agent_version_hash=agent_version_hash,
        council_model_snapshots=dict(council_model_snapshots or {}),
    )
