import uuid
from datetime import UTC, timedelta
from datetime import datetime as dt

import structlog
from fastapi import APIRouter, Depends, Query
from fastapi_cache.decorator import cache
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db, require_role
from api.sanitize import escape_like
from config import settings
from models.agent import Agent, AgentStatus, AgentVersion
from models.download import AgentDownloadRecord
from models.feedback import Feedback
from models.hook import HookDownload, HookListing, HookVersion
from models.mcp import ListingStatus, McpDownload, McpListing, McpVersion
from models.prompt import PromptDownload, PromptListing, PromptVersion
from models.sandbox import SandboxDownload, SandboxListing, SandboxVersion
from models.skill import SkillDownload, SkillListing, SkillVersion
from models.user import User, UserRole
from schemas.dashboard import (
    AgentMetrics,
    ComponentLeaderboardItem,
    DateAvg,
    GraphRagQuery,
    GraphRagStats,
    IdeBreakdown,
    IdeUsage,
    LatencyCell,
    LeaderboardItem,
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
    TopAgentItem,
    TopItem,
    TrendPoint,
    UnannotatedTrace,
)
from services.audit_helpers import audit
from services.clickhouse import _query

logger = structlog.get_logger(__name__)
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
        logger.warning("clickhouse_query_failed", error=str(e))
    return []


@router.get("/mcps/{listing_id}/metrics", response_model=McpMetrics)
@cache(expire=settings.CACHE_TTL_DEFAULT, namespace="dashboard")
async def mcp_metrics(
    listing_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
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

    await audit(current_user, "dashboard.mcp_metrics", resource_type="dashboard", resource_id=str(listing_id))
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
@cache(expire=settings.CACHE_TTL_DEFAULT, namespace="dashboard")
async def agent_metrics(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    from models.eval import Scorecard
    from services.eval.score_aggregator import ScoreAggregator

    dl_count = (
        await db.scalar(select(func.count(AgentDownloadRecord.id)).where(AgentDownloadRecord.agent_id == agent_id)) or 0
    )

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
        select(Scorecard).where(Scorecard.agent_id == agent_id).order_by(Scorecard.evaluated_at.desc()).limit(100)
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

    await audit(current_user, "dashboard.agent_metrics", resource_type="dashboard", resource_id=str(agent_id))
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
@cache(expire=settings.CACHE_TTL_DASHBOARD, namespace="dashboard")
async def overview_stats(
    range_: str | None = Query(None, alias="range"),
    db: AsyncSession = Depends(get_db),
):
    total_mcps = (
        await db.scalar(
            select(func.count(McpListing.id))
            .join(McpVersion, McpListing.latest_version_id == McpVersion.id)
            .where(McpVersion.status == ListingStatus.approved)
        )
        or 0
    )
    total_agents = (
        await db.scalar(
            select(func.count(Agent.id))
            .join(AgentVersion, Agent.latest_version_id == AgentVersion.id)
            .where(AgentVersion.status == AgentStatus.approved)
        )
        or 0
    )
    total_users = await db.scalar(select(func.count(User.id))) or 0

    days = _range_days(range_)
    tool_rows = await _ch_json(
        "SELECT count() as cnt FROM mcp_tool_calls WHERE timestamp > now() - INTERVAL {days:UInt32} DAY",
        {"param_days": str(days)},
    )
    agent_rows = await _ch_json(
        "SELECT count() as cnt FROM agent_interactions WHERE timestamp > now() - INTERVAL {days:UInt32} DAY",
        {"param_days": str(days)},
    )

    return OverviewStats(
        total_mcps=total_mcps,
        total_agents=total_agents,
        total_users=total_users,
        total_tool_calls=int(tool_rows[0].get("cnt", 0)) if tool_rows else 0,
        total_agent_interactions=int(agent_rows[0].get("cnt", 0)) if agent_rows else 0,
    )


@router.get("/overview/top-mcps", response_model=list[TopItem])
@cache(expire=settings.CACHE_TTL_DASHBOARD, namespace="dashboard")
async def top_mcps(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(McpDownload.listing_id, func.count(McpDownload.id).label("cnt"), McpListing.name)
        .join(McpListing, McpDownload.listing_id == McpListing.id)
        .group_by(McpDownload.listing_id, McpListing.name)
        .order_by(func.count(McpDownload.id).desc())
        .limit(5)
    )
    return [TopItem(id=row.listing_id, name=row.name, value=row.cnt) for row in result.all()]


@router.get("/overview/top-agents", response_model=list[TopAgentItem])
@cache(expire=settings.CACHE_TTL_DASHBOARD, namespace="dashboard")
async def top_agents(
    limit: int = Query(6, le=50),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(
            AgentDownloadRecord.agent_id,
            func.count(AgentDownloadRecord.id).label("cnt"),
            Agent.name,
            AgentVersion.description,
            Agent.owner,
            AgentVersion.version,
        )
        .join(Agent, AgentDownloadRecord.agent_id == Agent.id)
        .join(AgentVersion, Agent.latest_version_id == AgentVersion.id)
        .where(AgentVersion.status == AgentStatus.approved)
        .group_by(AgentDownloadRecord.agent_id, Agent.name, AgentVersion.description, Agent.owner, AgentVersion.version)
        .order_by(func.count(AgentDownloadRecord.id).desc())
        .limit(limit)
    )
    rows = result.all()

    # Batch-fetch average ratings
    agent_ids = [r.agent_id for r in rows]
    rating_map: dict[uuid.UUID, float] = {}
    if agent_ids:
        rating_rows = await db.execute(
            select(Feedback.listing_id, func.avg(Feedback.rating))
            .where(Feedback.listing_id.in_(agent_ids), Feedback.listing_type == "agent")
            .group_by(Feedback.listing_id)
        )
        rating_map = {r[0]: round(float(r[1]), 2) for r in rating_rows.all()}

    return [
        TopAgentItem(
            id=row.agent_id,
            name=row.name,
            description=row.description or "",
            owner=row.owner or "",
            version=row.version or "",
            download_count=row.cnt,
            average_rating=rating_map.get(row.agent_id),
        )
        for row in rows
    ]


@router.get("/overview/leaderboard", response_model=list[LeaderboardItem])
@cache(expire=settings.CACHE_TTL_DASHBOARD, namespace="dashboard")
async def agent_leaderboard(
    window: str = Query("7d", pattern="^(24h|7d|30d|all)$"),
    limit: int = Query(20, le=50),
    user: str | None = Query(None, description="Filter by creator email"),
    db: AsyncSession = Depends(get_db),
):
    """Public leaderboard of agents ranked by downloads within a time window."""
    stmt = (
        select(
            AgentDownloadRecord.agent_id,
            func.count(AgentDownloadRecord.id).label("cnt"),
            Agent.name,
            AgentVersion.description,
            Agent.owner,
            AgentVersion.version,
            Agent.created_by,
        )
        .join(Agent, AgentDownloadRecord.agent_id == Agent.id)
        .join(AgentVersion, Agent.latest_version_id == AgentVersion.id)
        .where(AgentVersion.status == AgentStatus.approved)
    )
    if user:
        stmt = stmt.join(User, Agent.created_by == User.id).where(User.email.ilike(f"%{escape_like(user)}%"))
    if window != "all":
        days = _RANGE_MAP.get(window, 7)
        stmt = stmt.where(AgentDownloadRecord.installed_at >= dt.now(UTC) - timedelta(days=days))
    group_cols = [
        AgentDownloadRecord.agent_id,
        Agent.name,
        AgentVersion.description,
        Agent.owner,
        AgentVersion.version,
        Agent.created_by,
    ]
    stmt = stmt.group_by(*group_cols).order_by(func.count(AgentDownloadRecord.id).desc()).limit(limit)
    result = await db.execute(stmt)
    rows = result.all()

    # Batch-fetch average ratings + creator emails
    agent_ids = [r.agent_id for r in rows]
    user_ids = {r.created_by for r in rows}
    rating_map: dict[uuid.UUID, float] = {}
    if agent_ids:
        rating_rows = await db.execute(
            select(Feedback.listing_id, func.avg(Feedback.rating))
            .where(Feedback.listing_id.in_(agent_ids), Feedback.listing_type == "agent")
            .group_by(Feedback.listing_id)
        )
        rating_map = {r[0]: round(float(r[1]), 2) for r in rating_rows.all()}
    email_map: dict[uuid.UUID, str] = {}
    username_map: dict[uuid.UUID, str | None] = {}
    if user_ids:
        email_rows = await db.execute(select(User.id, User.email, User.username).where(User.id.in_(user_ids)))
        for r in email_rows.all():
            email_map[r[0]] = r[1]
            username_map[r[0]] = r[2]

    # Also include agents with no downloads if window=all and we have fewer than limit
    if window == "all" and len(rows) < limit:
        existing_ids = {r.agent_id for r in rows}
        extra_stmt = (
            select(Agent)
            .join(AgentVersion, Agent.latest_version_id == AgentVersion.id)
            .where(AgentVersion.status == AgentStatus.approved, Agent.id.notin_(existing_ids))
        )
        if user:
            extra_stmt = extra_stmt.join(User, Agent.created_by == User.id).where(
                User.email.ilike(f"%{escape_like(user)}%")
            )
        extra_stmt = extra_stmt.order_by(Agent.created_at.desc()).limit(limit - len(rows))
        extra = (await db.execute(extra_stmt)).scalars().all()
        missing_ids = {a.created_by for a in extra} - set(email_map)
        if missing_ids:
            extra_user_rows = await db.execute(
                select(User.id, User.email, User.username).where(User.id.in_(missing_ids))
            )
            for r in extra_user_rows.all():
                email_map[r[0]] = r[1]
                username_map[r[0]] = r[2]
        extra_items = [
            LeaderboardItem(
                id=a.id,
                name=a.name,
                description=a.description or "",
                owner=a.owner or "",
                version=a.version or "",
                download_count=0,
                average_rating=rating_map.get(a.id),
                created_by_email=email_map.get(a.created_by, ""),
                created_by_username=username_map.get(a.created_by),
            )
            for a in extra
        ]
    else:
        extra_items = []

    return [
        LeaderboardItem(
            id=row.agent_id,
            name=row.name,
            description=row.description or "",
            owner=row.owner or "",
            version=row.version or "",
            download_count=row.cnt,
            average_rating=rating_map.get(row.agent_id),
            created_by_email=email_map.get(row.created_by, ""),
            created_by_username=username_map.get(row.created_by),
        )
        for row in rows
    ] + extra_items


@router.get("/overview/component-leaderboard", response_model=list[ComponentLeaderboardItem])
@cache(expire=settings.CACHE_TTL_DASHBOARD, namespace="dashboard")
async def component_leaderboard(
    window: str = Query("7d", pattern="^(24h|7d|30d|all)$"),
    limit: int = Query(20, le=50),
    user: str | None = Query(None, description="Filter by creator email"),
    db: AsyncSession = Depends(get_db),
):
    """Public leaderboard of components ranked by downloads within a time window."""
    # Define all component types: (DownloadModel, ListingModel, VersionModel, type_label)
    component_types = [
        (McpDownload, McpListing, McpVersion, "mcp"),
        (SkillDownload, SkillListing, SkillVersion, "skill"),
        (HookDownload, HookListing, HookVersion, "hook"),
        (PromptDownload, PromptListing, PromptVersion, "prompt"),
        (SandboxDownload, SandboxListing, SandboxVersion, "sandbox"),
    ]

    all_items: list[ComponentLeaderboardItem] = []
    all_user_ids: set[uuid.UUID] = set()

    # Collect raw rows from each component type
    raw_results: list[tuple[str, list]] = []
    for download_model, listing_model, version_model, type_label in component_types:
        stmt = (
            select(
                download_model.listing_id,
                func.count(download_model.id).label("cnt"),
                listing_model.name,
                version_model.description,
                listing_model.submitted_by,
            )
            .join(listing_model, download_model.listing_id == listing_model.id)
            .join(version_model, listing_model.latest_version_id == version_model.id)
            .where(version_model.status == ListingStatus.approved)
        )
        if user:
            stmt = stmt.join(User, listing_model.submitted_by == User.id).where(
                User.email.ilike(f"%{escape_like(user)}%")
            )
        if window != "all":
            days = _RANGE_MAP.get(window, 7)
            stmt = stmt.where(download_model.downloaded_at >= dt.now(UTC) - timedelta(days=days))
        stmt = (
            stmt.group_by(
                download_model.listing_id, listing_model.name, version_model.description, listing_model.submitted_by
            )
            .order_by(func.count(download_model.id).desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        rows = result.all()
        raw_results.append((type_label, rows))

    # Collect all listing IDs across component types for feedback lookup
    all_listing_ids: list[uuid.UUID] = []
    for _type_label, rows in raw_results:
        for r in rows:
            all_listing_ids.append(r.listing_id)
            all_user_ids.add(r.submitted_by)

    # Batch-fetch average ratings and review counts for all listings
    rating_map: dict[uuid.UUID, tuple[float | None, int]] = {}
    if all_listing_ids:
        fb_result = await db.execute(
            select(
                Feedback.listing_id,
                func.avg(Feedback.rating).label("avg_rating"),
                func.count(Feedback.id).label("total_reviews"),
            )
            .where(Feedback.listing_id.in_(all_listing_ids))
            .group_by(Feedback.listing_id)
        )
        for fb_row in fb_result.all():
            avg_r = round(float(fb_row.avg_rating), 2) if fb_row.avg_rating is not None else None
            rating_map[fb_row.listing_id] = (avg_r, fb_row.total_reviews)

    # Resolve user emails
    email_map: dict[uuid.UUID, str] = {}
    if all_user_ids:
        email_rows = await db.execute(select(User.id, User.email).where(User.id.in_(all_user_ids)))
        email_map = {r[0]: r[1] for r in email_rows.all()}

    # Build leaderboard items
    for type_label, rows in raw_results:
        for row in rows:
            avg_rating, total_reviews = rating_map.get(row.listing_id, (None, 0))
            all_items.append(
                ComponentLeaderboardItem(
                    id=row.listing_id,
                    name=row.name,
                    component_type=type_label,
                    description=row.description or "",
                    download_count=row.cnt,
                    created_by_email=email_map.get(row.submitted_by, ""),
                    average_rating=avg_rating,
                    total_reviews=total_reviews,
                )
            )

    # Sort by download count descending, then by total_reviews descending as tiebreaker
    all_items.sort(key=lambda x: (x.download_count, x.total_reviews), reverse=True)
    return all_items[:limit]


@router.get("/overview/trends", response_model=list[TrendPoint])
@cache(expire=settings.CACHE_TTL_DASHBOARD, namespace="dashboard")
async def trends(
    range_: str | None = Query(None, alias="range"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
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
    all_dates = sorted(set(submissions) | set(users))

    result = [TrendPoint(date=d, submissions=submissions.get(d, 0), users=users.get(d, 0)) for d in all_dates]
    await audit(current_user, "dashboard.trends", resource_type="dashboard")
    return result


# ---------------------------------------------------------------------------
# Token usage
# ---------------------------------------------------------------------------


@router.get("/dashboard/tokens", response_model=TokenStats)
@cache(expire=settings.CACHE_TTL_DASHBOARD, namespace="dashboard")
async def token_stats(
    range_: str | None = Query(None, alias="range"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    days = _range_days(range_)
    days_param = {"param_days": str(days)}
    # Totals
    totals = await _ch_json(
        "SELECT "
        "sumIf(token_count_input, token_count_input IS NOT NULL) AS total_input, "
        "sumIf(token_count_output, token_count_output IS NOT NULL) AS total_output, "
        "sumIf(token_count_total, token_count_total IS NOT NULL) AS total_tokens "
        "FROM spans FINAL WHERE project_id = 'default' AND is_deleted = 0 "
        "AND start_time >= now() - INTERVAL {days:UInt32} DAY",
        days_param,
    )
    t = totals[0] if totals else {}
    total_input = int(t.get("total_input", 0))
    total_output = int(t.get("total_output", 0))
    total_tokens = int(t.get("total_tokens", 0))

    # Avg per trace
    avg_rows = await _ch_json(
        "SELECT round(avg(s), 2) AS avg_per_trace FROM ("
        "SELECT trace_id, sum(token_count_total) AS s "
        "FROM spans FINAL WHERE project_id = 'default' AND is_deleted = 0 AND token_count_total IS NOT NULL "
        "AND start_time >= now() - INTERVAL {days:UInt32} DAY "
        "GROUP BY trace_id"
        ")",
        days_param,
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
        "WHERE s.project_id = 'default' AND s.is_deleted = 0 AND t.agent_id != '' "
        "AND s.start_time >= now() - INTERVAL {days:UInt32} DAY "
        "GROUP BY t.agent_id ORDER BY total DESC LIMIT 20",
        days_param,
    )
    agent_ids = [r["agent_id"] for r in by_agent_rows if r.get("agent_id")]
    agent_names: dict[str, str] = {}
    if agent_ids:
        rows = (
            await db.execute(select(Agent.id, Agent.name).where(Agent.id.in_([uuid.UUID(a) for a in agent_ids])))
        ).all()
        agent_names = {str(r.id): r.name for r in rows}
    by_agent = [
        TokenByEntity(
            id=r["agent_id"],
            name=agent_names.get(r["agent_id"], ""),
            input=int(r["input"]),
            output=int(r["output"]),
            total=int(r["total"]),
            traces=int(r["traces"]),
        )
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
        "WHERE s.project_id = 'default' AND s.is_deleted = 0 AND t.mcp_id != '' "
        "AND s.start_time >= now() - INTERVAL {days:UInt32} DAY "
        "GROUP BY t.mcp_id ORDER BY total DESC LIMIT 20",
        days_param,
    )
    mcp_ids = [r["mcp_id"] for r in by_mcp_rows if r.get("mcp_id")]
    mcp_names: dict[str, str] = {}
    if mcp_ids:
        uuid_ids = []
        name_ids = []
        for m in mcp_ids:
            try:
                uuid_ids.append(uuid.UUID(m))
            except (ValueError, AttributeError):
                name_ids.append(m)
        if uuid_ids:
            rows = (await db.execute(select(McpListing.id, McpListing.name).where(McpListing.id.in_(uuid_ids)))).all()
            mcp_names.update({str(r.id): r.name for r in rows})
        if name_ids:
            rows = (await db.execute(select(McpListing.id, McpListing.name).where(McpListing.name.in_(name_ids)))).all()
            mcp_names.update({r.name: r.name for r in rows})
            for n in name_ids:
                mcp_names.setdefault(n, n)
    by_mcp = [
        TokenByEntity(
            id=r["mcp_id"],
            name=mcp_names.get(r["mcp_id"], r["mcp_id"]),
            input=int(r["input"]),
            output=int(r["output"]),
            total=int(r["total"]),
            traces=int(r["traces"]),
        )
        for r in by_mcp_rows
    ]

    # Over time
    over_time_rows = await _ch_json(
        "SELECT toDate(start_time) AS date, "
        "sumIf(token_count_input, token_count_input IS NOT NULL) AS input, "
        "sumIf(token_count_output, token_count_output IS NOT NULL) AS output "
        "FROM spans FINAL WHERE project_id = 'default' AND is_deleted = 0 "
        "AND start_time >= now() - INTERVAL {days:UInt32} DAY "
        "GROUP BY date ORDER BY date",
        days_param,
    )
    over_time = [
        TokenTimePoint(date=str(r["date"]), input=int(r["input"]), output=int(r["output"])) for r in over_time_rows
    ]

    await audit(current_user, "dashboard.token_stats", resource_type="dashboard")
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
@cache(expire=settings.CACHE_TTL_DASHBOARD, namespace="dashboard")
async def ide_usage(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
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
    await audit(current_user, "dashboard.ide_usage", resource_type="dashboard")
    return IdeUsage(ides=ides)


# ---------------------------------------------------------------------------
# Sandbox metrics
# ---------------------------------------------------------------------------


@router.get("/dashboard/sandbox-metrics", response_model=SandboxStats)
@cache(expire=settings.CACHE_TTL_DASHBOARD, namespace="dashboard")
async def sandbox_metrics(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
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

    await audit(current_user, "dashboard.sandbox_metrics", resource_type="dashboard")
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
@cache(expire=settings.CACHE_TTL_DASHBOARD, namespace="dashboard")
async def graphrag_metrics(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
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

    await audit(current_user, "dashboard.graphrag_metrics", resource_type="dashboard")
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
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Run RAGAS evaluation on recent retrieval spans for a GraphRAG."""
    from services.eval.ragas_eval import run_ragas_on_graphrag

    result = await run_ragas_on_graphrag(
        graphrag_id=req.graphrag_id,
        limit=req.limit,
        ground_truths=req.ground_truths,
    )
    avgs = result.get("averages", {})
    await audit(
        current_user,
        "dashboard.graphrag_ragas_eval",
        resource_type="dashboard",
        detail=f"RAGAS eval on graphrag_id={req.graphrag_id}",
    )
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
@cache(expire=settings.CACHE_TTL_DASHBOARD, namespace="dashboard")
async def graphrag_ragas_scores(
    graphrag_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Get previously computed RAGAS scores. If graphrag_id is provided, scoped to that GraphRAG; otherwise aggregate."""
    if graphrag_id:
        from services.eval.ragas_eval import get_ragas_scores

        avgs = await get_ragas_scores(graphrag_id)
    else:
        from services.eval.ragas_eval import get_ragas_aggregate

        avgs = await get_ragas_aggregate()

    await audit(
        current_user,
        "dashboard.graphrag_ragas_scores",
        resource_type="dashboard",
        detail=f"graphrag_id={graphrag_id}" if graphrag_id else "aggregate",
    )
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
@cache(expire=settings.CACHE_TTL_DASHBOARD, namespace="dashboard")
async def latency_heatmap(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
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
    cells = [
        LatencyCell(name=r["name"], hour=str(r["hour"]), p50=float(r["p50"]), p90=float(r["p90"]), p99=float(r["p99"]))
        for r in rows
    ]
    await audit(current_user, "dashboard.latency_heatmap", resource_type="dashboard")
    return cells


# ---------------------------------------------------------------------------
# Unannotated traces
# ---------------------------------------------------------------------------


@router.get("/dashboard/unannotated-traces", response_model=list[UnannotatedTrace])
@cache(expire=settings.CACHE_TTL_DASHBOARD, namespace="dashboard")
async def unannotated_traces(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
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
    traces = [
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
    await audit(current_user, "dashboard.unannotated_traces", resource_type="dashboard")
    return traces
