"""Session listing and detail endpoints — backed by session_events table.

Reads from the session_events ClickHouse table populated by the
/api/v1/ingest/session endpoint.  Uses session parsers to transform
raw JSONL rows into frontend-friendly event dicts.
"""

import asyncio
import json
import logging
import uuid as _uuid

from fastapi import APIRouter, Depends, Query
from fastapi_cache.decorator import cache
from sqlalchemy import select

from api.deps import require_role
from config import settings
from database import async_session
from models.user import User, UserRole
from services.audit_helpers import audit
from services.clickhouse import _query

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])


async def _ch_json(sql: str, params: dict | None = None) -> list[dict]:
    try:
        r = await _query(f"{sql} FORMAT JSON", params)
        if r.status_code == 200:
            return r.json().get("data", [])
    except Exception as e:
        logger.warning("clickhouse_query_failed: %s", e)
    return []


def _is_admin_user(user: User) -> bool:
    return user.role in (UserRole.admin, UserRole.super_admin)


def _has_admin_trace_access(user: User) -> bool:
    """Check if user has admin-level trace access."""
    if not _is_admin_user(user):
        return False
    if user.role == UserRole.super_admin:
        return True
    return not getattr(user, "_trace_privacy", False)


@router.get("/crypto/public-key")
async def get_public_key():
    """Return the server's public key for client-side ECIES encryption."""
    from services.crypto import get_key_manager

    km = get_key_manager()
    pub_pem = km.get_public_key_pem()
    return {"public_key_pem": pub_pem}


@router.get("")
async def list_sessions(
    status: str | None = Query(None),
    platform: str | None = Query(None),
    days: int | None = Query(None),
    current_user: User = Depends(require_role(UserRole.user)),
):
    is_admin = _has_admin_trace_access(current_user)
    uid_str = str(current_user.id)
    capped_days = min(days, 365) if days is not None and days > 0 else days

    rows = await _list_sessions_query(
        platform=platform,
        days=capped_days,
        is_admin=is_admin,
        uid=uid_str,
    )

    # Resolve user display names from PostgreSQL
    uid_to_name: dict[str, str] = {}
    unresolved_ids: set[str] = set()
    for row in rows:
        uid = row.get("user_id", "")
        if uid:
            unresolved_ids.add(uid)

    if unresolved_ids:
        try:
            uuid_ids = []
            for uid in unresolved_ids:
                try:
                    uuid_ids.append(_uuid.UUID(uid))
                except ValueError:
                    pass
            if uuid_ids:
                async with async_session() as db:
                    result = await db.execute(select(User.id, User.name).where(User.id.in_(uuid_ids)))
                    for u_id, u_name in result.all():
                        uid_to_name[str(u_id)] = u_name
        except Exception:
            logger.warning("User name resolution failed", exc_info=True)

    _platform_names = {
        "kiro": "Kiro",
        "claude-code": "Claude Code",
    }

    for row in rows:
        uid = row.get("user_id", "")
        row["user_name"] = uid_to_name.get(uid, current_user.name)
        ide = row.pop("ide", "") or ""
        row["platform"] = _platform_names.get(ide, "Claude Code")
        row["service_name"] = ide
        row["is_active"] = bool(int(row.get("is_active", 0)))
        agent_id = row.get("agent_id") or None
        row["agent_id"] = agent_id if agent_id else None

    if status == "active":
        rows = [r for r in rows if r["is_active"]]

    await audit(current_user, "session.list", "session")
    return rows


async def _list_sessions_query(
    *,
    platform: str | None,
    days: int | None,
    is_admin: bool,
    uid: str,
) -> list[dict]:
    """Session list from session_stats_agg — no FINAL, no JSONExtract.

    session_stats_agg is an AggregatingMergeTree table fed by session_stats_mv.
    Each row is a partial aggregate for (project_id, session_id); GROUP BY merges
    parts at read time.  At ~1 tiny row per session this is orders of magnitude
    cheaper than session_events FINAL (ClickHouse Bluesky benchmark: 44s → 6ms).
    """
    user_where = ""
    params: dict[str, str] = {}

    if not is_admin:
        user_where = "AND user_id = {uid:String} "
        params["param_uid"] = uid

    # HAVING filters operate on the merged aggregate result (correct for all
    # SimpleAggregateFunction columns; cannot use WHERE for those columns).
    having_parts = ["anyLast(parent_session_id) = ''"]
    if days is not None and days > 0:
        having_parts.append(f"max(last_event_time) > now() - INTERVAL {int(days)} DAY")
    if platform:
        having_parts.append("anyLast(ide) = {platform:String}")
        params["param_platform"] = platform
    having_clause = "HAVING " + " AND ".join(having_parts) + " "

    return await _ch_json(
        "SELECT "
        "session_id, "
        "minIf(first_event_time, "
        "  first_event_time > '1970-01-02 00:00:00' AND first_event_time < '2099-01-01 00:00:00'"
        ") AS first_event_time, "
        "maxIf(last_event_time, "
        "  last_event_time > '1970-01-02 00:00:00' AND last_event_time < '2099-01-01 00:00:00'"
        ") AS last_event_time, "
        "(max(last_event_time) > now() - INTERVAL 30 MINUTE) AS is_active, "
        "sum(prompt_count)       AS prompt_count, "
        "0                       AS api_request_count, "
        "sum(tool_result_count)  AS tool_result_count, "
        "sum(input_tokens)       AS total_input_tokens, "
        "sum(output_tokens)      AS total_output_tokens, "
        "sum(cache_read_tokens)  AS total_cache_read_tokens, "
        "sum(cache_write_tokens) AS total_cache_write_tokens, "
        "sum(total_credits)      AS total_credits, "
        "anyLastIf(model, model != '') AS model, "
        "anyLast(ide)      AS ide, "
        "anyLast(agent_id) AS agent_id, "
        "anyLast(user_id)  AS user_id "
        "FROM session_stats_agg "
        "WHERE session_id != '' "
        + user_where
        + "GROUP BY session_id "
        + having_clause
        + "ORDER BY last_event_time DESC "
        "LIMIT 100",
        params or None,
    )


@router.get("/summary")
async def sessions_summary(
    current_user: User = Depends(require_role(UserRole.user)),
):
    is_admin = _has_admin_trace_access(current_user)
    user_filter = ""
    params: dict[str, str] = {}
    if not is_admin:
        user_filter = "AND user_id = {uid:String} "
        params["param_uid"] = str(current_user.id)

    # Use pre-aggregated session_stats_agg — avoids a full session_events FINAL scan.
    # AggregatingMergeTree + GROUP BY merges partial aggregates at read time; no FINAL needed.
    rows = await _ch_json(
        "SELECT "
        "count() AS total, "
        "countIf(toDate(last_event_time) = today()) AS today_sessions "
        "FROM ( "
        "  SELECT session_id, max(last_event_time) AS last_event_time "
        "  FROM session_stats_agg "
        "  WHERE session_id != '' " + user_filter + "  GROUP BY session_id "
        ")",
        params or None,
    )
    row = rows[0] if rows else {}
    await audit(current_user, "session.summary", "session")
    return {
        "total_sessions": int(row.get("total", 0)),
        "today_sessions": int(row.get("today_sessions", 0)),
    }


@router.get("/stats")
@cache(expire=settings.CACHE_TTL_DEFAULT, namespace="otel")
async def sessions_stats(current_user: User = Depends(require_role(UserRole.admin))):
    # Use pre-aggregated session_stats_agg — avoids a full session_events FINAL scan.
    # prompt_count / tool_call_count in the MV correspond to 'user_prompt' / 'tool_call'
    # event types (legacy otel names 'user' / 'tool_use' are not present in V3 events).
    rows = await _ch_json(
        "SELECT "
        "count() AS total_sessions, "
        "sum(prompt_count) AS total_prompts, "
        "0 AS total_api_requests, "
        "sum(tool_call_count) AS total_tool_calls, "
        "sum(event_count) AS total_events "
        "FROM ( "
        "  SELECT session_id, "
        "    sum(prompt_count) AS prompt_count, "
        "    sum(tool_call_count) AS tool_call_count, "
        "    sum(event_count) AS event_count "
        "  FROM session_stats_agg "
        "  WHERE session_id != '' "
        "  GROUP BY session_id "
        ")"
    )
    row = rows[0] if rows else {}
    await audit(current_user, "stats.view", "stats")
    return {
        "total_sessions": int(row.get("total_sessions", 0)),
        "total_prompts": int(row.get("total_prompts", 0)),
        "total_api_requests": int(row.get("total_api_requests", 0)),
        "total_tool_calls": int(row.get("total_tool_calls", 0)),
        "total_events": int(row.get("total_events", 0)),
    }


@router.get("/{session_id}")
async def get_session(session_id: str, current_user: User = Depends(require_role(UserRole.user))):
    is_admin = _has_admin_trace_access(current_user)
    params: dict[str, str] = {"param_sid": session_id}

    if not is_admin:
        # Verify the user owns this session
        params["param_uid"] = str(current_user.id)
        ownership = await _ch_json(
            "SELECT 1 FROM session_events WHERE session_id = {sid:String} AND user_id = {uid:String} LIMIT 1",
            params,
        )
        if not ownership:
            return {"session_id": session_id, "ide": "", "events": []}

    # Fan out both FINAL scans in parallel — wall time ≈ max(t1, t2) not t1+t2.
    # do_not_merge_across_partitions_select_final=1 lets CH process each monthly
    # partition independently instead of a single cross-partition merge pass.
    # (ClickHouse docs benchmark: 2.3s → 0.99s on 59M rows with yearly partitioning)
    _main_sql = (
        "SELECT "
        "timestamp, event_type, content_preview, tool_name, tool_id, "
        "uuid, parent_uuid, content_length, ide, raw_line, raw_line_truncated, "
        "credits, ingested_at "
        "FROM session_events FINAL "
        "WHERE session_id = {sid:String} "
        "ORDER BY line_offset ASC "
        "SETTINGS max_final_threads = 4, do_not_merge_across_partitions_select_final = 1"
    )
    _sub_sql = (
        "SELECT session_id, timestamp, event_type, content_preview, "
        "tool_name, tool_id, uuid, parent_uuid, content_length, ide, "
        "raw_line, raw_line_truncated, credits, ingested_at, line_offset "
        "FROM session_events FINAL "
        "WHERE parent_session_id = {sid:String} "
        "ORDER BY session_id, line_offset ASC "
        "SETTINGS max_final_threads = 4, do_not_merge_across_partitions_select_final = 1"
    )
    rows, sub_rows_all = await asyncio.gather(
        _ch_json(_main_sql, params),
        _ch_json(_sub_sql, {"param_sid": session_id}),
    )

    if not rows:
        return {"session_id": session_id, "service_name": "", "events": [], "traces": []}

    ide = rows[0].get("ide", "claude-code")

    # Parse raw events through the session parser for rich rendering
    from services.session_parsers import parse_raw_events

    events = parse_raw_events(rows)

    # sub_rows_all was fetched concurrently above alongside the main query.
    # Each subagent's first row carries parent_uuid pointing at the Agent
    # tool_call in the parent that spawned it — the frontend uses this to
    # nest the subagent inline at the right position.
    subagent_sessions = []
    if sub_rows_all:
        # Group by session_id
        from itertools import groupby

        sub_rows_all.sort(key=lambda r: r["session_id"])
        for sub_sid, sub_rows in groupby(sub_rows_all, key=lambda r: r["session_id"]):
            sub_rows_list = list(sub_rows)
            # first row's parent_uuid links to the Agent tool_call in the parent
            spawned_by = sub_rows_list[0].get("parent_uuid") if sub_rows_list else None
            sub_events = parse_raw_events(sub_rows_list)
            subagent_sessions.append(
                {
                    "session_id": sub_sid,
                    "spawned_by": spawned_by,
                    "events": sub_events,
                }
            )

    await audit(current_user, "session.view", "session", resource_id=session_id)
    return {
        "session_id": session_id,
        "service_name": ide,
        "events": events,
        "traces": [],
        "subagent_sessions": subagent_sessions,
    }


@router.get("/{session_id}/efficiency")
async def get_session_efficiency(session_id: str, current_user: User = Depends(require_role(UserRole.user))):
    """Run kernel efficiency analysis on a session's events."""
    if not session_id or not session_id.strip():
        return {"error": "No session ID provided"}

    is_admin = _is_admin_user(current_user)
    params: dict[str, str] = {"param_sid": session_id}

    if not is_admin:
        params["param_uid"] = str(current_user.id)
        ownership = await _ch_json(
            "SELECT 1 FROM session_events WHERE session_id = {sid:String} AND user_id = {uid:String} LIMIT 1",
            params,
        )
        if not ownership:
            return {"error": "Session not found or access denied"}

    rows = await _ch_json(
        "SELECT "
        "timestamp, "
        "event_type AS event_name, "
        "content_preview AS body, "
        "raw_line, "
        "ide AS service_name "
        "FROM session_events FINAL "
        "WHERE session_id = {sid:String} "
        "ORDER BY line_offset ASC "
        "SETTINGS max_final_threads = 4, do_not_merge_across_partitions_select_final = 1",
        params,
    )

    if not rows:
        return {"error": "No events found for session", "session_id": session_id}

    # Transform rows to event-shaped dicts for the efficiency analyzer
    events = []
    for r in rows:
        attrs = {}
        try:
            parsed = json.loads(r.get("raw_line", "{}"))
            attrs = {"event.name": r.get("event_name", ""), **parsed}
        except Exception:
            attrs = {"event.name": r.get("event_name", "")}
        events.append(
            {
                "timestamp": r.get("timestamp", ""),
                "event_name": r.get("event_name", ""),
                "body": r.get("body", ""),
                "attributes": attrs,
                "service_name": r.get("service_name", ""),
            }
        )

    from services.eval.kernel_bridge import analyze_session_efficiency

    try:
        return analyze_session_efficiency(events)
    except Exception:
        logger.exception("Session efficiency analysis failed for %s", session_id)
        return {"error": "Analysis failed", "session_id": session_id}


@router.post("/{session_id}/bind-agent")
async def bind_session_agent(
    session_id: str,
    agent_name: str = Query(..., description="Agent name to bind to this session"),
    current_user: User = Depends(require_role(UserRole.user)),
):
    """Explicitly bind a session to an agent name."""
    is_admin = _is_admin_user(current_user)
    if not is_admin:
        params = {"param_sid": session_id, "param_uid": str(current_user.id)}
        ownership = await _ch_json(
            "SELECT 1 FROM session_events WHERE session_id = {sid:String} AND user_id = {uid:String} LIMIT 1",
            params,
        )
        if not ownership:
            return {"error": "Session not found or access denied"}

    from redis.exceptions import RedisError

    from services.redis import get_redis

    try:
        redis = get_redis()
        await redis.set(f"session_agent:{session_id}", agent_name, ex=86400)
    except RedisError:
        return {"session_id": session_id, "agent_name": agent_name, "bound": False, "error": "Redis unavailable"}

    await audit(current_user, "session.bind_agent", "session", resource_id=session_id, detail=f"Bound to {agent_name}")
    return {"session_id": session_id, "agent_name": agent_name, "bound": True}
