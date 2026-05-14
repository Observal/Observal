# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Waste classification — deterministic, from Trace DAG only.

Emits CheckResults under category=waste. Cost attribution lives in
`meta.cost_usd` and `meta.tokens` when input/output token counts are
present on the underlying span; otherwise meta carries `cost_unknown=True`.

This module is pure: it does not call pricing services. The caller may
inject a `pricing_fn(model: str, tok_in: int, tok_out: int) -> float`
to attribute USD; default is None (cost_unknown).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from services.eval.check_result.models import (
    Category,
    CheckResult,
    CheckType,
    SpanRef,
    Status,
)
from services.eval.trace_dag.derivations import (
    effective_nodes,
    find_redundant_reads,
    find_reverts,
)

if TYPE_CHECKING:
    from services.eval.trace_dag.models import TraceDAG, TraceNode

PricingFn = Callable[[str, int, int], float]


def _cost_meta(node: TraceNode, pricing: PricingFn | None) -> dict[str, Any]:
    tok_in = 0
    tok_out = 0
    md = node.metadata or {}
    try:
        tok_in = int(md.get("token_count_input") or md.get("input_tokens") or 0)
        tok_out = int(md.get("token_count_output") or md.get("output_tokens") or 0)
    except (TypeError, ValueError):
        tok_in = tok_out = 0
    model = md.get("model") or md.get("gen_ai.request.model") or ""
    if pricing and (tok_in or tok_out) and model:
        try:
            cost = pricing(model, tok_in, tok_out)
            return {"tokens_in": tok_in, "tokens_out": tok_out, "model": model, "cost_usd": cost}
        except Exception:
            pass
    return {"tokens_in": tok_in, "tokens_out": tok_out, "model": model, "cost_unknown": True}


def _detect_cycles(dag: TraceDAG) -> list[list[str]]:
    """Action repetition cycles: same `(method|name, file_path)` repeated 3+ times."""
    sequence: list[tuple[str, str]] = []
    span_ids: list[str] = []
    for sid in dag.topo_sorted_ids():
        n = dag.nodes[sid]
        key = (n.method or n.name, "|".join(sorted(n.files_read + n.files_written)))
        sequence.append(key)
        span_ids.append(sid)

    cycles: list[list[str]] = []
    n = len(sequence)
    for cycle_len in (1, 2, 3):
        i = 0
        while i + cycle_len * 3 <= n:
            window = sequence[i : i + cycle_len]
            repeats = 1
            j = i + cycle_len
            while j + cycle_len <= n and sequence[j : j + cycle_len] == window:
                repeats += 1
                j += cycle_len
            if repeats >= 3:
                cycles.append(span_ids[i:j])
                i = j
            else:
                i += 1
    return cycles


def classify_waste(
    dag: TraceDAG,
    *,
    pricing: PricingFn | None = None,
) -> list[CheckResult]:
    """Pure: produce CheckResult[] with waste category."""
    out: list[CheckResult] = []

    eff = effective_nodes(dag)

    # WASTE_REVERT
    for pair in find_reverts(dag):
        earlier = dag.nodes.get(pair.earlier)
        if earlier is None:
            continue
        meta = _cost_meta(earlier, pricing)
        meta.update({"reverted_by": pair.later, "file": pair.file, "method": pair.method})
        out.append(
            CheckResult(
                check_type=CheckType.WASTE_REVERT,
                status=Status.WARN,
                weight=1.0,
                points_earned=0.0,
                points_possible=1.0,
                evidence=[
                    SpanRef(span_id=pair.earlier, trace_id=dag.trace_id),
                    SpanRef(span_id=pair.later, trace_id=dag.trace_id),
                ],
                category=Category.WASTE,
                meta=meta,
            )
        )

    # WASTE_CYCLE
    for cycle_span_ids in _detect_cycles(dag):
        first_node = dag.nodes.get(cycle_span_ids[0])
        if first_node is None:
            continue
        meta = _cost_meta(first_node, pricing)
        meta["span_count"] = len(cycle_span_ids)
        out.append(
            CheckResult(
                check_type=CheckType.WASTE_CYCLE,
                status=Status.WARN,
                weight=1.0,
                points_earned=0.0,
                points_possible=1.0,
                evidence=[SpanRef(span_id=sid, trace_id=dag.trace_id) for sid in cycle_span_ids],
                category=Category.WASTE,
                meta=meta,
            )
        )

    # WASTE_REDUNDANT_READ
    for earlier_sid, later_sid in find_redundant_reads(dag):
        later = dag.nodes.get(later_sid)
        if later is None:
            continue
        meta = _cost_meta(later, pricing)
        meta["redundant_with"] = earlier_sid
        out.append(
            CheckResult(
                check_type=CheckType.WASTE_REDUNDANT_READ,
                status=Status.WARN,
                weight=0.5,
                points_earned=0.0,
                points_possible=0.5,
                evidence=[
                    SpanRef(span_id=earlier_sid, trace_id=dag.trace_id),
                    SpanRef(span_id=later_sid, trace_id=dag.trace_id),
                ],
                category=Category.WASTE,
                meta=meta,
            )
        )

    # WASTE_DEAD_END — span not in effective set and not already counted as revert
    reverted_earlier = {p.earlier for p in find_reverts(dag)}
    for sid in dag.topo_sorted_ids():
        if sid in eff or sid in reverted_earlier:
            continue
        node = dag.nodes[sid]
        meta = _cost_meta(node, pricing)
        out.append(
            CheckResult(
                check_type=CheckType.WASTE_DEAD_END,
                status=Status.WARN,
                weight=0.5,
                points_earned=0.0,
                points_possible=0.5,
                evidence=[SpanRef(span_id=sid, trace_id=dag.trace_id)],
                category=Category.WASTE,
                meta=meta,
            )
        )

    return out
