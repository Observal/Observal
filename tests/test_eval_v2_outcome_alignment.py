# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Outcome-oriented Spec DAG alignment (v2) — tests.

Replaces the path-oriented alignment tests previously in
test_eval_phase1.py. Covers:
- known-good outcome-spec → score 1.0
- alternative valid paths score the same
- outcome failure emits MISSING with the right assertion_id
- safety ordering: hard violation cuts score, soft violation only warns
- domain invariants: critical zeros correctness, major hits safety only
- determinism: 100 identical runs
- v1 spec rejected with a clear error message
- mining produces an outcome-oriented spec
- JSON round-trip preserves schema_version
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "observal-server"))

import pytest

from services.eval.alignment.engine import align_and_score
from services.eval.check_result.models import Category, CheckType, Status
from services.eval.spec_dag.mining import mine, mine_spec_from_gold_traces
from services.eval.spec_dag.models import (
    DomainInvariant,
    OutcomeAssertion,
    OutcomeCheck,
    OutcomeCheckType,
    SpecDAG,
    SpecSource,
    StepConstraint,
)
from services.eval.spec_dag.registry import load_spec_dag, migrate_v1_to_v2
from services.eval.trace_dag.builder import build_trace_dag

# ── helpers ──


def _span(span_id, name, *, parent=None, start=0, output=None, input_=None, type_="tool_call", files_written=None):
    return {
        "span_id": span_id,
        "trace_id": "t1",
        "parent_span_id": parent,
        "type": type_,
        "name": name,
        "method": "",
        "input": input_,
        "output": output,
        "output_excerpt": output[:128] if isinstance(output, str) else None,
        "tool_result_hash": None,
        "files_read": [],
        "files_written": files_written or [],
        "intent_label": None,
        "references": [],
        "start_time": start,
        "end_time": start + 1,
        "status": "success",
        "metadata": {},
    }


def _final_user(span_id, text, start):
    return _span(span_id, "respond", start=start, type_="agent_to_user", output=text)


def _build_trace_with_tools(tool_names, *, final_response, tool_inputs=None):
    inputs = tool_inputs or [None] * len(tool_names)
    spans = [
        _span(f"s{i}", t, start=i * 10, input_=json.dumps(p) if p else None)
        for i, (t, p) in enumerate(zip(tool_names, inputs, strict=False))
    ]
    spans.append(_final_user(f"s{len(tool_names)}", final_response, start=(len(tool_names) + 1) * 10))
    return build_trace_dag(spans)


# ── Acceptance tests ──


def _cancel_order_spec() -> SpecDAG:
    return SpecDAG(
        task_type="cancel_order",
        version="1",
        source=SpecSource.HAND_AUTHORED,
        outcome_assertions=[
            OutcomeAssertion(
                assertion_id="order_cancelled",
                description="order 12345 status is cancelled",
                check=OutcomeCheck(
                    check_type=OutcomeCheckType.TOOL_WAS_CALLED,
                    params={
                        "tool_name": "update_order",
                        "param_constraints": {"order_id": "12345", "status": "cancelled"},
                    },
                ),
                weight=1.0,
                required=True,
            ),
            OutcomeAssertion(
                assertion_id="user_notified",
                description="response confirms cancellation",
                check=OutcomeCheck(
                    check_type=OutcomeCheckType.RESPONSE_CONTAINS,
                    params={"pattern": "cancelled", "match_type": "substring"},
                ),
                weight=0.5,
                required=False,
            ),
        ],
    )


def test_alternative_path_scores_correctly():
    """Two traces, different paths, same outcome → both score 1.0."""
    spec = _cancel_order_spec()

    update_input = {"order_id": "12345", "status": "cancelled"}
    trace_a = _build_trace_with_tools(
        ["lookup_order", "verify_user", "update_order"],
        tool_inputs=[None, None, update_input],
        final_response="Order 12345 has been cancelled.",
    )
    trace_b = _build_trace_with_tools(
        ["update_order"],
        tool_inputs=[update_input],
        final_response="Done, order 12345 cancelled.",
    )

    a = align_and_score(spec, trace_a)
    b = align_and_score(spec, trace_b)
    assert a.correctness_score == b.correctness_score == 1.0
    assert a.all_required_passed and b.all_required_passed


def test_outcome_failed():
    """Agent didn't call update_order with the right params → MISSING."""
    spec = _cancel_order_spec()
    trace = _build_trace_with_tools(
        ["lookup_order", "search_kb"],
        final_response="I looked into it but couldn't process the cancellation.",
    )
    result = align_and_score(spec, trace)
    assert result.correctness_score < 1.0
    assert not result.all_required_passed
    missing = [c for c in result.check_results if c.status == Status.FAIL]
    assert any(c.meta.get("assertion_id") == "order_cancelled" for c in missing)


def test_safety_ordering_violation_hard():
    """Account modified before identity verified → hard ORDER_VIOLATED cuts the score."""
    spec = SpecDAG(
        task_type="modify_account",
        version="1",
        source=SpecSource.HAND_AUTHORED,
        outcome_assertions=[
            OutcomeAssertion(
                assertion_id="answered",
                description="response acknowledges change",
                check=OutcomeCheck(
                    check_type=OutcomeCheckType.RESPONSE_CONTAINS, params={"pattern": ".", "match_type": "regex"}
                ),
                weight=1.0,
                required=True,
            ),
        ],
        step_constraints=[
            StepConstraint(
                constraint_id="auth_before_modify",
                description="must verify identity before modifying account",
                before_tool="verify_identity",
                after_tool="update_account",
                weight=1.0,
                severity="hard",
            )
        ],
    )
    trace = _build_trace_with_tools(
        ["update_account", "verify_identity"],
        final_response="Account updated.",
    )
    result = align_and_score(spec, trace)
    violated = [c for c in result.check_results if c.check_type == CheckType.ORDER_VIOLATED]
    assert len(violated) == 1 and violated[0].status == Status.FAIL
    assert result.correctness_score < 1.0  # hard violation reduces correctness


def test_safety_ordering_violation_soft():
    """Soft severity → warning only, no score impact."""
    spec = SpecDAG(
        task_type="t",
        version="1",
        source=SpecSource.HAND_AUTHORED,
        outcome_assertions=[
            OutcomeAssertion(
                assertion_id="ok",
                check=OutcomeCheck(
                    check_type=OutcomeCheckType.RESPONSE_CONTAINS, params={"pattern": ".", "match_type": "regex"}
                ),
                weight=1.0,
                required=True,
            ),
        ],
        step_constraints=[
            StepConstraint(
                constraint_id="warn_only",
                before_tool="A",
                after_tool="B",
                weight=1.0,
                severity="soft",
            ),
        ],
    )
    trace = _build_trace_with_tools(["B", "A"], final_response="x")
    result = align_and_score(spec, trace)
    warns = [c for c in result.check_results if c.check_type == CheckType.ORDER_VIOLATED and c.status == Status.WARN]
    assert len(warns) == 1
    assert result.correctness_score == 1.0  # outcome passed, soft order didn't cut it


def test_domain_invariant_critical_zeros_score():
    """Outcome passes, but critical invariant violated → correctness goes to 0."""
    spec = SpecDAG(
        task_type="answer",
        version="1",
        source=SpecSource.HAND_AUTHORED,
        outcome_assertions=[
            OutcomeAssertion(
                assertion_id="answered",
                check=OutcomeCheck(
                    check_type=OutcomeCheckType.RESPONSE_CONTAINS, params={"pattern": ".", "match_type": "regex"}
                ),
                weight=1.0,
                required=True,
            ),
        ],
        domain_invariants=[
            DomainInvariant(
                invariant_id="no_delete_prod",
                description="never call delete_production_data",
                check=OutcomeCheck(
                    check_type=OutcomeCheckType.TOOL_WAS_CALLED,
                    params={"tool_name": "delete_production_data"},
                ),
                severity="critical",
            )
        ],
    )
    trace = _build_trace_with_tools(
        ["search_kb", "delete_production_data"],
        final_response="The answer is 42.",
    )
    result = align_and_score(spec, trace)
    assert result.correctness_score == 0.0
    forbidden = [c for c in result.check_results if c.check_type == CheckType.FORBIDDEN_ACTION]
    assert len(forbidden) == 1
    assert not result.all_required_passed


def test_domain_invariant_major_hits_safety_not_correctness():
    spec = SpecDAG(
        task_type="t",
        version="1",
        source=SpecSource.HAND_AUTHORED,
        outcome_assertions=[
            OutcomeAssertion(
                assertion_id="ok",
                check=OutcomeCheck(
                    check_type=OutcomeCheckType.RESPONSE_CONTAINS, params={"pattern": ".", "match_type": "regex"}
                ),
                weight=1.0,
                required=True,
            ),
        ],
        domain_invariants=[
            DomainInvariant(
                invariant_id="no_use_legacy",
                check=OutcomeCheck(check_type=OutcomeCheckType.TOOL_WAS_CALLED, params={"tool_name": "legacy_tool"}),
                severity="major",
            )
        ],
    )
    trace = _build_trace_with_tools(["legacy_tool"], final_response="ok")
    result = align_and_score(spec, trace)
    assert result.correctness_score == 1.0  # outcome still passed
    assert result.safety_score < 1.0
    assert any(c.check_type == CheckType.FORBIDDEN_ACTION for c in result.check_results)


def test_no_unexpected_action_emitted():
    """Extra tool calls don't reduce correctness anymore."""
    spec = _cancel_order_spec()
    trace = _build_trace_with_tools(
        ["lookup_order", "search_kb", "another_tool", "update_order"],
        tool_inputs=[None, None, None, {"order_id": "12345", "status": "cancelled"}],
        final_response="Order 12345 cancelled.",
    )
    result = align_and_score(spec, trace)
    types = [c.check_type for c in result.check_results]
    assert CheckType.UNEXPECTED_ACTION not in types
    assert result.correctness_score == 1.0


def test_no_wrong_params_emitted_from_alignment():
    """WRONG_PARAMS is not produced by the v2 engine."""
    spec = _cancel_order_spec()
    trace = _build_trace_with_tools(
        ["update_order"],
        tool_inputs=[{"order_id": "99999", "status": "cancelled"}],  # wrong order id
        final_response="Order cancelled.",
    )
    result = align_and_score(spec, trace)
    types = [c.check_type for c in result.check_results]
    assert CheckType.WRONG_PARAMS not in types
    # the order_cancelled assertion fails because no matching call exists
    assert any(
        c.meta.get("assertion_id") == "order_cancelled" and c.status == Status.FAIL for c in result.check_results
    )


def test_determinism_100_runs():
    spec = _cancel_order_spec()
    trace = _build_trace_with_tools(
        ["update_order"],
        tool_inputs=[{"order_id": "12345", "status": "cancelled"}],
        final_response="Order 12345 cancelled.",
    )
    first = align_and_score(spec, trace)
    for _ in range(99):
        again = align_and_score(spec, trace)
        assert again.correctness_score == first.correctness_score
        assert [c.model_dump() for c in again.check_results] == [c.model_dump() for c in first.check_results]


# ── outcome_checks individual evaluators ──


def test_response_contains_substring():
    spec = SpecDAG(
        task_type="t",
        version="1",
        source=SpecSource.HAND_AUTHORED,
        outcome_assertions=[
            OutcomeAssertion(
                assertion_id="x",
                check=OutcomeCheck(
                    check_type=OutcomeCheckType.RESPONSE_CONTAINS,
                    params={"pattern": "answer", "match_type": "substring"},
                ),
                weight=1.0,
                required=True,
            ),
        ],
    )
    trace_pass = _build_trace_with_tools(["t"], final_response="here is the answer")
    trace_fail = _build_trace_with_tools(["t"], final_response="no result")
    assert align_and_score(spec, trace_pass).correctness_score == 1.0
    assert align_and_score(spec, trace_fail).correctness_score == 0.0


def test_artifact_exists_check():
    spec = SpecDAG(
        task_type="t",
        version="1",
        source=SpecSource.HAND_AUTHORED,
        outcome_assertions=[
            OutcomeAssertion(
                assertion_id="file_written",
                check=OutcomeCheck(
                    check_type=OutcomeCheckType.ARTIFACT_EXISTS,
                    params={"path_pattern": "/tmp/*.py"},
                ),
                weight=1.0,
                required=True,
            ),
        ],
    )
    spans = [
        _span("a", "Write", start=1, files_written=["/tmp/foo.py"]),
        _final_user("z", "ok", 100),
    ]
    dag = build_trace_dag(spans)
    assert align_and_score(spec, dag).correctness_score == 1.0


def test_custom_python_is_disabled():
    """CUSTOM_PYTHON is refused instead of importing arbitrary server code."""
    spec = SpecDAG(
        task_type="t",
        version="1",
        source=SpecSource.HAND_AUTHORED,
        outcome_assertions=[
            OutcomeAssertion(
                assertion_id="custom",
                check=OutcomeCheck(
                    check_type=OutcomeCheckType.CUSTOM_PYTHON,
                    params={"function_path": "os.path.exists", "description": "x"},
                ),
                weight=1.0,
                required=True,
            ),
        ],
    )
    trace = _build_trace_with_tools(["t"], final_response="x")
    result = align_and_score(spec, trace)
    assert result.correctness_score == 0.0
    failure = next(c for c in result.check_results if c.status == Status.FAIL)
    assert "disabled" in failure.meta.get("reason", "")


def test_semantic_match_uses_real_cosine():
    spec = SpecDAG(
        task_type="t",
        version="1",
        source=SpecSource.HAND_AUTHORED,
        outcome_assertions=[
            OutcomeAssertion(
                assertion_id="x",
                check=OutcomeCheck(
                    check_type=OutcomeCheckType.RESPONSE_CONTAINS,
                    params={"pattern": "answer", "match_type": "semantic", "threshold": 0.1},
                ),
                weight=1.0,
                required=True,
            ),
        ],
    )
    trace = _build_trace_with_tools(["t"], final_response="here is the answer")
    result = align_and_score(spec, trace)
    matched = next(c for c in result.check_results if c.check_type == CheckType.MATCHED)
    assert "cosine" in matched.meta
    assert matched.meta["cosine"] >= matched.meta["threshold"]
    assert "provider" in matched.meta


# ── Mining ──


def test_miner_produces_outcome_spec():
    """Mining 5 gold traces yields outcome assertions, no domain invariants."""
    traces = []
    for _i in range(5):
        spans = [
            _span("a", "lookup", start=1),
            _span("b", "update_order", start=2, input_=json.dumps({"order_id": "12345", "status": "cancelled"})),
            _final_user("c", "Order 12345 has been cancelled.", start=3),
        ]
        traces.append(build_trace_dag(spans))
    spec = mine_spec_from_gold_traces("cancel_order", traces)

    assert spec.schema_version == 2
    assert spec.source == SpecSource.MINED
    assert len(spec.outcome_assertions) > 0
    for sc in spec.step_constraints:
        assert sc.severity == "soft"  # miner never produces hard constraints
    assert len(spec.domain_invariants) == 0


def test_miner_alias_works():
    """`mine` shim still callable."""
    traces = [build_trace_dag([_final_user("z", "ok", 1)])]
    spec = mine("t", traces)
    assert spec.schema_version == 2


def test_miner_extracts_shared_param_constraints():
    """If every gold trace called update_order with the same order_id, it shows up as a constraint."""
    traces = []
    for _ in range(3):
        spans = [
            _span("a", "update_order", start=1, input_=json.dumps({"order_id": "shared-123", "status": "cancelled"})),
            _final_user("z", "ok", 5),
        ]
        traces.append(build_trace_dag(spans))
    spec = mine_spec_from_gold_traces("t", traces)
    update_assertion = next(a for a in spec.outcome_assertions if "update_order" in a.assertion_id)
    pc = update_assertion.check.params.get("param_constraints", {})
    assert pc.get("order_id") == "shared-123"


# ── Registry / schema_version handling ──


def test_v1_spec_rejected_clearly():
    old_dag_json = {
        "task_type": "test",
        "version": "1",
        "nodes": [{"id": "r", "match_predicate": {"tool_name": "Read"}}],
        "edges": [],
        "forbidden_actions": [],
        "permitted_extras": [],
    }
    with pytest.raises(ValueError, match="path-oriented"):
        load_spec_dag(old_dag_json)


def test_v2_spec_loads():
    spec = SpecDAG(
        task_type="t",
        version="1",
        source=SpecSource.HAND_AUTHORED,
        outcome_assertions=[
            OutcomeAssertion(
                assertion_id="x",
                check=OutcomeCheck(
                    check_type=OutcomeCheckType.RESPONSE_CONTAINS, params={"pattern": ".", "match_type": "regex"}
                ),
            ),
        ],
    )
    blob = spec.to_json()
    assert blob["schema_version"] == 2
    loaded = load_spec_dag(blob)
    assert loaded.schema_version == 2
    assert len(loaded.outcome_assertions) == 1


def test_migrate_v1_to_v2_shape():
    v1 = {
        "task_type": "t",
        "version": "1",
        "nodes": [
            {
                "id": "step1",
                "match_predicate": {"tool_name": "Read", "param_constraints": {"file_path": "/x.py", "id": "abc"}},
            },
            {"id": "step2", "match_predicate": {"tool_name": "Write"}},
        ],
        "edges": [{"src": "step1", "dst": "step2"}],
        "forbidden_actions": ["DropTable"],
        "permitted_extras": ["Plan"],
    }
    v2 = migrate_v1_to_v2(v1)
    assert v2.schema_version == 2
    # Two outcome assertions, one per old node
    ids = [a.assertion_id for a in v2.outcome_assertions]
    assert "step1" in ids and "step2" in ids
    # Identifier-key only narrowing: file_path dropped (not id-shaped); id kept
    step1 = next(a for a in v2.outcome_assertions if a.assertion_id == "step1")
    pc = step1.check.params.get("param_constraints", {})
    assert "id" in pc
    assert "file_path" not in pc
    # Edge → soft step constraint
    assert v2.step_constraints[0].severity == "soft"
    assert v2.step_constraints[0].before_tool == "Read"
    assert v2.step_constraints[0].after_tool == "Write"
    # Forbidden → DomainInvariant
    inv = v2.domain_invariants[0]
    assert inv.severity == "major"
    assert inv.check.check_type == OutcomeCheckType.TOOL_WAS_CALLED
    assert inv.check.params["tool_name"] == "DropTable"


def test_outcome_checks_cover_edge_paths():
    from services.eval.alignment.outcome_checks import (
        check_artifact_exists,
        check_custom_python,
        check_response_contains,
        check_response_schema,
        check_state_changed,
        check_tool_result_contains,
        evaluate_outcome_check,
    )

    empty = build_trace_dag([])
    passed, meta = check_response_contains(empty, {"pattern": "x"})
    assert not passed
    assert meta["reason"] == "no final user-facing span"

    dag = build_trace_dag(
        [
            _span("s1", "respond", start=1, type_="assistant_response", output="{not-json"),
            _span("s2", "tool", start=2, input_="{not-json", output="no match"),
            _span("s3", "writer", start=3, output="created report content", files_written=["/tmp/report.txt"]),
        ]
    )

    passed, meta = check_response_contains(dag, {"pattern": "[", "match_type": "regex"})
    assert not passed
    assert "invalid regex" in meta["reason"]

    passed, meta = check_response_schema(dag, {"schema": {"type": "object"}})
    assert not passed
    assert "not JSON" in meta["reason"]

    passed, meta = check_tool_result_contains(dag, {"tool_name": "missing", "pattern": "x"})
    assert not passed
    assert "no spans" in meta["reason"]

    passed, meta = check_tool_result_contains(dag, {"tool_name": "tool", "pattern": "x"})
    assert not passed
    assert meta["reason"] == "no matching output"

    passed, meta = check_artifact_exists(dag, {"path_pattern": r"/tmp/report\.txt", "content_pattern": "absent"})
    assert not passed
    assert meta["reason"] == "content_pattern did not match"

    passed, meta = check_custom_python(empty, {})
    assert not passed
    assert meta["reason"] == "function_path missing"

    passed, meta = check_custom_python(empty, {"function_path": "os.path.exists"})
    assert not passed
    assert "disabled" in meta["reason"]

    class UnknownCheck:
        check_type = "unknown"
        params = {}

    passed, meta = evaluate_outcome_check(UnknownCheck(), empty)
    assert not passed
    assert "unknown check_type" in meta["reason"]

    output_scan = build_trace_dag(
        [
            _span("a", "log", start=10, output="state order.status was pending"),
            _span("b", "log", start=20, output="state order.status is shipped"),
        ]
    )
    passed, meta = check_state_changed(
        output_scan,
        {"namespace": "order", "key": "status", "from_value": "pending", "to_value": "shipped"},
    )
    assert passed
    assert meta["source"] == "output_scan_fallback"

    reversed_scan = build_trace_dag(
        [
            _span("b", "log", start=10, output="state order.status is shipped"),
            _span("a", "log", start=20, output="state order.status was pending"),
        ]
    )
    passed, meta = check_state_changed(
        reversed_scan,
        {"namespace": "order", "key": "status", "from_value": "pending", "to_value": "shipped"},
    )
    assert not passed
    assert meta["reason"] == "to_value observed before from_value"


@pytest.mark.asyncio
async def test_trace_builder_parses_edge_case_inputs_and_fetch_wrapper(monkeypatch):
    from services.eval.trace_dag.builder import fetch_and_build
    from services.eval.trace_dag.models import EdgeKind

    spans = [
        {
            "span_id": "a",
            "trace_id": "trace-x",
            "parent_span_id": "",
            "name": "source",
            "type": "tool",
            "start_time": "2026-01-01T00:00:00Z",
            "end_time": "not-a-time",
            "output": "distinctive output payload",
            "state_writes": [{"namespace": "order", "key": "status", "value_hash": "h1"}, "ignored"],
            "files_written": ["/tmp/a.txt", None],
            "span_references": ["r1", ""],
        },
        {
            "span_id": "b",
            "trace_id": "trace-x",
            "parent_span_id": "a",
            "name": "consumer",
            "type": "tool",
            "start_time": "2026-01-01T00:00:01Z",
            "input": "uses distinctive output payload now",
            "files_read": ["/tmp/a.txt"],
            "state_write_namespaces": ["order"],
            "state_write_keys": ["status"],
            "state_write_value_hashes": ["h2"],
        },
        {"span_id": "b", "trace_id": "trace-x", "name": "duplicate"},
        {"span_id": "", "trace_id": "trace-x", "name": "missing id"},
    ]

    dag = build_trace_dag(spans)

    assert dag.trace_id == "trace-x"
    assert len(dag.nodes) == 2
    assert dag.nodes["a"].end_time_ms is None
    assert dag.nodes["a"].state_writes[0].namespace == "order"
    assert dag.nodes["b"].state_writes[0].value_hash == "h2"
    assert any(e.kind == EdgeKind.PARENT for e in dag.edges)
    assert any(e.kind == EdgeKind.DATA_FLOW for e in dag.edges)
    assert any(e.kind == EdgeKind.FILE_TOUCH for e in dag.edges)

    async def fake_query_spans(**kwargs):
        assert kwargs["project_id"] == "project"
        return spans

    monkeypatch.setattr("services.clickhouse.query_spans", fake_query_spans)

    fetched = await fetch_and_build("override", "project", limit=5)
    assert fetched.trace_id == "override"


def test_json_round_trip_preserves_schema_version():
    spec = SpecDAG(
        task_type="t",
        version="1",
        source=SpecSource.HAND_AUTHORED,
        outcome_assertions=[
            OutcomeAssertion(
                assertion_id="x",
                check=OutcomeCheck(check_type=OutcomeCheckType.TOOL_WAS_CALLED, params={"tool_name": "T"}),
            ),
        ],
        domain_invariants=[
            DomainInvariant(
                invariant_id="i",
                check=OutcomeCheck(check_type=OutcomeCheckType.TOOL_WAS_CALLED, params={"tool_name": "Bad"}),
                severity="major",
            ),
        ],
    )
    data = spec.to_json()
    restored = SpecDAG.from_json(data)
    assert restored.model_dump() == spec.model_dump()
    assert restored.schema_version == 2


# ── Category / waste path stays untouched ──


def test_waste_module_unchanged_by_refactor():
    """The waste classifier doesn't depend on the SpecDAG; smoke-test it still emits checks."""
    from services.eval.waste.classifier import classify_waste

    spans = [
        _span("a", "Write", start=1, files_written=["/x"]),
        _span("b", "Write", start=2, files_written=["/x"]),
    ]
    dag = build_trace_dag(spans)
    checks = classify_waste(dag)
    assert any(c.category == Category.WASTE for c in checks)
