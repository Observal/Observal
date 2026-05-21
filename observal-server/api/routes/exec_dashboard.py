# SPDX-License-Identifier: AGPL-3.0-only

"""Executive Dashboard API endpoints."""

import uuid
from datetime import UTC, timedelta
from datetime import datetime as dt

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db, require_role
from api.routes.dashboard import _ch_json_scoped, _range_days
from config import settings
from models.agent import Agent, AgentTeamAccess, AgentVersion, AgentStatus
from models.download import AgentDownloadRecord
from models.exec_config import ExecDashboardConfig
from models.feedback import Feedback
from models.organization import Organization
from models.user import User, UserRole
from models.user_group import UserGroup

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/exec", tags=["exec-dashboard"])


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def compute_trend_percent(current: int, previous: int) -> float:
    """Compute period-over-period trend as a percentage."""
    if previous == 0:
        return 100.0 if current > 0 else 0.0
    return round(((current - previous) / previous) * 100, 1)


def _period_bounds(range_: str | None) -> tuple[dt, dt, dt, dt]:
    """Return (current_start, current_end, previous_start, previous_end) for a range."""
    days = _range_days(range_)
    now = dt.now(UTC)
    current_start = now - timedelta(days=days)
    current_end = now
    previous_start = current_start - timedelta(days=days)
    previous_end = current_start
    return current_start, current_end, previous_start, previous_end


async def resolve_user_departments(db: AsyncSession, org_id: uuid.UUID | None) -> dict[str, list[str]]:
    """Return {department_name: [user_id_strings]} mapping.

    Priority: user_groups table (SSO) > users.department column (local-auth).
    Users with neither are grouped as 'Unassigned'.
    """
    dept_map: dict[str, list[str]] = {}
    assigned_user_ids: set[uuid.UUID] = set()

    # SSO groups
    if org_id:
        group_rows = (
            await db.execute(
                select(UserGroup.group_name, UserGroup.user_id)
                .join(User, UserGroup.user_id == User.id)
                .where(User.org_id == org_id)
            )
        ).all()
    else:
        group_rows = (await db.execute(select(UserGroup.group_name, UserGroup.user_id))).all()

    for row in group_rows:
        dept_map.setdefault(row.group_name, []).append(str(row.user_id))
        assigned_user_ids.add(row.user_id)

    # Fallback: users.department for users not in user_groups
    if org_id:
        dept_rows = (
            await db.execute(
                select(User.id, User.department)
                .where(User.org_id == org_id, User.department.isnot(None), User.id.notin_(assigned_user_ids) if assigned_user_ids else User.department.isnot(None))
            )
        ).all()
    else:
        dept_rows = (
            await db.execute(
                select(User.id, User.department)
                .where(User.department.isnot(None), User.id.notin_(assigned_user_ids) if assigned_user_ids else User.department.isnot(None))
            )
        ).all()

    for row in dept_rows:
        dept_map.setdefault(row.department, []).append(str(row.id))
        assigned_user_ids.add(row.id)

    # Unassigned users
    if org_id:
        all_users = (await db.execute(select(User.id).where(User.org_id == org_id))).scalars().all()
    else:
        all_users = (await db.execute(select(User.id))).scalars().all()

    unassigned = [str(uid) for uid in all_users if uid not in assigned_user_ids]
    if unassigned:
        dept_map["Unassigned"] = unassigned

    return dept_map


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ExecConfigResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    hourly_dev_cost: float
    pre_ai_baselines: dict
    department_budgets: dict
    target_adoption_pct: int
    target_adoption_date: str | None


class ExecConfigUpdate(BaseModel):
    hourly_dev_cost: float | None = None
    pre_ai_baselines: dict | None = None
    department_budgets: dict | None = None
    target_adoption_pct: int | None = None
    target_adoption_date: str | None = None


# ---------------------------------------------------------------------------
# Config endpoint
# ---------------------------------------------------------------------------


@router.get("/config", response_model=ExecConfigResponse | None)
async def get_exec_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Get exec dashboard configuration for the current org."""
    if not current_user.org_id:
        return None

    result = await db.execute(
        select(ExecDashboardConfig).where(ExecDashboardConfig.org_id == current_user.org_id)
    )
    config = result.scalar_one_or_none()
    if not config:
        return None

    return _config_to_response(config)


@router.put("/config", response_model=ExecConfigResponse)
async def update_exec_config(
    req: ExecConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Create or update exec dashboard configuration."""
    if not current_user.org_id:
        raise HTTPException(status_code=400, detail="User has no organization")

    result = await db.execute(
        select(ExecDashboardConfig).where(ExecDashboardConfig.org_id == current_user.org_id)
    )
    config = result.scalar_one_or_none()

    if not config:
        config = ExecDashboardConfig(org_id=current_user.org_id)
        db.add(config)

    if req.hourly_dev_cost is not None:
        config.hourly_dev_cost = req.hourly_dev_cost
    if req.pre_ai_baselines is not None:
        config.pre_ai_baselines = req.pre_ai_baselines
    if req.department_budgets is not None:
        config.department_budgets = req.department_budgets
    if req.target_adoption_pct is not None:
        config.target_adoption_pct = req.target_adoption_pct
    if req.target_adoption_date is not None:
        from datetime import date

        config.target_adoption_date = date.fromisoformat(req.target_adoption_date)

    await db.commit()
    await db.refresh(config)

    return _config_to_response(config)


def _config_to_response(config: ExecDashboardConfig) -> ExecConfigResponse:
    return ExecConfigResponse(
        id=config.id,
        org_id=config.org_id,
        hourly_dev_cost=float(config.hourly_dev_cost),
        pre_ai_baselines=config.pre_ai_baselines or {},
        department_budgets=config.department_budgets or {},
        target_adoption_pct=config.target_adoption_pct,
        target_adoption_date=str(config.target_adoption_date) if config.target_adoption_date else None,
    )


# ---------------------------------------------------------------------------
# Adoption Tab
# ---------------------------------------------------------------------------


class AdoptionPoint(BaseModel):
    month: str
    adoption_pct: float


class AdoptionResponse(BaseModel):
    monthly: list[AdoptionPoint]
    current_pct: float
    total_users: int
    active_users: int
    departments_covered: int


@router.get("/adoption", response_model=AdoptionResponse)
async def get_adoption(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Monthly AI adoption % (active users with traces / total users)."""
    org_id = current_user.org_id

    # Total users in org
    user_stmt = select(func.count(User.id))
    if org_id:
        user_stmt = user_stmt.where(User.org_id == org_id)
    total_users = await db.scalar(user_stmt) or 0

    # Monthly active users from ClickHouse (last 12 months)
    rows = await _ch_json_scoped(
        "SELECT toStartOfMonth(start_time) AS month, count(DISTINCT user_id) AS active "
        "FROM traces FINAL WHERE project_id = 'default' AND is_deleted = 0 "
        "AND start_time >= now() - INTERVAL 12 MONTH "
        "GROUP BY month ORDER BY month",
        current_user,
    )

    monthly = []
    for r in rows:
        active = int(r.get("active", 0))
        pct = round((active / total_users) * 100, 1) if total_users > 0 else 0.0
        monthly.append(AdoptionPoint(month=str(r["month"])[:7], adoption_pct=pct))

    # Current month active users
    current_rows = await _ch_json_scoped(
        "SELECT count(DISTINCT user_id) AS active "
        "FROM traces FINAL WHERE project_id = 'default' AND is_deleted = 0 "
        "AND start_time >= toStartOfMonth(now())",
        current_user,
    )
    active_users = int(current_rows[0]["active"]) if current_rows else 0
    current_pct = round((active_users / total_users) * 100, 1) if total_users > 0 else 0.0

    # Departments covered (groups with at least one active user)
    dept_map = await resolve_user_departments(db, org_id)
    departments_covered = sum(1 for k in dept_map if k != "Unassigned")

    return AdoptionResponse(
        monthly=monthly,
        current_pct=current_pct,
        total_users=total_users,
        active_users=active_users,
        departments_covered=departments_covered,
    )


class AgentCountBreakdown(BaseModel):
    total: int
    active: int
    published: int
    in_development: int
    by_category: list[dict]


@router.get("/agent-counts", response_model=AgentCountBreakdown)
async def get_agent_counts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Agent count breakdown by status and category."""
    org_id = current_user.org_id

    base = select(Agent)
    if org_id:
        base = base.where(Agent.owner_org_id == org_id)

    # Total
    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0

    # Published (approved latest version)
    pub_stmt = (
        select(func.count(Agent.id))
        .join(AgentVersion, Agent.latest_version_id == AgentVersion.id)
        .where(AgentVersion.status == AgentStatus.approved)
    )
    if org_id:
        pub_stmt = pub_stmt.where(Agent.owner_org_id == org_id)
    published = await db.scalar(pub_stmt) or 0

    # In development (pending/draft)
    dev_stmt = (
        select(func.count(Agent.id))
        .join(AgentVersion, Agent.latest_version_id == AgentVersion.id)
        .where(AgentVersion.status.in_([AgentStatus.pending, AgentStatus.draft]))
    )
    if org_id:
        dev_stmt = dev_stmt.where(Agent.owner_org_id == org_id)
    in_development = await db.scalar(dev_stmt) or 0

    # Active (had traces in last 7 days) — from ClickHouse
    active_rows = await _ch_json_scoped(
        "SELECT count(DISTINCT agent_id) AS cnt FROM traces FINAL "
        "WHERE project_id = 'default' AND is_deleted = 0 "
        "AND agent_id != '' AND start_time >= now() - INTERVAL 7 DAY",
        current_user,
    )
    active = int(active_rows[0]["cnt"]) if active_rows else 0

    # By category
    cat_stmt = select(Agent.category, func.count(Agent.id)).group_by(Agent.category)
    if org_id:
        cat_stmt = cat_stmt.where(Agent.owner_org_id == org_id)
    cat_rows = (await db.execute(cat_stmt)).all()
    by_category = [
        {"category": row[0] or "Uncategorized", "count": row[1]}
        for row in cat_rows
    ]

    return AgentCountBreakdown(
        total=total,
        active=active,
        published=published,
        in_development=in_development,
        by_category=by_category,
    )


class UsageByCategoryItem(BaseModel):
    category: str
    sessions: int
    growth_pct: float


@router.get("/usage-by-category", response_model=list[UsageByCategoryItem])
async def get_usage_by_category(
    range_: str | None = Query(None, alias="range"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Agent usage grouped by category with period-over-period growth."""
    days = _range_days(range_)

    # Current period sessions by agent
    current_rows = await _ch_json_scoped(
        "SELECT agent_id, count() AS cnt FROM traces FINAL "
        "WHERE project_id = 'default' AND is_deleted = 0 AND agent_id != '' "
        "AND start_time >= now() - INTERVAL {days:UInt32} DAY "
        "GROUP BY agent_id",
        current_user,
        {"param_days": str(days)},
    )

    # Previous period
    prev_rows = await _ch_json_scoped(
        "SELECT agent_id, count() AS cnt FROM traces FINAL "
        "WHERE project_id = 'default' AND is_deleted = 0 AND agent_id != '' "
        "AND start_time >= now() - INTERVAL {days2:UInt32} DAY "
        "AND start_time < now() - INTERVAL {days:UInt32} DAY "
        "GROUP BY agent_id",
        current_user,
        {"param_days": str(days), "param_days2": str(days * 2)},
    )

    # Resolve agent_id → category from PG
    agent_ids = list({r["agent_id"] for r in current_rows + prev_rows if r.get("agent_id")})
    cat_map: dict[str, str] = {}
    if agent_ids:
        import uuid as _uuid

        valid_ids = []
        for aid in agent_ids:
            try:
                valid_ids.append(_uuid.UUID(aid))
            except (ValueError, AttributeError):
                pass
        if valid_ids:
            rows = (await db.execute(select(Agent.id, Agent.category).where(Agent.id.in_(valid_ids)))).all()
            cat_map = {str(r.id): r.category or "Uncategorized" for r in rows}

    # Aggregate by category
    current_by_cat: dict[str, int] = {}
    for r in current_rows:
        cat = cat_map.get(r["agent_id"], "Uncategorized")
        current_by_cat[cat] = current_by_cat.get(cat, 0) + int(r["cnt"])

    prev_by_cat: dict[str, int] = {}
    for r in prev_rows:
        cat = cat_map.get(r["agent_id"], "Uncategorized")
        prev_by_cat[cat] = prev_by_cat.get(cat, 0) + int(r["cnt"])

    result = []
    for cat, sessions in sorted(current_by_cat.items(), key=lambda x: -x[1]):
        prev = prev_by_cat.get(cat, 0)
        growth = compute_trend_percent(sessions, prev)
        result.append(UsageByCategoryItem(category=cat, sessions=sessions, growth_pct=growth))

    return result


class PlatformCoverageItem(BaseModel):
    platform: str
    users: int
    sessions: int


@router.get("/platform-coverage", response_model=list[PlatformCoverageItem])
async def get_platform_coverage(
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """IDE/platform coverage — distinct users and sessions per platform."""
    rows = await _ch_json_scoped(
        "SELECT ide, count(DISTINCT user_id) AS users, count() AS sessions "
        "FROM traces FINAL WHERE project_id = 'default' AND is_deleted = 0 "
        "AND ide != '' "
        "GROUP BY ide ORDER BY sessions DESC",
        current_user,
    )
    return [
        PlatformCoverageItem(platform=r["ide"], users=int(r["users"]), sessions=int(r["sessions"]))
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Investments Tab (Platform Comparison)
# ---------------------------------------------------------------------------


class PlatformScore(BaseModel):
    platform: str
    composite_score: float
    sessions: int
    avg_cost: float
    avg_latency_ms: float
    success_rate: float
    error_rate: float
    users: int


@router.get("/platforms", response_model=list[PlatformScore])
async def get_platforms(
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Per-IDE platform comparison with composite scores."""
    rows = await _ch_json_scoped(
        "SELECT t.ide AS ide, "
        "count(DISTINCT t.trace_id) AS sessions, "
        "count(DISTINCT t.user_id) AS users, "
        "round(avg(s.cost), 4) AS avg_cost, "
        "round(avg(s.latency_ms), 1) AS avg_latency_ms, "
        "countIf(s.status = 'error') AS errors, "
        "count(s.span_id) AS total_spans "
        "FROM traces AS t FINAL "
        "INNER JOIN spans AS s FINAL ON t.trace_id = s.trace_id "
        "AND s.project_id = 'default' AND s.is_deleted = 0 "
        "WHERE t.project_id = 'default' AND t.is_deleted = 0 AND t.ide != '' "
        "GROUP BY t.ide ORDER BY sessions DESC",
        current_user,
    )

    if not rows:
        return []

    # Compute normalized scores for composite
    max_sessions = max(int(r.get("sessions", 1)) for r in rows) or 1
    results = []
    for r in rows:
        sessions = int(r.get("sessions", 0))
        users = int(r.get("users", 0))
        avg_cost = float(r.get("avg_cost") or 0)
        avg_latency = float(r.get("avg_latency_ms") or 0)
        errors = int(r.get("errors", 0))
        total_spans = int(r.get("total_spans", 1)) or 1

        error_rate = round(errors / total_spans, 4)
        success_rate = round(1 - error_rate, 4)

        # Normalized 0-100 components
        success_score = success_rate * 100
        cost_score = max(0, 100 - (avg_cost * 1000)) if avg_cost > 0 else 100
        speed_score = max(0, 100 - (avg_latency / 50)) if avg_latency > 0 else 100
        volume_score = (sessions / max_sessions) * 100

        composite = round(
            success_score * 0.30 + cost_score * 0.25 + speed_score * 0.25 + volume_score * 0.20,
            1,
        )

        results.append(PlatformScore(
            platform=r["ide"],
            composite_score=min(composite, 100),
            sessions=sessions,
            avg_cost=avg_cost,
            avg_latency_ms=avg_latency,
            success_rate=round(success_rate * 100, 1),
            error_rate=round(error_rate * 100, 2),
            users=users,
        ))

    return results


# ---------------------------------------------------------------------------
# Velocity Tab
# ---------------------------------------------------------------------------


class VelocityPoint(BaseModel):
    week: str
    traces: int


class VelocityResponse(BaseModel):
    weekly: list[VelocityPoint]
    current_weekly_avg: float
    baseline_weekly_avg: float
    multiplier: float


@router.get("/velocity", response_model=VelocityResponse)
async def get_velocity(
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Weekly trace counts with baseline comparison."""
    rows = await _ch_json_scoped(
        "SELECT toStartOfWeek(start_time) AS week, count() AS traces "
        "FROM traces FINAL WHERE project_id = 'default' AND is_deleted = 0 "
        "AND start_time >= now() - INTERVAL 12 WEEK "
        "GROUP BY week ORDER BY week",
        current_user,
    )

    weekly = [VelocityPoint(week=str(r["week"])[:10], traces=int(r["traces"])) for r in rows]

    if len(weekly) >= 4:
        baseline_weeks = weekly[:4]
        current_weeks = weekly[-4:]
        baseline_avg = sum(w.traces for w in baseline_weeks) / len(baseline_weeks)
        current_avg = sum(w.traces for w in current_weeks) / len(current_weeks)
    elif weekly:
        baseline_avg = weekly[0].traces
        current_avg = weekly[-1].traces
    else:
        baseline_avg = 0
        current_avg = 0

    multiplier = round(current_avg / baseline_avg, 1) if baseline_avg > 0 else 0.0

    return VelocityResponse(
        weekly=weekly,
        current_weekly_avg=round(current_avg, 1),
        baseline_weekly_avg=round(baseline_avg, 1),
        multiplier=multiplier,
    )


class TopAgentScored(BaseModel):
    id: str
    name: str
    category: str
    composite_score: float
    sessions: int
    downloads: int
    avg_rating: float | None
    weekly_trend: list[int]


@router.get("/top-agents", response_model=list[TopAgentScored])
async def get_top_agents(
    limit: int = Query(10, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Top agents by composite score (downloads + sessions + rating)."""
    org_id = current_user.org_id

    # Downloads from PG
    dl_stmt = (
        select(AgentDownloadRecord.agent_id, func.count(AgentDownloadRecord.id).label("downloads"))
        .group_by(AgentDownloadRecord.agent_id)
    )
    dl_rows = (await db.execute(dl_stmt)).all()
    dl_map = {str(r.agent_id): r.downloads for r in dl_rows}

    # Ratings from PG
    rating_stmt = (
        select(Feedback.listing_id, func.avg(Feedback.rating).label("avg_rating"))
        .where(Feedback.listing_type == "agent")
        .group_by(Feedback.listing_id)
    )
    rating_rows = (await db.execute(rating_stmt)).all()
    rating_map = {str(r.listing_id): round(float(r.avg_rating), 2) for r in rating_rows}

    # Sessions from ClickHouse (last 30 days)
    session_rows = await _ch_json_scoped(
        "SELECT agent_id, count() AS sessions "
        "FROM traces FINAL WHERE project_id = 'default' AND is_deleted = 0 "
        "AND agent_id != '' AND start_time >= now() - INTERVAL 30 DAY "
        "GROUP BY agent_id ORDER BY sessions DESC LIMIT 50",
        current_user,
    )
    session_map = {r["agent_id"]: int(r["sessions"]) for r in session_rows}

    # Weekly trend (last 6 weeks) per agent
    trend_rows = await _ch_json_scoped(
        "SELECT agent_id, toStartOfWeek(start_time) AS week, count() AS cnt "
        "FROM traces FINAL WHERE project_id = 'default' AND is_deleted = 0 "
        "AND agent_id != '' AND start_time >= now() - INTERVAL 6 WEEK "
        "GROUP BY agent_id, week ORDER BY agent_id, week",
        current_user,
    )
    trend_map: dict[str, list[int]] = {}
    for r in trend_rows:
        aid = r["agent_id"]
        trend_map.setdefault(aid, []).append(int(r["cnt"]))

    # Get all candidate agent_ids
    all_agent_ids = set(session_map.keys()) | set(dl_map.keys())
    if not all_agent_ids:
        return []

    # Resolve names + categories from PG
    import uuid as _uuid

    valid_ids = []
    for aid in all_agent_ids:
        try:
            valid_ids.append(_uuid.UUID(aid))
        except (ValueError, AttributeError):
            pass

    agent_info: dict[str, tuple[str, str]] = {}
    if valid_ids:
        info_stmt = select(Agent.id, Agent.name, Agent.category)
        if org_id:
            info_stmt = info_stmt.where(Agent.owner_org_id == org_id)
        info_stmt = info_stmt.where(Agent.id.in_(valid_ids))
        info_rows = (await db.execute(info_stmt)).all()
        agent_info = {str(r.id): (r.name, r.category or "Uncategorized") for r in info_rows}

    # Compute composite and rank
    max_downloads = max(dl_map.values(), default=1) or 1
    max_sessions = max(session_map.values(), default=1) or 1

    scored = []
    for aid, (name, category) in agent_info.items():
        downloads = dl_map.get(aid, 0)
        sessions = session_map.get(aid, 0)
        rating = rating_map.get(aid)

        dl_norm = (downloads / max_downloads) * 100
        sess_norm = (sessions / max_sessions) * 100
        rating_norm = ((rating or 0) / 5) * 100

        composite = round(dl_norm * 0.3 + sess_norm * 0.4 + rating_norm * 0.3, 1)

        scored.append(TopAgentScored(
            id=aid,
            name=name,
            category=category,
            composite_score=composite,
            sessions=sessions,
            downloads=downloads,
            avg_rating=rating,
            weekly_trend=trend_map.get(aid, []),
        ))

    scored.sort(key=lambda x: -x.composite_score)
    return scored[:limit]


# ---------------------------------------------------------------------------
# Departments Tab
# ---------------------------------------------------------------------------


class DepartmentItem(BaseModel):
    department: str
    user_count: int
    agent_count: int
    utilization_pct: float
    sessions_per_user: float


class DepartmentsResponse(BaseModel):
    departments: list[DepartmentItem]


@router.get("/departments", response_model=DepartmentsResponse)
async def get_departments(
    range_: str | None = Query(None, alias="range"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Per-department breakdown: users, agents, utilization, sessions/user."""
    org_id = current_user.org_id
    days = _range_days(range_)

    dept_map = await resolve_user_departments(db, org_id)
    if not dept_map:
        return DepartmentsResponse(departments=[])

    # Agent count per department (via AgentTeamAccess)
    agent_access_rows = (
        await db.execute(
            select(AgentTeamAccess.group_name, func.count(AgentTeamAccess.agent_id.distinct()))
            .group_by(AgentTeamAccess.group_name)
        )
    ).all()
    agent_count_by_dept: dict[str, int] = {r[0]: r[1] for r in agent_access_rows}

    # Get trace counts per user from ClickHouse
    all_user_ids = []
    for uids in dept_map.values():
        all_user_ids.extend(uids)

    user_sessions: dict[str, int] = {}
    if all_user_ids:
        # Batch query — get session count per user in period
        session_rows = await _ch_json_scoped(
            "SELECT user_id, count() AS sessions "
            "FROM traces FINAL WHERE project_id = 'default' AND is_deleted = 0 "
            "AND start_time >= now() - INTERVAL {days:UInt32} DAY "
            "GROUP BY user_id",
            current_user,
            {"param_days": str(days)},
        )
        user_sessions = {r["user_id"]: int(r["sessions"]) for r in session_rows}

    departments = []
    for dept_name, user_ids in sorted(dept_map.items()):
        user_count = len(user_ids)
        agent_count = agent_count_by_dept.get(dept_name, 0)

        # Utilization: users with >= 1 session in period
        active_in_dept = sum(1 for uid in user_ids if user_sessions.get(uid, 0) > 0)
        utilization = round((active_in_dept / user_count) * 100, 1) if user_count > 0 else 0.0

        # Sessions per user
        total_sessions = sum(user_sessions.get(uid, 0) for uid in user_ids)
        sessions_per_user = round(total_sessions / user_count, 1) if user_count > 0 else 0.0

        departments.append(DepartmentItem(
            department=dept_name,
            user_count=user_count,
            agent_count=agent_count,
            utilization_pct=utilization,
            sessions_per_user=sessions_per_user,
        ))

    return DepartmentsResponse(departments=departments)


class DeptTokenItem(BaseModel):
    department: str
    tokens_used: int
    cost_per_task: float
    sessions_per_user: float
    trend_pct: float


@router.get("/dept-tokens", response_model=list[DeptTokenItem])
async def get_dept_tokens(
    range_: str | None = Query(None, alias="range"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Token usage and cost per department with trend."""
    org_id = current_user.org_id
    days = _range_days(range_)

    dept_map = await resolve_user_departments(db, org_id)
    if not dept_map:
        return []

    # Current period: tokens + cost per user
    current_rows = await _ch_json_scoped(
        "SELECT s.user_id AS user_id, "
        "sumIf(s.token_count_total, s.token_count_total IS NOT NULL) AS tokens, "
        "count(DISTINCT t.trace_id) AS traces, "
        "sum(s.cost) AS total_cost "
        "FROM spans AS s FINAL "
        "INNER JOIN traces AS t FINAL ON s.trace_id = t.trace_id "
        "AND t.project_id = 'default' AND t.is_deleted = 0 "
        "WHERE s.project_id = 'default' AND s.is_deleted = 0 "
        "AND s.start_time >= now() - INTERVAL {days:UInt32} DAY "
        "GROUP BY s.user_id",
        current_user,
        {"param_days": str(days)},
    )
    current_by_user: dict[str, dict] = {
        r["user_id"]: {"tokens": int(r["tokens"]), "traces": int(r["traces"]), "cost": float(r.get("total_cost") or 0)}
        for r in current_rows
    }

    # Previous period: tokens per user (for trend)
    prev_rows = await _ch_json_scoped(
        "SELECT s.user_id AS user_id, "
        "sumIf(s.token_count_total, s.token_count_total IS NOT NULL) AS tokens "
        "FROM spans AS s FINAL "
        "WHERE s.project_id = 'default' AND s.is_deleted = 0 "
        "AND s.start_time >= now() - INTERVAL {days2:UInt32} DAY "
        "AND s.start_time < now() - INTERVAL {days:UInt32} DAY "
        "GROUP BY s.user_id",
        current_user,
        {"param_days": str(days), "param_days2": str(days * 2)},
    )
    prev_by_user: dict[str, int] = {r["user_id"]: int(r["tokens"]) for r in prev_rows}

    result = []
    for dept_name, user_ids in sorted(dept_map.items()):
        user_count = len(user_ids)
        tokens = sum(current_by_user.get(uid, {}).get("tokens", 0) for uid in user_ids)
        traces = sum(current_by_user.get(uid, {}).get("traces", 0) for uid in user_ids)
        cost = sum(current_by_user.get(uid, {}).get("cost", 0) for uid in user_ids)
        prev_tokens = sum(prev_by_user.get(uid, 0) for uid in user_ids)

        cost_per_task = round(cost / traces, 4) if traces > 0 else 0.0
        sessions_per_user = round(traces / user_count, 1) if user_count > 0 else 0.0
        trend = compute_trend_percent(tokens, prev_tokens)

        result.append(DeptTokenItem(
            department=dept_name,
            tokens_used=tokens,
            cost_per_task=cost_per_task,
            sessions_per_user=sessions_per_user,
            trend_pct=trend,
        ))

    return result


# ---------------------------------------------------------------------------
# Cost Intelligence Tab
# ---------------------------------------------------------------------------


class MonthlyCostPoint(BaseModel):
    month: str
    ai_spend: float
    savings: float


class CostByCategory(BaseModel):
    category: str
    baseline_cost: float
    actual_cost: float
    saved_pct: float


class CostSummaryResponse(BaseModel):
    monthly_savings: float
    cost_reduction_pct: float
    projected_annual_savings: float
    cost_per_task: float
    monthly_trend: list[MonthlyCostPoint]
    by_category: list[CostByCategory]
    configured: bool


@router.get("/cost-summary", response_model=CostSummaryResponse)
async def get_cost_summary(
    range_: str | None = Query(None, alias="range"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Cost savings, spend, and ROI. Requires exec_dashboard_config baselines."""
    org_id = current_user.org_id
    days = _range_days(range_)

    # Load config
    config = None
    if org_id:
        result = await db.execute(
            select(ExecDashboardConfig).where(ExecDashboardConfig.org_id == org_id)
        )
        config = result.scalar_one_or_none()

    if not config:
        return CostSummaryResponse(
            monthly_savings=0,
            cost_reduction_pct=0,
            projected_annual_savings=0,
            cost_per_task=0,
            monthly_trend=[],
            by_category=[],
            configured=False,
        )

    baselines = config.pre_ai_baselines or {}

    # Monthly AI spend from ClickHouse
    monthly_rows = await _ch_json_scoped(
        "SELECT toStartOfMonth(start_time) AS month, "
        "sum(cost) AS spend, count(DISTINCT trace_id) AS traces "
        "FROM spans FINAL WHERE project_id = 'default' AND is_deleted = 0 "
        "AND start_time >= now() - INTERVAL 12 MONTH "
        "AND cost IS NOT NULL AND cost > 0 "
        "GROUP BY month ORDER BY month",
        current_user,
    )

    # Compute average baseline cost (mean of all category baselines)
    avg_baseline = sum(baselines.values()) / len(baselines) if baselines else 0

    monthly_trend = []
    total_spend = 0.0
    total_traces = 0
    for r in monthly_rows:
        spend = float(r.get("spend") or 0)
        traces = int(r.get("traces") or 0)
        savings = max(0, (avg_baseline * traces) - spend) if avg_baseline > 0 else 0
        monthly_trend.append(MonthlyCostPoint(
            month=str(r["month"])[:7],
            ai_spend=round(spend, 2),
            savings=round(savings, 2),
        ))
        total_spend += spend
        total_traces += traces

    # Current month stats
    current_month = monthly_trend[-1] if monthly_trend else None
    monthly_savings = current_month.savings if current_month else 0
    cost_per_task = round(total_spend / total_traces, 4) if total_traces > 0 else 0

    # Cost reduction %
    baseline_total = avg_baseline * total_traces if avg_baseline > 0 else 0
    cost_reduction_pct = round(((baseline_total - total_spend) / baseline_total) * 100, 1) if baseline_total > 0 else 0

    # Projected annual (latest month × 12)
    projected_annual = round(monthly_savings * 12, 2)

    # Cost by category
    cat_rows = await _ch_json_scoped(
        "SELECT t.agent_id AS agent_id, "
        "round(avg(s.cost), 4) AS avg_cost, count(DISTINCT t.trace_id) AS traces "
        "FROM spans AS s FINAL "
        "INNER JOIN traces AS t FINAL ON s.trace_id = t.trace_id "
        "AND t.project_id = 'default' AND t.is_deleted = 0 "
        "WHERE s.project_id = 'default' AND s.is_deleted = 0 "
        "AND s.cost IS NOT NULL AND s.cost > 0 "
        "AND t.agent_id != '' "
        "AND s.start_time >= now() - INTERVAL {days:UInt32} DAY "
        "GROUP BY t.agent_id",
        current_user,
        {"param_days": str(days)},
    )

    # Resolve agent categories
    agent_ids = [r["agent_id"] for r in cat_rows if r.get("agent_id")]
    cat_map: dict[str, str] = {}
    if agent_ids:
        import uuid as _uuid

        valid_ids = []
        for aid in agent_ids:
            try:
                valid_ids.append(_uuid.UUID(aid))
            except (ValueError, AttributeError):
                pass
        if valid_ids:
            rows = (await db.execute(select(Agent.id, Agent.category).where(Agent.id.in_(valid_ids)))).all()
            cat_map = {str(r.id): r.category or "Uncategorized" for r in rows}

    # Aggregate cost by category
    cost_by_cat: dict[str, list[float]] = {}
    for r in cat_rows:
        cat = cat_map.get(r["agent_id"], "Uncategorized")
        cost_by_cat.setdefault(cat, []).append(float(r.get("avg_cost") or 0))

    by_category = []
    for cat, costs in sorted(cost_by_cat.items()):
        actual = round(sum(costs) / len(costs), 4) if costs else 0
        baseline = baselines.get(cat, avg_baseline)
        saved = round(((baseline - actual) / baseline) * 100, 1) if baseline > 0 else 0
        by_category.append(CostByCategory(
            category=cat,
            baseline_cost=round(baseline, 2),
            actual_cost=actual,
            saved_pct=max(saved, 0),
        ))

    return CostSummaryResponse(
        monthly_savings=round(monthly_savings, 2),
        cost_reduction_pct=cost_reduction_pct,
        projected_annual_savings=projected_annual,
        cost_per_task=cost_per_task,
        monthly_trend=monthly_trend,
        by_category=by_category,
        configured=True,
    )


# ---------------------------------------------------------------------------
# ROI Projections
# ---------------------------------------------------------------------------


class ROIProjectionPoint(BaseModel):
    quarter: str
    projected_savings: float
    cumulative_savings: float
    confidence: float


class ROIProjectionsResponse(BaseModel):
    projections: list[ROIProjectionPoint]
    growth_rate_pct: float
    time_to_breakeven_months: int | None
    total_invested: float
    total_saved: float
    roi_multiple: float


@router.get("/roi-projections", response_model=ROIProjectionsResponse)
async def get_roi_projections(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Project future savings using linear regression on historical monthly data."""
    org_id = current_user.org_id

    config = None
    if org_id:
        result = await db.execute(
            select(ExecDashboardConfig).where(ExecDashboardConfig.org_id == org_id)
        )
        config = result.scalar_one_or_none()

    if not config:
        return ROIProjectionsResponse(
            projections=[], growth_rate_pct=0, time_to_breakeven_months=None,
            total_invested=0, total_saved=0, roi_multiple=0,
        )

    baselines = config.pre_ai_baselines or {}
    avg_baseline = sum(baselines.values()) / len(baselines) if baselines else 0

    monthly_rows = await _ch_json_scoped(
        "SELECT toStartOfMonth(start_time) AS month, "
        "sum(cost) AS spend, count(DISTINCT trace_id) AS traces "
        "FROM spans FINAL WHERE project_id = 'default' AND is_deleted = 0 "
        "AND start_time >= now() - INTERVAL 12 MONTH "
        "AND cost IS NOT NULL AND cost > 0 "
        "GROUP BY month ORDER BY month",
        current_user,
    )

    if not monthly_rows or avg_baseline == 0:
        return ROIProjectionsResponse(
            projections=[], growth_rate_pct=0, time_to_breakeven_months=None,
            total_invested=0, total_saved=0, roi_multiple=0,
        )

    monthly_savings_list: list[float] = []
    monthly_spend_list: list[float] = []
    for r in monthly_rows:
        spend = float(r.get("spend") or 0)
        traces = int(r.get("traces") or 0)
        savings = max(0, (avg_baseline * traces) - spend)
        monthly_savings_list.append(savings)
        monthly_spend_list.append(spend)

    total_invested = sum(monthly_spend_list)
    total_saved = sum(monthly_savings_list)
    roi_multiple = round(total_saved / total_invested, 2) if total_invested > 0 else 0

    # Linear regression on savings for growth rate
    n = len(monthly_savings_list)
    if n >= 3:
        x_mean = (n - 1) / 2
        y_mean = sum(monthly_savings_list) / n
        numerator = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(monthly_savings_list))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        slope = numerator / denominator if denominator != 0 else 0
        intercept = y_mean - slope * x_mean
        growth_rate = round((slope / y_mean) * 100, 1) if y_mean > 0 else 0
    else:
        slope = 0
        intercept = monthly_savings_list[-1] if monthly_savings_list else 0
        growth_rate = 0

    # Project next 4 quarters
    now = dt.now(UTC)
    projections = []
    cumulative = total_saved
    for q_offset in range(1, 5):
        quarter_start_month = n + (q_offset - 1) * 3
        quarter_savings = 0.0
        for m in range(3):
            month_idx = quarter_start_month + m
            projected = max(0, slope * month_idx + intercept)
            quarter_savings += projected

        cumulative += quarter_savings
        confidence = max(0.5, 1.0 - (q_offset * 0.12))

        quarter_num = ((now.month - 1) // 3 + q_offset) % 4 + 1
        quarter_year = now.year + ((now.month - 1) // 3 + q_offset) // 4
        quarter_label = f"Q{quarter_num} {quarter_year}"

        projections.append(ROIProjectionPoint(
            quarter=quarter_label,
            projected_savings=round(quarter_savings, 2),
            cumulative_savings=round(cumulative, 2),
            confidence=round(confidence, 2),
        ))

    # Time to breakeven
    if total_invested > total_saved and slope > 0:
        months_remaining = (total_invested - total_saved) / slope if slope > 0 else None
        time_to_breakeven = int(months_remaining) if months_remaining and months_remaining > 0 else None
    elif total_saved >= total_invested:
        time_to_breakeven = 0
    else:
        time_to_breakeven = None

    return ROIProjectionsResponse(
        projections=projections,
        growth_rate_pct=growth_rate,
        time_to_breakeven_months=time_to_breakeven,
        total_invested=round(total_invested, 2),
        total_saved=round(total_saved, 2),
        roi_multiple=roi_multiple,
    )


# ---------------------------------------------------------------------------
# Strategic Insights (cross-org analysis from real telemetry)
# ---------------------------------------------------------------------------


class ModelComparisonItem(BaseModel):
    model: str
    sessions: int
    avg_cost: float
    avg_tokens: int
    success_rate: float
    best_at: str


class DepartmentGap(BaseModel):
    department: str
    adoption_pct: float
    sessions: int
    opportunity: str


class QuickWin(BaseModel):
    title: str
    detail: str
    estimated_savings: float
    effort: str


class PlatformComparison(BaseModel):
    platform: str
    avg_task_time_ms: float
    sessions: int
    success_rate: float


class StrategicInsightsResponse(BaseModel):
    model_comparison: list[ModelComparisonItem]
    department_gaps: list[DepartmentGap]
    quick_wins: list[QuickWin]
    platform_comparison: list[PlatformComparison]
    power_user_pct: float
    power_user_value_pct: float
    total_active_users: int
    automatable_pct: float


@router.get("/strategic-insights", response_model=StrategicInsightsResponse)
async def get_strategic_insights(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Cross-org strategic insights derived from real telemetry data."""
    org_id = current_user.org_id

    # 1. Model comparison from session_stats_agg
    model_rows = await _ch_json_scoped(
        "SELECT model, "
        "count() AS sessions, "
        "round(avg(total_credits), 4) AS avg_cost, "
        "round(avg(input_tokens + output_tokens)) AS avg_tokens "
        "FROM session_stats_agg "
        "WHERE project_id = 'default' AND model != '' "
        "GROUP BY model "
        "HAVING sessions >= 5 "
        "ORDER BY sessions DESC "
        "LIMIT 10",
        current_user,
    )

    # Success rate per model from spans
    model_success_rows = await _ch_json_scoped(
        "SELECT s.name AS model, "
        "countIf(s.status = 'success') AS successes, "
        "count() AS total "
        "FROM spans AS s FINAL "
        "WHERE s.project_id = 'default' AND s.is_deleted = 0 "
        "AND s.type = 'llm' AND s.name != '' "
        "AND s.start_time >= now() - INTERVAL 30 DAY "
        "GROUP BY s.name "
        "HAVING total >= 5",
        current_user,
    )
    model_success_map = {
        r["model"]: round(int(r["successes"]) / int(r["total"]) * 100, 1)
        for r in model_success_rows if int(r.get("total", 0)) > 0
    }

    model_comparison = []
    if model_rows:
        cheapest = min(model_rows, key=lambda r: float(r.get("avg_cost") or 999))
        most_used = model_rows[0] if model_rows else None

        for r in model_rows:
            model_name = r["model"]
            avg_cost = float(r.get("avg_cost") or 0)
            sessions = int(r.get("sessions", 0))
            avg_tokens = int(float(r.get("avg_tokens") or 0))
            success = model_success_map.get(model_name, 0)

            if model_name == cheapest["model"]:
                best_at = "Most cost-efficient"
            elif sessions == int(most_used.get("sessions", 0)):
                best_at = "Most popular, proven reliability"
            elif avg_tokens > 5000:
                best_at = "Complex/long-context tasks"
            else:
                best_at = "General purpose"

            model_comparison.append(ModelComparisonItem(
                model=model_name,
                sessions=sessions,
                avg_cost=avg_cost,
                avg_tokens=avg_tokens,
                success_rate=success,
                best_at=best_at,
            ))

    # 2. Department gaps
    dept_map = await resolve_user_departments(db, org_id)
    all_user_ids = []
    for uids in dept_map.values():
        all_user_ids.extend(uids)

    user_session_rows = await _ch_json_scoped(
        "SELECT user_id, count() AS sessions "
        "FROM session_stats_agg "
        "WHERE project_id = 'default' "
        "GROUP BY user_id",
        current_user,
    )
    user_sessions = {r["user_id"]: int(r["sessions"]) for r in user_session_rows}

    department_gaps = []
    for dept_name, user_ids in sorted(dept_map.items()):
        if dept_name == "Unassigned":
            continue
        user_count = len(user_ids)
        active_count = sum(1 for uid in user_ids if user_sessions.get(uid, 0) > 0)
        adoption = round((active_count / user_count) * 100, 1) if user_count > 0 else 0
        total_sessions = sum(user_sessions.get(uid, 0) for uid in user_ids)

        if adoption < 50:
            opportunity = f"{user_count - active_count} users not using AI — potential for automation"
        elif adoption < 80:
            opportunity = "Moderate adoption, room for deeper integration"
        else:
            opportunity = "High adoption — focus on optimization"

        department_gaps.append(DepartmentGap(
            department=dept_name,
            adoption_pct=adoption,
            sessions=total_sessions,
            opportunity=opportunity,
        ))

    department_gaps.sort(key=lambda d: d.adoption_pct)

    # 3. Quick wins — identify real cost-saving opportunities
    quick_wins = []

    # Win: expensive model used for simple tasks (low token count)
    expensive_simple_rows = await _ch_json_scoped(
        "SELECT model, count() AS sessions, round(sum(total_credits), 2) AS total_cost "
        "FROM session_stats_agg "
        "WHERE project_id = 'default' AND model != '' "
        "AND (input_tokens + output_tokens) < 2000 "
        "AND total_credits > 0.10 "
        "GROUP BY model "
        "HAVING sessions >= 10 "
        "ORDER BY total_cost DESC "
        "LIMIT 3",
        current_user,
    )
    for r in expensive_simple_rows:
        sessions = int(r["sessions"])
        total_cost = float(r["total_cost"])
        cheap_cost = sessions * 0.04
        savings = total_cost - cheap_cost
        if savings > 10:
            quick_wins.append(QuickWin(
                title=f"Route simple tasks away from {r['model']}",
                detail=f"{sessions} sessions with <2K tokens are using an expensive model. "
                       f"A cheaper model handles these identically.",
                estimated_savings=round(savings, 2),
                effort="low",
            ))

    # Win: inactive agents still consuming resources
    inactive_agent_rows = await _ch_json_scoped(
        "SELECT agent_id, count() AS sessions, round(sum(total_credits), 2) AS cost "
        "FROM session_stats_agg "
        "WHERE project_id = 'default' AND agent_id != '' "
        "AND first_event_time < now() - INTERVAL 14 DAY "
        "GROUP BY agent_id "
        "HAVING sessions <= 3 AND cost > 5 "
        "ORDER BY cost DESC "
        "LIMIT 3",
        current_user,
    )
    for r in inactive_agent_rows:
        quick_wins.append(QuickWin(
            title="Decommission low-usage agent",
            detail=f"Agent with only {r['sessions']} sessions in 14 days is still costing ${r['cost']}. "
                   f"Consider retiring or consolidating.",
            estimated_savings=float(r["cost"]),
            effort="low",
        ))

    # Win: high error-rate patterns
    error_rows = await _ch_json_scoped(
        "SELECT agent_id, "
        "countIf(status = 'error') AS errors, count() AS total, "
        "round(sum(cost), 2) AS wasted_cost "
        "FROM spans FINAL "
        "WHERE project_id = 'default' AND is_deleted = 0 "
        "AND agent_id != '' AND cost > 0 "
        "AND start_time >= now() - INTERVAL 30 DAY "
        "GROUP BY agent_id "
        "HAVING errors > 10 AND (errors / total) > 0.2 "
        "ORDER BY wasted_cost DESC "
        "LIMIT 3",
        current_user,
    )
    for r in error_rows:
        errors = int(r["errors"])
        total = int(r["total"])
        error_pct = round(errors / total * 100)
        quick_wins.append(QuickWin(
            title="Fix high-error agent to recover wasted spend",
            detail=f"Agent has {error_pct}% error rate ({errors}/{total} calls). "
                   f"Fixing this recovers ~${r['wasted_cost']} in failed request costs.",
            estimated_savings=float(r["wasted_cost"]),
            effort="medium",
        ))

    # 4. Platform comparison (task completion speed)
    platform_rows = await _ch_json_scoped(
        "SELECT ide, "
        "round(avg(dateDiff('millisecond', first_event_time, last_event_time))) AS avg_time_ms, "
        "count() AS sessions, "
        "countIf(event_count > 2) AS completed "
        "FROM session_stats_agg "
        "WHERE project_id = 'default' AND ide != '' "
        "AND first_event_time != last_event_time "
        "GROUP BY ide "
        "HAVING sessions >= 5 "
        "ORDER BY sessions DESC",
        current_user,
    )
    platform_comparison = [
        PlatformComparison(
            platform=r["ide"],
            avg_task_time_ms=float(r.get("avg_time_ms") or 0),
            sessions=int(r["sessions"]),
            success_rate=round(int(r["completed"]) / int(r["sessions"]) * 100, 1) if int(r["sessions"]) > 0 else 0,
        )
        for r in platform_rows
    ]

    # 5. Power user analysis
    user_value_rows = await _ch_json_scoped(
        "SELECT user_id, count() AS sessions, sum(total_credits) AS value "
        "FROM session_stats_agg "
        "WHERE project_id = 'default' "
        "AND first_event_time >= now() - INTERVAL 30 DAY "
        "GROUP BY user_id "
        "ORDER BY value DESC",
        current_user,
    )

    total_active = len(user_value_rows)
    if total_active > 0:
        top_20_count = max(1, total_active // 5)
        total_value = sum(float(r.get("value") or 0) for r in user_value_rows)
        top_20_value = sum(float(r.get("value") or 0) for r in user_value_rows[:top_20_count])
        power_user_value_pct = round((top_20_value / total_value) * 100, 1) if total_value > 0 else 0
    else:
        power_user_value_pct = 0

    # 6. Automatable task estimation (simple tasks = low tokens + high success)
    auto_rows = await _ch_json_scoped(
        "SELECT "
        "countIf((input_tokens + output_tokens) < 3000 AND event_count <= 5) AS simple, "
        "count() AS total "
        "FROM session_stats_agg "
        "WHERE project_id = 'default' "
        "AND first_event_time >= now() - INTERVAL 30 DAY",
        current_user,
    )
    simple = int(auto_rows[0]["simple"]) if auto_rows else 0
    total_tasks = int(auto_rows[0]["total"]) if auto_rows else 0
    automatable_pct = round((simple / total_tasks) * 100, 1) if total_tasks > 0 else 0

    return StrategicInsightsResponse(
        model_comparison=model_comparison,
        department_gaps=department_gaps,
        quick_wins=quick_wins,
        platform_comparison=platform_comparison,
        power_user_pct=20.0,
        power_user_value_pct=power_user_value_pct,
        total_active_users=total_active,
        automatable_pct=automatable_pct,
    )


# ---------------------------------------------------------------------------
# Developer Breakdown
# ---------------------------------------------------------------------------


class DeveloperActivityItem(BaseModel):
    user_id: str
    name: str
    department: str
    sessions: int
    tokens_consumed: int
    cost: float
    percentile: int


class DeveloperBreakdownResponse(BaseModel):
    total_developers: int
    active_developers: int
    top_20_value_pct: float
    developers: list[DeveloperActivityItem]


@router.get("/developer-breakdown", response_model=DeveloperBreakdownResponse)
async def get_developer_breakdown(
    limit: int = Query(20, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Per-developer activity breakdown with percentile ranking."""
    org_id = current_user.org_id

    # Total users in org
    user_stmt = select(func.count(User.id))
    if org_id:
        user_stmt = user_stmt.where(User.org_id == org_id)
    total_developers = await db.scalar(user_stmt) or 0

    # Per-user activity from ClickHouse (last 30 days)
    user_rows = await _ch_json_scoped(
        "SELECT user_id, "
        "count() AS sessions, "
        "sumIf(input_tokens + output_tokens, input_tokens IS NOT NULL) AS tokens, "
        "sum(total_credits) AS cost "
        "FROM session_stats_agg "
        "WHERE project_id = 'default' "
        "AND first_event_time >= now() - INTERVAL 30 DAY "
        "GROUP BY user_id "
        "ORDER BY sessions DESC",
        current_user,
    )

    active_developers = len(user_rows)

    # Top 20% value calculation
    total_value = sum(int(r.get("sessions", 0)) for r in user_rows)
    top_20_count = max(1, len(user_rows) // 5)
    top_20_value = sum(int(r.get("sessions", 0)) for r in user_rows[:top_20_count])
    top_20_value_pct = round((top_20_value / total_value) * 100, 1) if total_value > 0 else 0

    # Resolve user names + departments from PG
    user_ids = [r["user_id"] for r in user_rows[:limit]]
    user_info: dict[str, tuple[str, str]] = {}
    if user_ids:
        import uuid as _uuid

        valid_ids = []
        for uid in user_ids:
            try:
                valid_ids.append(_uuid.UUID(uid))
            except (ValueError, AttributeError):
                pass
        if valid_ids:
            info_rows = (await db.execute(
                select(User.id, User.name, User.department).where(User.id.in_(valid_ids))
            )).all()
            user_info = {str(r.id): (r.name, r.department or "Unassigned") for r in info_rows}

    # Also check user_groups for SSO department
    dept_map = await resolve_user_departments(db, org_id)
    uid_to_dept: dict[str, str] = {}
    for dept_name, uids in dept_map.items():
        for uid in uids:
            uid_to_dept[uid] = dept_name

    developers = []
    for i, r in enumerate(user_rows[:limit]):
        uid = r["user_id"]
        name, fallback_dept = user_info.get(uid, ("Unknown", "Unassigned"))
        department = uid_to_dept.get(uid, fallback_dept)
        percentile = max(1, 100 - int((i / max(len(user_rows), 1)) * 100))

        developers.append(DeveloperActivityItem(
            user_id=uid,
            name=name,
            department=department,
            sessions=int(r.get("sessions", 0)),
            tokens_consumed=int(r.get("tokens", 0)),
            cost=round(float(r.get("cost") or 0), 4),
            percentile=percentile,
        ))

    return DeveloperBreakdownResponse(
        total_developers=total_developers,
        active_developers=active_developers,
        top_20_value_pct=top_20_value_pct,
        developers=developers,
    )


# ---------------------------------------------------------------------------
# Inactivity / Churn Alerts
# ---------------------------------------------------------------------------


class InactiveAgentItem(BaseModel):
    id: str
    name: str
    category: str
    last_session_days_ago: int
    previous_sessions: int


class InactiveUserItem(BaseModel):
    user_id: str
    name: str
    department: str
    last_session_days_ago: int
    previous_sessions: int


class InactivityAlertsResponse(BaseModel):
    inactive_agents: list[InactiveAgentItem]
    inactive_users: list[InactiveUserItem]


@router.get("/inactivity-alerts", response_model=InactivityAlertsResponse)
async def get_inactivity_alerts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Agents and users that were active in days 15-28 but inactive in last 14 days."""
    org_id = current_user.org_id

    # Agents active 15-28 days ago but NOT in last 14 days
    prev_agent_rows = await _ch_json_scoped(
        "SELECT agent_id, count() AS sessions "
        "FROM traces FINAL WHERE project_id = 'default' AND is_deleted = 0 "
        "AND agent_id != '' "
        "AND start_time >= now() - INTERVAL 28 DAY "
        "AND start_time < now() - INTERVAL 14 DAY "
        "GROUP BY agent_id HAVING sessions >= 5",
        current_user,
    )

    recent_agent_rows = await _ch_json_scoped(
        "SELECT agent_id "
        "FROM traces FINAL WHERE project_id = 'default' AND is_deleted = 0 "
        "AND agent_id != '' "
        "AND start_time >= now() - INTERVAL 14 DAY "
        "GROUP BY agent_id",
        current_user,
    )
    recently_active_agents = {r["agent_id"] for r in recent_agent_rows}

    churned_agent_ids = [
        r for r in prev_agent_rows if r["agent_id"] not in recently_active_agents
    ]

    # Resolve agent names
    import uuid as _uuid

    agent_ids_to_resolve = []
    for r in churned_agent_ids:
        try:
            agent_ids_to_resolve.append(_uuid.UUID(r["agent_id"]))
        except (ValueError, AttributeError):
            pass

    agent_info: dict[str, tuple[str, str]] = {}
    if agent_ids_to_resolve:
        info_stmt = select(Agent.id, Agent.name, Agent.category)
        if org_id:
            info_stmt = info_stmt.where(Agent.owner_org_id == org_id)
        info_stmt = info_stmt.where(Agent.id.in_(agent_ids_to_resolve))
        rows = (await db.execute(info_stmt)).all()
        agent_info = {str(r.id): (r.name, r.category or "Uncategorized") for r in rows}

    inactive_agents = []
    for r in churned_agent_ids[:10]:
        aid = r["agent_id"]
        if aid in {str(k) for k in agent_ids_to_resolve} and aid in agent_info:
            name, category = agent_info[aid]
            inactive_agents.append(InactiveAgentItem(
                id=aid,
                name=name,
                category=category,
                last_session_days_ago=14,
                previous_sessions=int(r["sessions"]),
            ))

    # Users active 15-28 days ago but NOT in last 14 days
    prev_user_rows = await _ch_json_scoped(
        "SELECT user_id, count() AS sessions "
        "FROM traces FINAL WHERE project_id = 'default' AND is_deleted = 0 "
        "AND start_time >= now() - INTERVAL 28 DAY "
        "AND start_time < now() - INTERVAL 14 DAY "
        "GROUP BY user_id HAVING sessions >= 5",
        current_user,
    )

    recent_user_rows = await _ch_json_scoped(
        "SELECT user_id "
        "FROM traces FINAL WHERE project_id = 'default' AND is_deleted = 0 "
        "AND start_time >= now() - INTERVAL 14 DAY "
        "GROUP BY user_id",
        current_user,
    )
    recently_active_users = {r["user_id"] for r in recent_user_rows}

    churned_users = [
        r for r in prev_user_rows if r["user_id"] not in recently_active_users
    ]

    # Resolve user names + departments
    dept_map = await resolve_user_departments(db, org_id)
    uid_to_dept: dict[str, str] = {}
    for dept_name, uids in dept_map.items():
        for uid in uids:
            uid_to_dept[uid] = dept_name

    user_ids_to_resolve = []
    for r in churned_users[:10]:
        try:
            user_ids_to_resolve.append(_uuid.UUID(r["user_id"]))
        except (ValueError, AttributeError):
            pass

    user_names: dict[str, str] = {}
    if user_ids_to_resolve:
        rows = (await db.execute(select(User.id, User.name).where(User.id.in_(user_ids_to_resolve)))).all()
        user_names = {str(r.id): r.name for r in rows}

    inactive_users = []
    for r in churned_users[:10]:
        uid = r["user_id"]
        name = user_names.get(uid, "Unknown")
        dept = uid_to_dept.get(uid, "Unassigned")
        inactive_users.append(InactiveUserItem(
            user_id=uid,
            name=name,
            department=dept,
            last_session_days_ago=14,
            previous_sessions=int(r["sessions"]),
        ))

    return InactivityAlertsResponse(
        inactive_agents=inactive_agents,
        inactive_users=inactive_users,
    )


# ---------------------------------------------------------------------------
# Time to Value
# ---------------------------------------------------------------------------


class TimeToValueItem(BaseModel):
    id: str
    name: str
    category: str
    created_at: str
    days_to_100: int | None
    current_sessions: int


class TimeToValueResponse(BaseModel):
    agents: list[TimeToValueItem]
    avg_days_to_100: float | None


@router.get("/time-to-value", response_model=TimeToValueResponse)
async def get_time_to_value(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Days from agent deployment to reaching 100 sessions."""
    org_id = current_user.org_id

    # Get all agents with their created_at
    agent_stmt = select(Agent.id, Agent.name, Agent.category, Agent.created_at)
    if org_id:
        agent_stmt = agent_stmt.where(Agent.owner_org_id == org_id)
    agent_rows = (await db.execute(agent_stmt)).all()

    if not agent_rows:
        return TimeToValueResponse(agents=[], avg_days_to_100=None)

    # Get cumulative session counts per agent per day
    session_rows = await _ch_json_scoped(
        "SELECT agent_id, min(start_time) AS first_session, count() AS total_sessions "
        "FROM traces FINAL WHERE project_id = 'default' AND is_deleted = 0 "
        "AND agent_id != '' "
        "GROUP BY agent_id",
        current_user,
    )
    session_map: dict[str, dict] = {
        r["agent_id"]: {"first_session": r["first_session"], "total": int(r["total_sessions"])}
        for r in session_rows
    }

    # For agents with >=100 sessions, find when they hit 100
    agents_over_100 = [aid for aid, data in session_map.items() if data["total"] >= 100]
    day_100_map: dict[str, str] = {}
    if agents_over_100:
        # Get the date of the 100th session for each agent
        milestone_rows = await _ch_json_scoped(
            "SELECT agent_id, start_time "
            "FROM ("
            "  SELECT agent_id, start_time, "
            "    row_number() OVER (PARTITION BY agent_id ORDER BY start_time) AS rn "
            "  FROM traces FINAL WHERE project_id = 'default' AND is_deleted = 0 "
            "  AND agent_id IN ({aids:String})"
            ") WHERE rn = 100",
            current_user,
            {"param_aids": ",".join(f"'{a}'" for a in agents_over_100[:20])},
        )
        for r in milestone_rows:
            day_100_map[r["agent_id"]] = r["start_time"]

    import datetime as _dt

    items = []
    days_list = []
    for agent in agent_rows:
        aid = str(agent.id)
        data = session_map.get(aid)
        current_sessions = data["total"] if data else 0

        days_to_100: int | None = None
        if aid in day_100_map and agent.created_at:
            try:
                milestone_dt = _dt.datetime.fromisoformat(str(day_100_map[aid]).replace("Z", "+00:00"))
                created = agent.created_at if agent.created_at.tzinfo else agent.created_at.replace(tzinfo=_dt.timezone.utc)
                days_to_100 = max(0, (milestone_dt - created).days)
                days_list.append(days_to_100)
            except (ValueError, TypeError):
                pass

        items.append(TimeToValueItem(
            id=aid,
            name=agent.name,
            category=agent.category or "Uncategorized",
            created_at=str(agent.created_at)[:10] if agent.created_at else "",
            days_to_100=days_to_100,
            current_sessions=current_sessions,
        ))

    items.sort(key=lambda x: x.current_sessions, reverse=True)
    avg_days = round(sum(days_list) / len(days_list), 1) if days_list else None

    return TimeToValueResponse(agents=items[:20], avg_days_to_100=avg_days)
