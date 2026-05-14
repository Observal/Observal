# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Deterministic rules: Council facts → CheckResults.

The Council's structured fact never carries a number. Whatever score
emerges does so through these rules — same fact in, same CheckResult out.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from services.eval.check_result.models import (
    Category,
    CheckResult,
    CheckType,
    SpanRef,
    Status,
)
from services.eval.council.extractors import (
    CITE_CHECK_QUESTION,
    GROUNDED_QUANTITIES_QUESTION,
    CouncilFact,
)

if TYPE_CHECKING:
    from collections.abc import Callable


def _cite_check_to_result(fact: CouncilFact) -> CheckResult:
    cited = bool(fact.payload.get("cited"))
    evidence = fact.payload.get("evidence_span_id")
    refs = [SpanRef(span_id=fact.span_id)]
    if cited and evidence:
        refs.append(SpanRef(span_id=str(evidence)))
    return CheckResult(
        check_type=CheckType.EVIDENCE_GROUNDED if cited else CheckType.EVIDENCE_MISSING,
        status=Status.PASS if cited else Status.FAIL,
        weight=1.0,
        points_earned=1.0 if cited else 0.0,
        points_possible=1.0,
        evidence=refs,
        category=Category.CORRECTNESS,
        meta={"question_id": fact.question_id, "model_snapshot": fact.model_snapshot},
    )


def _grounded_quantities_to_result(fact: CouncilFact) -> CheckResult:
    ungrounded = fact.payload.get("ungrounded_quantities") or []
    cited = not ungrounded
    return CheckResult(
        check_type=CheckType.EVIDENCE_GROUNDED if cited else CheckType.EVIDENCE_MISSING,
        status=Status.PASS if cited else Status.FAIL,
        weight=1.0,
        points_earned=1.0 if cited else 0.0,
        points_possible=1.0,
        evidence=[SpanRef(span_id=fact.span_id)],
        category=Category.CORRECTNESS,
        meta={
            "question_id": fact.question_id,
            "model_snapshot": fact.model_snapshot,
            "ungrounded_quantities": list(ungrounded),
        },
    )


_RULES: dict[str, Callable[[CouncilFact], CheckResult]] = {
    CITE_CHECK_QUESTION.question_id: _cite_check_to_result,
    GROUNDED_QUANTITIES_QUESTION.question_id: _grounded_quantities_to_result,
}


def facts_to_check_results(facts: list[CouncilFact]) -> list[CheckResult]:
    out: list[CheckResult] = []
    for f in facts:
        rule = _RULES.get(f.question_id)
        if rule is None:
            continue  # unknown question — caller registered a new extractor without a rule
        out.append(rule(f))
    return out
