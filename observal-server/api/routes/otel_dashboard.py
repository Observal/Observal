import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Request

from api.deps import get_current_user
from models.user import User
from services.clickhouse import _query
from services.secrets_redactor import redact_secrets

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/otel", tags=["otel-dashboard"])


async def _ch_json(sql: str, params: dict | None = None) -> list[dict]:
    try:
        r = await _query(f"{sql} FORMAT JSON", params)
        if r.status_code == 200:
            return r.json().get("data", [])
    except Exception as e:
        logger.warning(f"ClickHouse query failed: {e}")
    return []


@router.get("/sessions")
async def list_sessions(
    status: str | None = Query(None),
    current_user: User = Depends(get_current_user),
):
    rows = await _ch_json(
        "SELECT "
        # For Kiro sessions with a conversation_id, group by that instead of
        # the ephemeral $PPID-based session_id.  This merges resumed sessions.
        "if(LogAttributes['conversation_id'] != '', "
        "   LogAttributes['conversation_id'], "
        "   LogAttributes['session.id']) AS session_id, "
        "min(Timestamp) AS first_event_time, "
        "max(Timestamp) AS last_event_time, "
        "(max(Timestamp) > now('UTC') - INTERVAL 30 MINUTE "
        " AND argMax("
        "   if(LogAttributes['event.name'] != '', LogAttributes['event.name'], EventName),"
        "   Timestamp"
        " ) NOT IN ('hook_stop', 'hook_stopfailure')"
        ") AS is_active, "
        "countIf(EventName = 'user_prompt' OR LogAttributes['event.name'] = 'user_prompt' OR LogAttributes['event.name'] = 'hook_userpromptsubmit') AS prompt_count, "
        "countIf(LogAttributes['event.name'] = 'api_request') AS api_request_count, "
        "countIf(LogAttributes['event.name'] = 'tool_result') AS tool_result_count, "
        "countIf(LogAttributes['event.name'] LIKE 'hook_%') AS hook_event_count, "
        "sum(toUInt64OrZero(LogAttributes['input_tokens'])) AS total_input_tokens, "
        "sum(toUInt64OrZero(LogAttributes['output_tokens'])) AS total_output_tokens, "
        "sum(toUInt64OrZero(LogAttributes['cache_read_tokens'])) AS total_cache_read_tokens, "
        "anyIf(LogAttributes['model'], LogAttributes['model'] != '') AS model, "
        "anyIf(LogAttributes['user.id'], LogAttributes['user.id'] != '') AS user_id, "
        "anyIf(LogAttributes['terminal.type'], LogAttributes['terminal.type'] != '') AS terminal_type, "
        "anyIf(LogAttributes['credits'], LogAttributes['credits'] != '') AS credits, "
        "anyIf(LogAttributes['tools_used'], LogAttributes['tools_used'] != '') AS tools_used, "
        "any(ServiceName) AS service_name "
        "FROM otel_logs "
        "WHERE LogAttributes['session.id'] != '' "
        "GROUP BY session_id "
        "ORDER BY last_event_time DESC "
        "LIMIT 100"
    )
    for row in rows:
        row["is_active"] = bool(int(row.get("is_active", 0)))
    if status == "active":
        rows = [r for r in rows if r["is_active"]]
    return rows


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, current_user: User = Depends(get_current_user)):
    events = await _ch_json(
        "SELECT "
        "Timestamp AS timestamp, "
        "if(LogAttributes['event.name'] != '', LogAttributes['event.name'], EventName) AS event_name, "
        "Body AS body, "
        "LogAttributes AS attributes, "
        "ServiceName AS service_name "
        "FROM otel_logs "
        "WHERE (LogAttributes['session.id'] = {sid:String} OR LogAttributes['conversation_id'] = {sid:String}) "
        "ORDER BY Timestamp ASC",
        {"param_sid": session_id},
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
    svc = events[0]["service_name"] if events else ""
    return {"session_id": session_id, "service_name": svc, "events": events, "traces": traces}


@router.get("/traces")
async def list_traces(current_user: User = Depends(get_current_user)):
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
    return rows


@router.get("/traces/{trace_id}")
async def get_trace(trace_id: str, current_user: User = Depends(get_current_user)):
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
    return spans


@router.get("/errors")
async def list_errors(current_user: User = Depends(get_current_user)):
    """List recent error events (tool failures, stop failures, API errors)."""
    rows = await _ch_json(
        "SELECT "
        "Timestamp AS timestamp, "
        "if(LogAttributes['event.name'] != '', LogAttributes['event.name'], EventName) AS event_name, "
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
        "OR EventName = 'api_error' "
        "ORDER BY Timestamp DESC "
        "LIMIT 200"
    )
    return rows


@router.get("/stats")
async def otel_stats(current_user: User = Depends(get_current_user)):
    log_rows = await _ch_json(
        "SELECT "
        "count(DISTINCT LogAttributes['session.id']) AS total_sessions, "
        "countIf(EventName = 'user_prompt' OR LogAttributes['event.name'] = 'user_prompt' OR LogAttributes['event.name'] = 'hook_userpromptsubmit') AS total_prompts, "
        "countIf(LogAttributes['event.name'] = 'api_request') AS total_api_requests, "
        "countIf(LogAttributes['event.name'] = 'tool_result') AS total_tool_calls, "
        "sum(toUInt64OrZero(LogAttributes['input_tokens'])) AS total_input_tokens, "
        "sum(toUInt64OrZero(LogAttributes['output_tokens'])) AS total_output_tokens "
        "FROM otel_logs"
    )
    trace_rows = await _ch_json(
        "SELECT count(DISTINCT TraceId) AS total_traces, count() AS total_spans FROM otel_traces"
    )
    log = log_rows[0] if log_rows else {}
    tr = trace_rows[0] if trace_rows else {}
    return {
        "total_sessions": int(log.get("total_sessions", 0)),
        "total_prompts": int(log.get("total_prompts", 0)),
        "total_api_requests": int(log.get("total_api_requests", 0)),
        "total_tool_calls": int(log.get("total_tool_calls", 0)),
        "total_input_tokens": int(log.get("total_input_tokens", 0)),
        "total_output_tokens": int(log.get("total_output_tokens", 0)),
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
    "postToolUse": "PostToolUse",
    "stop": "Stop",
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


@router.post("/hooks")
async def ingest_hook(request: Request):
    """Ingest hook events from Claude Code / Kiro and store in otel_logs.

    This is intentionally unauthenticated because CLI hooks fire
    from the terminal and can't easily carry auth tokens.  The endpoint only
    writes to ClickHouse — no destructive operations.
    """
    body = await request.json()
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    # ── Normalize Kiro camelCase fields to snake_case ──
    normalized: dict = {}
    for key, value in body.items():
        normalized[_KIRO_FIELD_MAP.get(key, key)] = value
    body = normalized

    # ── Normalize Kiro camelCase event names to PascalCase ──
    raw_event = body.get("hook_event_name", "unknown")
    hook_event = _KIRO_TO_CC_EVENT.get(raw_event, raw_event)
    body["hook_event_name"] = hook_event

    session_id = body.get("session_id", "")
    tool_name = body.get("tool_name", "")
    service_name = body.get("service_name", "observal-hooks")

    # Build the attributes map that the frontend already reads
    attrs: dict[str, str] = {
        "session.id": session_id,
        "event.name": f"hook_{hook_event.lower()}",
        "hook_event": hook_event,
        "tool_name": tool_name,
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
    user_id = body.get("user_id") or request.headers.get("x-observal-user-id") or ""
    if user_id:
        attrs["user.id"] = user_id

    # Capture full content — this is the Langfuse-equivalent visibility
    tool_input_raw = body.get("tool_input")
    tool_response_raw = body.get("tool_response")

    if tool_input_raw is not None:
        attrs["tool_input"] = _truncate(_safe_json(tool_input_raw))
    if tool_response_raw is not None:
        attrs["tool_response"] = _truncate(_safe_json(tool_response_raw))

    # ── Kiro-specific field extraction ──
    # Kiro sends `prompt` on agentSpawn/userPromptSubmit,
    # `assistant_response` on stop, and tool_input/tool_response as dicts.
    if body.get("prompt") and not attrs.get("tool_input"):
        attrs["tool_input"] = _truncate(str(body["prompt"]))
    if body.get("assistant_response") and not attrs.get("tool_response"):
        attrs["tool_response"] = _truncate(str(body["assistant_response"]))
        attrs["event.name"] = "hook_assistant_response"

    # UserPromptSubmit — capture the actual user prompt
    if hook_event == "UserPromptSubmit":
        prompt_text = body.get("prompt") or body.get("user_prompt") or ""
        if prompt_text:
            attrs["tool_input"] = _truncate(prompt_text)
            attrs["prompt_length"] = str(len(prompt_text))
        attrs["tool_name"] = "user_prompt"
        # Keep as hook_userpromptsubmit — the frontend uses this to start
        # new turns. "user_prompt" gets deduped away when hooks are present.

    # SessionStart / agentSpawn — capture initial prompt and mark as session start
    if hook_event == "SessionStart":
        prompt_text = body.get("prompt") or ""
        if prompt_text:
            attrs["tool_input"] = _truncate(prompt_text)
        attrs["event.name"] = "hook_sessionstart"

    # SubagentStart — capture agent spawn
    if hook_event == "SubagentStart" and body.get("last_assistant_message"):
        attrs["tool_input"] = _truncate(body["last_assistant_message"])

    # SubagentStop — capture agent final output
    if hook_event == "SubagentStop" and body.get("last_assistant_message"):
        attrs["tool_response"] = _truncate(body["last_assistant_message"])

    # PostToolUseFailure — tool failure (critical for debugging)
    if hook_event == "PostToolUseFailure" and body.get("error"):
        attrs["error"] = _truncate(str(body["error"]))

    # Stop — session/turn end (command hook sends assistant response text)
    if hook_event == "Stop":
        if body.get("stop_reason"):
            attrs["stop_reason"] = body["stop_reason"]
        # Kiro sends assistant_response directly; Claude Code sends via tool_response
        if body.get("assistant_response"):
            attrs["tool_response"] = _truncate(str(body["assistant_response"]))
            attrs["event.name"] = "hook_assistant_response"
        elif tool_name == "assistant_response" and tool_response_raw:
            attrs["event.name"] = "hook_assistant_response"
        # Sequence metadata for interleaving with tool calls
        if body.get("message_sequence") is not None:
            attrs["message_sequence"] = str(body["message_sequence"])
        if body.get("message_total") is not None:
            attrs["message_total"] = str(body["message_total"])

    # StopFailure — API error on turn end
    if hook_event == "StopFailure":
        if body.get("error"):
            attrs["error"] = _truncate(str(body["error"]))
        if body.get("stop_reason"):
            attrs["stop_reason"] = body["stop_reason"]

    # SessionStart — session lifecycle
    if hook_event == "SessionStart" and body.get("resume"):
        attrs["session_resumed"] = str(body["resume"])

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

    # PreCompact / PostCompact — context compaction
    if hook_event in ("PreCompact", "PostCompact") and body.get("summary"):
        attrs["tool_response"] = _truncate(str(body["summary"]))

    # WorktreeCreate / WorktreeRemove
    if hook_event in ("WorktreeCreate", "WorktreeRemove"):
        if body.get("worktree_path"):
            attrs["worktree_path"] = str(body["worktree_path"])
        if body.get("branch"):
            attrs["branch"] = str(body["branch"])

    # Elicitation / ElicitationResult — MCP server interactions
    if hook_event in ("Elicitation", "ElicitationResult"):
        for field in ("mcp_server_name", "message", "response", "elicitation_id"):
            if body.get(field):
                key = "tool_input" if field == "message" else ("tool_response" if field == "response" else field)
                attrs[key] = _truncate(str(body[field]))

    # Extra context fields (present on most events)
    if body.get("tool_use_id"):
        attrs["tool_use_id"] = body["tool_use_id"]
    if body.get("cwd"):
        attrs["cwd"] = body["cwd"]
    if body.get("permission_mode"):
        attrs["permission_mode"] = body["permission_mode"]

    # ── Enriched fields from Kiro SQLite DB (sent by kiro_stop_hook.py) ──
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
        resumed = " (resumed)" if attrs.get("session_resumed") == "True" else ""
        prompt_preview = (attrs.get("tool_input") or "")[:100]
        body_text = f"SessionStart{resumed}: {prompt_preview}" if prompt_preview else f"SessionStart{resumed}"
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

    # Event name for the EventName column (used by list_sessions countIf)
    event_name = attrs.get("event.name", f"hook_{hook_event.lower()}")

    # ── Redact secrets from user-content fields before storage ──
    for _redact_field in ("tool_input", "tool_response", "error"):
        if _redact_field in attrs:
            attrs[_redact_field] = redact_secrets(attrs[_redact_field])
    body_text = redact_secrets(body_text)

    # INSERT into otel_logs using JSONEachRow (safe against injection)
    row = {
        "Timestamp": now,
        "EventName": event_name,
        "Body": body_text,
        "LogAttributes": attrs,
        "ServiceName": service_name,
        "SeverityText": "INFO",
        "SeverityNumber": 9,
    }
    sql = "INSERT INTO otel_logs (Timestamp, EventName, Body, LogAttributes, ServiceName, SeverityText, SeverityNumber) FORMAT JSONEachRow"

    try:
        r = await _query(sql, data=json.dumps(row, default=str))
        if r.status_code != 200:
            logger.warning(f"Hook insert failed: {r.status_code} {r.text[:200]}")
            return {"ingested": 0, "error": "insert failed"}
    except Exception as e:
        logger.warning(f"Hook insert failed: {e}")
        return {"ingested": 0, "error": str(e)}

    return {"ingested": 1, "session_id": session_id, "event": hook_event}
