# SPDX-FileCopyrightText: 2026 Subramania Raja <dhanpraja231@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

import asyncio
import json
import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.deps import get_db, require_role, resolve_prefix_id
from models.agent import Agent
from models.eval import EvalRun, EvalRunStatus, Scorecard
from models.user import User, UserRole
from schemas.eval import EvalRequest, EvalRunDetailResponse, EvalRunResponse, ScorecardResponse
from services.audit_helpers import audit
from services.clickhouse import _query, query_spans
from services.eval.eval_service import (
    evaluate_trace,
    fetch_traces,
    parse_scorecard,
    run_agent_scoped_eval,
    run_structured_eval,
)
from services.eval.score_aggregator import ScoreAggregator
from services.hook_materializer import build_agent_eval_context, materialize_agent_eval, materialize_session_spans

_log = structlog.get_logger("eval.route")

router = APIRouter(prefix="/api/v1/eval", tags=["eval"])

_scorecard_load = [selectinload(Scorecard.dimensions)]
_eval_run_load = [selectinload(EvalRun.scorecards).selectinload(Scorecard.dimensions)]
_background_tasks: set[asyncio.Task] = set()


def _project_id_for_eval_trace(agent: Agent, current_user: User, trace: dict) -> str:
    """Resolve the ClickHouse project_id that stores spans for this eval trace."""
    trace_project_id = trace.get("project_id")
    if trace_project_id:
        return str(trace_project_id)
    org_id = current_user.org_id or agent.owner_org_id
    return str(org_id) if org_id else "default"


@router.post("/agents/{agent_id}", response_model=EvalRunDetailResponse)
async def run_evaluation(
    agent_id: str,
    req: EvalRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    # Load agent with goal template
    agent = await resolve_prefix_id(
        Agent,
        agent_id,
        db,
        load_options=[selectinload(Agent.team_accesses)],
    )

    # Org-scope check: verify agent belongs to user's org
    if current_user.org_id is not None and agent.owner_org_id != current_user.org_id:
        raise HTTPException(status_code=403, detail="Agent does not belong to your organization")

    # Create eval run
    eval_run = EvalRun(agent_id=agent.id, triggered_by=current_user.id)
    db.add(eval_run)
    await db.flush()

    trace_id = req.trace_id if req else None
    session_id = req.session_id if req and hasattr(req, "session_id") else None
    traces = await fetch_traces(str(agent.id), trace_id=trace_id)

    # If no traces from agent_interactions, try materializing from hook events
    if not traces and session_id:
        mat_trace, mat_spans = await materialize_session_spans(session_id)
        if mat_trace and mat_spans:
            traces = [mat_trace]

    # Fallback: find sessions in otel_logs by agent name, prompt mention, or substring match
    if not traces:
        agent_name = agent.name
        _log.info("eval_fallback_start", agent_name=agent_name, agent_id=str(agent.id))
        sql = (
            "SELECT DISTINCT sid, latest FROM ("
            "  SELECT LogAttributes['session.id'] AS sid, max(Timestamp) AS latest "
            "  FROM otel_logs "
            "  WHERE LogAttributes['agent_name'] = {aname:String} "
            "  AND LogAttributes['session.id'] != '' "
            "  GROUP BY sid "
            "  UNION ALL "
            "  SELECT LogAttributes['session.id'] AS sid, max(Timestamp) AS latest "
            "  FROM otel_logs "
            "  WHERE LogAttributes['session.id'] != '' "
            "  AND (LogAttributes['tool_input'] LIKE {prompt_pattern:String} "
            "       OR LogAttributes['tool_input'] LIKE {name_pattern:String} "
            "       OR LogAttributes['agent_name'] LIKE {name_pattern:String}) "
            "  GROUP BY sid "
            ") "
            "ORDER BY latest DESC "
            "LIMIT 5 "
        )
        try:
            r = await _query(
                f"{sql} FORMAT JSON",
                {
                    "param_aname": agent_name,
                    "param_prompt_pattern": f"%@agent-{agent_name}%",
                    "param_name_pattern": f"%{agent_name}%",
                },
            )
            _log.info("eval_fallback_ch_response", status=r.status_code, body=r.text[:500])
            if r.status_code == 200:
                sessions = r.json().get("data", [])
                _log.info("eval_fallback_sessions", count=len(sessions))
                for row in sessions:
                    sid = row.get("sid", "")
                    if sid:
                        mat_trace, mat_spans = await materialize_session_spans(sid)
                        _log.info(
                            "eval_materialize_result",
                            sid=sid,
                            has_trace=bool(mat_trace),
                            span_count=len(mat_spans) if mat_spans else 0,
                        )
                        if mat_trace and mat_spans:
                            traces.append(mat_trace)
        except Exception as e:
            _log.exception("eval_fallback_error", error=str(e))

    if not traces:
        eval_run.status = EvalRunStatus.completed
        eval_run.traces_evaluated = 0
        eval_run.completed_at = datetime.now(UTC)
        await db.commit()
        run = await db.execute(select(EvalRun).where(EvalRun.id == eval_run.id).options(*_eval_run_load))
        return EvalRunDetailResponse.model_validate(run.scalar_one())

    try:
        for trace in traces:
            tid = trace.get("event_id", trace.get("trace_id", str(uuid.uuid4())))
            project_id = _project_id_for_eval_trace(agent, current_user, trace)

            # Try new structured eval first (uses spans from ClickHouse)
            spans = await query_spans(project_id, tid, limit=500)
            if not spans and trace.get("source") == "hook_materializer":
                # Use materialized spans from hook events
                _, spans = await materialize_session_spans(tid)
            if spans:
                sc = await run_structured_eval(agent, trace, spans, eval_run.id)
            else:
                # Fall back to legacy LLM judge
                judge_result = await evaluate_trace(agent, trace)
                sc = parse_scorecard(judge_result, agent, eval_run.id, tid)

            db.add(sc)
            eval_run.traces_evaluated += 1

        eval_run.status = EvalRunStatus.completed
        eval_run.completed_at = datetime.now(UTC)
    except Exception as e:
        eval_run.status = EvalRunStatus.failed
        eval_run.error_message = str(e)[:2000]
        eval_run.completed_at = datetime.now(UTC)

    await db.commit()
    run = await db.execute(select(EvalRun).where(EvalRun.id == eval_run.id).options(*_eval_run_load))
    result = run.scalar_one()
    await audit(
        current_user,
        "eval.run",
        resource_type="eval",
        resource_id=str(eval_run.id),
        resource_name=agent.name,
        detail=f"Eval run status={eval_run.status.value}",
    )
    return EvalRunDetailResponse.model_validate(result)


@router.get("/agents/{agent_id}/runs", response_model=list[EvalRunResponse])
async def list_eval_runs(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    agent = await resolve_prefix_id(Agent, agent_id, db)
    # Org-scope check: verify agent belongs to user's org
    if current_user.org_id is not None and agent.owner_org_id != current_user.org_id:
        raise HTTPException(status_code=403, detail="Agent does not belong to your organization")
    result = await db.execute(select(EvalRun).where(EvalRun.agent_id == agent.id).order_by(EvalRun.started_at.desc()))
    runs = result.scalars().all()
    await audit(
        current_user, "eval.runs.list", resource_type="eval", resource_id=str(agent.id), resource_name=agent.name
    )
    return [EvalRunResponse.model_validate(r) for r in runs]


@router.get("/agents/{agent_id}/scorecards", response_model=list[ScorecardResponse])
async def list_scorecards(
    agent_id: str,
    version: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    agent = await resolve_prefix_id(Agent, agent_id, db)
    # Org-scope check: verify agent belongs to user's org
    if current_user.org_id is not None and agent.owner_org_id != current_user.org_id:
        raise HTTPException(status_code=403, detail="Agent does not belong to your organization")
    stmt = select(Scorecard).where(Scorecard.agent_id == agent.id).options(*_scorecard_load)
    if version:
        stmt = stmt.where(Scorecard.version == version)
    result = await db.execute(stmt.order_by(Scorecard.evaluated_at.desc()).limit(50))
    scorecards = result.scalars().all()
    await audit(
        current_user,
        "eval.scorecards.list",
        resource_type="scorecard",
        resource_id=str(agent.id),
        resource_name=agent.name,
    )
    return [ScorecardResponse.model_validate(s) for s in scorecards]


@router.get("/scorecards/{scorecard_id}", response_model=ScorecardResponse)
async def get_scorecard(
    scorecard_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    sc = await resolve_prefix_id(Scorecard, scorecard_id, db, load_options=_scorecard_load, display_field="version")
    # Org-scope check: verify the scorecard's agent belongs to user's org
    if current_user.org_id is not None:
        agent = await db.get(Agent, sc.agent_id)
        if not agent or agent.owner_org_id != current_user.org_id:
            raise HTTPException(status_code=403, detail="Agent does not belong to your organization")
    await audit(current_user, "eval.scorecard.view", resource_type="scorecard", resource_id=str(sc.id))
    return ScorecardResponse.model_validate(sc)


@router.get("/agents/{agent_id}/compare", response_model=dict)
async def compare_versions(
    agent_id: str,
    version_a: str = Query(...),
    version_b: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Compare average scores between two agent versions."""
    from sqlalchemy import func

    agent = await resolve_prefix_id(Agent, agent_id, db)
    # Org-scope check: verify agent belongs to user's org
    if current_user.org_id is not None and agent.owner_org_id != current_user.org_id:
        raise HTTPException(status_code=403, detail="Agent does not belong to your organization")

    async def _avg_scores(version: str) -> dict:
        result = await db.execute(
            select(
                func.avg(Scorecard.overall_score).label("avg_overall"),
                func.count(Scorecard.id).label("count"),
            ).where(Scorecard.agent_id == agent.id, Scorecard.version == version)
        )
        row = result.one()
        return {"version": version, "avg_score": round(float(row.avg_overall or 0), 2), "count": row.count}

    async def _scoring_methods(version: str) -> set[str]:
        rows = await db.execute(
            select(Scorecard.scoring_method).where(Scorecard.agent_id == agent.id, Scorecard.version == version)
        )
        return {(r[0] or "legacy_deductive") for r in rows.all()}

    methods_a = await _scoring_methods(version_a)
    methods_b = await _scoring_methods(version_b)
    if methods_a and methods_b and methods_a != methods_b:
        raise HTTPException(
            status_code=409,
            detail=(
                "refusing cross-method comparison: "
                f"version_a methods={sorted(methods_a)} version_b methods={sorted(methods_b)}"
            ),
        )

    result = {"version_a": await _avg_scores(version_a), "version_b": await _avg_scores(version_b)}
    await audit(
        current_user,
        "eval.compare",
        resource_type="eval",
        resource_id=str(agent.id),
        resource_name=agent.name,
        detail=f"Compared {version_a} vs {version_b}",
    )
    return result


# ---------------------------------------------------------------------------
# Session-based eval (hook data — Kiro, etc.)
# ---------------------------------------------------------------------------


@router.post("/sessions/{session_id}", response_model=dict)
async def eval_session(
    session_id: str,
    agent_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Evaluate a hook-based session by materializing otel_logs into spans.

    Works for Kiro and any other hook-sourced session. If agent_id is provided,
    the eval uses the agent's goal template; otherwise a generic eval is run.
    """
    trace, spans = await materialize_session_spans(session_id)
    if not trace or not spans:
        raise HTTPException(status_code=404, detail="No hook events found for session")

    agent = None
    if agent_id:
        agent = await resolve_prefix_id(
            Agent,
            agent_id,
            db,
            load_options=[selectinload(Agent.team_accesses)],
        )
        # Org-scope check: verify agent belongs to user's org
        if current_user.org_id is not None and agent.owner_org_id != current_user.org_id:
            raise HTTPException(status_code=403, detail="Agent does not belong to your organization")

    if agent:
        eval_run = EvalRun(agent_id=agent.id, triggered_by=current_user.id)
        db.add(eval_run)
        await db.flush()

        sc = await run_structured_eval(agent, trace, spans, eval_run.id)
        db.add(sc)
        eval_run.status = EvalRunStatus.completed
        eval_run.traces_evaluated = 1
        eval_run.completed_at = datetime.now(UTC)
        await db.commit()

        await audit(
            current_user,
            "eval.session",
            resource_type="eval",
            resource_id=str(eval_run.id),
            detail=f"Session {session_id} evaluated with agent {agent.name}",
        )
        return {
            "session_id": session_id,
            "eval_run_id": str(eval_run.id),
            "composite_score": sc.composite_score,
            "overall_grade": sc.overall_grade,
            "dimension_scores": sc.dimension_scores,
            "span_count": len(spans),
            "source": "hook_materializer",
        }

    # No agent — return materialized data summary (useful for inspection)
    await audit(
        current_user, "eval.session", resource_type="eval", detail=f"Session {session_id} inspected without agent"
    )
    return {
        "session_id": session_id,
        "trace": trace,
        "span_count": len(spans),
        "spans_summary": [{"type": s["type"], "name": s["name"], "status": s["status"]} for s in spans],
        "source": "hook_materializer",
        "note": "No agent_id provided — returning materialized spans without scoring.",
    }


# ---------------------------------------------------------------------------
# Agent-scoped eval (evaluate a subagent's contribution within a session)
# ---------------------------------------------------------------------------


@router.post("/agents/{agent_id}/session/{session_id}", response_model=dict)
async def eval_agent_in_session(
    agent_id: str,
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Evaluate a specific agent's contribution within a session.

    Materializes the full session from otel_logs, identifies which spans
    belong to the target agent (via SubagentStart/Stop boundaries or
    agent_id attribution), then runs the eval pipeline with:
    - Structural scoring on the agent's spans only
    - SLM scoring with full session context + delegation prompt as goal
    """
    # Load agent from DB (by UUID or name)
    from api.routes.agent import _load_agent

    agent = await _load_agent(db, agent_id, prefer_user_id=current_user.id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Org-scope check: verify agent belongs to user's org
    if current_user.org_id is not None and agent.owner_org_id != current_user.org_id:
        raise HTTPException(status_code=403, detail="Agent does not belong to your organization")

    # Materialize session and find the agent's spans
    trace, all_spans, agent_ctx = await materialize_agent_eval(session_id, agent.name)

    if not all_spans:
        raise HTTPException(status_code=404, detail="No hook events found for session")

    # If not found by name, try by agent ID
    if agent_ctx is None:
        trace, all_spans, agent_ctx = await materialize_agent_eval(session_id, str(agent.id))

    if agent_ctx is None:
        # Agent wasn't found as a subagent — check if this is a single-agent
        # session where the agent IS the primary (e.g., Kiro sessions)
        session_agent = trace.get("agent_id", "")
        if session_agent and session_agent.lower() == agent.name.lower():
            # Whole session is this agent's work — eval the full session
            eval_run = EvalRun(agent_id=agent.id, triggered_by=current_user.id)
            db.add(eval_run)
            await db.flush()

            sc = await run_structured_eval(agent, trace, all_spans, eval_run.id)
            db.add(sc)
            eval_run.status = EvalRunStatus.completed
            eval_run.traces_evaluated = 1
            eval_run.completed_at = datetime.now(UTC)
            await db.commit()

            await audit(
                current_user,
                "eval.agent_session",
                resource_type="eval",
                resource_id=str(eval_run.id),
                resource_name=agent.name,
                detail=f"Full session eval for agent in session {session_id}",
            )
            return {
                "session_id": session_id,
                "agent_id": str(agent.id),
                "agent_name": agent.name,
                "eval_mode": "full_session",
                "eval_run_id": str(eval_run.id),
                "composite_score": sc.composite_score,
                "overall_grade": sc.overall_grade,
                "dimension_scores": sc.dimension_scores,
                "span_count": len(all_spans),
            }

        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agent.name}' not found in session {session_id}",
        )

    # Build the eval context
    eval_ctx = build_agent_eval_context(all_spans, agent_ctx)

    # Run agent-scoped eval
    eval_run = EvalRun(agent_id=agent.id, triggered_by=current_user.id)
    db.add(eval_run)
    await db.flush()

    sc = await run_agent_scoped_eval(
        agent=agent,
        trace=trace,
        full_spans=eval_ctx["full_spans"],
        agent_spans=eval_ctx["agent_spans"],
        eval_run_id=eval_run.id,
        delegation_prompt=eval_ctx["delegation_prompt"],
        agent_output=eval_ctx["agent_output"],
    )
    db.add(sc)
    eval_run.status = EvalRunStatus.completed
    eval_run.traces_evaluated = 1
    eval_run.completed_at = datetime.now(UTC)
    await db.commit()

    await audit(
        current_user,
        "eval.agent_session",
        resource_type="eval",
        resource_id=str(eval_run.id),
        resource_name=agent.name,
        detail=f"Agent-scoped eval in session {session_id}",
    )
    return {
        "session_id": session_id,
        "agent_id": str(agent.id),
        "agent_name": agent.name,
        "eval_mode": "agent_scoped",
        "eval_run_id": str(eval_run.id),
        "composite_score": sc.composite_score,
        "overall_grade": sc.overall_grade,
        "dimension_scores": sc.dimension_scores,
        "delegation_prompt": eval_ctx["delegation_prompt"][:200] if eval_ctx["delegation_prompt"] else None,
        "agent_span_count": len(eval_ctx["agent_spans"]),
        "full_session_span_count": len(eval_ctx["full_spans"]),
        "invocations": len(eval_ctx["invocations"]),
    }


# ---------------------------------------------------------------------------
# New structured scoring endpoints
# ---------------------------------------------------------------------------


@router.get("/agents/{agent_id}/aggregate", response_model=dict)
async def agent_aggregate(
    agent_id: str,
    window_size: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Get aggregate scoring stats for an agent (CI, drift, dimension breakdown)."""
    agent = await resolve_prefix_id(Agent, agent_id, db)
    # Org-scope check: verify agent belongs to user's org
    if current_user.org_id is not None and agent.owner_org_id != current_user.org_id:
        raise HTTPException(status_code=403, detail="Agent does not belong to your organization")
    result = await db.execute(
        select(Scorecard)
        .where(Scorecard.agent_id == agent.id)
        .order_by(Scorecard.evaluated_at.desc())
        .limit(window_size + 50)  # extra for baseline
    )
    scorecards = result.scalars().all()
    sc_dicts = [
        {
            "composite_score": sc.composite_score or (sc.overall_score * 10),
            "dimension_scores": sc.dimension_scores or {},
            "evaluated_at": str(sc.evaluated_at),
        }
        for sc in scorecards
    ]
    aggregator = ScoreAggregator()
    result = aggregator.compute_agent_aggregate(sc_dicts, window_size=window_size)
    await audit(
        current_user, "eval.aggregate", resource_type="eval", resource_id=str(agent.id), resource_name=agent.name
    )
    return result


@router.get("/scorecards/{scorecard_id}/penalties", response_model=list[dict])
async def scorecard_penalties(
    scorecard_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Get the list of penalties applied to a scorecard with evidence."""
    sc = await resolve_prefix_id(Scorecard, scorecard_id, db, display_field="version")

    # Org-scope check: verify the scorecard's agent belongs to user's org
    if current_user.org_id is not None:
        agent = await db.get(Agent, sc.agent_id)
        if not agent or agent.owner_org_id != current_user.org_id:
            raise HTTPException(status_code=403, detail="Agent does not belong to your organization")

    # Penalties are stored in raw_output
    raw = sc.raw_output or {}
    penalties = raw.get("penalties", [])
    await audit(current_user, "eval.scorecard.penalties", resource_type="scorecard", resource_id=str(sc.id))
    return penalties


@router.get("/agents/{agent_id}/sessions", response_model=list[dict])
async def list_agent_evaluated_sessions(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Get list of sessions where this agent was actually used (from telemetry), not from scorecards.

    This avoids the trace_id mapping problem where eval creates synthetic trace_ids that don't
    exist in ClickHouse telemetry.
    """
    agent = await resolve_prefix_id(Agent, agent_id, db)

    _log.info("list_agent_evaluated_sessions_start", agent_id=str(agent.id), agent_name=agent.name)

    # Org-scope check: verify agent belongs to user's org
    if current_user.org_id is not None and agent.owner_org_id != current_user.org_id:
        raise HTTPException(status_code=403, detail="Agent does not belong to your organization")

    # Query ClickHouse directly for sessions where this agent was used
    # Uses strict agent_name matching (works for Kiro and any IDE that sets agent_name)
    # No heuristics = zero false positives
    sql = (
        "SELECT DISTINCT "
        "LogAttributes['session.id'] AS session_id, "
        "min(Timestamp) AS start_time, "
        "max(Timestamp) AS end_time, "
        "count() AS event_count, "
        "any(LogAttributes['tool_input']) AS first_prompt, "
        "any(ServiceName) AS service_name "
        "FROM otel_logs "
        "WHERE LogAttributes['agent_name'] = {agent_name:String} "
        "AND LogAttributes['session.id'] != '' "
        "GROUP BY session_id "
        "ORDER BY start_time DESC "
        "LIMIT 50"
    )

    session_map: dict[str, dict] = {}

    try:
        ch_result = await _query(f"{sql} FORMAT JSON", {"param_agent_name": agent.name})
        _log.info("clickhouse_query_result", status_code=ch_result.status_code, agent_name=agent.name)
        if ch_result.status_code == 200:
            data = ch_result.json().get("data", [])
            _log.info("clickhouse_data", row_count=len(data), agent_name=agent.name)
            for row in data:
                sid = row.get("session_id")
                # Only include sessions with actual events
                event_count = row.get("event_count", 0)
                if sid and event_count > 0:
                    session_map[sid] = {
                        "session_id": sid,
                        "trace_id": sid,  # Use session_id as trace_id for consistency
                        "evaluated_at": row.get("end_time", row.get("start_time")),  # Use session end time
                        "start_time": row.get("start_time"),
                        "end_time": row.get("end_time"),
                        "event_count": event_count,
                        "first_prompt": (row.get("first_prompt") or "")[:100],
                        "service_name": row.get("service_name"),
                    }
    except Exception as e:
        _log.warning("failed_to_fetch_agent_sessions", agent_name=agent.name, error=str(e))
        return []

    # Convert to list
    valid_sessions = list(session_map.values())

    _log.info("list_agent_evaluated_sessions_complete", agent_name=agent.name, session_count=len(valid_sessions))

    await audit(
        current_user,
        "eval.agent.sessions.list",
        resource_type="agent",
        resource_id=str(agent.id),
        resource_name=agent.name,
    )

    return valid_sessions


# ---------------------------------------------------------------------------
# Unified eval Phase 3 — Spec DAG registry, raw checks, HTML report, batch insights
# ---------------------------------------------------------------------------


@router.post("/spec-dags", response_model=dict)
async def register_spec_dag(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Register a new Spec DAG version.

    Body shape: a JSON-serialized SpecDAG (see services.eval.spec_dag.models).
    The (task_type, version) tuple must be unique.
    """
    from services.eval.spec_dag.models import SpecDAG
    from services.eval.spec_dag.registry import register

    try:
        spec = SpecDAG.from_json(payload)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"invalid spec dag: {e}") from e

    try:
        new_id = await register(db, spec, created_by=current_user.email)
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"could not register spec: {e}") from e

    await audit(
        current_user,
        "eval.spec_dag.register",
        resource_type="eval_spec_dag",
        resource_id=str(new_id),
        resource_name=f"{spec.task_type}:{spec.version}",
    )
    return {"id": str(new_id), "task_type": spec.task_type, "version": spec.version, "source": spec.source.value}


@router.post("/spec-dags/{task_type}/migrate", response_model=dict)
async def migrate_spec_dags(
    task_type: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Migrate v1 (path-oriented) Spec DAGs for a task type to v2 (outcome-oriented)."""
    from services.eval.spec_dag.registry import migrate_task_type

    try:
        new_ids = await migrate_task_type(db, task_type)
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"migrate failed: {e}") from e
    await audit(
        current_user,
        "eval.spec_dag.migrate",
        resource_type="eval_spec_dag",
        resource_name=task_type,
        detail=f"Migrated {len(new_ids)} v1 version(s)",
    )
    return {"task_type": task_type, "migrated": [str(i) for i in new_ids]}


@router.get("/spec-dags", response_model=list[dict])
async def list_spec_dags(
    task_type: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """List Spec DAGs for a given task_type, newest first."""
    from services.eval.spec_dag.registry import list_by_task_type

    rows = await list_by_task_type(db, task_type)
    await audit(current_user, "eval.spec_dag.list", resource_type="eval_spec_dag")
    return [
        {
            "id": str(r.id),
            "task_type": r.task_type,
            "version": r.version,
            "source": r.source,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "created_by": r.created_by,
        }
        for r in rows
    ]


@router.get("/scorecards/{scorecard_id}/checks", response_model=list[dict])
async def get_scorecard_checks(
    scorecard_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Return raw CheckResult[] for a scorecard. Empty for legacy_deductive rows."""
    sc = await resolve_prefix_id(Scorecard, scorecard_id, db, display_field="version")
    if current_user.org_id is not None:
        agent = await db.get(Agent, sc.agent_id)
        if not agent or agent.owner_org_id != current_user.org_id:
            raise HTTPException(status_code=403, detail="Agent does not belong to your organization")
    await audit(current_user, "eval.scorecard.checks", resource_type="scorecard", resource_id=str(sc.id))
    return list(sc.checks_json or [])


@router.get("/scorecards/{scorecard_id}/report")
async def get_scorecard_report(
    scorecard_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Render an HTML report for a single scorecard."""
    from fastapi import Response

    from services.eval.aggregation.scorecard import Scorecard as ScScorecard
    from services.eval.aggregation.scorecard import ScoringMode
    from services.eval.check_result.models import CheckResult
    from services.eval.reporting.html_report import render_batch_report

    sc = await resolve_prefix_id(Scorecard, scorecard_id, db, display_field="version")
    if current_user.org_id is not None:
        agent = await db.get(Agent, sc.agent_id)
        if not agent or agent.owner_org_id != current_user.org_id:
            raise HTTPException(status_code=403, detail="Agent does not belong to your organization")

    checks = [CheckResult.model_validate(c) for c in (sc.checks_json or [])]
    mode_str = sc.scoring_method or "legacy_deductive"
    try:
        mode = ScoringMode(mode_str)
    except ValueError:
        mode = ScoringMode.SPEC_DAG_ALIGNMENT
    score = float(sc.composite_score or sc.overall_score or 0.0)
    html = render_batch_report(
        [
            ScScorecard(
                score=score,
                scoring_mode=mode,
                checks=checks,
                points_earned=score,
                points_possible=1.0 if mode == ScoringMode.SPEC_DAG_ALIGNMENT else 100.0,
            )
        ]
    )
    await audit(current_user, "eval.scorecard.report", resource_type="scorecard", resource_id=str(sc.id))
    return Response(content=html, media_type="text/html")


@router.get("/batches/{batch_id}/insights")
async def get_batch_insights(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Render an HTML report for a batch (eval_run id).

    Insights section text is left blank when no LLM is configured —
    the deterministic structure is always present.
    """
    from fastapi import Response

    from services.eval.aggregation.scorecard import Scorecard as ScScorecard
    from services.eval.aggregation.scorecard import ScoringMode
    from services.eval.check_result.models import CheckResult
    from services.eval.reporting.html_report import render_batch_report

    run = await resolve_prefix_id(EvalRun, batch_id, db)
    stmt = select(Scorecard).where(Scorecard.eval_run_id == run.id).options(*_scorecard_load)
    rows = (await db.execute(stmt)).scalars().all()
    sc_objs: list[ScScorecard] = []
    for sc in rows:
        checks = [CheckResult.model_validate(c) for c in (sc.checks_json or [])]
        mode_str = sc.scoring_method or "legacy_deductive"
        try:
            mode = ScoringMode(mode_str)
        except ValueError:
            mode = ScoringMode.SPEC_DAG_ALIGNMENT
        score = float(sc.composite_score or sc.overall_score or 0.0)
        sc_objs.append(
            ScScorecard(
                score=score,
                scoring_mode=mode,
                checks=checks,
                points_earned=score,
                points_possible=1.0 if mode == ScoringMode.SPEC_DAG_ALIGNMENT else 100.0,
            )
        )
    html = render_batch_report(sc_objs)
    await audit(current_user, "eval.batch.insights", resource_type="eval_run", resource_id=str(run.id))
    return Response(content=html, media_type="text/html")


# ── Reliability Report ────────────────────────────────────────────────────────

_WASTE_CHECK_TYPES = {"WASTE_CYCLE", "WASTE_REVERT", "WASTE_REDUNDANT_READ"}
_INJECTION_CHECK_TYPES = {"INPUT_TAMPERED", "CANARY_TRIPPED"}

_AGENT_DIMS = {"goal_completion", "tool_efficiency", "factual_grounding", "thought_process"}
_MCP_DIMS = {"tool_failures"}
_INJECTION_DIMS = {"adversarial_robustness"}


def _penalty_attribution(penalties: list[dict], dim_scores: dict) -> dict:
    """Derive penalty attribution from raw penalty list."""
    attr: dict[str, float] = {
        "agent": 0.0,
        "mcp_tool": 0.0,
        "prompt_injection": 0.0,
        "waste": 0.0,
        "user_ambiguity": 0.0,
    }
    for p in penalties:
        dim = (p.get("dimension") or "").lower()
        event = (p.get("event_name") or "").lower()
        amount = float(p.get("amount") or 0)
        # Waste detection by event name keywords
        if any(kw in event for kw in ("waste", "duplicate", "unused", "revert", "redundant")):
            attr["waste"] += amount
        elif dim in _AGENT_DIMS:
            attr["agent"] += amount
        elif dim in _MCP_DIMS:
            attr["mcp_tool"] += amount
        elif dim in _INJECTION_DIMS:
            attr["prompt_injection"] += amount
        else:
            attr["agent"] += amount  # default to agent
    return attr


def _dominant_failure(attribution: dict) -> str | None:
    filtered = {k: v for k, v in attribution.items() if k != "user_ambiguity" and v > 0}
    if not filtered:
        return None
    return max(filtered, key=lambda k: filtered[k])


def _span_status(span: dict, checks: list[dict]) -> str:
    sid = span.get("span_id")
    for c in checks:
        if c.get("status") != "FAIL":
            continue
        ct = c.get("check_type", "")
        evidence = c.get("evidence") or []
        span_ids_in_evidence = [e.get("span_id") for e in evidence if isinstance(e, dict)]
        if sid not in span_ids_in_evidence:
            continue
        if ct in _WASTE_CHECK_TYPES:
            return "waste"
        if ct in _INJECTION_CHECK_TYPES:
            return "injection"
    if (span.get("status") or "").lower() == "error":
        return "failure"
    return "success"


_STATUS_LABELS = {
    "success": "OK",
    "failure": "Error",
    "waste": "Waste",
    "injection": "Injection",
    "recovery": "Recovery",
}


def _latency_display(ms: int | float | None) -> str:
    if ms is None:
        return "—"
    if ms < 1000:
        return f"{int(ms)}ms"
    return f"{ms / 1000:.1f}s"


def _build_trace_dag_simple(spans: list[dict]) -> dict:
    """Build a simple linear DAG from spans for hook-materialized traces."""
    nodes = []
    edges = []
    span_ids_set = set()
    for i, span in enumerate(spans):
        sid = span.get("span_id", f"span_{i}")
        span_ids_set.add(sid)
        nodes.append(
            {
                "span_id": sid,
                "name": span.get("name", ""),
                "type": span.get("type", ""),
                "status": span.get("status", "ok"),
                "is_cycle": False,
                "depth": i,
            }
        )
        if i > 0:
            prev_sid = spans[i - 1].get("span_id", f"span_{i - 1}")
            edges.append({"src": prev_sid, "dst": sid, "kind": "temporal", "confidence": "high"})

    # Check for cycles: span_id appears as both src and dst
    srcs = {e["src"] for e in edges}
    dsts = {e["dst"] for e in edges}
    cycle_ids = srcs & dsts
    for node in nodes:
        if node["span_id"] in cycle_ids:
            # Mark if it also appears as a src pointing back (true cycle)
            # Simple heuristic: if same id appears >1 time in edges as dst, likely cycle
            node["is_cycle"] = True

    return {"nodes": nodes, "edges": edges}


def _waste_clusters(checks: list[dict]) -> list[dict]:
    clusters = []
    for i, c in enumerate(checks):
        ct = c.get("check_type", "")
        if ct not in _WASTE_CHECK_TYPES or c.get("status") != "FAIL":
            continue
        evidence = c.get("evidence") or []
        span_ids = [e.get("span_id") for e in evidence if isinstance(e, dict) and e.get("span_id")]
        meta = c.get("meta") or {}
        clusters.append(
            {
                "cluster_id": f"cluster_{i}",
                "check_type": ct,
                "span_ids": span_ids,
                "tokens_wasted": int(meta.get("tokens_in", 0) or 0) + int(meta.get("tokens_out", 0) or 0),
                "cost_usd": meta.get("cost_usd"),
                "fix_suggestion": meta.get("fix_suggestion"),
            }
        )
    return clusters


@router.get("/traces/{trace_id}/reliability-report")
async def get_reliability_report(
    trace_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Return the full reliability report for a trace (latest scorecard)."""
    from services.redis import get_redis

    redis = get_redis()

    # Manual Redis cache
    cache_key = f"reliability:{trace_id}"
    try:
        cached = await redis.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        pass  # degrade gracefully

    # Look up latest scorecard by trace_id
    stmt = (
        select(Scorecard)
        .where(Scorecard.trace_id == trace_id)
        .order_by(Scorecard.evaluated_at.desc().nullslast())
        .limit(1)
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        # Try without ordering as fallback
        stmt2 = select(Scorecard).where(Scorecard.trace_id == trace_id).limit(1)
        row = (await db.execute(stmt2)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="No scorecard found for trace_id")

    sc = row

    # Org-scope check
    if current_user.org_id is not None:
        agent = await db.get(Agent, sc.agent_id)
        if not agent or agent.owner_org_id != current_user.org_id:
            raise HTTPException(status_code=403, detail="Agent does not belong to your organization")

    # Load penalties and checks
    raw_output = sc.raw_output or {}
    penalties: list[dict] = raw_output.get("penalties") or []
    checks: list[dict] = list(sc.checks_json or [])
    dim_scores: dict = sc.dimension_scores or {}

    # Rebuild spans
    try:
        _trace_dict, spans = await materialize_session_spans(trace_id)
    except Exception:
        spans = []

    # Sort spans by start_time
    def _span_sort_key(s: dict):
        t = s.get("start_time")
        if t is None:
            return ""
        if isinstance(t, str):
            return t
        return str(t)

    spans_sorted = sorted(spans, key=_span_sort_key)

    # Build causal timeline
    causal_timeline = []
    for span in spans_sorted:
        status = _span_status(span, checks)
        causal_timeline.append(
            {
                "span_id": span.get("span_id", ""),
                "name": span.get("name", ""),
                "type": span.get("type", ""),
                "status": status,
                "status_label": _STATUS_LABELS.get(status, status),
                "description": span.get("error") or "",
                "latency_ms": span.get("latency_ms"),
                "start_time": str(span.get("start_time") or ""),
                "is_main_path": True,
            }
        )

    # Build trace DAG
    trace_dag = _build_trace_dag_simple(spans_sorted)

    # Penalty attribution
    attribution = _penalty_attribution(penalties, dim_scores)
    dominant = _dominant_failure(attribution)

    # Reliability dimensions from dim_scores
    reliability_dimensions = {
        "goal_completion": dim_scores.get("goal_completion"),
        "tool_efficiency": dim_scores.get("tool_efficiency"),
        "tool_failures": dim_scores.get("tool_failures"),
        "factual_grounding": dim_scores.get("factual_grounding"),
        "thought_process": dim_scores.get("thought_process"),
        "adversarial_robustness": dim_scores.get("adversarial_robustness"),
    }

    # Waste clusters
    waste_clusters = _waste_clusters(checks)

    result = {
        "trace_id": trace_id,
        "scorecard_id": str(sc.id),
        "agent_id": str(sc.agent_id),
        "agent_version": sc.version or "",
        "overall_score": float(sc.display_score or sc.overall_score or 0.0),
        "overall_grade": sc.grade or sc.overall_grade or "",
        "penalty_attribution": attribution,
        "dominant_failure": dominant,
        "penalties": penalties,
        "checks": checks,
        "causal_timeline": causal_timeline,
        "trace_dag": trace_dag,
        "reliability_dimensions": reliability_dimensions,
        "waste_clusters": waste_clusters,
        "adversarial_findings": raw_output.get("adversarial_findings"),
    }

    try:
        await redis.set(cache_key, json.dumps(result, default=str), ex=300)
    except Exception:
        pass  # degrade gracefully

    await audit(current_user, "eval.reliability_report.view", resource_type="scorecard", resource_id=str(sc.id))
    return result


async def _generate_scorecard_explanation(
    scorecard_id: str,
    cache_key: str,
    sc: Scorecard,
    redis,
) -> None:
    """Background task: generate prose explanation for a scorecard."""
    from services.eval.eval_service import call_eval_model

    try:
        dim_scores = sc.dimension_scores or {}
        bottleneck = sc.bottleneck or "unknown"
        penalty_count = sc.penalty_count or 0
        score = float(sc.display_score or sc.overall_score or 0.0)
        grade = sc.grade or sc.overall_grade or "N/A"
        dims_text = "; ".join(f"{k}={v:.1f}" for k, v in dim_scores.items() if v is not None)

        raw_output = sc.raw_output or {}
        penalties: list[dict] = raw_output.get("penalties") or []
        attribution = _penalty_attribution(penalties, dim_scores)
        dominant = _dominant_failure(attribution) or "none"

        prompt = (
            f"You are a reliability analyst reviewing an AI agent scorecard.\n\n"
            f"Agent version: {sc.version or 'unknown'}\n"
            f"Overall score: {score:.1f} (Grade: {grade})\n"
            f"Dimension scores: {dims_text or 'none'}\n"
            f"Penalty count: {penalty_count}\n"
            f"Bottleneck: {bottleneck}\n"
            f"Dominant failure category: {dominant}\n\n"
            "Provide a concise (3-5 sentence) root cause analysis explaining why this agent scored "
            "as it did, what the main reliability issues are, and one concrete recommendation to "
            "improve the score. Be direct and technical. No markdown headers."
        )

        result = await call_eval_model(prompt, max_tokens=512)
        explanation = result.get("text") or ""
        if not explanation:
            explanation = (
                f"Agent scored {score:.1f}/{100} (Grade: {grade}). "
                f"Primary failure category: {dominant}. "
                f"{penalty_count} penalties recorded. "
                "Configure an eval model for detailed root cause analysis."
            )
    except Exception as exc:
        _log.warning("scorecard_explanation_failed", scorecard_id=scorecard_id, error=str(exc))
        explanation = "Root cause analysis unavailable — eval model not configured or failed."

    try:
        await redis.set(cache_key, explanation, ex=300)
        await redis.delete(f"{cache_key}:pending")
    except Exception:
        pass


@router.get("/scorecards/{scorecard_id}/explanation")
async def get_scorecard_explanation(
    scorecard_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """202/poll endpoint: prose explanation for a scorecard."""
    from services.redis import get_redis

    sc = await resolve_prefix_id(Scorecard, scorecard_id, db, display_field="version")
    if current_user.org_id is not None:
        agent = await db.get(Agent, sc.agent_id)
        if not agent or agent.owner_org_id != current_user.org_id:
            raise HTTPException(status_code=403, detail="Agent does not belong to your organization")

    cache_key = f"explanation:scorecard:{scorecard_id}"

    try:
        redis = get_redis()
        cached = await redis.get(cache_key)
        if cached:
            return {"status": "ready", "explanation": cached.decode()}

        in_progress = await redis.get(f"{cache_key}:pending")
        if in_progress:
            return JSONResponse(status_code=202, content={"status": "pending", "retry_after": 2})

        await redis.set(f"{cache_key}:pending", "1", ex=60)
    except Exception:
        # Redis unavailable — run synchronously
        dim_scores = sc.dimension_scores or {}
        score = float(sc.display_score or sc.overall_score or 0.0)
        grade = sc.grade or sc.overall_grade or "N/A"
        raw_output = sc.raw_output or {}
        penalties: list[dict] = raw_output.get("penalties") or []
        attribution = _penalty_attribution(penalties, dim_scores)
        dominant = _dominant_failure(attribution) or "none"
        explanation = (
            f"Agent scored {score:.1f}/100 (Grade: {grade}). "
            f"Primary failure category: {dominant}. "
            f"{sc.penalty_count or 0} penalties recorded."
        )
        return {"status": "ready", "explanation": explanation}

    task = asyncio.create_task(_generate_scorecard_explanation(scorecard_id, cache_key, sc, redis))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return JSONResponse(status_code=202, content={"status": "pending", "retry_after": 2})


async def _generate_check_explanation(
    scorecard_id: str,
    check_index: int,
    cache_key: str,
    check: dict,
    redis,
) -> None:
    """Background task: generate prose explanation for a single check result."""
    from services.eval.eval_service import call_eval_model

    try:
        ct = check.get("check_type", "UNKNOWN")
        status = check.get("status", "UNKNOWN")
        category = check.get("category", "unknown")
        points_earned = check.get("points_earned", 0)
        points_possible = check.get("points_possible", 0)
        meta = check.get("meta") or {}
        evidence_list = check.get("evidence") or []
        evidence_spans = ", ".join(e.get("span_id", "") for e in evidence_list if isinstance(e, dict))

        prompt = (
            f"You are a reliability analyst. Explain the following eval check result in plain English.\n\n"
            f"Check type: {ct}\n"
            f"Status: {status}\n"
            f"Category: {category}\n"
            f"Points: {points_earned}/{points_possible}\n"
            f"Evidence spans: {evidence_spans or 'none'}\n"
            f"Metadata: {json.dumps(meta)}\n\n"
            "Provide a 2-3 sentence explanation of what this check detected and why it matters. "
            "Then give one concrete fix suggestion. Be concise and technical."
        )

        result = await call_eval_model(prompt, max_tokens=256)
        explanation = result.get("text") or ""
        if not explanation:
            fix = meta.get("fix_suggestion") or "Review the flagged spans and address the root cause."
            explanation = f"Check {ct} {status.lower()} for {category}. {fix}"
    except Exception as exc:
        _log.warning("check_explanation_failed", scorecard_id=scorecard_id, check_index=check_index, error=str(exc))
        fix = (check.get("meta") or {}).get("fix_suggestion") or ""
        explanation = f"Explanation unavailable. {fix}".strip()

    try:
        await redis.set(cache_key, explanation, ex=300)
        await redis.delete(f"{cache_key}:pending")
    except Exception:
        pass


@router.get("/scorecards/{scorecard_id}/checks/{check_id}/explanation")
async def get_check_explanation(
    scorecard_id: str,
    check_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """202/poll endpoint: explanation for a specific check result (check_id = 0-based index)."""
    from services.redis import get_redis

    sc = await resolve_prefix_id(Scorecard, scorecard_id, db, display_field="version")
    if current_user.org_id is not None:
        agent = await db.get(Agent, sc.agent_id)
        if not agent or agent.owner_org_id != current_user.org_id:
            raise HTTPException(status_code=403, detail="Agent does not belong to your organization")

    checks = list(sc.checks_json or [])
    try:
        check_index = int(check_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="check_id must be a 0-based integer index")

    if check_index < 0 or check_index >= len(checks):
        raise HTTPException(status_code=404, detail=f"Check index {check_index} out of range (0..{len(checks) - 1})")

    check = checks[check_index]

    # Return fix_suggestion directly if available in meta
    meta = check.get("meta") or {}
    fix_suggestion = meta.get("fix_suggestion")
    if fix_suggestion:
        return {"status": "ready", "explanation": fix_suggestion}

    cache_key = f"explanation:check:{scorecard_id}:{check_id}"

    try:
        redis = get_redis()
        cached = await redis.get(cache_key)
        if cached:
            return {"status": "ready", "explanation": cached.decode()}

        in_progress = await redis.get(f"{cache_key}:pending")
        if in_progress:
            return JSONResponse(status_code=202, content={"status": "pending", "retry_after": 2})

        await redis.set(f"{cache_key}:pending", "1", ex=60)
    except Exception:
        ct = check.get("check_type", "UNKNOWN")
        status = check.get("status", "UNKNOWN")
        explanation = f"Check {ct} {status.lower()}. Explanation unavailable (Redis not available)."
        return {"status": "ready", "explanation": explanation}

    task = asyncio.create_task(_generate_check_explanation(scorecard_id, check_index, cache_key, check, redis))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return JSONResponse(status_code=202, content={"status": "pending", "retry_after": 2})
