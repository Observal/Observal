import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Request

from services.clickhouse import _escape, _map_literal, _query

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
async def list_sessions():
    rows = await _ch_json(
        "SELECT "
        "LogAttributes['session.id'] AS session_id, "
        "min(Timestamp) AS first_event_time, "
        "max(Timestamp) AS last_event_time, "
        "countIf(EventName = 'user_prompt' OR LogAttributes['event.name'] = 'user_prompt') AS prompt_count, "
        "countIf(LogAttributes['event.name'] = 'api_request') AS api_request_count, "
        "countIf(LogAttributes['event.name'] = 'tool_result') AS tool_result_count, "
        "countIf(LogAttributes['event.name'] LIKE 'hook_%') AS hook_event_count, "
        "sum(toUInt64OrZero(LogAttributes['input_tokens'])) AS total_input_tokens, "
        "sum(toUInt64OrZero(LogAttributes['output_tokens'])) AS total_output_tokens, "
        "sum(toUInt64OrZero(LogAttributes['cache_read_tokens'])) AS total_cache_read_tokens, "
        "anyIf(LogAttributes['model'], LogAttributes['model'] != '') AS model, "
        "any(ServiceName) AS service_name "
        "FROM otel_logs "
        "WHERE LogAttributes['session.id'] != '' "
        "GROUP BY session_id "
        "ORDER BY last_event_time DESC "
        "LIMIT 100"
    )
    return rows


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    sid = _escape(session_id)
    events = await _ch_json(
        "SELECT "
        "Timestamp AS timestamp, "
        "if(LogAttributes['event.name'] != '', LogAttributes['event.name'], EventName) AS event_name, "
        "Body AS body, "
        "LogAttributes AS attributes, "
        "ServiceName AS service_name "
        f"FROM otel_logs "
        f"WHERE LogAttributes['session.id'] = '{sid}' "
        "ORDER BY Timestamp ASC"
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
        f"FROM otel_traces "
        f"WHERE SpanAttributes['session.id'] = '{sid}' "
        "ORDER BY Timestamp ASC"
    )
    svc = events[0]["service_name"] if events else ""
    return {"session_id": session_id, "service_name": svc, "events": events, "traces": traces}


@router.get("/traces")
async def list_traces():
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
async def get_trace(trace_id: str):
    tid = _escape(trace_id)
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
        f"FROM otel_traces "
        f"WHERE TraceId = '{tid}' "
        "ORDER BY Timestamp ASC"
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


@router.get("/stats")
async def otel_stats():
    log_rows = await _ch_json(
        "SELECT "
        "count(DISTINCT LogAttributes['session.id']) AS total_sessions, "
        "countIf(EventName = 'user_prompt' OR LogAttributes['event.name'] = 'user_prompt') AS total_prompts, "
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


@router.post("/hooks")
async def ingest_hook(request: Request):
    """Ingest hook events from Claude Code and store in otel_logs.

    This is intentionally unauthenticated because Claude Code hooks fire
    from the CLI and can't easily carry auth tokens.  The endpoint only
    writes to ClickHouse — no destructive operations.
    """
    body = await request.json()
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    hook_event = body.get("hook_event_name", "unknown")
    session_id = body.get("session_id", "")
    tool_name = body.get("tool_name", "")

    # Build the attributes map that the frontend already reads
    attrs: dict[str, str] = {
        "session.id": session_id,
        "event.name": f"hook_{hook_event.lower()}",
        "hook_event": hook_event,
        "tool_name": tool_name,
    }

    # ── Agent attribution (present on ALL events fired within a subagent) ──
    if body.get("agent_id"):
        attrs["agent_id"] = body["agent_id"]
    if body.get("agent_type"):
        attrs["agent_type"] = body["agent_type"]

    # Capture full content — this is the Langfuse-equivalent visibility
    tool_input_raw = body.get("tool_input")
    tool_response_raw = body.get("tool_response")

    if tool_input_raw is not None:
        attrs["tool_input"] = _truncate(_safe_json(tool_input_raw))
    if tool_response_raw is not None:
        attrs["tool_response"] = _truncate(_safe_json(tool_response_raw))

    # UserPromptSubmit — capture the actual user prompt
    if hook_event == "UserPromptSubmit":
        prompt_text = body.get("prompt") or body.get("user_prompt") or ""
        if prompt_text:
            attrs["tool_input"] = _truncate(prompt_text)
            attrs["prompt_length"] = str(len(prompt_text))
        attrs["tool_name"] = "user_prompt"

    # SubagentStart — capture agent spawn
    if hook_event == "SubagentStart":
        if body.get("last_assistant_message"):
            attrs["tool_input"] = _truncate(body["last_assistant_message"])

    # SubagentStop — capture agent final output
    if hook_event == "SubagentStop":
        if body.get("last_assistant_message"):
            attrs["tool_response"] = _truncate(body["last_assistant_message"])

    # PostToolUseFailure — tool failure (critical for debugging)
    if hook_event == "PostToolUseFailure":
        if body.get("error"):
            attrs["error"] = _truncate(str(body["error"]))

    # Stop — session/turn end (command hook sends assistant response text)
    if hook_event == "Stop":
        if body.get("stop_reason"):
            attrs["stop_reason"] = body["stop_reason"]
        # If the stop hook captured Claude's response, mark it clearly
        if tool_name == "assistant_response" and tool_response_raw:
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
    if hook_event == "SessionStart":
        if body.get("resume"):
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
    if hook_event in ("PreCompact", "PostCompact"):
        if body.get("summary"):
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
    elif hook_event == "Stop" and tool_name == "assistant_response":
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
        body_text = f"SessionStart{resumed}"
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

    # INSERT into otel_logs
    attr_map = _map_literal(attrs)
    sql = (
        "INSERT INTO otel_logs "
        "(Timestamp, EventName, Body, LogAttributes, ServiceName, "
        "SeverityText, SeverityNumber) VALUES "
        f"('{_escape(now)}', '{_escape(event_name)}', "
        f"'{_escape(body_text)}', {attr_map}, "
        f"'observal-hooks', 'INFO', 9)"
    )

    try:
        r = await _query(sql)
        if r.status_code != 200:
            logger.warning(f"Hook insert failed: {r.status_code} {r.text[:200]}")
            return {"ingested": 0, "error": "insert failed"}
    except Exception as e:
        logger.warning(f"Hook insert failed: {e}")
        return {"ingested": 0, "error": str(e)}

    return {"ingested": 1, "session_id": session_id, "event": hook_event}
