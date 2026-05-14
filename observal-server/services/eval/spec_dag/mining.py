# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Mine an outcome-oriented Spec DAG from a set of gold traces.

Replaces the v1 path-oriented miner. We extract what was true at the END
of every gold trace (responses, tool calls with shared params, files
written, state observed in outputs) and turn those into OutcomeAssertions.
Step constraints are produced very conservatively — only when there's a
clear safety relationship (auth-before-mutation pattern) — and always at
``severity="soft"``. Humans promote to ``"hard"`` after review. Domain
invariants are never mined.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

from services.eval.spec_dag.models import (
    OutcomeAssertion,
    OutcomeCheck,
    OutcomeCheckType,
    SpecDAG,
    SpecSource,
    StepConstraint,
)
from services.eval.trace_dag.helpers import tool_key

if TYPE_CHECKING:
    from services.eval.trace_dag.models import TraceDAG


def _final_response_text(dag: TraceDAG) -> str:
    """Best-effort — last span's output_excerpt or output."""
    ids = dag.topo_sorted_ids()
    for sid in reversed(ids):
        node = dag.nodes[sid]
        text = node.output_excerpt or node.output or ""
        if text:
            return text
    return ""


def _longest_common_substring(strings: list[str]) -> str:
    if not strings:
        return ""
    s0 = strings[0]
    best = ""
    # cubic-ish but bounded by output_excerpt cap (2KB)
    for length in range(min(len(s) for s in strings), 7, -1):
        for start in range(0, len(s0) - length + 1):
            cand = s0[start : start + length]
            if all(cand in s for s in strings[1:]):
                if len(cand) > len(best):
                    best = cand
                break  # one match per length is enough; move on
        if best:
            break
    return best


# Loose heuristic for "auth before mutation" candidates.
_AUTH_TOKENS = ("verify", "auth", "check", "validate", "confirm", "lookup")
_MUTATE_TOKENS = ("update", "delete", "modify", "send", "execute", "create", "write")


def _is_safety_pair(before: str, after: str) -> bool:
    bl = before.lower()
    al = after.lower()
    if not any(tok in bl for tok in _AUTH_TOKENS):
        return False
    return any(tok in al for tok in _MUTATE_TOKENS)


def _mine_outcome_assertions(traces: list[TraceDAG]) -> list[OutcomeAssertion]:
    n = len(traces)
    assertions: list[OutcomeAssertion] = []

    # 1. Response substring across all traces
    finals = [_final_response_text(t) for t in traces]
    if all(finals):
        common = _longest_common_substring(finals)
        if common:
            assertions.append(
                OutcomeAssertion(
                    assertion_id="response_common_substring",
                    description=f"final response contains: {common!r}",
                    check=OutcomeCheck(
                        check_type=OutcomeCheckType.RESPONSE_CONTAINS,
                        params={"pattern": common, "match_type": "substring"},
                    ),
                    weight=1.0,
                    required=True,
                )
            )

    # 2. Tools called in every trace + tools in >50% (weight 0.5)
    tool_counts: Counter[str] = Counter()
    per_trace_calls: list[dict[str, list[dict[str, Any]]]] = []
    for trace in traces:
        seen_in_trace: dict[str, list[dict[str, Any]]] = {}
        for sid in trace.topo_sorted_ids():
            node = trace.nodes[sid]
            key = tool_key(node)
            if not key:
                continue
            params: dict[str, Any] = {}
            if node.input:
                try:
                    import json as _json

                    parsed = _json.loads(node.input)
                    if isinstance(parsed, dict):
                        params = parsed
                except (ValueError, TypeError):
                    params = {}
            seen_in_trace.setdefault(key, []).append(params)
        per_trace_calls.append(seen_in_trace)
        for key in seen_in_trace:
            tool_counts[key] += 1

    for tool, count in tool_counts.items():
        if count == n:
            shared = _shared_param_constraints(tool, per_trace_calls)
            params: dict[str, Any] = {"tool_name": tool, "min_count": 1}
            if shared:
                params["param_constraints"] = shared
            assertions.append(
                OutcomeAssertion(
                    assertion_id=f"tool_{tool}",
                    description=f"{tool} called in every gold trace",
                    check=OutcomeCheck(check_type=OutcomeCheckType.TOOL_WAS_CALLED, params=params),
                    weight=1.0,
                    required=True,
                )
            )
        elif count > n / 2:
            assertions.append(
                OutcomeAssertion(
                    assertion_id=f"tool_{tool}_frequent",
                    description=f"{tool} called in {count}/{n} gold traces",
                    check=OutcomeCheck(
                        check_type=OutcomeCheckType.TOOL_WAS_CALLED,
                        params={"tool_name": tool, "min_count": 1},
                    ),
                    weight=0.5,
                    required=False,
                )
            )

    # 3. Artifacts: file paths written in every trace
    files_per_trace: list[set[str]] = []
    for trace in traces:
        files_in_trace: set[str] = set()
        for sid in trace.topo_sorted_ids():
            files_in_trace.update(trace.nodes[sid].files_written)
        files_per_trace.append(files_in_trace)
    if files_per_trace and all(files_per_trace):
        common_files = set.intersection(*files_per_trace)
        for path in sorted(common_files):
            assertions.append(
                OutcomeAssertion(
                    assertion_id=f"artifact_{path}",
                    description=f"file written in every gold trace: {path}",
                    check=OutcomeCheck(
                        check_type=OutcomeCheckType.ARTIFACT_EXISTS,
                        params={"path_pattern": path},
                    ),
                    weight=1.0,
                    required=True,
                )
            )

    return assertions


def _shared_param_constraints(tool: str, per_trace_calls: list[dict[str, list[dict[str, Any]]]]) -> dict[str, Any]:
    """Return params whose value was identical for some call to `tool` in every trace."""
    if not per_trace_calls:
        return {}
    candidates: dict[str, set[Any]] | None = None
    for trace_calls in per_trace_calls:
        calls = trace_calls.get(tool, [])
        if not calls:
            return {}
        # take the union over calls in *this* trace
        per_trace: dict[str, set[Any]] = {}
        for params in calls:
            for k, v in params.items():
                try:
                    per_trace.setdefault(k, set()).add(_freeze(v))
                except TypeError:
                    continue
        if candidates is None:
            candidates = per_trace
        else:
            new_candidates: dict[str, set[Any]] = {}
            for k, vals in candidates.items():
                if k in per_trace:
                    common = vals & per_trace[k]
                    if common:
                        new_candidates[k] = common
            candidates = new_candidates
        if not candidates:
            return {}
    out: dict[str, Any] = {}
    for k, vals in (candidates or {}).items():
        if len(vals) == 1:
            out[k] = next(iter(vals))
    return out


def _freeze(v: Any) -> Any:
    if isinstance(v, dict):
        return tuple(sorted((k, _freeze(val)) for k, val in v.items()))
    if isinstance(v, list):
        return tuple(_freeze(x) for x in v)
    return v


def _mine_step_constraints(traces: list[TraceDAG]) -> list[StepConstraint]:
    """Conservative: emit only safety-relationship pairs that hold in every trace."""
    if not traces:
        return []
    universal_pairs: set[tuple[str, str]] | None = None
    for trace in traces:
        seq = [(tool_key(trace.nodes[sid]), trace.nodes[sid].start_time_ms) for sid in trace.topo_sorted_ids()]
        seq = [(k, t) for k, t in seq if k]
        pairs: set[tuple[str, str]] = set()
        for i in range(len(seq)):
            for j in range(i + 1, len(seq)):
                ki, kj = seq[i][0], seq[j][0]
                if ki != kj and seq[i][1] <= seq[j][1]:
                    pairs.add((ki, kj))
        universal_pairs = pairs if universal_pairs is None else universal_pairs & pairs
    if not universal_pairs:
        return []
    out: list[StepConstraint] = []
    for before, after in sorted(universal_pairs):
        if not _is_safety_pair(before, after):
            continue
        out.append(
            StepConstraint(
                constraint_id=f"safety_{before}_before_{after}",
                description=f"{before!r} appears before {after!r} in every gold trace; review if this is a safety constraint",
                before_tool=before,
                after_tool=after,
                weight=1.0,
                severity="soft",
            )
        )
    return out


def mine_spec_from_gold_traces(
    task_type: str,
    traces: list[TraceDAG],
    *,
    version: str = "mined-1",
) -> SpecDAG:
    """Extract an outcome-oriented spec from gold traces."""
    if not traces:
        return SpecDAG(task_type=task_type, version=version, source=SpecSource.MINED)

    return SpecDAG(
        task_type=task_type,
        version=version,
        source=SpecSource.MINED,
        outcome_assertions=_mine_outcome_assertions(traces),
        step_constraints=_mine_step_constraints(traces),
        domain_invariants=[],  # never mined
    )


# Back-compat alias for older callers (test file imports `mine`)
def mine(task_type: str, gold: list[TraceDAG], *, version: str = "mined-1") -> SpecDAG:
    return mine_spec_from_gold_traces(task_type, gold, version=version)


__all__ = ["mine", "mine_spec_from_gold_traces"]
