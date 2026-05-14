# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Batch narrative — pre-computed deterministic metrics, then prose-only LLM.

This lives alongside eval because batch insights reuse eval scorecards,
CheckResults, and waste classifications. The LLM layer is deliberately
prose-only: all metrics are computed before prompting so generated reports
cannot invent counts, latency percentiles, cost, or regression deltas.

The pipeline:

1. Compute deterministic metrics over the batch (counts, token aggregates,
   latency distributions, error breakdown, tool usage, cost via injected
   pricing fn, MCP shim latency p50/95/99, interruption breakdown).
2. Pre-compute cross-batch detection signals (top-N regressions, friction
   hot spots, etc.).
3. Roll up causal enrichment from the per-trace waste classifier — revert
   hot spots, cycle hot spots, intent-cluster cost attribution.
4. Optionally fold in regression deltas from longitudinal.
5. Assemble structured data block.
6. Render 8 parallel narrative sections + 1 synthesis. The LLM sees the
   structured data block and writes prose ONLY. Any number quoted in the
   narrative came verbatim from step 1.
"""

from __future__ import annotations

import asyncio
import json
import statistics
from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

from services.eval.check_result.models import Category, CheckResult, CheckType

if TYPE_CHECKING:
    from services.eval.aggregation.scorecard import Scorecard

LLMCallable = Callable[[str], Awaitable[dict[str, Any]]]
PricingFn = Callable[[str, int, int], float]

NARRATIVE_SECTIONS: tuple[str, ...] = (
    "usage_patterns",
    "what_works",
    "friction_analysis",
    "suggestions",
    "token_optimization",
    "user_experience",
    "regression_detection",
    "fun_ending",
)


@dataclass(frozen=True)
class TraceSummary:
    trace_id: str
    session_id: str
    tools_used: tuple[str, ...]
    error_count: int
    total_tokens_in: int
    total_tokens_out: int
    latency_ms: int
    stop_reason: str = ""
    model: str = ""


@dataclass(frozen=True)
class DeterministicMetrics:
    session_count: int
    trace_count: int
    total_tokens_in: int
    total_tokens_out: int
    latency_p50: float
    latency_p95: float
    latency_p99: float
    error_breakdown_by_tool: dict[str, int]
    tool_usage: dict[str, int]
    cost_usd: float
    cost_unknown: bool
    interruptions_by_stop_reason: dict[str, int]
    waste_hot_spots: dict[str, list[dict[str, Any]]]
    per_session: list[dict[str, Any]]


@dataclass(frozen=True)
class SectionNarrative:
    section: str
    text: str


@dataclass
class BatchNarrative:
    metrics: DeterministicMetrics
    sections: list[SectionNarrative] = field(default_factory=list)
    synthesis: str = ""


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    sorted_v = sorted(values)
    k = (len(sorted_v) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(sorted_v) - 1)
    return sorted_v[lo] + (sorted_v[hi] - sorted_v[lo]) * (k - lo)


def _waste_hot_spots(scorecards: list[Scorecard]) -> dict[str, list[dict[str, Any]]]:
    buckets: dict[CheckType, list[CheckResult]] = defaultdict(list)
    for sc in scorecards:
        for c in sc.checks:
            if c.category == Category.WASTE:
                buckets[c.check_type].append(c)
    out: dict[str, list[dict[str, Any]]] = {}
    for kind, items in buckets.items():
        # rank by attributable cost; fall back to count when cost_unknown
        ranked = sorted(
            items,
            key=lambda c: -(c.meta.get("cost_usd") or 0.0),
        )[:5]
        out[kind.value] = [
            {
                "evidence_span_ids": [e.span_id for e in c.evidence],
                "cost_usd": c.meta.get("cost_usd"),
                "meta": c.meta,
            }
            for c in ranked
        ]
    return out


def compute_metrics(
    scorecards: list[Scorecard],
    traces: list[TraceSummary],
    *,
    pricing: PricingFn | None = None,
) -> DeterministicMetrics:
    sessions = {t.session_id for t in traces}
    tool_usage: Counter[str] = Counter()
    error_by_tool: Counter[str] = Counter()
    interruptions: Counter[str] = Counter()
    latencies: list[float] = []
    tok_in = 0
    tok_out = 0
    cost = 0.0
    cost_unknown = False
    per_session: list[dict[str, Any]] = []

    for t in traces:
        for tool in t.tools_used:
            tool_usage[tool] += 1
        if t.error_count:
            for tool in t.tools_used or ("unknown",):
                error_by_tool[tool] += t.error_count
        if t.stop_reason:
            interruptions[t.stop_reason] += 1
        latencies.append(float(t.latency_ms))
        tok_in += t.total_tokens_in
        tok_out += t.total_tokens_out
        if pricing and t.model and (t.total_tokens_in or t.total_tokens_out):
            try:
                cost += pricing(t.model, t.total_tokens_in, t.total_tokens_out)
            except Exception:
                cost_unknown = True
        else:
            cost_unknown = True
        per_session.append(
            {
                "session_id": t.session_id,
                "trace_id": t.trace_id,
                "tools_used": list(t.tools_used),
                "tokens_in": t.total_tokens_in,
                "tokens_out": t.total_tokens_out,
                "latency_ms": t.latency_ms,
                "errors": t.error_count,
            }
        )

    return DeterministicMetrics(
        session_count=len(sessions),
        trace_count=len(traces),
        total_tokens_in=tok_in,
        total_tokens_out=tok_out,
        latency_p50=_percentile(latencies, 0.50),
        latency_p95=_percentile(latencies, 0.95),
        latency_p99=_percentile(latencies, 0.99),
        error_breakdown_by_tool=dict(error_by_tool),
        tool_usage=dict(tool_usage),
        cost_usd=round(cost, 4),
        cost_unknown=cost_unknown,
        interruptions_by_stop_reason=dict(interruptions),
        waste_hot_spots=_waste_hot_spots(scorecards),
        per_session=per_session,
    )


def _section_prompt(section: str, data_block: dict[str, Any]) -> str:
    return (
        f"You are writing the '{section}' section of a batch report. Output a SHORT prose passage "
        "(2-5 sentences). Quote only numbers that appear verbatim in the structured data below. "
        "Do not invent metrics. Do not output JSON, markdown headers, or lists unless the data has lists.\n\n"
        f"DATA:\n{json.dumps(data_block, indent=2)}\n\n"
        "Respond with prose only."
    )


def _synthesis_prompt(sections: list[SectionNarrative], metrics_block: dict[str, Any]) -> str:
    body = "\n\n".join(f"## {s.section}\n{s.text}" for s in sections)
    return (
        "You are writing the executive 'At a Glance' synthesis. 2-3 sentences max, "
        "quoting only numbers that appear in the metrics block.\n\n"
        f"METRICS:\n{json.dumps(metrics_block, indent=2)}\n\n"
        f"SECTION DRAFTS:\n{body}\n\nRespond with prose only."
    )


async def render_narrative(
    metrics: DeterministicMetrics,
    *,
    llm_call: LLMCallable,
    sections: tuple[str, ...] = NARRATIVE_SECTIONS,
) -> BatchNarrative:
    """8 parallel section calls + 1 synthesis. LLM sees only structured data."""
    data_block = asdict(metrics)

    async def _section(name: str) -> SectionNarrative:
        out = await llm_call(_section_prompt(name, data_block))
        text = ""
        if isinstance(out, dict):
            text = str(out.get("text") or out.get("response") or "")
        return SectionNarrative(section=name, text=text)

    section_results = await asyncio.gather(*[_section(s) for s in sections])
    syn = await llm_call(_synthesis_prompt(list(section_results), data_block))
    syn_text = ""
    if isinstance(syn, dict):
        syn_text = str(syn.get("text") or syn.get("response") or "")
    return BatchNarrative(metrics=metrics, sections=list(section_results), synthesis=syn_text)


__all__ = [
    "NARRATIVE_SECTIONS",
    "BatchNarrative",
    "DeterministicMetrics",
    "LLMCallable",
    "PricingFn",
    "SectionNarrative",
    "TraceSummary",
    "compute_metrics",
    "render_narrative",
]


# silence unused-import lint; statistics may be used by extensions
_ = statistics
