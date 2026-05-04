import json
import logging
import uuid as _uuid

from fastapi import APIRouter, Depends, Query
from fastapi_cache.decorator import cache
from sqlalchemy import or_, select

from api.deps import require_role
from config import settings
from database import async_session
from models.user import User, UserRole
from services.audit_helpers import audit
from services.clickhouse import _query, query_shim_spans_for_window

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])

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
        logger.warning("clickhouse_query_failed: %s", e)
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
        "  any(ServiceName) IN ('kiro', 'kiro-cli'), 'kiro',"
        "  any(ServiceName) IN ('gemini', 'gemini-cli'), 'gemini',"
        "  any(ServiceName) IN ('copilot', 'copilot-cli', 'github-copilot'), 'copilot',"
        "  any(ServiceName) IN ('cursor', 'cursor-cli'), 'cursor',"
        "  any(ServiceName) IN ('claude-code', 'observal-hooks', 'observal-shim'), 'claude-code',"
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


@router.get("/summary")
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


def _collapse_trace_events(events: list[dict]) -> list[dict]:
    """Collapse duplicate tool-call events from hook + OTLP + reconcile sources.

    The raw otel_logs event format uses `timestamp` and an `attributes` dict
    with `event.name` and `tool_name`.  This bridges that shape to
    collapse_duplicate_tool_spans which expects materialized span dicts.

    Non-tool events (reconcile_enrichment, session_start, user_prompt, etc.)
    pass through unchanged.  Only tool-call events within a 2-second window
    sharing the same tool_name are collapsed.
    """
    from services.insights.trace_dedup import collapse_duplicate_tool_spans

    tool_call_events = frozenset(
        {
            "hook_posttooluse",
            "hook_posttoolusefailure",
            "hook_pretooluse",
            "shim_tool_call",
            "tool_result",
        }
    )

    # Split into tool-call events (candidates for collapse) and everything else
    tool_events: list[dict] = []
    other_events: list[dict] = []

    for e in events:
        attrs = e.get("attributes", {})
        if isinstance(attrs, str):
            try:
                attrs = json.loads(attrs)
            except Exception:
                attrs = {}
        event_name = attrs.get("event.name", e.get("event_name", ""))
        if event_name in tool_call_events:
            tool_events.append(e)
        else:
            other_events.append(e)

    if not tool_events:
        return events

    # Translate otel_logs events to span-shaped dicts for collapse_duplicate_tool_spans
    def _to_span(e: dict) -> dict:
        attrs = e.get("attributes", {})
        if isinstance(attrs, str):
            try:
                attrs = json.loads(attrs)
            except Exception:
                attrs = {}
        return {
            "_original": e,
            "type": "tool_call",
            "name": attrs.get("tool_name") or "",
            "start_time": e.get("timestamp", ""),
            "tool_input": attrs.get("tool_input", ""),
            "tool_response": attrs.get("tool_response", ""),
            "error": attrs.get("error", ""),
            "model": attrs.get("model", ""),
            "input_tokens": int(attrs.get("input_tokens", 0) or 0),
            "output_tokens": int(attrs.get("output_tokens", 0) or 0),
            "source": attrs.get("source", ""),
        }

    def _from_span(span: dict) -> dict:
        """Reconstruct an otel_logs event from a collapsed span."""
        original = span.pop("_original", None)
        if original is None:
            return span
        # Merge enriched fields back into the original event's attributes
        original = dict(original)
        attrs = original.get("attributes", {})
        if isinstance(attrs, str):
            try:
                attrs = json.loads(attrs)
            except Exception:
                attrs = {}
        else:
            attrs = dict(attrs)

        for field in ("tool_input", "tool_response", "error", "model"):
            if span.get(field):
                attrs[field] = span[field]
        for field in ("input_tokens", "output_tokens"):
            if span.get(field):
                attrs[field] = str(span[field])

        original["attributes"] = attrs
        return original

    spans = [_to_span(e) for e in tool_events]
    collapsed = collapse_duplicate_tool_spans(spans)
    collapsed_events = [_from_span(s) for s in collapsed]

    all_events = collapsed_events + other_events
    all_events.sort(key=lambda e: e.get("timestamp", ""))
    return all_events


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
async def sessions_stats(current_user: User = Depends(require_role(UserRole.admin))):
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


@router.get("/{session_id}")
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
    # Collapse duplicate tool spans so the trace viewer shows one row per tool call
    # (hook + OTLP + reconcile may each record the same tool invocation)
    events = _collapse_trace_events(events)
    svc = _normalize_service(events[0]["service_name"]) if events else ""
    await audit(current_user, "session.view", "session", resource_id=session_id)
    return {"session_id": session_id, "service_name": svc, "events": events, "traces": traces}


@router.get("/{session_id}/efficiency")
async def get_session_efficiency(session_id: str, current_user: User = Depends(require_role(UserRole.user))):
    """Run kernel efficiency analysis on a session's hook events."""
    if not session_id or not session_id.strip():
        return {"error": "No session ID provided"}

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

    # Try querying by session.id first
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

    # If no events found, try querying by TraceId (for evaluation traces)
    if not events:
        events = await _ch_json(
            "SELECT "
            "Timestamp AS timestamp, "
            "LogAttributes['event.name'] AS event_name, "
            "Body AS body, "
            "LogAttributes AS attributes, "
            "ServiceName AS service_name "
            "FROM otel_logs "
            "WHERE TraceId = {sid:String} "
            "AND (LogAttributes['user.id'] = {uid:String} "
            "     OR LogAttributes['user.id'] = {uemail:String}) "
            "ORDER BY Timestamp ASC",
            params,
        )

    if not events:
        return {"error": "No events found for session", "session_id": session_id}

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
    """Explicitly bind a session to an agent name.

    Overrides any cached attribution.  Used when frontmatter hooks are
    unavailable or when the wrong agent was initially attributed.
    """
    is_admin = _is_admin_user(current_user)
    if not is_admin:
        params = {"param_sid": session_id, "param_uid": str(current_user.id), "param_uemail": current_user.email}
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

    from redis.exceptions import RedisError

    from services.redis import get_redis

    try:
        redis = get_redis()
        await redis.set(f"session_agent:{session_id}", agent_name, ex=86400)
    except RedisError:
        return {"session_id": session_id, "agent_name": agent_name, "bound": False, "error": "Redis unavailable"}

    await audit(current_user, "session.bind_agent", "session", resource_id=session_id, detail=f"Bound to {agent_name}")
    return {"session_id": session_id, "agent_name": agent_name, "bound": True}
