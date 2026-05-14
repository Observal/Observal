# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for unified eval Phase 1 — deterministic substrate.

Covers acceptance criteria stated in the unified prompt:
- alignment determinism (same inputs → identical CheckResults)
- score-of-1.0 on a known-good trace + spec
- exactly-one MISSING when a required tool call is removed
- Trace DAG construction edge cases (orphans, cycles, missing parent_ids,
  missing files_touched fallback)
- waste classification on hand-built reverts/cycles/redundant reads
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "observal-server"))

import pytest

from services.eval.aggregation.scorecard import (
    ScoringMode,
    aggregate,
    council_deductive_score,
    spec_dag_alignment_score,
)
from services.eval.check_result.models import (
    Category,
    CheckResult,
    CheckType,
    SpanRef,
    Status,
)
from services.eval.trace_dag.builder import build_trace_dag
from services.eval.trace_dag.derivations import (
    cluster_writes,
    effective_nodes,
    find_redundant_reads,
    find_reverts,
    intent_ancestor,
)
from services.eval.trace_dag.models import Confidence, EdgeKind
from services.eval.waste.classifier import classify_waste

# ── helpers ──


def _span(
    span_id,
    name,
    *,
    parent=None,
    start=0,
    output=None,
    files_read=None,
    files_written=None,
    intent=None,
    method=None,
    hash_=None,
    input_=None,
    metadata=None,
    type_="tool_call",
    status="success",
):
    return {
        "span_id": span_id,
        "trace_id": "t1",
        "parent_span_id": parent,
        "type": type_,
        "name": name,
        "method": method or "",
        "input": input_,
        "output": output,
        "output_excerpt": output[:128] if isinstance(output, str) else None,
        "tool_result_hash": hash_,
        "files_read": files_read or [],
        "files_written": files_written or [],
        "intent_label": intent,
        "references": [],
        "start_time": start,
        "end_time": start + 1,
        "status": status,
        "metadata": metadata or {},
    }


# ── CheckResult basics ──


class TestCheckResult:
    def test_invariants(self):
        c = CheckResult(
            check_type=CheckType.MATCHED,
            status=Status.PASS,
            weight=1.0,
            points_earned=1.0,
            points_possible=1.0,
            evidence=[SpanRef(span_id="s1")],
            category=Category.CORRECTNESS,
        )
        assert c.points_earned == c.points_possible

    def test_negative_points_rejected(self):
        with pytest.raises(ValueError):
            CheckResult(
                check_type=CheckType.MATCHED,
                status=Status.PASS,
                weight=1.0,
                points_earned=-0.1,
                points_possible=1.0,
                category=Category.CORRECTNESS,
            )

    def test_overshoot_rejected(self):
        with pytest.raises(ValueError):
            CheckResult(
                check_type=CheckType.MATCHED,
                status=Status.PASS,
                weight=1.0,
                points_earned=2.0,
                points_possible=1.0,
                category=Category.CORRECTNESS,
            )


# ── Trace DAG construction ──


class TestBuildTraceDAG:
    def test_basic(self):
        spans = [
            _span("a", "Read", start=10),
            _span("b", "Write", parent="a", start=20),
        ]
        dag = build_trace_dag(spans)
        assert set(dag.nodes) == {"a", "b"}
        assert any(e.src == "a" and e.dst == "b" and e.kind == EdgeKind.PARENT for e in dag.edges)

    def test_orphan_span_does_not_crash(self):
        spans = [_span("a", "Read", parent="ghost", start=1)]
        dag = build_trace_dag(spans)
        assert "a" in dag.nodes
        assert all(e.kind != EdgeKind.PARENT for e in dag.edges)  # ghost parent not present

    def test_duplicate_span_id_dedup(self):
        spans = [_span("a", "Read", start=1), _span("a", "Read", start=2)]
        dag = build_trace_dag(spans)
        assert list(dag.nodes) == ["a"]

    def test_unix_epoch_seconds_are_converted_to_ms(self):
        dag = build_trace_dag([_span("a", "Read", start=1_750_000_000)])
        assert dag.nodes["a"].start_time_ms == 1_750_000_000_000

    def test_unix_epoch_ms_are_preserved(self):
        dag = build_trace_dag([_span("a", "Read", start=1_750_000_000_000)])
        assert dag.nodes["a"].start_time_ms == 1_750_000_000_000

    def test_missing_parent_id_no_parent_edge(self):
        spans = [_span("a", "Read", start=1), _span("b", "Write", start=2)]
        dag = build_trace_dag(spans)
        assert all(e.kind != EdgeKind.PARENT for e in dag.edges)

    def test_file_touch_edge_inferred(self):
        spans = [
            _span("w", "Write", start=1, files_written=["/x"]),
            _span("r", "Read", start=2, files_read=["/x"]),
        ]
        dag = build_trace_dag(spans)
        assert any(e.kind == EdgeKind.FILE_TOUCH and e.src == "w" and e.dst == "r" for e in dag.edges)

    def test_data_flow_edge_inferred_low_confidence_without_excerpt(self):
        spans = [
            {**_span("a", "ToolA", start=1, output="UNIQUE_NEEDLE_XYZ_12345"), "output_excerpt": None},
            _span("b", "ToolB", start=2, input_="see UNIQUE_NEEDLE_XYZ_12345 here"),
        ]
        dag = build_trace_dag(spans)
        df = [e for e in dag.edges if e.kind == EdgeKind.DATA_FLOW]
        assert df and df[0].confidence == Confidence.LOW

    def test_data_flow_edge_high_confidence_with_excerpt(self):
        spans = [
            _span("a", "ToolA", start=1, output="UNIQUE_NEEDLE_XYZ_12345 plus"),
            _span("b", "ToolB", start=2, input_="see UNIQUE_NEEDLE_XYZ_12345 plus other"),
        ]
        dag = build_trace_dag(spans)
        df = [e for e in dag.edges if e.kind == EdgeKind.DATA_FLOW]
        assert df and df[0].confidence == Confidence.HIGH

    def test_dag_confidence_low_when_metadata_sparse(self):
        spans = [
            {**_span("a", "ToolA", start=1, output="LONG_DISTINCTIVE_NEEDLE_VALUE"), "output_excerpt": None},
            _span("b", "ToolB", start=2, input_="LONG_DISTINCTIVE_NEEDLE_VALUE"),
        ]
        dag = build_trace_dag(spans)
        assert dag.confidence() == Confidence.LOW


# ── Derivations ──


class TestDerivations:
    def test_find_reverts_hash_match(self):
        # Write A (hash=H1) → Write B (hash=H2) → Write C (hash=H1) ⇒ B is reverted
        spans = [
            _span("a", "Write", start=1, files_written=["/x"], hash_="H1"),
            _span("b", "Write", start=2, files_written=["/x"], hash_="H2"),
            _span("c", "Write", start=3, files_written=["/x"], hash_="H1"),
        ]
        dag = build_trace_dag(spans)
        pairs = find_reverts(dag)
        assert any(p.earlier == "b" and p.method == "hash_match" for p in pairs)

    def test_find_reverts_file_overwrite(self):
        spans = [
            _span("a", "Write", start=1, files_written=["/y"]),
            _span("b", "Write", start=2, files_written=["/y"]),
        ]
        dag = build_trace_dag(spans)
        pairs = find_reverts(dag)
        assert any(p.earlier == "a" and p.later == "b" for p in pairs)

    def test_redundant_read(self):
        spans = [
            _span("r1", "Read", start=1, files_read=["/x"], hash_="H"),
            _span("r2", "Read", start=2, files_read=["/x"], hash_="H"),
        ]
        dag = build_trace_dag(spans)
        assert ("r1", "r2") in find_redundant_reads(dag)

    def test_cluster_writes_groups_by_parent(self):
        spans = [
            _span("p", "Plan", start=1, intent="task_a"),
            _span("w1", "Write", parent="p", start=2, files_written=["/a"]),
            _span("w2", "Write", parent="p", start=3, files_written=["/b"]),
        ]
        dag = build_trace_dag(spans)
        clusters = cluster_writes(dag)
        assert len(clusters) == 1
        assert set(clusters[0].span_ids) == {"w1", "w2"}

    def test_intent_ancestor_walks_up(self):
        spans = [
            _span("root", "Plan", start=1, intent="search_kb"),
            _span("mid", "Tool", parent="root", start=2),
            _span("leaf", "Tool", parent="mid", start=3),
        ]
        dag = build_trace_dag(spans)
        assert intent_ancestor(dag, "leaf") == "root"

    def test_effective_nodes_excludes_reverts_and_dup_reads(self):
        spans = [
            _span("a", "Write", start=1, files_written=["/x"], hash_="H1"),
            _span("b", "Write", start=2, files_written=["/x"], hash_="H2"),
            _span("c", "Write", start=3, files_written=["/x"], hash_="H1"),
            _span("r1", "Read", start=4, files_read=["/x"], hash_="HR"),
            _span("r2", "Read", start=5, files_read=["/x"], hash_="HR"),
        ]
        dag = build_trace_dag(spans)
        eff = effective_nodes(dag)
        assert "b" not in eff  # reverted
        assert "r1" in eff
        assert "r2" not in eff  # dup read


# ── Predicate matchers ──


# (Path-oriented matchers + alignment tests removed in the v2 refactor.
# See tests/test_eval_v2_outcome_alignment.py for outcome-oriented coverage.)


# ── Waste ──


class TestWaste:
    def test_revert_pattern_emits_checks(self):
        spans = [
            _span("a", "Write", start=1, files_written=["/x"], hash_="H1"),
            _span("b", "Write", start=2, files_written=["/x"], hash_="H2"),
            _span("c", "Write", start=3, files_written=["/x"], hash_="H1"),
        ]
        dag = build_trace_dag(spans)
        checks = classify_waste(dag)
        kinds = [c.check_type for c in checks]
        assert CheckType.WASTE_REVERT in kinds
        # B's work was undone → it appears in a revert pair (and may also be flagged dead-end
        # depending on effectiveness — this is the documented overlap).

    def test_revert_then_dead_end(self):
        # A writes, B reverts A, A's output not used → A is dead-end too
        spans = [
            _span("a", "Write", start=1, files_written=["/x"], hash_="H1"),
            _span("b", "Write", start=2, files_written=["/x"], hash_="H2"),
        ]
        dag = build_trace_dag(spans)
        checks = classify_waste(dag)
        kinds = [c.check_type for c in checks]
        assert CheckType.WASTE_REVERT in kinds

    def test_redundant_read_emits_check(self):
        spans = [
            _span("r1", "Read", start=1, files_read=["/x"], hash_="H"),
            _span("r2", "Read", start=2, files_read=["/x"], hash_="H"),
        ]
        dag = build_trace_dag(spans)
        checks = classify_waste(dag)
        assert any(c.check_type == CheckType.WASTE_REDUNDANT_READ for c in checks)

    def test_cycle_detection(self):
        spans = [_span(f"s{i}", "Tool", start=i, files_read=["/x"]) for i in range(1, 10)]
        dag = build_trace_dag(spans)
        checks = classify_waste(dag)
        assert any(c.check_type == CheckType.WASTE_CYCLE for c in checks)

    def test_pricing_fn_attributes_cost(self):
        spans = [
            _span(
                "a",
                "Write",
                start=1,
                files_written=["/x"],
                metadata={"token_count_input": "100", "token_count_output": "50", "model": "claude-opus-4-7"},
            ),
            _span("b", "Write", start=2, files_written=["/x"]),
        ]
        dag = build_trace_dag(spans)
        called = []

        def pricer(model, ti, to_):
            called.append((model, ti, to_))
            return 0.0042

        checks = classify_waste(dag, pricing=pricer)
        revs = [c for c in checks if c.check_type == CheckType.WASTE_REVERT]
        assert revs and revs[0].meta.get("cost_usd") == 0.0042
        assert called

    def test_waste_is_deterministic(self):
        spans = [
            _span("a", "Write", start=1, files_written=["/x"], hash_="H1"),
            _span("b", "Write", start=2, files_written=["/x"], hash_="H2"),
            _span("c", "Write", start=3, files_written=["/x"], hash_="H1"),
        ]
        dag = build_trace_dag(spans)
        first = [c.model_dump() for c in classify_waste(dag)]
        for _ in range(20):
            again = [c.model_dump() for c in classify_waste(dag)]
            assert again == first


# ── Aggregation ──


class TestAggregation:
    def _checks(self):
        return [
            CheckResult(
                check_type=CheckType.MATCHED,
                status=Status.PASS,
                weight=1.0,
                points_earned=1.0,
                points_possible=1.0,
                category=Category.CORRECTNESS,
            ),
            CheckResult(
                check_type=CheckType.MISSING,
                status=Status.FAIL,
                weight=1.0,
                points_earned=0.0,
                points_possible=1.0,
                category=Category.CORRECTNESS,
            ),
            CheckResult(
                check_type=CheckType.WASTE_REVERT,
                status=Status.WARN,
                weight=1.0,
                points_earned=0.0,
                points_possible=1.0,
                category=Category.WASTE,
            ),
        ]

    def test_spec_dag_alignment_ratio(self):
        score, earned, possible = spec_dag_alignment_score(self._checks())
        assert score == pytest.approx(1 / 3)
        assert earned == 1.0 and possible == 3.0

    def test_council_deductive_subtracts_from_100(self):
        score, deduction, base = council_deductive_score(self._checks())
        assert deduction == 2.0  # MISSING + WASTE_REVERT
        assert score == pytest.approx(98.0)
        assert base == 100.0

    def test_aggregate_records_mode(self):
        sc = aggregate(self._checks(), mode=ScoringMode.SPEC_DAG_ALIGNMENT, spec_dag_version="v1")
        assert sc.scoring_mode == ScoringMode.SPEC_DAG_ALIGNMENT
        assert sc.spec_dag_version == "v1"
        assert "correctness" in sc.per_category
        assert "waste" in sc.per_category


# Spec DAG JSON round-trip moved to tests/test_eval_v2_outcome_alignment.py
