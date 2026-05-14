# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Reasoning layer — produces prose over CheckResult[]. Never returns a score.

The LLM sees a structured data block (CheckResult summaries + trace
excerpts) and emits root cause / severity per category / fix suggestions.
Re-running this never affects any number on the scorecard.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from services.eval.check_result.models import CheckResult, Status

LLMCallable = Callable[[str], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class ReasoningOutput:
    root_cause: str
    severity_by_category: dict[str, str]  # category → "low" | "medium" | "high"
    fix_suggestions: list[str]
    raw_model_output: dict[str, Any] = field(default_factory=dict)


def _summarize_checks(checks: list[CheckResult]) -> dict[str, Any]:
    by_cat: dict[str, dict[str, int]] = defaultdict(lambda: {"pass": 0, "fail": 0, "warn": 0, "total": 0})
    failing_examples: list[dict[str, Any]] = []
    for c in checks:
        cat = c.category.value
        by_cat[cat][c.status.value.lower()] += 1
        by_cat[cat]["total"] += 1
        if c.status != Status.PASS and len(failing_examples) < 12:
            failing_examples.append(
                {
                    "check_type": c.check_type.value,
                    "category": cat,
                    "weight": c.weight,
                    "evidence_span_ids": [e.span_id for e in c.evidence],
                    "meta": c.meta,
                }
            )
    return {"counts_by_category": dict(by_cat), "failing_examples": failing_examples}


def _build_prompt(summary: dict[str, Any], trace_excerpts: list[dict[str, Any]]) -> str:
    return (
        "You explain evaluation failures. You DO NOT produce numeric scores. "
        "Output ONLY a JSON object with these keys: "
        "root_cause (string), severity_by_category (object: category->{low|medium|high}), "
        "fix_suggestions (list of strings). Do not include any other keys.\n\n"
        f"CheckResult summary:\n{json.dumps(summary, indent=2)}\n\n"
        f"Trace excerpts (span_id → excerpt):\n{json.dumps(trace_excerpts, indent=2)}\n\n"
        "Respond with the JSON object only."
    )


def _coerce_severity(value: Any) -> str:
    s = str(value).strip().lower()
    return s if s in {"low", "medium", "high"} else "medium"


async def explain(
    checks: list[CheckResult],
    trace_excerpts: list[dict[str, Any]],
    *,
    llm_call: LLMCallable,
) -> ReasoningOutput:
    """Produce prose. Never modifies, references, or returns a numeric score."""
    summary = _summarize_checks(checks)
    prompt = _build_prompt(summary, trace_excerpts)
    raw = await llm_call(prompt)
    if not isinstance(raw, dict):
        raw = {}

    severity_in = raw.get("severity_by_category") or {}
    if not isinstance(severity_in, dict):
        severity_in = {}
    severity = {str(k): _coerce_severity(v) for k, v in severity_in.items()}
    # ensure every category present in checks has an entry
    for cat in {c.category.value for c in checks}:
        severity.setdefault(cat, "low")

    fix_in = raw.get("fix_suggestions") or []
    if not isinstance(fix_in, list):
        fix_in = []
    fixes = [str(x) for x in fix_in if isinstance(x, (str, int, float))]

    # strip out anything number-shaped that an LLM might smuggle through
    cleaned_raw = {k: v for k, v in raw.items() if k in {"root_cause", "severity_by_category", "fix_suggestions"}}

    return ReasoningOutput(
        root_cause=str(raw.get("root_cause") or ""),
        severity_by_category=severity,
        fix_suggestions=fixes,
        raw_model_output=cleaned_raw,
    )


# Helper exposed for tests / ad-hoc inspection
def category_counts(checks: list[CheckResult]) -> dict[str, dict[str, int]]:
    return _summarize_checks(checks)["counts_by_category"]


__all__ = ["LLMCallable", "ReasoningOutput", "category_counts", "explain"]
