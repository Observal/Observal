# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
#
# SPDX-License-Identifier: AGPL-3.0-only

"""SDK Phase 2: state_writes capture + outcome-check primary path."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "observal-server"))


from schemas.telemetry import SpanIngest, StateWriteIn
from services.eval.alignment.engine import align_and_score
from services.eval.alignment.outcome_checks import (
    check_state_changed,
    check_state_equals,
)
from services.eval.spec_dag.models import (
    OutcomeAssertion,
    OutcomeCheck,
    OutcomeCheckType,
    SpecDAG,
    SpecSource,
)
from services.eval.trace_dag.builder import build_trace_dag
from services.eval.trace_dag.models import StateWrite
from services.span_enrichment import hash_state_value


def _span(span_id, *, start, output=None, type_="tool_call", state_writes=None, parallel=None):
    base = {
        "span_id": span_id,
        "trace_id": "t1",
        "parent_span_id": None,
        "type": type_,
        "name": "tool",
        "method": "",
        "input": None,
        "output": output,
        "output_excerpt": (output[:128] if isinstance(output, str) else None),
        "tool_result_hash": None,
        "files_read": [],
        "files_written": [],
        "intent_label": None,
        "references": [],
        "start_time": start,
        "end_time": start + 1,
        "status": "success",
        "metadata": {},
    }
    if state_writes is not None:
        base["state_writes"] = state_writes
    if parallel is not None:
        ns, keys, hashes = parallel
        base["state_write_namespaces"] = ns
        base["state_write_keys"] = keys
        base["state_write_value_hashes"] = hashes
    return base


# ── hash_state_value determinism ──


class TestHashStateValue:
    def test_deterministic(self):
        assert hash_state_value({"a": 1, "b": 2}) == hash_state_value({"a": 1, "b": 2})

    def test_key_order_invariant(self):
        assert hash_state_value({"a": 1, "b": 2}) == hash_state_value({"b": 2, "a": 1})

    def test_distinguishes_values(self):
        assert hash_state_value("cancelled") != hash_state_value("active")

    def test_handles_primitives_and_collections(self):
        assert len(hash_state_value(42)) == 64
        assert len(hash_state_value("x")) == 64
        assert len(hash_state_value([1, 2, 3])) == 64


# ── SpanIngest schema accepts state_writes ──


class TestSpanIngestSchema:
    def test_state_writes_field(self):
        s = SpanIngest(
            span_id="s1",
            trace_id="t1",
            type="tool_call",
            name="x",
            start_time="2026-05-08T00:00:00Z",
            state_writes=[
                StateWriteIn(namespace="memory", key="order_status", value_hash="abc"),
            ],
        )
        assert s.state_writes is not None
        assert s.state_writes[0].namespace == "memory"

    def test_optional(self):
        s = SpanIngest(span_id="s", trace_id="t", type="x", name="y", start_time="2026-05-08T00:00:00Z")
        assert s.state_writes is None


# ── builder reads both shapes ──


class TestTraceNodeStateWrites:
    def test_reads_list_of_dicts(self):
        spans = [
            _span(
                "a",
                start=1,
                state_writes=[
                    {"namespace": "kv", "key": "x", "value_hash": "h1"},
                    {"namespace": "kv", "key": "y", "value_hash": "h2"},
                ],
            )
        ]
        dag = build_trace_dag(spans)
        sws = dag.nodes["a"].state_writes
        assert len(sws) == 2
        assert sws[0] == StateWrite(namespace="kv", key="x", value_hash="h1")

    def test_reads_parallel_arrays(self):
        spans = [_span("a", start=1, parallel=(["kv", "kv"], ["x", "y"], ["h1", "h2"]))]
        dag = build_trace_dag(spans)
        sws = dag.nodes["a"].state_writes
        assert len(sws) == 2
        assert sws[1].key == "y"

    def test_absent_is_empty_tuple(self):
        spans = [_span("a", start=1)]
        dag = build_trace_dag(spans)
        assert dag.nodes["a"].state_writes == ()


# ── outcome checks: STATE_EQUALS via state_writes ──


class TestStateEqualsViaStateWrites:
    def test_passes_when_last_write_matches(self):
        target_hash = hash_state_value("cancelled")
        spans = [
            _span(
                "a",
                start=1,
                state_writes=[{"namespace": "orders", "key": "12345", "value_hash": hash_state_value("active")}],
            ),
            _span("b", start=2, state_writes=[{"namespace": "orders", "key": "12345", "value_hash": target_hash}]),
        ]
        dag = build_trace_dag(spans)
        passed, meta = check_state_equals(dag, {"namespace": "orders", "key": "12345", "expected_value": "cancelled"})
        assert passed
        assert meta["source"] == "state_writes"
        assert meta["matched_span_id"] == "b"

    def test_fails_with_clear_meta(self):
        spans = [
            _span(
                "a",
                start=1,
                state_writes=[{"namespace": "orders", "key": "12345", "value_hash": hash_state_value("active")}],
            )
        ]
        dag = build_trace_dag(spans)
        passed, meta = check_state_equals(dag, {"namespace": "orders", "key": "12345", "expected_value": "cancelled"})
        assert not passed
        assert meta["reason"] == "state not equal"
        assert meta["expected_hash"] != meta["observed_hash"]

    def test_takes_last_write_not_first(self):
        """Even if a write matched mid-trace, the LAST write is what we score against."""
        target_hash = hash_state_value("active")
        spans = [
            _span("a", start=1, state_writes=[{"namespace": "o", "key": "1", "value_hash": target_hash}]),
            _span(
                "b", start=2, state_writes=[{"namespace": "o", "key": "1", "value_hash": hash_state_value("cancelled")}]
            ),
        ]
        dag = build_trace_dag(spans)
        passed, _ = check_state_equals(dag, {"namespace": "o", "key": "1", "expected_value": "active"})
        assert not passed  # final state is "cancelled", not "active"


class TestStateEqualsFallback:
    def test_uses_output_scan_when_no_state_writes(self):
        spans = [_span("a", start=1, output="orders.12345 = cancelled now")]
        dag = build_trace_dag(spans)
        passed, meta = check_state_equals(dag, {"namespace": "orders", "key": "12345", "expected_value": "cancelled"})
        assert passed
        assert meta["source"] == "output_scan_fallback"

    def test_unobservable(self):
        spans = [_span("a", start=1, output="unrelated content")]
        dag = build_trace_dag(spans)
        passed, meta = check_state_equals(dag, {"namespace": "orders", "key": "12345", "expected_value": "cancelled"})
        assert not passed
        assert meta["reason"] == "state not observable"


# ── outcome checks: STATE_CHANGED ──


class TestStateChanged:
    def test_via_state_writes(self):
        spans = [
            _span(
                "a", start=1, state_writes=[{"namespace": "o", "key": "1", "value_hash": hash_state_value("active")}]
            ),
            _span(
                "b", start=2, state_writes=[{"namespace": "o", "key": "1", "value_hash": hash_state_value("cancelled")}]
            ),
        ]
        dag = build_trace_dag(spans)
        passed, meta = check_state_changed(
            dag,
            {
                "namespace": "o",
                "key": "1",
                "from_value": "active",
                "to_value": "cancelled",
            },
        )
        assert passed
        assert meta["source"] == "state_writes"
        assert meta["from_span"] == "a"
        assert meta["to_span"] == "b"

    def test_to_after_from_required(self):
        spans = [
            _span(
                "a", start=1, state_writes=[{"namespace": "o", "key": "1", "value_hash": hash_state_value("cancelled")}]
            ),
            _span(
                "b", start=2, state_writes=[{"namespace": "o", "key": "1", "value_hash": hash_state_value("active")}]
            ),
        ]
        dag = build_trace_dag(spans)
        passed, _ = check_state_changed(
            dag,
            {
                "namespace": "o",
                "key": "1",
                "from_value": "active",
                "to_value": "cancelled",
            },
        )
        assert not passed  # cancelled appears BEFORE active


# ── End-to-end alignment with state_writes ──


class TestEndToEndAlignment:
    def test_alignment_uses_state_writes_primary(self):
        spec = SpecDAG(
            task_type="cancel_order",
            version="1",
            source=SpecSource.HAND_AUTHORED,
            outcome_assertions=[
                OutcomeAssertion(
                    assertion_id="status_cancelled",
                    description="order ends in cancelled state",
                    check=OutcomeCheck(
                        check_type=OutcomeCheckType.STATE_EQUALS,
                        params={"namespace": "orders", "key": "12345", "expected_value": "cancelled"},
                    ),
                    weight=1.0,
                    required=True,
                ),
            ],
        )
        spans = [
            _span(
                "a",
                start=1,
                state_writes=[{"namespace": "orders", "key": "12345", "value_hash": hash_state_value("cancelled")}],
            ),
            _span("z", start=2, type_="agent_to_user", output="done"),
        ]
        dag = build_trace_dag(spans)
        result = align_and_score(spec, dag)
        assert result.correctness_score == 1.0

    def test_alignment_falls_back_for_legacy_spans(self):
        """Span with no state_writes still scores via output scan."""
        spec = SpecDAG(
            task_type="t",
            version="1",
            source=SpecSource.HAND_AUTHORED,
            outcome_assertions=[
                OutcomeAssertion(
                    assertion_id="ns_set",
                    check=OutcomeCheck(
                        check_type=OutcomeCheckType.STATE_EQUALS,
                        params={"namespace": "kv", "key": "k", "expected_value": "v"},
                    ),
                    weight=1.0,
                    required=True,
                ),
            ],
        )
        spans = [
            _span("a", start=1, output="kv.k = v completed"),
            _span("z", start=2, type_="agent_to_user", output="ok"),
        ]
        dag = build_trace_dag(spans)
        result = align_and_score(spec, dag)
        assert result.correctness_score == 1.0


# ── Round-trip via SpanIngest dict ──


class TestRoundTrip:
    def test_serialization_through_span_ingest(self):
        sw = StateWriteIn(namespace="memory", key="x", value_hash=hash_state_value("v"))
        s = SpanIngest(
            span_id="s1",
            trace_id="t1",
            type="tool_call",
            name="rec",
            start_time="2026-05-08T00:00:00Z",
            state_writes=[sw],
        )
        # what telemetry route writes to ClickHouse:
        row = {
            "state_write_namespaces": [w.namespace for w in (s.state_writes or [])],
            "state_write_keys": [w.key for w in (s.state_writes or [])],
            "state_write_value_hashes": [w.value_hash for w in (s.state_writes or [])],
        }
        # Round-trip back to TraceNode
        spans = [
            _span(
                "s1",
                start=1,
                parallel=(
                    row["state_write_namespaces"],
                    row["state_write_keys"],
                    row["state_write_value_hashes"],
                ),
            )
        ]
        dag = build_trace_dag(spans)
        sws = dag.nodes["s1"].state_writes
        assert len(sws) == 1
        assert sws[0].namespace == "memory"
        assert sws[0].value_hash == sw.value_hash
