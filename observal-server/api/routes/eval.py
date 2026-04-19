import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.deps import get_db, require_role, resolve_prefix_id
from models.agent import Agent, AgentGoalTemplate
from models.eval import EvalRun, EvalRunStatus, Scorecard
from models.user import User, UserRole
from schemas.eval import EvalRequest, EvalRunDetailResponse, EvalRunResponse, ScorecardResponse
from services.clickhouse import query_spans
from services.eval.eval_service import (
    evaluate_trace,
    fetch_traces,
    parse_scorecard,
    run_agent_scoped_eval,
    run_structured_eval,
)
from services.eval.score_aggregator import ScoreAggregator
from services.hook_materializer import build_agent_eval_context, materialize_agent_eval, materialize_session_spans

router = APIRouter(prefix="/api/v1/eval", tags=["eval"])

_scorecard_load = [selectinload(Scorecard.dimensions)]
_eval_run_load = [selectinload(EvalRun.scorecards).selectinload(Scorecard.dimensions)]


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
        load_options=[selectinload(Agent.goal_template).selectinload(AgentGoalTemplate.sections)],
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

            # Try new structured eval first (uses spans from ClickHouse)
            spans = await query_spans("default", tid, limit=500)
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
    return EvalRunDetailResponse.model_validate(run.scalar_one())


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
    return [EvalRunResponse.model_validate(r) for r in result.scalars().all()]


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
    return [ScorecardResponse.model_validate(s) for s in result.scalars().all()]


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

    return {"version_a": await _avg_scores(version_a), "version_b": await _avg_scores(version_b)}


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
            load_options=[selectinload(Agent.goal_template).selectinload(AgentGoalTemplate.sections)],
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
    return aggregator.compute_agent_aggregate(sc_dicts, window_size=window_size)


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
    return raw.get("penalties", [])
