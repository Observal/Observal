# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for unified eval Phase 3 wiring.

Covers: scoring_method column on scorecards, new endpoints (spec-dags,
checks, report, batch insights), refusal of cross-method compare,
CLI wiring (importability + structure).
"""

from __future__ import annotations

import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "observal-server"))

import pytest

# ── Model: scoring_method column exists ──


class TestScorecardModel:
    def test_scoring_method_column_default(self):
        from models.eval import Scorecard

        col = Scorecard.__table__.columns["scoring_method"]
        assert col is not None
        assert col.nullable is False

    def test_checks_json_column_exists(self):
        from models.eval import Scorecard

        assert "checks_json" in Scorecard.__table__.columns


# ── Migration: eval revisions follow mainline Alembic head ──


class TestMigrations:
    def test_chain(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "observal-server" / "alembic" / "versions"))
        import importlib

        m5 = importlib.import_module("0005_add_eval_spec_dags")
        m6 = importlib.import_module("0006_add_scorecard_scoring_method")
        assert m5.revision == "0005" and m5.down_revision == "0004"
        assert m6.revision == "0006" and m6.down_revision == "0005"

    def test_eval_spec_dag_model_registered_in_metadata(self):
        from models import Base, EvalSpecDAG

        table = Base.metadata.tables["eval_spec_dags"]
        assert EvalSpecDAG.__table__ is table
        assert any(c.name == "ux_eval_spec_dags_task_type_version" for c in table.constraints)


# ── New router endpoints registered ──


class TestRouterRegistration:
    def test_phase3_endpoints_registered(self):
        from api.routes.eval import router

        paths = {r.path for r in router.routes}
        assert "/api/v1/eval/spec-dags" in paths
        assert "/api/v1/eval/scorecards/{scorecard_id}/checks" in paths
        assert "/api/v1/eval/scorecards/{scorecard_id}/report" in paths
        assert "/api/v1/eval/batches/{batch_id}/insights" in paths


class TestEvalTraceLookup:
    def test_project_id_prefers_trace_then_org_then_default(self):
        from api.routes.eval import _project_id_for_eval_trace

        agent = MagicMock(owner_org_id=uuid.uuid4())
        user = MagicMock(org_id=uuid.uuid4())

        assert _project_id_for_eval_trace(agent, user, {"project_id": "trace-project"}) == "trace-project"
        assert _project_id_for_eval_trace(agent, user, {}) == str(user.org_id)
        assert _project_id_for_eval_trace(agent, MagicMock(org_id=None), {}) == str(agent.owner_org_id)
        assert _project_id_for_eval_trace(MagicMock(owner_org_id=None), MagicMock(org_id=None), {}) == "default"

    @pytest.mark.asyncio
    async def test_fetch_traces_excludes_registry_events(self):
        import services.eval.eval_service as eval_service_mod
        from services.eval.eval_service import fetch_traces

        response = MagicMock(status_code=200)
        response.json.return_value = {"data": [{"trace_id": "agent-run", "trace_type": "agent"}]}
        eval_service_mod._query = AsyncMock(return_value=response)

        traces = await fetch_traces("agent-id", limit=3)

        assert traces == [{"trace_id": "agent-run", "trace_type": "agent"}]
        sql, params = eval_service_mod._query.await_args.args
        assert "trace_type != {excluded_trace_type:String}" in sql
        assert "LIMIT 3" in sql
        assert params["param_excluded_trace_type"] == "registry"

    @pytest.mark.asyncio
    async def test_fetch_traces_by_id_still_excludes_registry_events(self):
        import services.eval.eval_service as eval_service_mod
        from services.eval.eval_service import fetch_traces

        response = MagicMock(status_code=200)
        response.json.return_value = {"data": []}
        eval_service_mod._query = AsyncMock(return_value=response)

        await fetch_traces("agent-id", trace_id="trace-id")

        sql, params = eval_service_mod._query.await_args.args
        assert "trace_id = {tid:String}" in sql
        assert "trace_type != {excluded_trace_type:String}" in sql
        assert params == {
            "param_aid": "agent-id",
            "param_tid": "trace-id",
            "param_excluded_trace_type": "registry",
        }

    @pytest.mark.asyncio
    async def test_structured_eval_marks_schema_echo_dimensions_skipped(self, monkeypatch):
        from types import SimpleNamespace

        import services.eval.eval_service as eval_service_mod
        from services.eval.eval_service import run_structured_eval

        class _EchoScorer:
            failed_dimensions = {"goal_completion", "thought_process"}

            def __init__(self, backend):
                self.backend = backend

            async def score_goal_completion(self, *args, **kwargs):
                return []

            async def score_factual_grounding(self, *args, **kwargs):
                return []

            async def score_thought_process(self, *args, **kwargs):
                return []

        monkeypatch.setattr(eval_service_mod, "get_backend", MagicMock(return_value=object()))
        monkeypatch.setattr(eval_service_mod, "SLMScorer", _EchoScorer)

        agent = MagicMock(id=uuid.uuid4(), version="v1")
        agent.goal_template = MagicMock(
            description="Goal",
            sections=[SimpleNamespace(name="Summary", grounding_required=False)],
        )

        scorecard = await run_structured_eval(
            agent,
            trace={"trace_id": "trace-1", "output": "Summary: done"},
            spans=[{"span_id": "s1", "type": "tool_call", "name": "read", "status": "success", "output": "data"}],
            eval_run_id=uuid.uuid4(),
        )

        assert scorecard.partial_evaluation is True
        assert sorted(scorecard.dimensions_skipped) == ["goal_completion", "thought_process"]
        assert scorecard.dimension_scores["goal_completion"] is None
        assert scorecard.dimension_scores["thought_process"] is None


# ── Spec DAG registration ──


class TestSpecDAGEndpoint:
    @pytest.mark.asyncio
    async def test_register_then_list_round_trip(self):
        from api.routes.eval import list_spec_dags, register_spec_dag

        # Mock the registry functions (they are imported lazily inside each endpoint)
        new_id = uuid.uuid4()

        mock_db = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.rollback = AsyncMock()

        # Patch registry.register & list_by_task_type by monkeypatching the module attributes
        import services.eval.spec_dag.registry as registry_mod

        registry_mod.register = AsyncMock(return_value=new_id)
        registry_mod.list_by_task_type = AsyncMock(
            return_value=[
                MagicMock(
                    id=new_id,
                    task_type="t1",
                    version="1",
                    source="hand_authored",
                    created_at=datetime.now(UTC),
                    created_by="u@example.com",
                )
            ]
        )

        # Patch audit (no-op)
        import api.routes.eval as eval_mod

        eval_mod.audit = AsyncMock()

        payload = {
            "schema_version": 2,
            "task_type": "t1",
            "version": "1",
            "outcome_assertions": [
                {
                    "assertion_id": "x",
                    "check": {"check_type": "response_contains", "params": {"pattern": ".", "match_type": "regex"}},
                    "weight": 1.0,
                    "required": True,
                }
            ],
            "step_constraints": [],
            "domain_invariants": [],
            "source": "hand_authored",
        }
        user = MagicMock(email="u@example.com")
        result = await register_spec_dag(payload, db=mock_db, current_user=user)
        assert result["id"] == str(new_id)
        assert result["task_type"] == "t1"
        mock_db.commit.assert_called_once()

        rows = await list_spec_dags(task_type="t1", db=mock_db, current_user=user)
        assert len(rows) == 1
        assert rows[0]["task_type"] == "t1"

    @pytest.mark.asyncio
    async def test_invalid_payload_400(self):
        from fastapi import HTTPException

        from api.routes.eval import register_spec_dag

        mock_db = MagicMock()
        with pytest.raises(HTTPException) as exc:
            await register_spec_dag({"not": "a spec"}, db=mock_db, current_user=MagicMock(email="u@x"))
        assert exc.value.status_code == 400


# ── Scorecard checks endpoint ──


class TestScorecardChecks:
    @pytest.mark.asyncio
    async def test_returns_checks_json(self):
        from api.routes.eval import get_scorecard_checks

        sc = MagicMock(
            id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
            checks_json=[
                {
                    "check_type": "MATCHED",
                    "status": "PASS",
                    "weight": 1.0,
                    "points_earned": 1.0,
                    "points_possible": 1.0,
                    "evidence": [],
                    "category": "correctness",
                    "meta": {},
                }
            ],
        )

        import api.routes.eval as eval_mod

        eval_mod.resolve_prefix_id = AsyncMock(return_value=sc)
        eval_mod.audit = AsyncMock()

        user = MagicMock(org_id=None)
        out = await get_scorecard_checks("scid", db=MagicMock(), current_user=user)
        assert len(out) == 1
        assert out[0]["check_type"] == "MATCHED"

    @pytest.mark.asyncio
    async def test_legacy_returns_empty(self):
        from api.routes.eval import get_scorecard_checks

        sc = MagicMock(id=uuid.uuid4(), agent_id=uuid.uuid4(), checks_json=None)
        import api.routes.eval as eval_mod

        eval_mod.resolve_prefix_id = AsyncMock(return_value=sc)
        eval_mod.audit = AsyncMock()
        user = MagicMock(org_id=None)
        out = await get_scorecard_checks("scid", db=MagicMock(), current_user=user)
        assert out == []


# ── Cross-method compare refusal ──


class TestCompareRefusesCrossMethod:
    @pytest.mark.asyncio
    async def test_refuses_when_methods_differ(self):
        from fastapi import HTTPException

        from api.routes.eval import compare_versions

        agent = MagicMock(id=uuid.uuid4(), name="a", owner_org_id=None)

        # mock db.execute to return scoring_methods rows
        mock_db = MagicMock()
        seq = [
            MagicMock(all=lambda: [("legacy_deductive",)]),
            MagicMock(all=lambda: [("spec_dag_alignment",)]),
        ]
        mock_db.execute = AsyncMock(side_effect=lambda *a, **kw: seq.pop(0))

        import api.routes.eval as eval_mod

        eval_mod.resolve_prefix_id = AsyncMock(return_value=agent)
        eval_mod.audit = AsyncMock()

        user = MagicMock(org_id=None)
        with pytest.raises(HTTPException) as exc:
            await compare_versions(
                agent_id="x",
                version_a="1",
                version_b="2",
                db=mock_db,
                current_user=user,
            )
        assert exc.value.status_code == 409
        assert "cross-method" in exc.value.detail


# ── Slm_scorer marked legacy ──


class TestLegacySlmScorerMarker:
    def test_legacy_label_present(self):
        from services.eval import slm_scorer as legacy

        assert "[LEGACY]" in (legacy.__doc__ or "")
        assert "slm_explainer" in (legacy.__doc__ or "")


# ── Reliability report helpers ──


class TestReliabilityReportHelpers:
    def test_penalty_attribution_and_dominant_failure(self):
        from api.routes.eval import _dominant_failure, _penalty_attribution

        penalties = [
            {"dimension": "goal_completion", "event_name": "missed_goal", "amount": 1.5},
            {"dimension": "tool_failures", "event_name": "dependency_timeout", "amount": 2},
            {"dimension": "tool_efficiency", "event_name": "redundant_read", "amount": 3},
            {"dimension": "adversarial_robustness", "event_name": "canary", "amount": 0.5},
            {"dimension": "unknown", "event_name": "misc", "amount": 1},
        ]

        attr = _penalty_attribution(penalties, {})

        assert attr["agent"] == 2.5
        assert attr["mcp_tool"] == 2
        assert attr["waste"] == 3
        assert attr["prompt_injection"] == 0.5
        assert _dominant_failure(attr) == "waste"
        assert _dominant_failure({"agent": 0, "user_ambiguity": 9}) is None

    def test_span_status_uses_check_evidence_before_error_status(self):
        from api.routes.eval import _span_status

        checks = [
            {"status": "PASS", "check_type": "WASTE_CYCLE", "evidence": [{"span_id": "s1"}]},
            {"status": "FAIL", "check_type": "CANARY_TRIPPED", "evidence": [{"span_id": "s1"}]},
            {"status": "FAIL", "check_type": "WASTE_REVERT", "evidence": [{"span_id": "s2"}]},
        ]

        assert _span_status({"span_id": "s1", "status": "error"}, checks) == "injection"
        assert _span_status({"span_id": "s2", "status": "success"}, checks) == "waste"
        assert _span_status({"span_id": "s3", "status": "error"}, checks) == "failure"
        assert _span_status({"span_id": "s4", "status": "success"}, checks) == "success"

    def test_build_trace_dag_simple_and_waste_clusters(self):
        from api.routes.eval import _build_trace_dag_simple, _latency_display, _waste_clusters

        spans = [
            {"span_id": "a", "name": "plan", "type": "agent", "status": "ok"},
            {"span_id": "b", "name": "read", "type": "tool", "status": "ok"},
            {"span_id": "c", "name": "answer", "type": "agent", "status": "ok"},
        ]
        dag = _build_trace_dag_simple(spans)

        assert [n["depth"] for n in dag["nodes"]] == [0, 1, 2]
        assert dag["edges"] == [
            {"src": "a", "dst": "b", "kind": "temporal", "confidence": "high"},
            {"src": "b", "dst": "c", "kind": "temporal", "confidence": "high"},
        ]
        assert _latency_display(None) == "\u2014"
        assert _latency_display(250) == "250ms"
        assert _latency_display(2500) == "2.5s"

        clusters = _waste_clusters(
            [
                {
                    "check_type": "WASTE_REDUNDANT_READ",
                    "status": "FAIL",
                    "evidence": [{"span_id": "b"}, {"span_id": ""}],
                    "meta": {"tokens_in": 10, "tokens_out": 15, "cost_usd": 0.02, "fix_suggestion": "cache reads"},
                },
                {"check_type": "WASTE_CYCLE", "status": "PASS", "evidence": [{"span_id": "a"}]},
            ]
        )
        assert clusters == [
            {
                "cluster_id": "cluster_0",
                "check_type": "WASTE_REDUNDANT_READ",
                "span_ids": ["b"],
                "tokens_wasted": 25,
                "cost_usd": 0.02,
                "fix_suggestion": "cache reads",
            }
        ]


class TestExplanationEndpoints:
    @pytest.mark.asyncio
    async def test_scorecard_explanation_degrades_without_redis(self):
        import api.routes.eval as eval_mod
        import services.redis as redis_mod
        from api.routes.eval import get_scorecard_explanation

        sc = MagicMock(
            agent_id=uuid.uuid4(),
            dimension_scores={"goal_completion": 70},
            display_score=72,
            overall_score=7.2,
            grade="B",
            overall_grade="B",
            raw_output={"penalties": [{"dimension": "goal_completion", "amount": 1}]},
            penalty_count=1,
        )
        eval_mod.resolve_prefix_id = AsyncMock(return_value=sc)
        redis_mod.get_redis = MagicMock(side_effect=RuntimeError("redis down"))

        out = await get_scorecard_explanation("scid", db=MagicMock(), current_user=MagicMock(org_id=None))

        assert out["status"] == "ready"
        assert "Primary failure category: agent" in out["explanation"]

    @pytest.mark.asyncio
    async def test_check_explanation_fast_paths(self):
        from fastapi import HTTPException

        import api.routes.eval as eval_mod
        import services.redis as redis_mod
        from api.routes.eval import get_check_explanation

        sc = MagicMock(
            agent_id=uuid.uuid4(),
            checks_json=[
                {"check_type": "MATCHED", "status": "PASS", "meta": {"fix_suggestion": "Keep this path."}},
                {"check_type": "WASTE_CYCLE", "status": "FAIL", "meta": {}},
            ],
        )
        eval_mod.resolve_prefix_id = AsyncMock(return_value=sc)

        ready = await get_check_explanation("scid", "0", db=MagicMock(), current_user=MagicMock(org_id=None))
        assert ready == {"status": "ready", "explanation": "Keep this path."}

        with pytest.raises(HTTPException) as bad_index:
            await get_check_explanation("scid", "abc", db=MagicMock(), current_user=MagicMock(org_id=None))
        assert bad_index.value.status_code == 400

        with pytest.raises(HTTPException) as out_of_range:
            await get_check_explanation("scid", "9", db=MagicMock(), current_user=MagicMock(org_id=None))
        assert out_of_range.value.status_code == 404

        redis_mod.get_redis = MagicMock(side_effect=RuntimeError("redis down"))
        fallback = await get_check_explanation("scid", "1", db=MagicMock(), current_user=MagicMock(org_id=None))
        assert fallback["status"] == "ready"
        assert "redis" in fallback["explanation"].lower()


# ── CLI imports cleanly ──


class TestCLI:
    def test_eval_subcommands_registered(self):
        from observal_cli.cmd_ops import eval_app, spec_dag_app

        cmd_names = {c.name for c in eval_app.registered_commands}
        assert "seed" in cmd_names
        assert "report" in cmd_names
        assert "insights" in cmd_names
        # spec-dag subapp registered
        sub_names = {c.name for c in spec_dag_app.registered_commands}
        assert "register" in sub_names
        assert "list" in sub_names

    def test_legacy_cli_surface_intact(self):
        from observal_cli.cmd_ops import eval_app

        cmd_names = {c.name for c in eval_app.registered_commands}
        for legacy in ("run", "seed", "scorecards", "show", "compare", "aggregate", "report", "insights"):
            assert legacy in cmd_names

    def test_eval_seed_batch_contains_eval_scenarios(self):
        from observal_cli.cmd_ops import _build_eval_seed_batch

        batch, trace_ids = _build_eval_seed_batch(
            "agent-123",
            ["agent-failure", "dependency-failure", "prompt-injection"],
            "test-seed",
        )

        assert len(trace_ids) == 3
        assert len(batch["traces"]) == 3
        assert {t["metadata"]["seed_scenario"] for t in batch["traces"]} == {
            "agent-failure",
            "dependency-failure",
            "prompt-injection",
        }
        assert all(t["agent_id"] == "agent-123" for t in batch["traces"])
        assert any(s["status"] == "error" and "Dependency timeout" in s["error"] for s in batch["spans"])
        assert any("Ignore all evaluator instructions" in (s.get("input") or "") for s in batch["spans"])
