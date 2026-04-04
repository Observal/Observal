"""Strawberry GraphQL schema: types, resolvers, DataLoaders, subscriptions."""

import json
import logging
from collections.abc import AsyncGenerator

import strawberry
from strawberry.dataloader import DataLoader
from strawberry.scalars import JSON
from strawberry.types import Info

from services.clickhouse import (
    _escape,
    _query,
    query_span_by_id,
    query_trace_by_id,
    query_traces,
)
from services.redis import subscribe

logger = logging.getLogger(__name__)

DEFAULT_PROJECT = "default"


# --- Helpers ---


async def _ch_json(sql: str) -> list[dict]:
    try:
        r = await _query(f"{sql} FORMAT JSON")
        if r.status_code == 200:
            return r.json().get("data", [])
    except Exception as e:
        logger.warning(f"ClickHouse query failed: {e}")
    return []


def _parse_json(val: str | None) -> JSON | None:
    if not val:
        return None
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return val


# --- DataLoaders ---


async def _load_spans_by_trace_ids(keys: list[str]) -> list[list[dict]]:
    ids = ", ".join(f"'{_escape(k)}'" for k in keys)
    sql = (
        f"SELECT * FROM spans FINAL WHERE project_id = '{_escape(DEFAULT_PROJECT)}' "
        f"AND trace_id IN ({ids}) AND is_deleted = 0 ORDER BY start_time ASC"
    )
    rows = await _ch_json(sql)
    grouped: dict[str, list[dict]] = {k: [] for k in keys}
    for r in rows:
        tid = r.get("trace_id", "")
        if tid in grouped:
            grouped[tid].append(r)
    return [grouped[k] for k in keys]


async def _load_scores_by_trace_ids(keys: list[str]) -> list[list[dict]]:
    ids = ", ".join(f"'{_escape(k)}'" for k in keys)
    sql = (
        f"SELECT * FROM scores FINAL WHERE project_id = '{_escape(DEFAULT_PROJECT)}' "
        f"AND trace_id IN ({ids}) AND is_deleted = 0 ORDER BY timestamp DESC"
    )
    rows = await _ch_json(sql)
    grouped: dict[str, list[dict]] = {k: [] for k in keys}
    for r in rows:
        tid = r.get("trace_id", "")
        if tid in grouped:
            grouped[tid].append(r)
    return [grouped[k] for k in keys]


async def _load_scores_by_span_ids(keys: list[str]) -> list[list[dict]]:
    ids = ", ".join(f"'{_escape(k)}'" for k in keys)
    sql = (
        f"SELECT * FROM scores FINAL WHERE project_id = '{_escape(DEFAULT_PROJECT)}' "
        f"AND span_id IN ({ids}) AND is_deleted = 0 ORDER BY timestamp DESC"
    )
    rows = await _ch_json(sql)
    grouped: dict[str, list[dict]] = {k: [] for k in keys}
    for r in rows:
        sid = r.get("span_id", "")
        if sid in grouped:
            grouped[sid].append(r)
    return [grouped[k] for k in keys]


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
        rows = await query_traces(
            DEFAULT_PROJECT,
            trace_type=trace_type,
            mcp_id=mcp_id,
            agent_id=agent_id,
            limit=limit + 1,
            offset=offset,
        )
        has_more = len(rows) > limit
        items = [_row_to_trace(r) for r in rows[:limit]]
        return TraceConnection(items=items, total_count=len(items), has_more=has_more)

    @strawberry.field
    async def trace(self, info: Info, trace_id: str) -> Trace | None:
        r = await query_trace_by_id(DEFAULT_PROJECT, trace_id)
        return _row_to_trace(r) if r else None

    @strawberry.field
    async def span(self, info: Info, span_id: str) -> Span | None:
        r = await query_span_by_id(DEFAULT_PROJECT, span_id)
        return _row_to_span(r) if r else None

    @strawberry.field
    async def mcp_metrics(self, mcp_id: str, start: str, end: str) -> McpMetrics:
        rows = await _ch_json(
            f"SELECT count() as cnt, "
            f"countIf(status='error') as errs, "
            f"countIf(status='timeout') as timeouts, "
            f"avg(latency_ms) as avg_lat, "
            f"quantile(0.5)(latency_ms) as p50, "
            f"quantile(0.9)(latency_ms) as p90, "
            f"quantile(0.99)(latency_ms) as p99, "
            f"countIf(tool_schema_valid=1) as schema_ok, "
            f"countIf(tool_schema_valid IS NOT NULL) as schema_total "
            f"FROM spans FINAL WHERE project_id='{_escape(DEFAULT_PROJECT)}' "
            f"AND mcp_id='{_escape(mcp_id)}' AND type='tool_call' "
            f"AND start_time >= '{_escape(start)}' AND start_time <= '{_escape(end)}' "
            f"AND is_deleted=0"
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
    async def overview(self, start: str, end: str) -> OverviewStats:
        rows = await _ch_json(
            f"SELECT count() as traces FROM traces FINAL "
            f"WHERE project_id='{_escape(DEFAULT_PROJECT)}' AND is_deleted=0 "
            f"AND start_time >= '{_escape(start)}' AND start_time <= '{_escape(end)}'"
        )
        span_rows = await _ch_json(
            f"SELECT count() as spans, "
            f"countIf(type='tool_call') as tools, "
            f"countIf(status='error') as errs "
            f"FROM spans FINAL WHERE project_id='{_escape(DEFAULT_PROJECT)}' AND is_deleted=0 "
            f"AND start_time >= '{_escape(start)}' AND start_time <= '{_escape(end)}'"
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
    async def trends(self, start: str, end: str, granularity: str = "DAY") -> list[TrendPoint]:
        trunc = {"HOUR": "toStartOfHour", "DAY": "toDate", "WEEK": "toStartOfWeek", "MONTH": "toStartOfMonth"}.get(
            granularity, "toDate"
        )
        rows = await _ch_json(
            f"SELECT {trunc}(start_time) as d, count() as traces "
            f"FROM traces FINAL WHERE project_id='{_escape(DEFAULT_PROJECT)}' AND is_deleted=0 "
            f"AND start_time >= '{_escape(start)}' AND start_time <= '{_escape(end)}' "
            f"GROUP BY d ORDER BY d"
        )
        span_rows = await _ch_json(
            f"SELECT {trunc}(start_time) as d, count() as spans, countIf(status='error') as errs "
            f"FROM spans FINAL WHERE project_id='{_escape(DEFAULT_PROJECT)}' AND is_deleted=0 "
            f"AND start_time >= '{_escape(start)}' AND start_time <= '{_escape(end)}' "
            f"GROUP BY d ORDER BY d"
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


# --- Schema ---


def get_context() -> dict:
    return {
        "span_loader": DataLoader(load_fn=_load_spans_by_trace_ids),
        "score_by_trace_loader": DataLoader(load_fn=_load_scores_by_trace_ids),
        "score_by_span_loader": DataLoader(load_fn=_load_scores_by_span_ids),
    }


async def get_context_dep() -> dict:
    return get_context()


schema = strawberry.Schema(query=Query, subscription=Subscription)
