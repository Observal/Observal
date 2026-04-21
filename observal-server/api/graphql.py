"""Strawberry GraphQL schema: types, resolvers, DataLoaders, subscriptions."""

import json
import logging
from collections.abc import AsyncGenerator

import jwt
import strawberry
from starlette.requests import Request
from strawberry.dataloader import DataLoader
from strawberry.scalars import JSON
from strawberry.types import Info

from services.clickhouse import (
    _query,
    query_span_by_id,
    query_trace_by_id,
    query_traces,
)
from services.jwt_service import decode_access_token
from services.redis import subscribe

logger = logging.getLogger(__name__)

_DEFAULT_PROJECT = "default"


# --- Helpers ---


async def _ch_json(sql: str, params: dict | None = None) -> list[dict]:
    try:
        r = await _query(f"{sql} FORMAT JSON", params)
        if r.status_code == 200:
            return r.json().get("data", [])
    except Exception as e:
        logger.warning("clickhouse_query_failed", error=str(e))
    return []


def _parse_json(val: str | None) -> JSON | None:
    if not val:
        return None
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return val


# --- DataLoaders ---


def _make_span_loader(project_id: str):
    async def _load(keys: list[str]) -> list[list[dict]]:
        sql = (
            "SELECT * FROM spans FINAL WHERE project_id = {pid:String} "
            "AND trace_id IN ({ids:Array(String)}) AND is_deleted = 0 ORDER BY start_time ASC"
        )
        params = {
            "param_pid": project_id,
            "param_ids": json.dumps(list(keys)),
        }
        rows = await _ch_json(sql, params)
        grouped: dict[str, list[dict]] = {k: [] for k in keys}
        for r in rows:
            tid = r.get("trace_id", "")
            if tid in grouped:
                grouped[tid].append(r)
        return [grouped[k] for k in keys]

    return _load


def _make_score_by_trace_loader(project_id: str):
    async def _load(keys: list[str]) -> list[list[dict]]:
        sql = (
            "SELECT * FROM scores FINAL WHERE project_id = {pid:String} "
            "AND trace_id IN ({ids:Array(String)}) AND is_deleted = 0 ORDER BY timestamp DESC"
        )
        params = {
            "param_pid": project_id,
            "param_ids": json.dumps(list(keys)),
        }
        rows = await _ch_json(sql, params)
        grouped: dict[str, list[dict]] = {k: [] for k in keys}
        for r in rows:
            tid = r.get("trace_id", "")
            if tid in grouped:
                grouped[tid].append(r)
        return [grouped[k] for k in keys]

    return _load


def _make_score_by_span_loader(project_id: str):
    async def _load(keys: list[str]) -> list[list[dict]]:
        sql = (
            "SELECT * FROM scores FINAL WHERE project_id = {pid:String} "
            "AND span_id IN ({ids:Array(String)}) AND is_deleted = 0 ORDER BY timestamp DESC"
        )
        params = {
            "param_pid": project_id,
            "param_ids": json.dumps(list(keys)),
        }
        rows = await _ch_json(sql, params)
        grouped: dict[str, list[dict]] = {k: [] for k in keys}
        for r in rows:
            sid = r.get("span_id", "")
            if sid in grouped:
                grouped[sid].append(r)
        return [grouped[k] for k in keys]

    return _load


# --- Types ---


@strawberry.type
class Score:
    score_id: str
    trace_id: str | None
    span_id: str | None
    name: str
    source: str
    data_type: str
    value: float
    string_value: str | None
    comment: str | None
    timestamp: str


@strawberry.type
class Span:
    span_id: str
    trace_id: str
    parent_span_id: str | None
    type: str
    name: str
    method: str | None
    input: JSON | None
    output: JSON | None
    error: JSON | None
    start_time: str
    end_time: str | None
    latency_ms: int | None
    status: str
    token_count_input: int | None
    token_count_output: int | None
    token_count_total: int | None
    cost: float | None
    hop_count: int | None
    tool_schema_valid: bool | None
    tools_available: int | None
    metadata: JSON | None

    @strawberry.field
    async def scores(self, info: Info) -> list[Score]:
        loader = info.context["score_by_span_loader"]
        rows = await loader.load(self.span_id)
        return [_row_to_score(r) for r in rows]


@strawberry.type
class TraceMetrics:
    total_spans: int
    error_count: int
    total_latency_ms: int | None
    tool_call_count: int
    token_count_total: int | None


@strawberry.type
class Trace:
    trace_id: str
    parent_trace_id: str | None
    trace_type: str
    mcp_id: str | None
    agent_id: str | None
    user_id: str
    session_id: str | None
    ide: str | None
    name: str | None
    start_time: str
    end_time: str | None
    input: JSON | None
    output: JSON | None
    tags: list[str] | None
    metadata: JSON | None

    @strawberry.field
    async def spans(self, info: Info, type: str | None = None) -> list[Span]:
        loader = info.context["span_loader"]
        rows = await loader.load(self.trace_id)
        if type:
            rows = [r for r in rows if r.get("type") == type]
        return [_row_to_span(r) for r in rows]

    @strawberry.field
    async def scores(self, info: Info) -> list[Score]:
        loader = info.context["score_by_trace_loader"]
        rows = await loader.load(self.trace_id)
        return [_row_to_score(r) for r in rows]

    @strawberry.field
    async def metrics(self, info: Info) -> TraceMetrics:
        loader = info.context["span_loader"]
        rows = await loader.load(self.trace_id)
        errors = sum(1 for r in rows if r.get("status") == "error")
        tool_calls = sum(1 for r in rows if r.get("type") == "tool_call")
        tokens = sum(int(r.get("token_count_total") or 0) for r in rows)
        latencies = [int(r.get("latency_ms") or 0) for r in rows if r.get("latency_ms")]
        return TraceMetrics(
            total_spans=len(rows),
            error_count=errors,
            total_latency_ms=sum(latencies) if latencies else None,
            tool_call_count=tool_calls,
            token_count_total=tokens or None,
        )


@strawberry.type
class TraceConnection:
    items: list[Trace]
    total_count: int
    has_more: bool


@strawberry.type
class McpMetrics:
    tool_call_count: int
    error_rate: float
    avg_latency_ms: float
    p50_latency_ms: float
    p90_latency_ms: float
    p99_latency_ms: float
    timeout_rate: float
    schema_compliance_rate: float


@strawberry.type
class OverviewStats:
    total_traces: int
    total_spans: int
    tool_calls_today: int
    errors_today: int


@strawberry.type
class TrendPoint:
    date: str
    traces: int
    spans: int
    errors: int


# --- Row converters ---


def _row_to_trace(r: dict) -> Trace:
    return Trace(
        trace_id=r.get("trace_id", ""),
        parent_trace_id=r.get("parent_trace_id"),
        trace_type=r.get("trace_type", "mcp"),
        mcp_id=r.get("mcp_id"),
        agent_id=r.get("agent_id"),
        user_id=r.get("user_id", ""),
        session_id=r.get("session_id"),
        ide=r.get("ide"),
        name=r.get("name"),
        start_time=r.get("start_time", ""),
        end_time=r.get("end_time"),
        input=_parse_json(r.get("input")),
        output=_parse_json(r.get("output")),
        tags=r.get("tags", []),
        metadata=r.get("metadata"),
    )


def _row_to_span(r: dict) -> Span:
    tsv = r.get("tool_schema_valid")
    return Span(
        span_id=r.get("span_id", ""),
        trace_id=r.get("trace_id", ""),
        parent_span_id=r.get("parent_span_id"),
        type=r.get("type", ""),
        name=r.get("name", ""),
        method=r.get("method"),
        input=_parse_json(r.get("input")),
        output=_parse_json(r.get("output")),
        error=_parse_json(r.get("error")),
        start_time=r.get("start_time", ""),
        end_time=r.get("end_time"),
        latency_ms=int(r["latency_ms"]) if r.get("latency_ms") else None,
        status=r.get("status", "success"),
        token_count_input=int(r["token_count_input"]) if r.get("token_count_input") else None,
        token_count_output=int(r["token_count_output"]) if r.get("token_count_output") else None,
        token_count_total=int(r["token_count_total"]) if r.get("token_count_total") else None,
        cost=float(r["cost"]) if r.get("cost") else None,
        hop_count=int(r["hop_count"]) if r.get("hop_count") else None,
        tool_schema_valid=bool(int(tsv)) if tsv is not None and tsv != "" else None,
        tools_available=int(r["tools_available"]) if r.get("tools_available") else None,
        metadata=r.get("metadata"),
    )


def _row_to_score(r: dict) -> Score:
    return Score(
        score_id=r.get("score_id", ""),
        trace_id=r.get("trace_id"),
        span_id=r.get("span_id"),
        name=r.get("name", ""),
        source=r.get("source", ""),
        data_type=r.get("data_type", "numeric"),
        value=float(r.get("value", 0)),
        string_value=r.get("string_value"),
        comment=r.get("comment"),
        timestamp=r.get("timestamp", ""),
    )


# --- Query resolvers ---


@strawberry.type
class Query:
    @strawberry.field
    async def traces(
        self,
        info: Info,
        trace_type: str | None = None,
        mcp_id: str | None = None,
        agent_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> TraceConnection:
        ctx = info.context
        project_id = ctx.get("project_id", _DEFAULT_PROJECT)
        uid = None if _is_admin(ctx) else ctx.get("user_id")
        rows = await query_traces(
            project_id,
            trace_type=trace_type,
            mcp_id=mcp_id,
            agent_id=agent_id,
            user_id=uid,
            limit=limit + 1,
            offset=offset,
        )
        has_more = len(rows) > limit
        items = [_row_to_trace(r) for r in rows[:limit]]
        return TraceConnection(items=items, total_count=len(items), has_more=has_more)

    @strawberry.field
    async def trace(self, info: Info, trace_id: str) -> Trace | None:
        ctx = info.context
        project_id = ctx.get("project_id", _DEFAULT_PROJECT)
        uid = None if _is_admin(ctx) else ctx.get("user_id")
        r = await query_trace_by_id(project_id, trace_id, user_id=uid)
        return _row_to_trace(r) if r else None

    @strawberry.field
    async def span(self, info: Info, span_id: str) -> Span | None:
        ctx = info.context
        project_id = ctx.get("project_id", _DEFAULT_PROJECT)
        uid = None if _is_admin(ctx) else ctx.get("user_id")
        r = await query_span_by_id(project_id, span_id, user_id=uid)
        return _row_to_span(r) if r else None

    @strawberry.field
    async def mcp_metrics(self, info: Info, mcp_id: str, start: str, end: str) -> McpMetrics:
        ctx = info.context
        project_id = ctx.get("project_id", _DEFAULT_PROJECT)
        uid = None if _is_admin(ctx) else ctx.get("user_id")
        uid_clause = " AND user_id={uid:String}" if uid else ""
        params: dict[str, str] = {
            "param_pid": project_id,
            "param_mid": mcp_id,
            "param_start": start,
            "param_end": end,
        }
        if uid:
            params["param_uid"] = uid
        rows = await _ch_json(
            "SELECT count() as cnt, "
            "countIf(status='error') as errs, "
            "countIf(status='timeout') as timeouts, "
            "avg(latency_ms) as avg_lat, "
            "quantile(0.5)(latency_ms) as p50, "
            "quantile(0.9)(latency_ms) as p90, "
            "quantile(0.99)(latency_ms) as p99, "
            "countIf(tool_schema_valid=1) as schema_ok, "
            "countIf(tool_schema_valid IS NOT NULL) as schema_total "
            "FROM spans FINAL WHERE project_id={pid:String} "
            "AND mcp_id={mid:String} AND type='tool_call' "
            "AND start_time >= {start:String} AND start_time <= {end:String} "
            "AND is_deleted=0" + uid_clause,
            params,
        )
        r = rows[0] if rows else {}
        cnt = int(r.get("cnt", 0))
        errs = int(r.get("errs", 0))
        timeouts = int(r.get("timeouts", 0))
        schema_total = int(r.get("schema_total", 0))
        schema_ok = int(r.get("schema_ok", 0))
        return McpMetrics(
            tool_call_count=cnt,
            error_rate=errs / cnt if cnt else 0,
            avg_latency_ms=float(r.get("avg_lat", 0)),
            p50_latency_ms=float(r.get("p50", 0)),
            p90_latency_ms=float(r.get("p90", 0)),
            p99_latency_ms=float(r.get("p99", 0)),
            timeout_rate=timeouts / cnt if cnt else 0,
            schema_compliance_rate=schema_ok / schema_total if schema_total else 0,
        )

    @strawberry.field
    async def overview(self, info: Info, start: str, end: str) -> OverviewStats:
        ctx = info.context
        project_id = ctx.get("project_id", _DEFAULT_PROJECT)
        uid = None if _is_admin(ctx) else ctx.get("user_id")
        uid_clause = " AND user_id={uid:String}" if uid else ""
        params: dict[str, str] = {
            "param_pid": project_id,
            "param_start": start,
            "param_end": end,
        }
        if uid:
            params["param_uid"] = uid
        rows = await _ch_json(
            "SELECT count() as traces FROM traces FINAL "
            "WHERE project_id={pid:String} AND is_deleted=0 "
            "AND start_time >= {start:String} AND start_time <= {end:String}" + uid_clause,
            params,
        )
        span_rows = await _ch_json(
            "SELECT count() as spans, "
            "countIf(type='tool_call') as tools, "
            "countIf(status='error') as errs "
            "FROM spans FINAL WHERE project_id={pid:String} AND is_deleted=0 "
            "AND start_time >= {start:String} AND start_time <= {end:String}" + uid_clause,
            params,
        )
        tr = rows[0] if rows else {}
        sr = span_rows[0] if span_rows else {}
        return OverviewStats(
            total_traces=int(tr.get("traces", 0)),
            total_spans=int(sr.get("spans", 0)),
            tool_calls_today=int(sr.get("tools", 0)),
            errors_today=int(sr.get("errs", 0)),
        )

    @strawberry.field
    async def trends(self, info: Info, start: str, end: str, granularity: str = "DAY") -> list[TrendPoint]:
        ctx = info.context
        project_id = ctx.get("project_id", _DEFAULT_PROJECT)
        uid = None if _is_admin(ctx) else ctx.get("user_id")
        uid_clause = " AND user_id={uid:String}" if uid else ""
        trunc_whitelist = {
            "HOUR": "toStartOfHour",
            "DAY": "toDate",
            "WEEK": "toStartOfWeek",
            "MONTH": "toStartOfMonth",
        }
        trunc = trunc_whitelist.get(granularity, "toDate")
        params: dict[str, str] = {
            "param_pid": project_id,
            "param_start": start,
            "param_end": end,
        }
        if uid:
            params["param_uid"] = uid
        rows = await _ch_json(
            f"SELECT {trunc}(start_time) as d, count() as traces "
            "FROM traces FINAL WHERE project_id={pid:String} AND is_deleted=0 "
            "AND start_time >= {start:String} AND start_time <= {end:String}" + uid_clause + " GROUP BY d ORDER BY d",
            params,
        )
        span_rows = await _ch_json(
            f"SELECT {trunc}(start_time) as d, count() as spans, countIf(status='error') as errs "
            "FROM spans FINAL WHERE project_id={pid:String} AND is_deleted=0 "
            "AND start_time >= {start:String} AND start_time <= {end:String}" + uid_clause + " GROUP BY d ORDER BY d",
            params,
        )
        span_map = {r["d"]: r for r in span_rows}
        return [
            TrendPoint(
                date=r["d"],
                traces=int(r.get("traces", 0)),
                spans=int(span_map.get(r["d"], {}).get("spans", 0)),
                errors=int(span_map.get(r["d"], {}).get("errs", 0)),
            )
            for r in rows
        ]


# --- Subscriptions ---


@strawberry.type
class SessionEvent:
    session_id: str
    event_name: str


@strawberry.type
class Subscription:
    @strawberry.subscription
    async def trace_created(
        self, mcp_id: str | None = None, agent_id: str | None = None
    ) -> AsyncGenerator[Trace, None]:
        channel = "traces:created"
        async for data in subscribe(channel):
            if mcp_id and data.get("mcp_id") != mcp_id:
                continue
            if agent_id and data.get("agent_id") != agent_id:
                continue
            yield _row_to_trace(data)

    @strawberry.subscription
    async def span_created(self, trace_id: str) -> AsyncGenerator[Span, None]:
        channel = f"spans:{trace_id}"
        async for data in subscribe(channel):
            yield _row_to_span(data)

    @strawberry.subscription
    async def session_updated(self, session_id: str | None = None) -> AsyncGenerator[SessionEvent, None]:
        channel = "sessions:updated"
        async for data in subscribe(channel):
            sid = data.get("session_id", "")
            if session_id and sid != session_id:
                continue
            yield SessionEvent(
                session_id=sid,
                event_name=data.get("event_name", ""),
            )


# --- Schema ---


async def _resolve_user_context_from_request(request) -> dict:
    """Extract project_id, user_id, and user_role from the Authorization header.

    Returns a dict with ``project_id``, ``user_id`` (str or None), and
    ``user_role`` (str or None).  Non-admin users will have their queries
    scoped to only their own traces.
    """
    import uuid as _uuid

    from sqlalchemy import select

    from database import async_session
    from models.user import User

    default = {"project_id": _DEFAULT_PROJECT, "user_id": None, "user_role": None}

    auth: str | None = None
    if request is not None:
        auth = request.headers.get("authorization")
    if not auth or not auth.startswith("Bearer "):
        return default
    token = auth.removeprefix("Bearer ").strip()
    try:
        payload = decode_access_token(token)
    except jwt.InvalidTokenError:
        return default

    sub = payload.get("sub")
    if not sub:
        return default

    try:
        uid = _uuid.UUID(sub)
    except ValueError:
        return default

    try:
        async with async_session() as session:
            result = await session.execute(select(User.org_id, User.role).where(User.id == uid))
            row = result.one_or_none()
            if not row:
                return default
            org_id, role = row
            return {
                "project_id": str(org_id) if org_id else _DEFAULT_PROJECT,
                "user_id": str(uid),
                "user_role": role.value if role else None,
            }
    except Exception:
        logger.debug("Failed to resolve user context for GraphQL", exc_info=True)
        return default


def get_context(
    project_id: str = _DEFAULT_PROJECT,
    user_id: str | None = None,
    user_role: str | None = None,
) -> dict:
    return {
        "project_id": project_id,
        "user_id": user_id,
        "user_role": user_role,
        "span_loader": DataLoader(load_fn=_make_span_loader(project_id)),
        "score_by_trace_loader": DataLoader(load_fn=_make_score_by_trace_loader(project_id)),
        "score_by_span_loader": DataLoader(load_fn=_make_score_by_span_loader(project_id)),
    }


def _is_admin(ctx: dict) -> bool:
    return ctx.get("user_role") in ("admin", "super_admin")


async def get_context_dep(request: Request = None) -> dict:
    """Strawberry FastAPI context getter — receives the incoming ``Request``."""
    uctx = await _resolve_user_context_from_request(request)
    return get_context(uctx["project_id"], uctx["user_id"], uctx["user_role"])


schema = strawberry.Schema(query=Query, subscription=Subscription)
