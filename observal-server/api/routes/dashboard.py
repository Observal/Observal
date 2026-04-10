import logging
import uuid
from datetime import UTC, timedelta
from datetime import datetime as dt

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user, get_db
from models.agent import Agent, AgentStatus
from models.download import AgentDownloadRecord
from models.mcp import ListingStatus, McpDownload, McpListing
from models.user import User
from schemas.dashboard import (
    AgentMetrics,
    DateAvg,
    GraphRagQuery,
    GraphRagStats,
    IdeBreakdown,
    IdeUsage,
    LatencyCell,
    McpMetrics,
    OverviewStats,
    RagasDimensionScore,
    RagasEvalRequest,
    RagasEvalResponse,
    RagasScores,
    RagasSpanResult,
    RelevanceBucket,
    SandboxRun,
    SandboxStats,
    TokenByEntity,
    TokenStats,
    TokenTimePoint,
    TopItem,
    TrendPoint,
    UnannotatedTrace,
)
from services.clickhouse import _query

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["dashboard"])

_RANGE_MAP = {"24h": 1, "7d": 7, "30d": 30, "90d": 90}


def _range_days(range_: str | None) -> int:
    return _RANGE_MAP.get(range_ or "7d", 7)


async def _ch_json(sql: str, params: dict | None = None) -> list[dict]:
    """Run a ClickHouse query and return data rows."""
    try:
        r = await _query(f"{sql} FORMAT JSON", params)
        if r.status_code == 200:
            return r.json().get("data", [])
    except Exception as e:
        logger.warning(f"ClickHouse query failed: {e}")
    return []


@router.get("/mcps/{listing_id}/metrics", response_model=McpMetrics)
async def mcp_metrics(
    listing_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dl_count = await db.scalar(select(func.count(McpDownload.id)).where(McpDownload.listing_id == listing_id)) or 0

    rows = await _ch_json(
        "SELECT "
        "count() as total_calls, "
        "countIf(status='error') as error_count, "
        "round(avg(latency_ms),1) as avg_latency, "
        "quantile(0.5)(latency_ms) as p50, "
        "quantile(0.9)(latency_ms) as p90, "
        "quantile(0.99)(latency_ms) as p99 "
        "FROM mcp_tool_calls WHERE mcp_server_id = {sid:String}",
        {"param_sid": str(listing_id)},
    )
    r = rows[0] if rows else {}
    total_calls = int(r.get("total_calls", 0))
    error_count = int(r.get("error_count", 0))

    return McpMetrics(
        listing_id=listing_id,
        total_downloads=dl_count,
        total_calls=total_calls,
        error_count=error_count,
        error_rate=round(error_count / total_calls, 4) if total_calls else 0,
        avg_latency_ms=float(r.get("avg_latency", 0)),
        p50_latency_ms=int(float(r.get("p50", 0))),
        p90_latency_ms=int(float(r.get("p90", 0))),
        p99_latency_ms=int(float(r.get("p99", 0))),
    )


@router.get("/agents/{agent_id}/metrics", response_model=AgentMetrics)
async def agent_metrics(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from models.eval import Scorecard
    from services.score_aggregator import ScoreAggregator

    dl_count = await db.scalar(select(func.count(AgentDownloadRecord.id)).where(AgentDownloadRecord.agent_id == agent_id)) or 0

    rows = await _ch_json(
        "SELECT "
        "count() as total, "
        "countIf(user_action='accepted') as accepted, "
        "round(avg(tool_calls),1) as avg_tools, "
        "round(avg(latency_ms),1) as avg_latency "
        "FROM agent_interactions WHERE agent_id = {aid:String}",
        {"param_aid": str(agent_id)},
    )
    r = rows[0] if rows else {}
    total = int(r.get("total", 0))
    accepted = int(r.get("accepted", 0))

    # Fetch recent scorecards for dimension breakdown
    sc_result = await db.execute(
        select(Scorecard)
        .where(Scorecard.agent_id == agent_id)
        .order_by(Scorecard.evaluated_at.desc())
        .limit(100)
    )
    scorecards = sc_result.scalars().all()
    dimension_averages = None
    weakest_dimension = None
    drift_alert = False
    if scorecards:
        sc_dicts = [
            {
                "composite_score": sc.composite_score or (sc.overall_score * 10),
                "dimension_scores": sc.dimension_scores or {},
                "evaluated_at": str(sc.evaluated_at),
            }
            for sc in scorecards
        ]
        agg = ScoreAggregator().compute_agent_aggregate(sc_dicts)
        dimension_averages = agg.get("dimension_averages")
        weakest_dimension = agg.get("weakest_dimension")
        drift_alert = agg.get("drift_alert", False)

    return AgentMetrics(
        agent_id=agent_id,
        total_interactions=total,
        total_downloads=dl_count,
        acceptance_rate=round(accepted / total, 4) if total else 0,
        avg_tool_calls=float(r.get("avg_tools", 0)),
        avg_latency_ms=float(r.get("avg_latency", 0)),
        dimension_averages=dimension_averages,
        weakest_dimension=weakest_dimension,
        drift_alert=drift_alert,
    )


@router.get("/overview/stats", response_model=OverviewStats)
async def overview_stats(
    range_: str | None = Query(None, alias="range"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    total_mcps = (
        await db.scalar(select(func.count(McpListing.id)).where(McpListing.status == ListingStatus.approved)) or 0
    )
    total_agents = await db.scalar(select(func.count(Agent.id)).where(Agent.status == AgentStatus.active)) or 0
    total_users = await db.scalar(select(func.count(User.id))) or 0

    days = _range_days(range_)
    tool_rows = await _ch_json(
        f"SELECT count() as cnt FROM mcp_tool_calls WHERE timestamp > now() - INTERVAL {days} DAY"
    )
    agent_rows = await _ch_json(
        f"SELECT count() as cnt FROM agent_interactions WHERE timestamp > now() - INTERVAL {days} DAY"
    )

    return OverviewStats(
        total_mcps=total_mcps,
        total_agents=total_agents,
        total_users=total_users,
        total_tool_calls_today=int(tool_rows[0].get("cnt", 0)) if tool_rows else 0,
        total_agent_interactions_today=int(agent_rows[0].get("cnt", 0)) if agent_rows else 0,
    )


@router.get("/overview/top-mcps", response_model=list[TopItem])
async def top_mcps(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(
        select(McpDownload.listing_id, func.count(McpDownload.id).label("cnt"), McpListing.name)
        .join(McpListing, McpDownload.listing_id == McpListing.id)
        .group_by(McpDownload.listing_id, McpListing.name)
        .order_by(func.count(McpDownload.id).desc())
        .limit(5)
    )
    return [TopItem(id=row.listing_id, name=row.name, value=row.cnt) for row in result.all()]


@router.get("/overview/top-agents", response_model=list[TopItem])
async def top_agents(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(
        select(AgentDownloadRecord.agent_id, func.count(AgentDownloadRecord.id).label("cnt"), Agent.name)
        .join(Agent, AgentDownloadRecord.agent_id == Agent.id)
        .group_by(AgentDownloadRecord.agent_id, Agent.name)
        .order_by(func.count(AgentDownloadRecord.id).desc())
        .limit(5)
    )
    return [TopItem(id=row.agent_id, name=row.name, value=row.cnt) for row in result.all()]


@router.get("/overview/trends", response_model=list[TrendPoint])
async def trends(
    range_: str | None = Query(None, alias="range"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    days = _range_days(range_)
    now = dt.now(UTC)
    start = now - timedelta(days=days)

    day_col_mcp = func.date_trunc("day", McpListing.created_at).label("day")
    mcp_rows = await db.execute(
        select(day_col_mcp, func.count(McpListing.id).label("cnt"))
        .where(McpListing.created_at >= start)
        .group_by(day_col_mcp)
        .order_by(day_col_mcp)
    )

    day_col_user = func.date_trunc("day", User.created_at).label("day")
    user_rows = await db.execute(
        select(day_col_user, func.count(User.id).label("cnt"))
        .where(User.created_at >= start)
        .group_by(day_col_user)
        .order_by(day_col_user)
    )

    submissions = {str(r.day.date()): r.cnt for r in mcp_rows.all()}
    users = {str(r.day.date()): r.cnt for r in user_rows.all()}
    all_dates = sorted(set(list(submissions.keys()) + list(users.keys())))

    return [TrendPoint(date=d, submissions=submissions.get(d, 0), users=users.get(d, 0)) for d in all_dates]


# ---------------------------------------------------------------------------
# Token usage
# ---------------------------------------------------------------------------


@router.get("/dashboard/tokens", response_model=TokenStats)
async def token_stats(
    range_: str | None = Query(None, alias="range"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    days = _range_days(range_)
    time_filter = f"AND start_time >= now() - INTERVAL {days} DAY"
    # Totals
    totals = await _ch_json(
        "SELECT "
        "sumIf(token_count_input, token_count_input IS NOT NULL) AS total_input, "
        "sumIf(token_count_output, token_count_output IS NOT NULL) AS total_output, "
        "sumIf(token_count_total, token_count_total IS NOT NULL) AS total_tokens "
        f"FROM spans FINAL WHERE project_id = 'default' AND is_deleted = 0 {time_filter}"
    )
    t = totals[0] if totals else {}
    total_input = int(t.get("total_input", 0))
    total_output = int(t.get("total_output", 0))
    total_tokens = int(t.get("total_tokens", 0))

    # Avg per trace
    avg_rows = await _ch_json(
        "SELECT round(avg(s), 2) AS avg_per_trace FROM ("
        "SELECT trace_id, sum(token_count_total) AS s "
        f"FROM spans FINAL WHERE project_id = 'default' AND is_deleted = 0 AND token_count_total IS NOT NULL {time_filter} "
        "GROUP BY trace_id"
        ")"
    )
    avg_per_trace = float((avg_rows[0] if avg_rows else {}).get("avg_per_trace", 0))

    # By agent
    by_agent_rows = await _ch_json(
        "SELECT t.agent_id AS agent_id, "
        "sumIf(s.token_count_input, s.token_count_input IS NOT NULL) AS input, "
        "sumIf(s.token_count_output, s.token_count_output IS NOT NULL) AS output, "
        "sumIf(s.token_count_total, s.token_count_total IS NOT NULL) AS total, "
        "count(DISTINCT t.trace_id) AS traces "
        "FROM spans AS s FINAL "
        "INNER JOIN traces AS t FINAL ON s.trace_id = t.trace_id AND t.project_id = 'default' AND t.is_deleted = 0 "
        f"WHERE s.project_id = 'default' AND s.is_deleted = 0 AND t.agent_id != '' {time_filter.replace('start_time', 's.start_time')} "
        "GROUP BY t.agent_id ORDER BY total DESC LIMIT 20"
    )
    agent_ids = [r["agent_id"] for r in by_agent_rows if r.get("agent_id")]
    agent_names: dict[str, str] = {}
    if agent_ids:
        rows = (await db.execute(select(Agent.id, Agent.name).where(Agent.id.in_([uuid.UUID(a) for a in agent_ids])))).all()
        agent_names = {str(r.id): r.name for r in rows}
    by_agent = [
        TokenByEntity(id=r["agent_id"], name=agent_names.get(r["agent_id"], ""), input=int(r["input"]), output=int(r["output"]), total=int(r["total"]), traces=int(r["traces"]))
        for r in by_agent_rows
    ]

    # By MCP
    by_mcp_rows = await _ch_json(
        "SELECT t.mcp_id AS mcp_id, "
        "sumIf(s.token_count_input, s.token_count_input IS NOT NULL) AS input, "
        "sumIf(s.token_count_output, s.token_count_output IS NOT NULL) AS output, "
        "sumIf(s.token_count_total, s.token_count_total IS NOT NULL) AS total, "
        "count(DISTINCT t.trace_id) AS traces "
        "FROM spans AS s FINAL "
        "INNER JOIN traces AS t FINAL ON s.trace_id = t.trace_id AND t.project_id = 'default' AND t.is_deleted = 0 "
        f"WHERE s.project_id = 'default' AND s.is_deleted = 0 AND t.mcp_id != '' {time_filter.replace('start_time', 's.start_time')} "
        "GROUP BY t.mcp_id ORDER BY total DESC LIMIT 20"
    )
    mcp_ids = [r["mcp_id"] for r in by_mcp_rows if r.get("mcp_id")]
    mcp_names: dict[str, str] = {}
    if mcp_ids:
        rows = (await db.execute(select(McpListing.id, McpListing.name).where(McpListing.id.in_([uuid.UUID(m) for m in mcp_ids])))).all()
        mcp_names = {str(r.id): r.name for r in rows}
    by_mcp = [
        TokenByEntity(id=r["mcp_id"], name=mcp_names.get(r["mcp_id"], ""), input=int(r["input"]), output=int(r["output"]), total=int(r["total"]), traces=int(r["traces"]))
        for r in by_mcp_rows
    ]

    # Over time
    over_time_rows = await _ch_json(
        "SELECT toDate(start_time) AS date, "
        "sumIf(token_count_input, token_count_input IS NOT NULL) AS input, "
        "sumIf(token_count_output, token_count_output IS NOT NULL) AS output "
        f"FROM spans FINAL WHERE project_id = 'default' AND is_deleted = 0 {time_filter} "
        "GROUP BY date ORDER BY date"
    )
    over_time = [TokenTimePoint(date=str(r["date"]), input=int(r["input"]), output=int(r["output"])) for r in over_time_rows]

    return TokenStats(
        total_input=total_input,
        total_output=total_output,
        total_tokens=total_tokens,
        avg_per_trace=avg_per_trace,
        by_agent=by_agent,
        by_mcp=by_mcp,
        over_time=over_time,
    )


# ---------------------------------------------------------------------------
# IDE usage
# ---------------------------------------------------------------------------


@router.get("/dashboard/ide-usage", response_model=IdeUsage)
async def ide_usage(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = await _ch_json(
        "SELECT t.ide AS ide, "
        "count(DISTINCT t.trace_id) AS traces, "
        "round(avg(s.latency_ms), 1) AS avg_latency_ms, "
        "countIf(s.status = 'error') AS error_count, "
        "count(s.span_id) AS total_spans "
        "FROM traces AS t FINAL "
        "INNER JOIN spans AS s FINAL ON t.trace_id = s.trace_id AND s.project_id = 'default' AND s.is_deleted = 0 "
        "WHERE t.project_id = 'default' AND t.is_deleted = 0 "
        "GROUP BY t.ide ORDER BY traces DESC"
    )
    ides = [
        IdeBreakdown(
            ide=r["ide"],
            traces=int(r["traces"]),
            avg_latency_ms=float(r.get("avg_latency_ms") or 0),
            error_count=int(r["error_count"]),
            error_rate=round(int(r["error_count"]) / int(r["total_spans"]), 4) if int(r.get("total_spans", 0)) else 0,
        )
        for r in rows
    ]
    return IdeUsage(ides=ides)


# ---------------------------------------------------------------------------
# Sandbox metrics
# ---------------------------------------------------------------------------


@router.get("/dashboard/sandbox-metrics", response_model=SandboxStats)
async def sandbox_metrics(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    agg = await _ch_json(
        "SELECT count() AS total_runs, "
        "countIf(metadata['oom'] = '1' OR metadata['oom'] = 'true') AS oom_count, "
        "countIf(metadata['timeout'] = '1' OR metadata['timeout'] = 'true') AS timeout_count, "
        "avg(toFloat64OrNull(metadata['exit_code'])) AS avg_exit_code "
        "FROM spans FINAL WHERE project_id = 'default' AND is_deleted = 0 AND type = 'sandbox_exec'"
    )
    a = agg[0] if agg else {}
    total_runs = int(a.get("total_runs", 0))
    oom_count = int(a.get("oom_count", 0))
    timeout_count = int(a.get("timeout_count", 0))

    recent = await _ch_json(
        "SELECT span_id, name, "
        "metadata['exit_code'] AS exit_code, "
        "latency_ms AS duration_ms, memory_mb, cpu_ms, "
        "metadata['oom'] AS oom, "
        "start_time "
        "FROM spans FINAL WHERE project_id = 'default' AND is_deleted = 0 AND type = 'sandbox_exec' "
        "ORDER BY start_time DESC LIMIT 20"
    )
    recent_runs = [
        SandboxRun(
            span_id=r["span_id"],
            name=r.get("name", ""),
            exit_code=int(r["exit_code"]) if r.get("exit_code") else None,
            duration_ms=int(r["duration_ms"]) if r.get("duration_ms") else None,
            memory_mb=float(r["memory_mb"]) if r.get("memory_mb") else None,
            cpu_ms=int(r["cpu_ms"]) if r.get("cpu_ms") else None,
            oom=r.get("oom") in ("1", "true"),
            timestamp=str(r.get("start_time", "")),
        )
        for r in recent
    ]

    cpu_rows = await _ch_json(
        "SELECT toDate(start_time) AS date, round(avg(cpu_ms), 1) AS avg_cpu "
        "FROM spans FINAL WHERE project_id = 'default' AND is_deleted = 0 AND type = 'sandbox_exec' AND cpu_ms IS NOT NULL "
        "GROUP BY date ORDER BY date"
    )
    mem_rows = await _ch_json(
        "SELECT toDate(start_time) AS date, round(avg(memory_mb), 2) AS avg_memory "
        "FROM spans FINAL WHERE project_id = 'default' AND is_deleted = 0 AND type = 'sandbox_exec' AND memory_mb IS NOT NULL "
        "GROUP BY date ORDER BY date"
    )

    return SandboxStats(
        total_runs=total_runs,
        oom_count=oom_count,
        oom_rate=round(oom_count / total_runs, 4) if total_runs else 0,
        timeout_count=timeout_count,
        timeout_rate=round(timeout_count / total_runs, 4) if total_runs else 0,
        avg_exit_code=float(a["avg_exit_code"]) if a.get("avg_exit_code") else None,
        recent_runs=recent_runs,
        cpu_over_time=[DateAvg(date=str(r["date"]), avg_cpu=float(r["avg_cpu"])) for r in cpu_rows],
        memory_over_time=[DateAvg(date=str(r["date"]), avg_memory=float(r["avg_memory"])) for r in mem_rows],
    )


# ---------------------------------------------------------------------------
# GraphRAG metrics
# ---------------------------------------------------------------------------


@router.get("/dashboard/graphrag-metrics", response_model=GraphRagStats)
async def graphrag_metrics(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    agg = await _ch_json(
        "SELECT count() AS total_queries, "
        "round(avg(entities_retrieved), 2) AS avg_entities, "
        "round(avg(relationships_used), 2) AS avg_relationships, "
        "round(avg(toFloat64OrNull(metadata['relevance_score'])), 4) AS avg_relevance_score, "
        "round(avg(toFloat64OrNull(metadata['embedding_latency_ms'])), 1) AS avg_embedding_latency_ms "
        "FROM spans FINAL WHERE project_id = 'default' AND is_deleted = 0 AND type = 'retrieval'"
    )
    a = agg[0] if agg else {}

    dist = await _ch_json(
        "SELECT multiIf("
        "toFloat64OrNull(metadata['relevance_score']) < 0.2, '0.0-0.2', "
        "toFloat64OrNull(metadata['relevance_score']) < 0.4, '0.2-0.4', "
        "toFloat64OrNull(metadata['relevance_score']) < 0.6, '0.4-0.6', "
        "toFloat64OrNull(metadata['relevance_score']) < 0.8, '0.6-0.8', "
        "'0.8-1.0') AS bucket, "
        "count() AS count "
        "FROM spans FINAL WHERE project_id = 'default' AND is_deleted = 0 AND type = 'retrieval' "
        "AND metadata['relevance_score'] != '' "
        "GROUP BY bucket ORDER BY bucket"
    )

    recent = await _ch_json(
        "SELECT span_id, name, "
        "metadata['query_interface'] AS query_interface, "
        "entities_retrieved, relationships_used, "
        "metadata['relevance_score'] AS relevance_score, "
        "latency_ms, start_time "
        "FROM spans FINAL WHERE project_id = 'default' AND is_deleted = 0 AND type = 'retrieval' "
        "ORDER BY start_time DESC LIMIT 20"
    )

    return GraphRagStats(
        total_queries=int(a.get("total_queries", 0)),
        avg_entities=float(a["avg_entities"]) if a.get("avg_entities") else None,
        avg_relationships=float(a["avg_relationships"]) if a.get("avg_relationships") else None,
        avg_relevance_score=float(a["avg_relevance_score"]) if a.get("avg_relevance_score") else None,
        avg_embedding_latency_ms=float(a["avg_embedding_latency_ms"]) if a.get("avg_embedding_latency_ms") else None,
        relevance_distribution=[RelevanceBucket(bucket=r["bucket"], count=int(r["count"])) for r in dist],
        recent_queries=[
            GraphRagQuery(
                span_id=r["span_id"],
                name=r.get("name", ""),
                query_interface=r.get("query_interface") or None,
                entities=int(r["entities_retrieved"]) if r.get("entities_retrieved") else None,
                relationships=int(r["relationships_used"]) if r.get("relationships_used") else None,
                relevance_score=float(r["relevance_score"]) if r.get("relevance_score") else None,
                latency_ms=int(r["latency_ms"]) if r.get("latency_ms") else None,
                timestamp=str(r.get("start_time", "")),
            )
            for r in recent
        ],
    )


# ---------------------------------------------------------------------------
# RAGAS evaluation for GraphRAGs
# ---------------------------------------------------------------------------


@router.post("/dashboard/graphrag-ragas-eval", response_model=RagasEvalResponse)
async def run_graphrag_ragas_eval(
    req: RagasEvalRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Run RAGAS evaluation on recent retrieval spans for a GraphRAG."""
    from services.ragas_eval import run_ragas_on_graphrag

    result = await run_ragas_on_graphrag(
        graphrag_id=req.graphrag_id,
        limit=req.limit,
        ground_truths=req.ground_truths,
    )
    avgs = result.get("averages", {})
    return RagasEvalResponse(
        spans_evaluated=result["spans_evaluated"],
        scores=[RagasSpanResult(**s) for s in result["scores"]],
        averages=RagasScores(
            faithfulness=RagasDimensionScore(avg=avgs.get("faithfulness"), count=result["spans_evaluated"]),
            answer_relevancy=RagasDimensionScore(avg=avgs.get("answer_relevancy"), count=result["spans_evaluated"]),
            context_precision=RagasDimensionScore(avg=avgs.get("context_precision"), count=result["spans_evaluated"]),
            context_recall=RagasDimensionScore(avg=avgs.get("context_recall"), count=result["spans_evaluated"]),
        ),
    )


@router.get("/dashboard/graphrag-ragas-scores", response_model=RagasScores)
async def graphrag_ragas_scores(
    graphrag_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get previously computed RAGAS scores. If graphrag_id is provided, scoped to that GraphRAG; otherwise aggregate."""
    if graphrag_id:
        from services.ragas_eval import get_ragas_scores
        avgs = await get_ragas_scores(graphrag_id)
    else:
        from services.ragas_eval import get_ragas_aggregate
        avgs = await get_ragas_aggregate()

    return RagasScores(
        faithfulness=RagasDimensionScore(**avgs.get("faithfulness", {"avg": None, "count": 0})),
        answer_relevancy=RagasDimensionScore(**avgs.get("answer_relevancy", {"avg": None, "count": 0})),
        context_precision=RagasDimensionScore(**avgs.get("context_precision", {"avg": None, "count": 0})),
        context_recall=RagasDimensionScore(**avgs.get("context_recall", {"avg": None, "count": 0})),
    )


# ---------------------------------------------------------------------------
# Latency heatmap
# ---------------------------------------------------------------------------


@router.get("/dashboard/latency-heatmap", response_model=list[LatencyCell])
async def latency_heatmap(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = await _ch_json(
        "SELECT name, toStartOfHour(start_time) AS hour, "
        "round(quantile(0.5)(latency_ms), 1) AS p50, "
        "round(quantile(0.9)(latency_ms), 1) AS p90, "
        "round(quantile(0.99)(latency_ms), 1) AS p99 "
        "FROM spans FINAL "
        "WHERE project_id = 'default' AND is_deleted = 0 "
        "AND start_time >= now() - INTERVAL 24 HOUR "
        "AND latency_ms IS NOT NULL "
        "AND name IN ("
        "SELECT name FROM spans FINAL "
        "WHERE project_id = 'default' AND is_deleted = 0 "
        "AND start_time >= now() - INTERVAL 24 HOUR "
        "AND latency_ms IS NOT NULL "
        "GROUP BY name ORDER BY count() DESC LIMIT 20"
        ") "
        "GROUP BY name, hour ORDER BY name, hour"
    )
    return [
        LatencyCell(name=r["name"], hour=str(r["hour"]), p50=float(r["p50"]), p90=float(r["p90"]), p99=float(r["p99"]))
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Unannotated traces
# ---------------------------------------------------------------------------


@router.get("/dashboard/unannotated-traces", response_model=list[UnannotatedTrace])
async def unannotated_traces(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = await _ch_json(
        "SELECT trace_id, name, session_id, ide, trace_type, start_time "
        "FROM traces FINAL "
        "WHERE project_id = 'default' AND is_deleted = 0 "
        "AND trace_id NOT IN ("
        "SELECT DISTINCT trace_id FROM scores FINAL "
        "WHERE project_id = 'default' AND is_deleted = 0 AND source = 'human'"
        ") "
        "ORDER BY start_time DESC LIMIT 50"
    )
    return [
        UnannotatedTrace(
            trace_id=r["trace_id"],
            name=r.get("name") or None,
            session_id=r.get("session_id") or None,
            ide=r.get("ide") or None,
            trace_type=r.get("trace_type") or None,
            start_time=str(r.get("start_time", "")),
        )
        for r in rows
    ]
