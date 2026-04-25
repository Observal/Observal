import asyncio
import json
import re
import time as _time
import uuid as _uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, Query, Request
from fastapi_cache.decorator import cache
from sqlalchemy import or_, select

from api.deps import require_role
from config import settings
from database import async_session
from models.user import User, UserRole
from services.audit_helpers import audit
from services.clickhouse import _query, query_shim_spans_for_window
from services.redis import publish
from services.secrets_redactor import redact_secrets

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/otel", tags=["otel-dashboard"])

# Normalize legacy ServiceName values to canonical IDE names.
# Old events in ClickHouse may still carry these; normalization at query
# time ensures the frontend always sees the canonical form.
_SERVICE_NAME_MAP: dict[str, str] = {
    "kiro-cli": "kiro",
    "observal-hooks": "claude-code",
    "observal-shim": "claude-code",
    "copilot-cli": "copilot",
    "github-copilot": "copilot",
    "gemini-cli": "gemini",
    "cursor-cli": "cursor",
}


def _normalize_service(svc: str) -> str:
    return _SERVICE_NAME_MAP.get(svc, svc)


# ── Kiro IDE session correlation ──
# When Kiro IDE fires hooks, each event may have a different $PPID-based
# session ID. We correlate them by cwd within a 30-minute window.

_kiro_session_cache: dict[str, tuple[str, float]] = {}  # cwd -> (session_id, timestamp)
_KIRO_SESSION_WINDOW = 1800  # 30 minutes


# Background tasks that must survive until completion (prevent GC)
_background_tasks: set[asyncio.Task] = set()


@router.get("/crypto/public-key")
async def get_public_key():
    """Return the server's public key for client-side ECIES encryption.

    This endpoint is intentionally unauthenticated so CLI clients can
    fetch the key during login without a pre-existing session.
    """
    from services.crypto import get_key_manager

    km = get_key_manager()
    pub_pem = km.get_public_key_pem()
    return {"public_key_pem": pub_pem}


async def _ch_json(sql: str, params: dict | None = None) -> list[dict]:
    try:
        r = await _query(f"{sql} FORMAT JSON", params)
        if r.status_code == 200:
            return r.json().get("data", [])
    except Exception as e:
        logger.warning("clickhouse_query_failed", error=str(e))
    return []


def _is_admin_user(user: User) -> bool:
    return user.role in (UserRole.admin, UserRole.super_admin)


def _has_admin_trace_access(user: User) -> bool:
    """Check if user has admin-level trace access.

    Super-admins always have full trace visibility regardless of the
    trace_privacy setting.  When trace privacy is on, regular admins are
    treated like normal users — they can only see their own traces.

    The trace_privacy flag is resolved once at authentication time (see
    deps._authenticate_via_jwt) and attached to the user object, so this
    check never makes an extra DB call.
    """
    if not _is_admin_user(user):
        return False
    if user.role == UserRole.super_admin:
        return True
    return not getattr(user, "_trace_privacy", False)


@router.get("/sessions")
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
        uemail=current_user.email,
    )

    # ── Resolve user display names ──
    # Build uuid→name and email→name maps from PostgreSQL,
    # querying only the user_ids that actually need resolution.
    uid_to_name: dict[str, str] = {}
    unresolved_ids: set[str] = set()
    for row in rows:
        user_ids = row.pop("user_ids", []) or []
        best_uid = ""
        for u in user_ids:
            try:
                _uuid.UUID(u)
                best_uid = u
                break
            except ValueError:
                best_uid = best_uid or u
        row["user_id"] = best_uid
        if not row.get("user_name") and best_uid:
            unresolved_ids.add(best_uid)

    if unresolved_ids:
        try:
            uuid_ids = []
            email_ids = []
            for uid in unresolved_ids:
                try:
                    uuid_ids.append(_uuid.UUID(uid))
                except ValueError:
                    email_ids.append(uid)
            filters = []
            if uuid_ids:
                filters.append(User.id.in_(uuid_ids))
            if email_ids:
                filters.append(User.email.in_(email_ids))
            if filters:
                async with async_session() as db:
                    result = await db.execute(select(User.id, User.email, User.name).where(or_(*filters)))
                    for u_id, u_email, u_name in result.all():
                        uid_to_name[str(u_id)] = u_name
                        if u_email:
                            uid_to_name[u_email] = u_name
        except Exception:
            logger.warning("User name resolution failed", exc_info=True)

    # For admin: map unresolved OTLP hashes to users.
    # On Windows, .sh hooks don't run, so sessions only have native OTLP
    # hashes (not Observal UUIDs). If all unresolved user_ids map to a
    # single hash, attribute them to the current admin (the person who
    # set up OTLP via `observal auth login`).
    if is_admin:
        unresolved: set[str] = set()
        for row in rows:
            uid = row.get("user_id", "")
            if uid and not row.get("user_name") and uid not in uid_to_name:
                unresolved.add(uid)
        if len(unresolved) == 1:
            uid_to_name[unresolved.pop()] = current_user.name

    for row in rows:
        row["is_active"] = bool(int(row.get("is_active", 0)))
        row["service_name"] = _normalize_service(row.get("service_name", ""))
        if not row.get("user_name") and row.get("user_id"):
            row["user_name"] = uid_to_name.get(row["user_id"], "")
        # Remaining blank names: non-admins only see their own sessions
        # (query filter guarantees this); admins get Kiro sessions that
        # lack user_id entirely. Either way, attribute to current user.
        if not row.get("user_name"):
            row["user_name"] = current_user.name
        svc = row.get("service_name", "")
        sid = row.get("session_id", "")
        _platform_names = {
            "kiro": "Kiro",
            "gemini": "Gemini CLI",
            "cursor": "Cursor",
            "copilot": "GitHub Copilot",
            "claude-code": "Claude Code",
        }
        if svc == "kiro" or sid.startswith("kiro-"):
            row["platform"] = "Kiro"
        else:
            row["platform"] = _platform_names.get(svc, "Claude Code")

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
    uemail: str,
) -> list[dict]:
    """ClickHouse query for session list."""
    session_filter = ""
    time_filter = ""
    platform_filter = ""
    params: dict[str, str] = {}
    if not is_admin:
        session_filter = (
            "AND LogAttributes['session.id'] IN ("
            "  SELECT DISTINCT LogAttributes['session.id'] FROM otel_logs"
            "  WHERE LogAttributes['session.id'] != ''"
            "  AND (LogAttributes['user.id'] = {uid:String}"
            "       OR LogAttributes['user.id'] = {uemail:String})"
            ") "
        )
        params["param_uid"] = uid
        params["param_uemail"] = uemail

    if days is not None and days > 0:
        time_filter = f"AND Timestamp > now('UTC') - INTERVAL {int(days)} DAY "

    if platform:
        platform_filter = "HAVING service_name = {platform:String} "
        params["param_platform"] = platform

    return await _ch_json(
        "SELECT "
        "LogAttributes['session.id'] AS session_id, "
        "min(Timestamp) AS first_event_time, "
        "max(Timestamp) AS last_event_time, "
        "(max(Timestamp) > now('UTC') - INTERVAL 30 MINUTE "
        " AND argMax("
        "   LogAttributes['event.name'],"
        "   Timestamp"
        " ) NOT IN ('hook_stop', 'hook_stopfailure')"
        ") AS is_active, "
        "greatest(countIf(LogAttributes['event.name'] = 'user_prompt'), countIf(LogAttributes['event.name'] = 'hook_userpromptsubmit')) AS prompt_count, "
        "greatest(countIf(LogAttributes['event.name'] = 'api_request'), countIf(LogAttributes['event.name'] = 'hook_userpromptsubmit')) AS api_request_count, "
        "greatest(countIf(LogAttributes['event.name'] = 'tool_result'), countIf(LogAttributes['event.name'] = 'hook_posttooluse')) AS tool_result_count, "
        "countIf(LogAttributes['event.name'] LIKE 'hook_%') AS hook_event_count, "
        "sum(toUInt64OrZero(LogAttributes['input_tokens'])) AS total_input_tokens, "
        "sum(toUInt64OrZero(LogAttributes['output_tokens'])) AS total_output_tokens, "
        "sum(toUInt64OrZero(LogAttributes['cache_read_tokens'])) AS total_cache_read_tokens, "
        "sum(toUInt64OrZero(LogAttributes['cache_creation_tokens'])) AS total_cache_write_tokens, "
        "topKIf(1)(LogAttributes['model'], LogAttributes['model'] != '')[1] AS model, "
        "groupUniqArrayIf(LogAttributes['user.id'], LogAttributes['user.id'] != '') AS user_ids, "
        "anyIf(LogAttributes['user.name'], LogAttributes['user.name'] != '') AS user_name, "
        "anyIf(LogAttributes['terminal.type'], LogAttributes['terminal.type'] != '') AS terminal_type, "
        "anyIf(LogAttributes['credits'], LogAttributes['credits'] != '') AS credits, "
        "anyIf(LogAttributes['tools_used'], LogAttributes['tools_used'] != '') AS tools_used, "
        "multiIf("
        "  any(ServiceName) = 'kiro-cli', 'kiro',"
        "  any(ServiceName) IN ('observal-hooks', 'observal-shim'), 'claude-code',"
        "  any(ServiceName)"
        ") AS service_name "
        "FROM otel_logs "
        "WHERE LogAttributes['session.id'] != '' "
        + session_filter
        + time_filter
        + "GROUP BY session_id "
        + platform_filter
        + "ORDER BY last_event_time DESC "
        "LIMIT 100",
        params or None,
    )


@router.get("/sessions/summary")
async def sessions_summary(
    current_user: User = Depends(require_role(UserRole.user)),
):
    is_admin = _has_admin_trace_access(current_user)
    session_filter = ""
    params: dict[str, str] = {}
    if not is_admin:
        session_filter = (
            "AND LogAttributes['session.id'] IN ("
            "  SELECT DISTINCT LogAttributes['session.id'] FROM otel_logs"
            "  WHERE LogAttributes['session.id'] != ''"
            "  AND (LogAttributes['user.id'] = {uid:String}"
            "       OR LogAttributes['user.id'] = {uemail:String})"
            ") "
        )
        params["param_uid"] = str(current_user.id)
        params["param_uemail"] = current_user.email

    rows = await _ch_json(
        "SELECT "
        "count(DISTINCT LogAttributes['session.id']) AS total, "
        "count(DISTINCT CASE WHEN Timestamp > today() "
        "  THEN LogAttributes['session.id'] END) AS today_sessions "
        "FROM otel_logs "
        "WHERE LogAttributes['session.id'] != '' " + session_filter,
        params or None,
    )
    row = rows[0] if rows else {}
    await audit(current_user, "session.summary", "session")
    return {
        "total_sessions": int(row.get("total", 0)),
        "today_sessions": int(row.get("today_sessions", 0)),
    }


def _merge_session_events(events: list[dict]) -> list[dict]:
    """Merge events from multiple sources (hook, shim, otlp, collector).

    Strategy:
    1. Partition events by source.
    2. For each shim tool_call, find the matching hook PostToolUse by
       tool_name + timestamp within 500ms.  Merge: hook fields (tool_input,
       tool_response, agent_id) + shim fields (mcp_id, tool_schema_valid,
       mcp_latency_ms) → single event with source='merged'.
    3. Unmatched shim events pass through (shim-only sessions).
    4. All other events pass through unchanged.

    Zero data loss: every unique field from every source survives.
    """
    from datetime import datetime

    def _parse_ts(ts_str: str) -> float:
        """Parse timestamp string to epoch seconds for proximity matching."""
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%S.%f"):
            try:
                return datetime.strptime(ts_str[:26], fmt).timestamp()
            except (ValueError, TypeError):
                continue
        return 0.0

    hooks: list[dict] = []
    shims: list[dict] = []
    rest: list[dict] = []

    for e in events:
        attrs = e.get("attributes", {})
        if isinstance(attrs, str):
            try:
                attrs = json.loads(attrs)
            except Exception:
                attrs = {}
        source = attrs.get("source", "")
        event_name = attrs.get("event.name", e.get("event_name", ""))

        if source == "shim" and event_name == "shim_tool_call":
            shims.append(e)
        elif source == "hook" and event_name in ("hook_posttooluse", "hook_posttoolusefailure"):
            hooks.append(e)
        else:
            rest.append(e)

    # Index hooks by (tool_name, timestamp) for matching
    matched_hook_indices: set[int] = set()
    merged: list[dict] = []

    for shim_event in shims:
        shim_attrs = shim_event.get("attributes", {})
        if isinstance(shim_attrs, str):
            try:
                shim_attrs = json.loads(shim_attrs)
            except Exception:
                shim_attrs = {}
        shim_tool = shim_attrs.get("tool_name", "")
        shim_ts = _parse_ts(shim_event.get("timestamp", ""))

        best_idx = -1
        best_delta = 0.5  # 500ms max window

        for i, hook in enumerate(hooks):
            if i in matched_hook_indices:
                continue
            hook_attrs = hook.get("attributes", {})
            if isinstance(hook_attrs, str):
                try:
                    hook_attrs = json.loads(hook_attrs)
                except Exception:
                    hook_attrs = {}
            if hook_attrs.get("tool_name", "") != shim_tool:
                continue
            hook_ts = _parse_ts(hook.get("timestamp", ""))
            delta = abs(shim_ts - hook_ts)
            if delta < best_delta:
                best_delta = delta
                best_idx = i

        if best_idx >= 0:
            # Merge: hook is the base, shim enriches
            matched_hook_indices.add(best_idx)
            hook_event = hooks[best_idx]
            hook_attrs = hook_event.get("attributes", {})
            if isinstance(hook_attrs, str):
                try:
                    hook_attrs = json.loads(hook_attrs)
                except Exception:
                    hook_attrs = {}

            # Merge attributes: hook fields are base, shim fields overlay
            merged_attrs = dict(hook_attrs)
            # Shim-unique fields that enrich hook data
            for key in (
                "mcp_id",
                "mcp_method",
                "mcp_latency_ms",
                "tool_schema_valid",
                "tools_available",
                "mcp_input",
                "mcp_output",
                "mcp_error",
                "mcp_span_id",
                "mcp_trace_id",
                "mcp_status",
            ):
                if shim_attrs.get(key):
                    merged_attrs[key] = shim_attrs[key]

            merged_attrs["source"] = "merged"
            merged_attrs["_sources"] = "hook,shim"

            merged.append(
                {
                    "timestamp": hook_event.get("timestamp", shim_event.get("timestamp", "")),
                    "event_name": hook_event.get("event_name", hook_attrs.get("event.name", "")),
                    "body": hook_event.get("body", ""),
                    "attributes": merged_attrs,
                    "service_name": hook_event.get("service_name", ""),
                }
            )
        else:
            # Unmatched shim event — keep as-is (shim-only session)
            rest.append(shim_event)

    # Unmatched hooks pass through
    for i, hook in enumerate(hooks):
        if i not in matched_hook_indices:
            rest.append(hook)

    # Combine merged + rest, sort by timestamp
    all_events = merged + rest
    all_events.sort(key=lambda e: e.get("timestamp", ""))
    return all_events


def _annotate_agent_scope(events: list[dict]) -> list[dict]:
    """Annotate events with agent context from SubagentStart/SubagentStop pairs.

    Works across all IDEs: Claude Code (agent_id/agent_type/agent_name),
    Copilot (agent_name/agent_type from display name), Gemini
    (BeforeAgent/AfterAgent brackets).  Scans chronologically and tracks
    the active agent scope stack so every event between start/stop
    inherits the agent's identity.
    """
    agent_stack: list[dict[str, str]] = []

    for event in events:
        attrs = event.get("attributes", {})
        if isinstance(attrs, str):
            try:
                attrs = json.loads(attrs)
                event["attributes"] = attrs
            except Exception:
                continue

        hook_event = attrs.get("hook_event", "")

        if hook_event == "SubagentStart":
            agent_stack.append(
                {
                    "agent_id": attrs.get("agent_id", ""),
                    "agent_type": attrs.get("agent_type", ""),
                    "agent_name": attrs.get("agent_name", ""),
                }
            )
        elif hook_event == "SubagentStop" and agent_stack:
            agent_stack.pop()

        if agent_stack and not attrs.get("agent_id") and not attrs.get("agent_name"):
            current = agent_stack[-1]
            if current.get("agent_id"):
                attrs["agent_id"] = current["agent_id"]
            if current.get("agent_type"):
                attrs["agent_type"] = current["agent_type"]
            if current.get("agent_name"):
                attrs["agent_name"] = current["agent_name"]

    return events


# Shim span type → otel_logs event.name (matches telemetry.py _SHIM_EVENT_NAMES)
_SHIM_TYPE_TO_EVENT: dict[str, str] = {
    "tool_call": "shim_tool_call",
    "tool_list": "shim_tool_list",
    "initialize": "shim_initialize",
    "resource_read": "shim_resource_read",
    "resource_list": "shim_resource_list",
    "resource_subscribe": "shim_resource_subscribe",
    "prompt_get": "shim_prompt_get",
    "prompt_list": "shim_prompt_list",
    "ping": "shim_ping",
    "completion": "shim_completion",
    "config": "shim_config",
    "other": "shim_other",
}


def _synthesize_shim_events(
    shim_spans: list[dict],
    existing_shim_span_ids: set[str],
    session_service_name: str = "claude-code",
) -> list[dict]:
    """Convert shim span rows into otel_logs-shaped event dicts.

    Skips spans whose span_id is already present in otel_logs (dedup
    against write-time mirroring when session_id was available).
    """
    events: list[dict] = []
    for s in shim_spans:
        span_id = s.get("span_id", "")
        if span_id in existing_shim_span_ids:
            continue

        span_type = s.get("type", "other")
        event_name = _SHIM_TYPE_TO_EVENT.get(span_type, "shim_other")
        tool_name = s.get("name", "")
        latency_ms = s.get("latency_ms")
        mcp_id = s.get("mcp_id", "")

        latency_label = f" ({latency_ms}ms)" if latency_ms else ""
        body_text = f"shim: {span_type} {tool_name}{latency_label}"

        attrs: dict[str, str] = {
            "event.name": event_name,
            "source": "shim",
            "tool_name": tool_name,
            "mcp_id": mcp_id or "",
            "mcp_method": s.get("method", ""),
            "mcp_span_id": span_id,
            "mcp_trace_id": s.get("trace_id", ""),
        }
        if latency_ms is not None:
            attrs["mcp_latency_ms"] = str(latency_ms)
        if s.get("tool_schema_valid") is not None:
            attrs["tool_schema_valid"] = str(s["tool_schema_valid"])
        if s.get("tools_available") is not None:
            attrs["tools_available"] = str(s["tools_available"])
        if s.get("input"):
            attrs["mcp_input"] = str(s["input"])[:2000]
        if s.get("output"):
            attrs["mcp_output"] = str(s["output"])[:2000]
        if s.get("error"):
            attrs["mcp_error"] = str(s["error"])[:2000]
        if s.get("status"):
            attrs["mcp_status"] = s["status"]

        events.append(
            {
                "timestamp": s.get("start_time", ""),
                "event_name": event_name,
                "body": body_text,
                "attributes": attrs,
                "service_name": session_service_name,
            }
        )
    return events


async def _sideload_shim_spans(events: list[dict]) -> list[dict]:
    """Side-load shim spans from the spans table for sessions missing shim data.

    When shim processes don't have OBSERVAL_SESSION_ID set, their spans
    land in the spans table but not in otel_logs.  This function queries
    spans by user_id + time window overlap and synthesizes otel_logs-shaped
    events for the merge logic.

    Works for both Claude Code and Kiro sessions — matches by user_id
    and timestamp, not session_id format.
    """
    if not events:
        return events

    # Extract user_id, time bounds, and dominant service_name from existing events
    user_id = ""
    min_ts = ""
    max_ts = ""
    session_service = ""
    existing_shim_span_ids: set[str] = set()

    for e in events:
        attrs = e.get("attributes", {})
        if isinstance(attrs, str):
            try:
                attrs = json.loads(attrs)
            except Exception:
                attrs = {}
        if not user_id and attrs.get("user.id"):
            user_id = attrs["user.id"]
        ts = e.get("timestamp", "")
        if ts:
            if not min_ts or ts < min_ts:
                min_ts = ts
            if not max_ts or ts > max_ts:
                max_ts = ts
        # Track shim spans already in otel_logs (from write-time mirroring)
        if attrs.get("source") == "shim" and attrs.get("mcp_span_id"):
            existing_shim_span_ids.add(attrs["mcp_span_id"])
        # Prefer a canonical IDE service_name (skip legacy "observal-shim"
        # that old data may still carry — new shim events use the IDE name).
        svc = e.get("service_name", "")
        if svc and svc != "observal-shim" and not session_service:
            session_service = svc

    if not user_id or not min_ts or not max_ts:
        return events

    shim_spans = await query_shim_spans_for_window(user_id, min_ts, max_ts)
    if not shim_spans:
        return events

    synthetic = _synthesize_shim_events(
        shim_spans, existing_shim_span_ids, _normalize_service(session_service) or "claude-code"
    )
    if not synthetic:
        return events

    return events + synthetic


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, current_user: User = Depends(require_role(UserRole.user))):
    is_admin = _has_admin_trace_access(current_user)
    params: dict[str, str] = {"param_sid": session_id}

    if not is_admin:
        # Verify the user owns this session (any event with their UUID/email)
        params["param_uid"] = str(current_user.id)
        params["param_uemail"] = current_user.email
        ownership = await _ch_json(
            "SELECT 1 FROM otel_logs "
            "WHERE LogAttributes['session.id'] = {sid:String} "
            "AND (LogAttributes['user.id'] = {uid:String} "
            "     OR LogAttributes['user.id'] = {uemail:String}) "
            "LIMIT 1",
            params,
        )
        if not ownership:
            return {"session_id": session_id, "service_name": "", "events": [], "traces": []}

    # Fetch all events for the session (both hook and native telemetry)
    events = await _ch_json(
        "SELECT "
        "Timestamp AS timestamp, "
        "LogAttributes['event.name'] AS event_name, "
        "Body AS body, "
        "LogAttributes AS attributes, "
        "ServiceName AS service_name "
        "FROM otel_logs "
        "WHERE LogAttributes['session.id'] = {sid:String} "
        "ORDER BY Timestamp ASC",
        params,
    )
    traces = await _ch_json(
        "SELECT "
        "TraceId AS trace_id, "
        "SpanId AS span_id, "
        "ParentSpanId AS parent_span_id, "
        "SpanName AS span_name, "
        "Duration AS duration_ns, "
        "StatusCode AS status_code, "
        "SpanAttributes AS span_attributes, "
        "Timestamp AS timestamp "
        "FROM otel_traces "
        "WHERE SpanAttributes['session.id'] = {sid:String} "
        "ORDER BY Timestamp ASC",
        {"param_sid": session_id},
    )
    # Side-load shim spans that lack session_id (query-time resolution)
    events = await _sideload_shim_spans(events)
    # Merge events from multiple sources (hook + shim + collector)
    events = _merge_session_events(events)
    events = _annotate_agent_scope(events)
    svc = _normalize_service(events[0]["service_name"]) if events else ""
    await audit(current_user, "session.view", "session", resource_id=session_id)
    return {"session_id": session_id, "service_name": svc, "events": events, "traces": traces}


@router.get("/sessions/{session_id}/efficiency")
async def get_session_efficiency(session_id: str, current_user: User = Depends(require_role(UserRole.user))):
    """Run kernel efficiency analysis on a session's hook events."""
    is_admin = _is_admin_user(current_user)
    params: dict[str, str] = {"param_sid": session_id}

    if not is_admin:
        params["param_uid"] = str(current_user.id)
        params["param_uemail"] = current_user.email
        ownership = await _ch_json(
            "SELECT 1 FROM otel_logs "
            "WHERE LogAttributes['session.id'] = {sid:String} "
            "AND (LogAttributes['user.id'] = {uid:String} "
            "     OR LogAttributes['user.id'] = {uemail:String}) "
            "LIMIT 1",
            params,
        )
        if not ownership:
            return {"error": "Session not found or access denied"}

    events = await _ch_json(
        "SELECT "
        "Timestamp AS timestamp, "
        "LogAttributes['event.name'] AS event_name, "
        "Body AS body, "
        "LogAttributes AS attributes, "
        "ServiceName AS service_name "
        "FROM otel_logs "
        "WHERE LogAttributes['session.id'] = {sid:String} "
        "ORDER BY Timestamp ASC",
        params,
    )

    if not events:
        return {"error": "No events found for session", "session_id": session_id}

    from services.eval.kernel_bridge import analyze_session_efficiency

    return analyze_session_efficiency(events)


@router.get("/traces")
@cache(expire=settings.CACHE_TTL_OTEL, namespace="otel")
async def list_traces(current_user: User = Depends(require_role(UserRole.admin))):
    rows = await _ch_json(
        "SELECT "
        "TraceId AS trace_id, "
        "SpanName AS span_name, "
        "ServiceName AS service_name, "
        "Duration AS duration_ns, "
        "StatusCode AS status, "
        "Timestamp AS timestamp, "
        "SpanAttributes['session.id'] AS session_id "
        "FROM otel_traces "
        "WHERE ParentSpanId = '' "
        "ORDER BY Timestamp DESC "
        "LIMIT 100"
    )
    await audit(current_user, "trace.list", "trace")
    return rows


@router.get("/traces/{trace_id}")
async def get_trace(trace_id: str, current_user: User = Depends(require_role(UserRole.admin))):
    rows = await _ch_json(
        "SELECT "
        "SpanId AS span_id, "
        "ParentSpanId AS parent_span_id, "
        "SpanName AS span_name, "
        "Duration AS duration_ns, "
        "StatusCode AS status_code, "
        "SpanAttributes AS span_attributes, "
        "Events.Name AS event_names, "
        "Events.Timestamp AS event_timestamps, "
        "Events.Attributes AS event_attributes "
        "FROM otel_traces "
        "WHERE TraceId = {tid:String} "
        "ORDER BY Timestamp ASC",
        {"param_tid": trace_id},
    )
    spans = []
    for r in rows:
        events = []
        names = r.get("event_names") or []
        timestamps = r.get("event_timestamps") or []
        attrs = r.get("event_attributes") or []
        for i in range(len(names)):
            events.append(
                {
                    "name": names[i],
                    "timestamp": timestamps[i] if i < len(timestamps) else None,
                    "attributes": attrs[i] if i < len(attrs) else {},
                }
            )
        spans.append(
            {
                "span_id": r["span_id"],
                "parent_span_id": r["parent_span_id"],
                "span_name": r["span_name"],
                "duration_ns": r["duration_ns"],
                "status_code": r["status_code"],
                "span_attributes": r["span_attributes"],
                "events": events,
            }
        )
    await audit(current_user, "trace.view", "trace", resource_id=trace_id)
    return spans


@router.get("/errors")
@cache(expire=settings.CACHE_TTL_OTEL, namespace="otel")
async def list_errors(current_user: User = Depends(require_role(UserRole.admin))):
    """List recent error events (tool failures, stop failures, API errors)."""
    rows = await _ch_json(
        "SELECT "
        "Timestamp AS timestamp, "
        "LogAttributes['event.name'] AS event_name, "
        "Body AS body, "
        "LogAttributes['session.id'] AS session_id, "
        "LogAttributes['tool_name'] AS tool_name, "
        "LogAttributes['error'] AS error, "
        "LogAttributes['agent_id'] AS agent_id, "
        "LogAttributes['agent_type'] AS agent_type, "
        "LogAttributes['tool_input'] AS tool_input, "
        "LogAttributes['tool_response'] AS tool_response, "
        "LogAttributes['stop_reason'] AS stop_reason, "
        "LogAttributes['user.id'] AS user_id "
        "FROM otel_logs "
        "WHERE LogAttributes['event.name'] IN "
        "('hook_posttoolusefailure', 'hook_stopfailure', 'api_error') "
        "ORDER BY Timestamp DESC "
        "LIMIT 200"
    )
    await audit(current_user, "error.list", "error")
    return rows


@router.get("/stats")
@cache(expire=settings.CACHE_TTL_DEFAULT, namespace="otel")
async def otel_stats(current_user: User = Depends(require_role(UserRole.admin))):
    log_rows = await _ch_json(
        "SELECT "
        "count() AS total_sessions, "
        "sum(p) AS total_prompts, "
        "sum(a) AS total_api_requests, "
        "sum(t) AS total_tool_calls, "
        "sum(it) AS total_input_tokens, "
        "sum(ot) AS total_output_tokens, "
        "sum(cr) AS total_cache_read_tokens, "
        "sum(cw) AS total_cache_write_tokens "
        "FROM ("
        "SELECT "
        "LogAttributes['session.id'] AS sid, "
        "greatest(countIf(LogAttributes['event.name'] = 'user_prompt'), countIf(LogAttributes['event.name'] = 'hook_userpromptsubmit')) AS p, "
        "greatest(countIf(LogAttributes['event.name'] = 'api_request'), countIf(LogAttributes['event.name'] = 'hook_userpromptsubmit')) AS a, "
        "greatest(countIf(LogAttributes['event.name'] = 'tool_result'), countIf(LogAttributes['event.name'] = 'hook_posttooluse')) AS t, "
        "sum(toUInt64OrZero(LogAttributes['input_tokens'])) AS it, "
        "sum(toUInt64OrZero(LogAttributes['output_tokens'])) AS ot, "
        "sum(toUInt64OrZero(LogAttributes['cache_read_tokens'])) AS cr, "
        "sum(toUInt64OrZero(LogAttributes['cache_creation_tokens'])) AS cw "
        "FROM otel_logs "
        "WHERE LogAttributes['session.id'] != '' "
        "GROUP BY sid"
        ")"
    )
    trace_rows = await _ch_json(
        "SELECT count(DISTINCT TraceId) AS total_traces, count() AS total_spans FROM otel_traces"
    )
    log = log_rows[0] if log_rows else {}
    tr = trace_rows[0] if trace_rows else {}
    await audit(current_user, "stats.view", "stats")
    return {
        "total_sessions": int(log.get("total_sessions", 0)),
        "total_prompts": int(log.get("total_prompts", 0)),
        "total_api_requests": int(log.get("total_api_requests", 0)),
        "total_tool_calls": int(log.get("total_tool_calls", 0)),
        "total_input_tokens": int(log.get("total_input_tokens", 0)),
        "total_output_tokens": int(log.get("total_output_tokens", 0)),
        "total_cache_read_tokens": int(log.get("total_cache_read_tokens", 0)),
        "total_cache_write_tokens": int(log.get("total_cache_write_tokens", 0)),
        "total_traces": int(tr.get("total_traces", 0)),
        "total_spans": int(tr.get("total_spans", 0)),
    }


# ── Hook ingestion (unauthenticated — Claude Code hooks fire from CLI) ──


def _truncate(s: str, max_len: int = 64000) -> str:
    """Truncate a string to fit in ClickHouse without blowing up storage."""
    if len(s) <= max_len:
        return s
    return s[:max_len] + f"\n... [truncated, {len(s)} total chars]"


def _safe_json(obj: object) -> str:
    """Serialize to JSON string, falling back to str()."""
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    try:
        return json.dumps(obj, default=str)
    except Exception:
        return str(obj)


_KIRO_TO_CC_EVENT = {
    "agentSpawn": "SessionStart",
    "userPromptSubmit": "UserPromptSubmit",
    "preToolUse": "PreToolUse",
    "promptSubmit": "UserPromptSubmit",  # Kiro IDE variant
    "postToolUse": "PostToolUse",
    "stop": "Stop",
    "agentStop": "Stop",  # Kiro IDE variant
}

_KIRO_FIELD_MAP = {
    "hookEventName": "hook_event_name",
    "sessionId": "session_id",
    "toolName": "tool_name",
    "toolInput": "tool_input",
    "toolResponse": "tool_response",
    "toolUseId": "tool_use_id",
    "agentId": "agent_id",
    "agentType": "agent_type",
    "stopReason": "stop_reason",
    "permissionMode": "permission_mode",
    "lastAssistantMessage": "last_assistant_message",
    "userPrompt": "user_prompt",
}

# ── Gemini CLI event + field normalization ──
_GEMINI_TO_CC_EVENT = {
    "SessionStart": "SessionStart",
    "BeforeAgent": "SubagentStart",
    "AfterAgent": "SubagentStop",
    "BeforeTool": "PreToolUse",
    "AfterTool": "PostToolUse",
    "BeforeToolSelection": "PreToolUse",
    "AfterModel": "Stop",
    "SessionEnd": "Stop",
}

_GEMINI_FIELD_MAP = {
    "hookEventName": "hook_event_name",
    "hook_event_name": "hook_event_name",
    "sessionId": "session_id",
    "session_id": "session_id",
    "toolName": "tool_name",
    "tool_name": "tool_name",
    "toolInput": "tool_input",
    "toolResponse": "tool_response",
    "transcriptPath": "transcript_path",
    "transcript_path": "transcript_path",
}

# ── Cursor event + field normalization ──
_CURSOR_TO_CC_EVENT = {
    "preToolUse": "PreToolUse",
    "postToolUse": "PostToolUse",
    "sessionStart": "SessionStart",
    "sessionEnd": "Stop",
    "stop": "Stop",
}

_CURSOR_FIELD_MAP = {
    "hookEventName": "hook_event_name",
    "hook_event_name": "hook_event_name",
    "sessionId": "session_id",
    "session_id": "session_id",
    "toolName": "tool_name",
    "tool_name": "tool_name",
    "toolInput": "tool_input",
    "tool_input": "tool_input",
    "toolOutput": "tool_response",
    "tool_output": "tool_response",
    "toolUseId": "tool_use_id",
    "tool_use_id": "tool_use_id",
    "agentMessage": "agent_message",
    "agent_message": "agent_message",
}

# ── Copilot event + field normalization ──
_COPILOT_TO_CC_EVENT = {
    "onPreToolUse": "PreToolUse",
    "preToolUse": "PreToolUse",
    "onPostToolUse": "PostToolUse",
    "postToolUse": "PostToolUse",
    "onUserPromptSubmitted": "UserPromptSubmit",
    "userPromptSubmitted": "UserPromptSubmit",
    "onSessionStart": "SessionStart",
    "sessionStart": "SessionStart",
    "onSessionEnd": "Stop",
    "sessionEnd": "Stop",
    "onErrorOccurred": "StopFailure",
    "errorOccurred": "StopFailure",
    "subagent.started": "SubagentStart",
    "subagent.completed": "SubagentStop",
    "subagent.failed": "SubagentStop",
    "subagent.selected": "SubagentStart",
    "subagent.deselected": "SubagentStop",
}

_COPILOT_FIELD_MAP = {
    "hookEventName": "hook_event_name",
    "hook_event_name": "hook_event_name",
    "sessionId": "session_id",
    "session_id": "session_id",
    "toolName": "tool_name",
    "tool_name": "tool_name",
    "toolInput": "tool_input",
    "tool_input": "tool_input",
    "toolResponse": "tool_response",
    "tool_response": "tool_response",
    "toolCallId": "tool_use_id",
    "toolUseId": "tool_use_id",
    "tool_use_id": "tool_use_id",
    "agentName": "agent_name",
    "agentDisplayName": "agent_display_name",
    "agentDescription": "agent_description",
    "stopReason": "stop_reason",
    "userPrompt": "user_prompt",
}


# ── IDE-specific extraction helpers ──────────────────────────────────


def _extract_kiro(body: dict, hook_event: str, attrs: dict[str, str]) -> None:
    """Extract Kiro-specific fields into *attrs*.

    Kiro sends: ``prompt`` on agentSpawn/userPromptSubmit,
    ``assistant_response`` on stop, and ``tool_input``/``tool_response``
    as dicts (not strings).
    """
    tool_input_raw = body.get("tool_input")
    tool_response_raw = body.get("tool_response")

    if tool_input_raw is not None:
        attrs["tool_input"] = _truncate(_safe_json(tool_input_raw))
    if tool_response_raw is not None:
        attrs["tool_response"] = _truncate(_safe_json(tool_response_raw))

    # Kiro uses ``prompt`` for the user's message
    if body.get("prompt") and not attrs.get("tool_input"):
        attrs["tool_input"] = _truncate(str(body["prompt"]))
    # ``assistant_response`` arrives on Stop payloads
    if body.get("assistant_response") and not attrs.get("tool_response"):
        attrs["tool_response"] = _truncate(str(body["assistant_response"]))

    if hook_event == "UserPromptSubmit":
        prompt_text = body.get("prompt") or body.get("user_prompt") or ""
        if prompt_text:
            attrs["tool_input"] = _truncate(prompt_text)
            attrs["prompt_length"] = str(len(prompt_text))
        attrs["tool_name"] = "user_prompt"

    if hook_event == "SessionStart":
        prompt_text = body.get("prompt") or ""
        if prompt_text:
            attrs["tool_input"] = _truncate(prompt_text)
        attrs["event.name"] = "hook_sessionstart"

    if hook_event == "Stop":
        if body.get("stop_reason"):
            attrs["stop_reason"] = body["stop_reason"]
        # Kiro packs assistant_response into the Stop payload.
        # Keep event.name as hook_stop (lifecycle), content in tool_response.
        if body.get("assistant_response"):
            attrs["tool_response"] = _truncate(str(body["assistant_response"]))

    if hook_event == "PostToolUseFailure" and body.get("error"):
        attrs["error"] = _truncate(str(body["error"]))

    # Agent / Skill attribution from tool_input (Kiro uses same Agent/Skill
    # tool schema as Claude Code when running MCP-based agents)
    tool_name = attrs.get("tool_name", "")
    if hook_event in ("PreToolUse", "PostToolUse") and tool_input_raw:
        try:
            ti = json.loads(tool_input_raw) if isinstance(tool_input_raw, str) else tool_input_raw
        except (json.JSONDecodeError, TypeError):
            ti = None
        if isinstance(ti, dict):
            if tool_name == "Agent":
                if ti.get("subagent_type"):
                    attrs["agent_type"] = ti["subagent_type"]
                if ti.get("description"):
                    attrs["agent_name"] = ti["description"]
            elif tool_name == "Skill":
                if ti.get("skill"):
                    attrs["skill_name"] = ti["skill"]

    # Enriched fields from kiro_stop_hook.py SQLite extraction
    for enriched_field in (
        "input_tokens",
        "output_tokens",
        "turn_count",
        "credits",
        "tools_used",
        "conversation_id",
    ):
        if body.get(enriched_field):
            attrs[enriched_field] = str(body[enriched_field])


def _extract_claude_code(body: dict, hook_event: str, attrs: dict[str, str]) -> None:
    """Extract Claude Code-specific fields into *attrs*.

    Claude Code sends rich per-event payloads with ``tool_input`` /
    ``tool_response`` as strings, per-message Stop events with
    ``tool_name`` discriminators, subagent events, task tracking,
    compaction, worktrees, elicitations, and notifications.
    """
    tool_name = attrs.get("tool_name", "")
    tool_input_raw = body.get("tool_input")
    tool_response_raw = body.get("tool_response")

    if tool_input_raw is not None:
        attrs["tool_input"] = _truncate(_safe_json(tool_input_raw))
    if tool_response_raw is not None:
        attrs["tool_response"] = _truncate(_safe_json(tool_response_raw))

    # UserPromptSubmit
    if hook_event == "UserPromptSubmit":
        prompt_text = body.get("user_prompt") or body.get("prompt") or ""
        if prompt_text:
            attrs["tool_input"] = _truncate(prompt_text)
            attrs["prompt_length"] = str(len(prompt_text))
        attrs["tool_name"] = "user_prompt"

    # SessionStart
    if hook_event == "SessionStart":
        prompt_text = body.get("prompt") or ""
        if prompt_text:
            attrs["tool_input"] = _truncate(prompt_text)
        attrs["event.name"] = "hook_sessionstart"
        source = body.get("source", "")
        if source:
            attrs["session_source"] = source
        if source in ("resume", "compact") or body.get("resume"):
            attrs["session_resumed"] = "true"

    # Agent / Skill tool — extract structured metadata for attribution
    if hook_event in ("PreToolUse", "PostToolUse") and tool_input_raw:
        try:
            ti = json.loads(tool_input_raw) if isinstance(tool_input_raw, str) else tool_input_raw
        except (json.JSONDecodeError, TypeError):
            ti = None
        if isinstance(ti, dict):
            if tool_name == "Agent":
                if ti.get("subagent_type"):
                    attrs["agent_type"] = ti["subagent_type"]
                if ti.get("description"):
                    attrs["agent_name"] = ti["description"]
            elif tool_name == "Skill":
                if ti.get("skill"):
                    attrs["skill_name"] = ti["skill"]

    # SubagentStart / SubagentStop
    if hook_event == "SubagentStart" and body.get("last_assistant_message"):
        attrs["tool_input"] = _truncate(body["last_assistant_message"])
    if hook_event == "SubagentStop" and body.get("last_assistant_message"):
        attrs["tool_response"] = _truncate(body["last_assistant_message"])

    # PostToolUseFailure
    if hook_event == "PostToolUseFailure" and body.get("error"):
        attrs["error"] = _truncate(str(body["error"]))

    # Stop — Claude Code fires per-message Stop events discriminated by tool_name
    if hook_event == "Stop":
        if body.get("stop_reason"):
            attrs["stop_reason"] = body["stop_reason"]
        if tool_name == "assistant_response" and tool_response_raw:
            attrs["event.name"] = "hook_assistant_response"
        elif tool_name == "assistant_thinking" and tool_response_raw:
            attrs["event.name"] = "hook_assistant_thinking"
        if body.get("message_sequence") is not None:
            attrs["message_sequence"] = str(body["message_sequence"])
        if body.get("message_total") is not None:
            attrs["message_total"] = str(body["message_total"])

    # StopFailure
    if hook_event == "StopFailure":
        if body.get("error"):
            attrs["error"] = _truncate(str(body["error"]))
        if body.get("stop_reason"):
            attrs["stop_reason"] = body["stop_reason"]

    # Notification
    if hook_event == "Notification":
        if body.get("message"):
            attrs["tool_response"] = _truncate(str(body["message"]))
        if body.get("title"):
            attrs["notification_title"] = str(body["title"])

    # TaskCreated / TaskCompleted
    if hook_event in ("TaskCreated", "TaskCompleted"):
        for field in ("task_id", "task_subject", "task_status"):
            if body.get(field):
                attrs[field] = str(body[field])

    # PreCompact / PostCompact
    if hook_event in ("PreCompact", "PostCompact") and body.get("summary"):
        attrs["tool_response"] = _truncate(str(body["summary"]))

    # WorktreeCreate / WorktreeRemove
    if hook_event in ("WorktreeCreate", "WorktreeRemove"):
        if body.get("worktree_path"):
            attrs["worktree_path"] = str(body["worktree_path"])
        if body.get("branch"):
            attrs["branch"] = str(body["branch"])

    # Elicitation / ElicitationResult
    if hook_event in ("Elicitation", "ElicitationResult"):
        for field in ("mcp_server_name", "message", "response", "elicitation_id"):
            if body.get(field):
                key = "tool_input" if field == "message" else ("tool_response" if field == "response" else field)
                attrs[key] = _truncate(str(body[field]))


def _extract_gemini(body: dict, hook_event: str, attrs: dict[str, str]) -> None:
    """Extract Gemini CLI-specific fields into *attrs*.

    Gemini CLI hooks receive a minimal base payload (session_id, cwd,
    transcript_path, timestamp) plus an optional ``llm_request`` with
    the full message history.  BeforeAgent/AfterAgent bracket agent scope.
    """
    tool_input_raw = body.get("tool_input")
    tool_response_raw = body.get("tool_response")

    if tool_input_raw is not None:
        attrs["tool_input"] = _truncate(_safe_json(tool_input_raw))
    if tool_response_raw is not None:
        attrs["tool_response"] = _truncate(_safe_json(tool_response_raw))

    if hook_event == "SessionStart":
        attrs["event.name"] = "hook_sessionstart"

    if hook_event in ("SubagentStart", "SubagentStop") and body.get("additional_context"):
        field = "tool_input" if hook_event == "SubagentStart" else "tool_response"
        attrs[field] = _truncate(str(body["additional_context"]))

    if hook_event == "PreToolUse":
        tool_name = body.get("tool_name") or ""
        if tool_name:
            attrs["tool_name"] = tool_name
        llm_req = body.get("llm_request")
        if isinstance(llm_req, dict):
            messages = llm_req.get("messages") or []
            if messages:
                last_user = None
                for m in reversed(messages):
                    if m.get("role") == "user":
                        last_user = m
                        break
                if last_user:
                    content = last_user.get("content", "")
                    if isinstance(content, str) and not attrs.get("tool_input"):
                        attrs["tool_input"] = _truncate(content)

    if hook_event == "Stop" and body.get("stop_reason"):
        attrs["stop_reason"] = body["stop_reason"]

    if body.get("model"):
        attrs["model"] = str(body["model"])

    # Token usage from gemini_hook.py AfterModel extraction
    for enriched_field in ("input_tokens", "output_tokens", "total_tokens"):
        if body.get(enriched_field):
            attrs[enriched_field] = str(body[enriched_field])


def _extract_cursor(body: dict, hook_event: str, attrs: dict[str, str]) -> None:
    """Extract Cursor-specific fields into *attrs*.

    Cursor sends preToolUse/postToolUse via HTTP hooks with tool_input as
    an object, tool_output as a JSON string, plus ``model``, ``duration``,
    and ``agent_message``.
    """
    tool_input_raw = body.get("tool_input")
    tool_response_raw = body.get("tool_response") or body.get("tool_output")

    if tool_input_raw is not None:
        attrs["tool_input"] = _truncate(_safe_json(tool_input_raw))
    if tool_response_raw is not None:
        attrs["tool_response"] = _truncate(_safe_json(tool_response_raw))

    if hook_event == "SessionStart":
        attrs["event.name"] = "hook_sessionstart"

    if hook_event == "PreToolUse" and body.get("agent_message"):
        attrs["agent_message"] = _truncate(str(body["agent_message"]))

    if hook_event in ("PreToolUse", "PostToolUse") and body.get("duration"):
        attrs["duration_ms"] = str(body["duration"])

    if hook_event == "Stop" and body.get("stop_reason"):
        attrs["stop_reason"] = body["stop_reason"]

    if body.get("model"):
        attrs["model"] = str(body["model"])


def _extract_copilot(body: dict, hook_event: str, attrs: dict[str, str]) -> None:
    """Extract GitHub Copilot-specific fields into *attrs*.

    Copilot has full subagent support: subagent.started/completed/failed
    events carry ``agentName``, ``agentDisplayName``, ``agentDescription``.
    Tool events carry ``toolCallId`` for correlation.
    """
    tool_input_raw = body.get("tool_input")
    tool_response_raw = body.get("tool_response")

    if tool_input_raw is not None:
        attrs["tool_input"] = _truncate(_safe_json(tool_input_raw))
    if tool_response_raw is not None:
        attrs["tool_response"] = _truncate(_safe_json(tool_response_raw))

    if hook_event == "SessionStart":
        attrs["event.name"] = "hook_sessionstart"
        if body.get("source"):
            attrs["session_source"] = str(body["source"])

    if hook_event == "UserPromptSubmit":
        prompt_text = body.get("user_prompt") or body.get("prompt") or ""
        if prompt_text:
            attrs["tool_input"] = _truncate(prompt_text)
            attrs["prompt_length"] = str(len(prompt_text))
        attrs["tool_name"] = "user_prompt"

    # Subagent events carry rich agent identity
    if hook_event in ("SubagentStart", "SubagentStop"):
        if body.get("agent_name"):
            attrs["agent_name"] = body["agent_name"]
        if body.get("agent_display_name"):
            attrs["agent_name"] = body["agent_display_name"]
        if body.get("agent_description"):
            attrs["agent_type"] = body["agent_description"][:100]
        if body.get("tool_use_id"):
            attrs["tool_use_id"] = body["tool_use_id"]
        if hook_event == "SubagentStop" and body.get("error"):
            attrs["error"] = _truncate(str(body["error"]))

    if hook_event == "Stop" and (body.get("stop_reason") or body.get("reason")):
        attrs["stop_reason"] = body.get("stop_reason") or body.get("reason", "")

    if hook_event == "StopFailure" and body.get("error"):
        attrs["error"] = _truncate(str(body["error"]))

    if body.get("model"):
        attrs["model"] = str(body["model"])


@router.post("/hooks")
async def ingest_hook(request: Request):
    """Ingest hook events from IDE agents and store in otel_logs.

    Supports Claude Code, Kiro, Gemini CLI, Cursor, and GitHub Copilot.
    Each IDE's camelCase fields and event names are normalized to a
    canonical snake_case/PascalCase schema before storage.

    Intentionally unauthenticated — CLI hooks can't easily carry auth tokens.
    Supports ECIES-encrypted payloads via the ``X-Observal-Encrypted`` header.
    """
    encrypted_header = request.headers.get("X-Observal-Encrypted")
    if encrypted_header == "ecies-p256":
        raw_body = await request.body()
        from services.crypto import get_key_manager

        km = get_key_manager()
        decrypted_json = km.decrypt_payload(raw_body)
        body = json.loads(decrypted_json)
    else:
        body = await request.json()
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    # ── Detect IDE early so we pick the right normalization maps ──
    raw_service = body.get("service_name") or body.get("serviceName") or "claude-code"
    service_name = _SERVICE_NAME_MAP.get(raw_service, raw_service)

    # ── Normalize camelCase fields to snake_case (per-IDE map) ──
    field_map = {
        "kiro": _KIRO_FIELD_MAP,
        "gemini": _GEMINI_FIELD_MAP,
        "cursor": _CURSOR_FIELD_MAP,
        "copilot": _COPILOT_FIELD_MAP,
    }.get(service_name, _KIRO_FIELD_MAP)
    normalized: dict = {}
    for key, value in body.items():
        normalized[field_map.get(key, key)] = value
    body = normalized

    # ── Normalize event names to canonical PascalCase (per-IDE map) ──
    raw_event = body.get("hook_event_name", "unknown")
    event_map = {
        "kiro": _KIRO_TO_CC_EVENT,
        "gemini": _GEMINI_TO_CC_EVENT,
        "cursor": _CURSOR_TO_CC_EVENT,
        "copilot": _COPILOT_TO_CC_EVENT,
    }.get(service_name, {})
    hook_event = event_map.get(raw_event, raw_event)

    # Kiro/Cursor postToolUse with tool_response.success=false → PostToolUseFailure
    if hook_event == "PostToolUse":
        tool_resp = body.get("tool_response")
        if isinstance(tool_resp, dict) and tool_resp.get("success") is False:
            hook_event = "PostToolUseFailure"
            result = tool_resp.get("result", "")
            if result and not body.get("error"):
                body["error"] = _truncate(str(result))

    body["hook_event_name"] = hook_event

    session_id = body.get("session_id", "")
    tool_name = body.get("tool_name", "")

    # ── Kiro IDE session correlation ──
    # $PPID differs per hook invocation in IDE context. Correlate by cwd.
    cwd = body.get("cwd", "")
    is_kiro = service_name == "kiro"
    is_kiro_ppid = bool(re.match(r"^kiro-\d+$", session_id))

    # Fallback: if a Kiro event arrives with no session_id, synthesize one from cwd
    if is_kiro and not session_id and cwd:
        import hashlib

        session_id = f"kiro-{hashlib.sha256(cwd.encode()).hexdigest()[:12]}"
        is_kiro_ppid = True  # treat it like a PPID session for caching below

    if is_kiro_ppid and cwd:
        now_ts = _time.monotonic()
        cached = _kiro_session_cache.get(cwd)
        if cached and (now_ts - cached[1]) < _KIRO_SESSION_WINDOW:
            session_id = cached[0]
        else:
            _kiro_session_cache[cwd] = (session_id, now_ts)
        body["session_id"] = session_id

    # Build the attributes map that the frontend already reads
    attrs: dict[str, str] = {
        "session.id": session_id,
        "event.name": f"hook_{hook_event.lower()}",
        "hook_event": hook_event,
        "tool_name": tool_name,
        "source": "hook",
    }

    # ── Agent attribution ──
    if body.get("agent_id"):
        attrs["agent_id"] = body["agent_id"]
    if body.get("agent_type"):
        attrs["agent_type"] = body["agent_type"]
    if body.get("agent_name"):
        attrs["agent_name"] = body["agent_name"]
    if body.get("model"):
        attrs["model"] = body["model"]

    # ── User identity (from Observal login, injected by CLI) ──
    # Kiro: user_id in body (via sed injection)
    # Claude Code: X-Observal-User-Id header (via HTTP hook header)
    # Claude Code also sends native user.id in some events
    # Note: this endpoint is unauthenticated, so these values are
    # self-reported. The /sessions endpoint resolves canonical names
    # from PostgreSQL, so hook-supplied names are only a fallback.
    user_id = body.get("user_id") or request.headers.get("x-observal-user-id") or ""
    if user_id:
        attrs["user.id"] = user_id

    user_name = body.get("user_name") or request.headers.get("x-observal-username") or ""
    if user_name:
        attrs["user.name"] = user_name

    # ── IDE-specific extraction ──
    _ide_extractors = {
        "kiro": _extract_kiro,
        "gemini": _extract_gemini,
        "cursor": _extract_cursor,
        "copilot": _extract_copilot,
    }
    extractor = _ide_extractors.get(service_name, _extract_claude_code)
    extractor(body, hook_event, attrs)

    # Extra context fields (present on most events, all IDEs)
    if body.get("tool_use_id"):
        attrs["tool_use_id"] = body["tool_use_id"]
    if body.get("cwd"):
        attrs["cwd"] = body["cwd"]
    if body.get("permission_mode"):
        attrs["permission_mode"] = body["permission_mode"]

    # Build the Body as a readable summary
    agent_prefix = f"[{attrs.get('agent_type', '')}] " if attrs.get("agent_id") else ""
    if hook_event in ("PostToolUse", "PreToolUse"):
        body_text = f"{agent_prefix}{hook_event}: {tool_name}"
    elif hook_event == "PostToolUseFailure":
        body_text = f"{agent_prefix}ToolFailure: {tool_name}"
    elif hook_event == "UserPromptSubmit":
        prompt_preview = (attrs.get("tool_input") or "")[:100]
        body_text = f"Prompt: {prompt_preview}"
    elif hook_event in ("SubagentStop", "SubagentStart"):
        body_text = f"{hook_event}: {attrs.get('agent_type', 'unknown')}"
    elif hook_event in ("Elicitation", "ElicitationResult"):
        body_text = f"{hook_event}: {body.get('mcp_server_name', 'unknown')}"
    elif hook_event == "Stop" and tool_name == "assistant_thinking":
        seq = attrs.get("message_sequence", "")
        total = attrs.get("message_total", "")
        seq_label = f" [{seq}/{total}]" if seq and total else ""
        preview = (attrs.get("tool_response") or "")[:100]
        body_text = f"Thinking{seq_label}: {preview}"
    elif hook_event == "Stop" and (tool_name == "assistant_response" or body.get("assistant_response")):
        seq = attrs.get("message_sequence", "")
        total = attrs.get("message_total", "")
        seq_label = f" [{seq}/{total}]" if seq and total else ""
        preview = (attrs.get("tool_response") or "")[:100]
        body_text = f"Response{seq_label}: {preview}"
    elif hook_event == "Stop":
        body_text = f"Stop: {body.get('stop_reason', 'end_turn')}"
    elif hook_event == "StopFailure":
        body_text = f"StopFailure: {attrs.get('error', 'unknown')[:80]}"
    elif hook_event == "SessionStart":
        source_label = ""
        if attrs.get("session_source") == "compact":
            source_label = " (continued)"
        elif attrs.get("session_resumed") == "true":
            source_label = " (resumed)"
        prompt_preview = (attrs.get("tool_input") or "")[:100]
        body_text = f"SessionStart{source_label}: {prompt_preview}" if prompt_preview else f"SessionStart{source_label}"
    elif hook_event == "Notification":
        body_text = f"Notification: {attrs.get('notification_title', '')}"
    elif hook_event in ("TaskCreated", "TaskCompleted"):
        body_text = f"{hook_event}: {attrs.get('task_subject', '')[:60]}"
    elif hook_event in ("PreCompact", "PostCompact"):
        body_text = f"{hook_event}"
    elif hook_event in ("WorktreeCreate", "WorktreeRemove"):
        body_text = f"{hook_event}: {attrs.get('branch', '')}"
    else:
        body_text = f"{agent_prefix}hook: {hook_event}"

    # ── Redact secrets from user-content fields before storage ──
    for _redact_field in ("tool_input", "tool_response", "error"):
        if _redact_field in attrs:
            attrs[_redact_field] = redact_secrets(attrs[_redact_field])
    body_text = redact_secrets(body_text)

    # INSERT into otel_logs using JSONEachRow (safe against injection)
    # Note: The otel_logs table is created by the OTEL collector with its
    # standard schema — there is no EventName column.  Event names live in
    # LogAttributes['event.name'] (already set above).
    row = {
        "Timestamp": now,
        "Body": body_text,
        "LogAttributes": attrs,
        "ServiceName": service_name,
        "SeverityText": "INFO",
        "SeverityNumber": 9,
    }
    sql = "INSERT INTO otel_logs (Timestamp, Body, LogAttributes, ServiceName, SeverityText, SeverityNumber) FORMAT JSONEachRow"

    try:
        r = await _query(sql, data=json.dumps(row, default=str))
        if r.status_code != 200:
            logger.warning("hook_insert_failed", status_code=r.status_code, response=r.text[:200])
            return {"ingested": 0, "error": "insert failed"}
    except Exception as e:
        logger.warning("hook_insert_failed", error=str(e))
        return {"ingested": 0, "error": str(e)}

    # Notify subscribers (fire-and-forget — don't block the response)
    if session_id:
        task = asyncio.create_task(publish("sessions:updated", {"session_id": session_id, "event_name": hook_event}))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

    return {"ingested": 1, "session_id": session_id, "event": hook_event}
