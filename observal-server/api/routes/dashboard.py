# SPDX-FileCopyrightText: 2026 Subramania Raja <dhanpraja231@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Shreem Seth <shreemseth26@gmail.com>
# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import asyncio
import uuid  # noqa: TC003
from datetime import UTC, timedelta
from datetime import datetime as dt

from fastapi import APIRouter, Depends, Query
from fastapi_cache.decorator import cache
from loguru import logger as optic
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

import services.dynamic_settings as ds
from api.deps import get_db, require_role
from api.sanitize import escape_like
from models.agent import Agent, AgentStatus, AgentVersion
from models.agent_component import AgentComponent
from models.download import AgentDownloadRecord
from models.feedback import Feedback
from models.hook import HookListing, HookVersion
from models.mcp import ListingStatus, McpDownload, McpListing, McpVersion
from models.prompt import PromptListing, PromptVersion
from models.sandbox import SandboxListing, SandboxVersion
from models.skill import SkillListing, SkillVersion
from models.user import User, UserRole
from schemas.dashboard import (
    ComponentLeaderboardItem,
    GraphRagStats,
    HarnessUsage,
    LatencyCell,
    LeaderboardItem,
    OverviewStats,
    SandboxStats,
    TokenStats,
    TopAgentItem,
    TopItem,
    TrendPoint,
    UnannotatedTrace,
)
from services.clickhouse import _query

router = APIRouter(prefix="/api/v1", tags=["dashboard"])

_RANGE_MAP = {"24h": 1, "7d": 7, "30d": 30, "90d": 90}


def _range_days(range_: str | None) -> int:
    return _RANGE_MAP.get(range_ or "7d", 7)


async def _ch_json(sql: str, params: dict | None = None) -> list[dict]:
    """Run a ClickHouse query and return data rows."""
    # Optimize FINAL scans: process partitions independently instead of a
    # single cross-partition merge pass.  Benchmarks show ~2x speedup.
    if "FINAL" in sql and "SETTINGS" not in sql:
        sql += " SETTINGS do_not_merge_across_partitions_select_final = 1"
    try:
        r = await _query(f"{sql} FORMAT JSON", params)
        if r.status_code == 200:
            return r.json().get("data", [])
    except Exception as e:
        optic.warning("clickhouse_query_failed", error=str(e))
    return []


def _project_id_for_user(current_user) -> str:
    """ClickHouse project_id scoped to the requesting user's org."""
    if current_user is not None and current_user.org_id is not None:
        return str(current_user.org_id)
    return "default"


async def _ch_json_scoped(sql: str, current_user, params: dict | None = None) -> list[dict]:
    """_ch_json variant for admin endpoints that scopes queries to the user's org.

    Replaces the hardcoded ``project_id = 'default'`` literal with a
    parameterised placeholder and injects ``param_pid`` automatically.
    """
    pid = _project_id_for_user(current_user)
    scoped_sql = sql.replace("project_id = 'default'", "project_id = {pid:String}")
    scoped_params = {**(params or {}), "param_pid": pid}
    return await _ch_json(scoped_sql, scoped_params)


@router.get("/overview/stats", response_model=OverviewStats)
@cache(expire=ds.get_sync_int("data.cache_ttl_dashboard", 60), namespace="dashboard")
async def overview_stats(
    range_: str | None = Query(None, alias="range"),
    db: AsyncSession = Depends(get_db),
):

    optic.trace("range={}", range_)

    days = _range_days(range_)

    # Fan out all independent queries in parallel (3 Postgres + 2 ClickHouse)
    total_mcps_coro = db.scalar(
        select(func.count(McpListing.id))
        .join(McpVersion, McpListing.latest_version_id == McpVersion.id)
        .where(McpVersion.status == ListingStatus.approved)
    )
    total_agents_coro = db.scalar(
        select(func.count(Agent.id))
        .join(AgentVersion, Agent.latest_version_id == AgentVersion.id)
        .where(AgentVersion.status == AgentStatus.approved, Agent.deleted_at.is_(None))
    )
    total_users_coro = db.scalar(select(func.count(User.id)))
    tool_rows_coro = _ch_json(
        "SELECT sum(tool_call_count) as cnt FROM session_stats_agg WHERE last_event_time > now() - INTERVAL {days:UInt32} DAY",
        {"param_days": str(days)},
    )
    agent_rows_coro = _ch_json(
        "SELECT count() as cnt FROM session_stats_agg WHERE last_event_time > now() - INTERVAL {days:UInt32} DAY",
        {"param_days": str(days)},
    )

    total_mcps, total_agents, total_users, tool_rows, agent_rows = await asyncio.gather(
        total_mcps_coro,
        total_agents_coro,
        total_users_coro,
        tool_rows_coro,
        agent_rows_coro,
    )

    return OverviewStats(
        total_mcps=total_mcps or 0,
        total_agents=total_agents or 0,
        total_users=total_users or 0,
        total_tool_calls=int(tool_rows[0].get("cnt", 0)) if tool_rows else 0,
        total_agent_interactions=int(agent_rows[0].get("cnt", 0)) if agent_rows else 0,
    )


@router.get("/overview/top-mcps", response_model=list[TopItem])
@cache(expire=ds.get_sync_int("data.cache_ttl_dashboard", 60), namespace="dashboard")
async def top_mcps(db: AsyncSession = Depends(get_db)):
    optic.debug("top_mcps called")
    result = await db.execute(
        select(McpDownload.listing_id, func.count(McpDownload.id).label("cnt"), McpListing.name)
        .join(McpListing, McpDownload.listing_id == McpListing.id)
        .group_by(McpDownload.listing_id, McpListing.name)
        .order_by(func.count(McpDownload.id).desc())
        .limit(5)
    )
    return [TopItem(id=row.listing_id, name=row.name, value=row.cnt) for row in result.all()]


@router.get("/overview/top-agents", response_model=list[TopAgentItem])
@cache(expire=ds.get_sync_int("data.cache_ttl_dashboard", 60), namespace="dashboard")
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
        .where(AgentVersion.status == AgentStatus.approved, Agent.deleted_at.is_(None))
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
@cache(expire=ds.get_sync_int("data.cache_ttl_dashboard", 60), namespace="dashboard")
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
        .where(AgentVersion.status == AgentStatus.approved, Agent.deleted_at.is_(None))
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
            .where(
                AgentVersion.status == AgentStatus.approved,
                Agent.deleted_at.is_(None),
                Agent.id.notin_(existing_ids),
            )
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
@cache(expire=ds.get_sync_int("data.cache_ttl_dashboard", 60), namespace="dashboard")
async def component_leaderboard(
    window: str = Query("7d", pattern="^(24h|7d|30d|all)$"),
    limit: int = Query(20, le=50),
    user: str | None = Query(None, description="Filter by creator email"),
    db: AsyncSession = Depends(get_db),
):
    """Public leaderboard of components ranked by agent downloads within a time window."""
    listing_types = [
        (McpListing, McpVersion, "mcp"),
        (SkillListing, SkillVersion, "skill"),
        (HookListing, HookVersion, "hook"),
        (PromptListing, PromptVersion, "prompt"),
        (SandboxListing, SandboxVersion, "sandbox"),
    ]

    all_items: list[ComponentLeaderboardItem] = []
    all_user_ids: set[uuid.UUID] = set()
    all_listing_ids: list[uuid.UUID] = []
    submitted_by_map: dict[uuid.UUID, uuid.UUID] = {}  # component_id -> user_id

    for listing_model, version_model, type_label in listing_types:
        # Count agent downloads for each component via AgentComponent linkage
        stmt = (
            select(
                AgentComponent.component_id,
                func.count(func.distinct(AgentDownloadRecord.id)).label("cnt"),
                listing_model.name,
                version_model.description,
                listing_model.submitted_by,
            )
            .join(AgentVersion, AgentComponent.agent_version_id == AgentVersion.id)
            .join(Agent, Agent.latest_version_id == AgentVersion.id)
            .join(AgentDownloadRecord, AgentDownloadRecord.agent_id == Agent.id)
            .join(listing_model, AgentComponent.component_id == listing_model.id)
            .join(version_model, listing_model.latest_version_id == version_model.id)
            .where(
                AgentComponent.component_type == type_label,
                version_model.status == ListingStatus.approved,
                Agent.deleted_at.is_(None),
            )
        )
        if user:
            stmt = stmt.join(User, listing_model.submitted_by == User.id).where(
                User.email.ilike(f"%{escape_like(user)}%")
            )
        if window != "all":
            days = _RANGE_MAP.get(window, 7)
            stmt = stmt.where(AgentDownloadRecord.installed_at >= dt.now(UTC) - timedelta(days=days))
        stmt = (
            stmt.group_by(
                AgentComponent.component_id, listing_model.name, version_model.description, listing_model.submitted_by
            )
            .order_by(func.count(func.distinct(AgentDownloadRecord.id)).desc())
            .limit(limit)
        )
        rows = (await db.execute(stmt)).all()
        for r in rows:
            all_listing_ids.append(r.component_id)
            all_user_ids.add(r.submitted_by)
            submitted_by_map[r.component_id] = r.submitted_by
            all_items.append(
                ComponentLeaderboardItem(
                    id=r.component_id,
                    name=r.name,
                    component_type=type_label,
                    description=r.description or "",
                    download_count=r.cnt,
                    created_by_email="",
                    average_rating=None,
                    total_reviews=0,
                )
            )

    # Batch-fetch feedback ratings
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

    # Patch in emails and ratings
    for item in all_items:
        avg_rating, total_reviews = rating_map.get(item.id, (None, 0))
        item.average_rating = avg_rating
        item.total_reviews = total_reviews
    for item in all_items:
        uid = submitted_by_map.get(item.id)
        if uid and not item.created_by_email:
            item.created_by_email = email_map.get(uid, "")

    # Backfill: include approved components with zero agent downloads
    if len(all_items) < limit:
        existing_ids = {item.id for item in all_items}
        for listing_model, version_model, type_label in listing_types:
            if len(all_items) >= limit:
                break
            extra_stmt = (
                select(listing_model.id, listing_model.name, version_model.description, listing_model.submitted_by)
                .join(version_model, listing_model.latest_version_id == version_model.id)
                .where(version_model.status == ListingStatus.approved, listing_model.id.notin_(existing_ids))
                .order_by(listing_model.created_at.desc())
                .limit(limit - len(all_items))
            )
            extra_rows = (await db.execute(extra_stmt)).all()
            extra_sub_ids = {r.submitted_by for r in extra_rows if r.submitted_by} - set(email_map)
            if extra_sub_ids:
                for er in (await db.execute(select(User.id, User.email).where(User.id.in_(extra_sub_ids)))).all():
                    email_map[er[0]] = er[1]
            for r in extra_rows:
                if r.id in existing_ids:
                    continue
                existing_ids.add(r.id)
                avg_rating, total_reviews = rating_map.get(r.id, (None, 0))
                all_items.append(
                    ComponentLeaderboardItem(
                        id=r.id,
                        name=r.name,
                        component_type=type_label,
                        description=r.description or "",
                        download_count=0,
                        created_by_email=email_map.get(r.submitted_by, "") if r.submitted_by else "",
                        average_rating=avg_rating,
                        total_reviews=total_reviews,
                    )
                )
                if len(all_items) >= limit:
                    break

    # Sort by download count descending, then by total_reviews descending as tiebreaker
    all_items.sort(key=lambda x: (x.download_count, x.total_reviews), reverse=True)
    return all_items[:limit]


@router.get("/overview/trends", response_model=list[TrendPoint])
@cache(expire=ds.get_sync_int("data.cache_ttl_dashboard", 60), namespace="dashboard")
async def trends(
    range_: str | None = Query(None, alias="range"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    days = _range_days(range_)
    now = dt.now(UTC)
    start = now - timedelta(days=days)

    day_col_mcp = func.date_trunc("day", McpListing.created_at).label("day")
    mcp_stmt = select(day_col_mcp, func.count(McpListing.id).label("cnt")).where(McpListing.created_at >= start)
    if current_user.org_id is not None:
        mcp_stmt = mcp_stmt.where(McpListing.owner_org_id == current_user.org_id)
    mcp_rows = await db.execute(mcp_stmt.group_by(day_col_mcp).order_by(day_col_mcp))

    day_col_user = func.date_trunc("day", User.created_at).label("day")
    user_stmt = select(day_col_user, func.count(User.id).label("cnt")).where(User.created_at >= start)
    if current_user.org_id is not None:
        user_stmt = user_stmt.where(User.org_id == current_user.org_id)
    user_rows = await db.execute(user_stmt.group_by(day_col_user).order_by(day_col_user))

    submissions = {str(r.day.date()): r.cnt for r in mcp_rows.all()}
    users = {str(r.day.date()): r.cnt for r in user_rows.all()}
    all_dates = sorted(set(submissions) | set(users))

    result = [TrendPoint(date=d, submissions=submissions.get(d, 0), users=users.get(d, 0)) for d in all_dates]
    return result


# ---------------------------------------------------------------------------
# Token usage
# ---------------------------------------------------------------------------


@router.get("/dashboard/tokens", response_model=TokenStats)
async def token_stats(range_: str | None = Query(None, alias="range")):
    optic.trace("range={}", range_)
    return TokenStats(
        total_input=0, total_output=0, total_tokens=0, avg_per_trace=0, by_agent=[], by_mcp=[], over_time=[]
    )


@router.get("/dashboard/harness-usage", response_model=HarnessUsage)
async def harness_usage(current_user: User = Depends(require_role(UserRole.admin))):
    optic.trace("user_id={}", current_user.id)
    return HarnessUsage(harnesses=[])


@router.get("/dashboard/sandbox-metrics", response_model=SandboxStats)
async def sandbox_metrics(current_user: User = Depends(require_role(UserRole.admin))):
    optic.trace("user_id={}", current_user.id)
    return SandboxStats(
        total_runs=0,
        oom_count=0,
        oom_rate=0,
        timeout_count=0,
        timeout_rate=0,
        avg_exit_code=None,
        recent_runs=[],
        cpu_over_time=[],
        memory_over_time=[],
    )


@router.get("/dashboard/graphrag-metrics", response_model=GraphRagStats)
async def graphrag_metrics(current_user: User = Depends(require_role(UserRole.admin))):
    optic.trace("user_id={}", current_user.id)
    return GraphRagStats(
        total_queries=0,
        avg_entities=None,
        avg_relationships=None,
        avg_relevance_score=None,
        avg_embedding_latency_ms=None,
        relevance_distribution=[],
        recent_queries=[],
    )


@router.get("/dashboard/latency-heatmap", response_model=list[LatencyCell])
async def latency_heatmap(current_user: User = Depends(require_role(UserRole.admin))):
    optic.trace("user_id={}", current_user.id)
    return []


@router.get("/dashboard/unannotated-traces", response_model=list[UnannotatedTrace])
async def unannotated_traces(current_user: User = Depends(require_role(UserRole.admin))):
    optic.trace("user_id={}", current_user.id)
    return []
