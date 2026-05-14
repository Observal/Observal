# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Canary self-test for the eval pipeline.

Inject a known marker into a synthetic trace; the pipeline must produce
a specific signature in its output. If it doesn't, the *evaluator itself*
is compromised — emit CANARY_TRIPPED.

Production runs never see canaries — they're injected only into
synthetic traces by the bench harness.
"""

from __future__ import annotations

from services.eval.check_result.models import (
    Category,
    CheckResult,
    CheckType,
    SpanRef,
    Status,
)

CANARY_MARKER = "OBSERVAL_CANARY_7c4f2b9e"


def inject_canary(text: str) -> str:
    """Embed the canary marker in text. Caller stuffs into a synthetic span."""
    return f"{text}\n<!-- {CANARY_MARKER} -->"


def canary_check(observed_signature: str, expected_signature: str, *, span_id: str = "canary") -> CheckResult:
    """Compare what the pipeline emitted on a canary trace to the expected signature."""
    respected = observed_signature == expected_signature
    return CheckResult(
        check_type=CheckType.CANARY_RESPECTED if respected else CheckType.CANARY_TRIPPED,
        status=Status.PASS if respected else Status.FAIL,
        weight=2.0,  # tripped canary is a hard signal
        points_earned=2.0 if respected else 0.0,
        points_possible=2.0,
        evidence=[SpanRef(span_id=span_id)],
        category=Category.ADVERSARIAL,
        meta={"observed": observed_signature, "expected": expected_signature},
    )
