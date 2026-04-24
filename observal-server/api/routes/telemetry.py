import asyncio
import json
import logging
import re
import time as _time
import uuid
from datetime import UTC, datetime

import jwt
from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy import select

from api.deps import get_project_id, require_role
from database import async_session
from models.user import User, UserRole
from schemas.telemetry import (
    IngestBatch,
    IngestResponse,
    TelemetryStatusResponse,
)
from services.clickhouse import (
    _query,
    insert_otel_logs,
    insert_scores,
    insert_spans,
    insert_traces,
    query_recent_events,
)
from services.jwt_service import decode_access_token
from services.redis import publish
from services.secrets_redactor import get_and_reset_redaction_count, redact_secrets
from services.security_events import (
    EventType,
    SecurityEvent,
    Severity,
    emit_security_event,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/telemetry", tags=["telemetry"])
otlp_router = APIRouter(prefix="", tags=["otlp"])

# Background tasks that must survive until completion (prevent GC)
_background_tasks: set[asyncio.Task] = set()

# ── Service name normalization ──
# Normalize legacy ServiceName values to canonical IDE names.
_SERVICE_NAME_MAP: dict[str, str] = {
    "kiro-cli": "kiro",
    "observal-hooks": "claude-code",
    "observal-shim": "claude-code",
    "copilot-cli": "copilot",
    "github-copilot": "copilot",
    "gemini-cli": "gemini",
    "cursor-cli": "cursor",
}

# ── Kiro IDE session correlation ──
_kiro_session_cache: dict[str, tuple[str, float]] = {}  # cwd -> (session_id, timestamp)
_KIRO_SESSION_WINDOW = 1800  # 30 minutes

# ── Per-IDE event name normalization maps ──

_KIRO_TO_CC_EVENT = {
    "agentSpawn": "SessionStart",
    "userPromptSubmit": "UserPromptSubmit",
    "preToolUse": "PreToolUse",
    "promptSubmit": "UserPromptSubmit",  # Kiro IDE variant
    "postToolUse": "PostToolUse",
    "stop": "Stop",
    "agentStop": "Stop",  # Kiro IDE variant
}

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

_CURSOR_TO_CC_EVENT = {
    "preToolUse": "PreToolUse",
    "postToolUse": "PostToolUse",
    "sessionStart": "SessionStart",
    "sessionEnd": "Stop",
    "stop": "Stop",
}

_COPILOT_TO_CC_EVENT = {
    "onPreToolUse": "PreToolUse",
    "preToolUse": "PreToolUse",
    "onPostToolUse": "PostToolUse",
    "postToolUse": "PostToolUse",
    "onUserPromptSubmitted": "UserPromptSubmit",
    "onSessionStart": "SessionStart",
    "sessionStart": "SessionStart",
    "onSessionEnd": "Stop",
    "sessionEnd": "Stop",
    "onErrorOccurred": "StopFailure",
    "subagent.started": "SubagentStart",
    "subagent.completed": "SubagentStop",
    "subagent.failed": "SubagentStop",
    "subagent.selected": "SubagentStart",
    "subagent.deselected": "SubagentStop",
}

# ── Per-IDE field normalization maps ──

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


# ── Hook ingestion helpers ──


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


# ── IDE-specific extraction helpers ──


def _extract_kiro(body: dict, hook_event: str, attrs: dict[str, str]) -> None:
    """Extract Kiro-specific fields into *attrs*."""
    tool_input_raw = body.get("tool_input")
    tool_response_raw = body.get("tool_response")

    if tool_input_raw is not None:
        attrs["tool_input"] = _truncate(_safe_json(tool_input_raw))
    if tool_response_raw is not None:
        attrs["tool_response"] = _truncate(_safe_json(tool_response_raw))

    if body.get("prompt") and not attrs.get("tool_input"):
        attrs["tool_input"] = _truncate(str(body["prompt"]))
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
        if body.get("assistant_response"):
            attrs["tool_response"] = _truncate(str(body["assistant_response"]))

    if hook_event == "PostToolUseFailure" and body.get("error"):
        attrs["error"] = _truncate(str(body["error"]))

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
    """Extract Claude Code-specific fields into *attrs*."""
    tool_name = attrs.get("tool_name", "")
    tool_input_raw = body.get("tool_input")
    tool_response_raw = body.get("tool_response")

    if tool_input_raw is not None:
        attrs["tool_input"] = _truncate(_safe_json(tool_input_raw))
    if tool_response_raw is not None:
        attrs["tool_response"] = _truncate(_safe_json(tool_response_raw))

    if hook_event == "UserPromptSubmit":
        prompt_text = body.get("user_prompt") or body.get("prompt") or ""
        if prompt_text:
            attrs["tool_input"] = _truncate(prompt_text)
            attrs["prompt_length"] = str(len(prompt_text))
        attrs["tool_name"] = "user_prompt"

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

    if hook_event == "SubagentStart" and body.get("last_assistant_message"):
        attrs["tool_input"] = _truncate(body["last_assistant_message"])
    if hook_event == "SubagentStop" and body.get("last_assistant_message"):
        attrs["tool_response"] = _truncate(body["last_assistant_message"])

    if hook_event == "PostToolUseFailure" and body.get("error"):
        attrs["error"] = _truncate(str(body["error"]))

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

    if hook_event == "StopFailure":
        if body.get("error"):
            attrs["error"] = _truncate(str(body["error"]))
        if body.get("stop_reason"):
            attrs["stop_reason"] = body["stop_reason"]

    if hook_event == "Notification":
        if body.get("message"):
            attrs["tool_response"] = _truncate(str(body["message"]))
        if body.get("title"):
            attrs["notification_title"] = str(body["title"])

    if hook_event in ("TaskCreated", "TaskCompleted"):
        for field in ("task_id", "task_subject", "task_status"):
            if body.get(field):
                attrs[field] = str(body[field])

    if hook_event in ("PreCompact", "PostCompact") and body.get("summary"):
        attrs["tool_response"] = _truncate(str(body["summary"]))

    if hook_event in ("WorktreeCreate", "WorktreeRemove"):
        if body.get("worktree_path"):
            attrs["worktree_path"] = str(body["worktree_path"])
        if body.get("branch"):
            attrs["branch"] = str(body["branch"])

    if hook_event in ("Elicitation", "ElicitationResult"):
        for field in ("mcp_server_name", "message", "response", "elicitation_id"):
            if body.get(field):
                key = "tool_input" if field == "message" else ("tool_response" if field == "response" else field)
                attrs[key] = _truncate(str(body[field]))


def _extract_gemini(body: dict, hook_event: str, attrs: dict[str, str]) -> None:
    """Extract Gemini CLI-specific fields into *attrs*."""
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

    for enriched_field in ("input_tokens", "output_tokens", "total_tokens"):
        if body.get(enriched_field):
            attrs[enriched_field] = str(body[enriched_field])


def _extract_cursor(body: dict, hook_event: str, attrs: dict[str, str]) -> None:
    """Extract Cursor-specific fields into *attrs*."""
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
    """Extract GitHub Copilot-specific fields into *attrs*."""
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


# Shim span type → otel_logs event.name mapping
_SHIM_EVENT_NAMES: dict[str, str] = {
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


@router.post("/ingest", response_model=IngestResponse)
async def ingest(
    batch: IngestBatch,
    current_user: User = Depends(require_role(UserRole.user)),
    x_observal_environment: str = Header("default"),
):
    """New ingestion endpoint for shim/proxy telemetry."""
    user_id = str(current_user.id)
    project_id = get_project_id(current_user)
    environment = x_observal_environment or "default"
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    ingested = 0
    errors = 0

    # --- Traces ---
    if batch.traces:
        try:
            rows = []
            for t in batch.traces:
                rows.append(
                    {
                        "trace_id": t.trace_id,
                        "parent_trace_id": t.parent_trace_id,
                        "project_id": project_id,
                        "mcp_id": t.mcp_id,
                        "agent_id": t.agent_id,
                        "user_id": user_id,
                        "session_id": t.session_id,
                        "ide": t.ide,
                        "environment": environment,
                        "start_time": t.start_time,
                        "end_time": t.end_time,
                        "trace_type": t.trace_type,
                        "name": t.name,
                        "metadata": t.metadata,
                        "tags": t.tags,
                        "input": redact_secrets(t.input) if t.input else t.input,
                        "output": redact_secrets(t.output) if t.output else t.output,
                        "tool_id": t.tool_id,
                        "sandbox_id": t.sandbox_id,
                        "graphrag_id": t.graphrag_id,
                        "hook_id": t.hook_id,
                        "skill_id": t.skill_id,
                        "prompt_id": t.prompt_id,
                    }
                )
            await insert_traces(rows)
            ingested += len(rows)
        except Exception:
            logger.exception("Failed to insert traces")
            errors += len(batch.traces)

    # --- Spans ---
    if batch.spans:
        try:
            rows = []
            for s in batch.spans:
                rows.append(
                    {
                        "span_id": s.span_id,
                        "trace_id": s.trace_id,
                        "parent_span_id": s.parent_span_id,
                        "project_id": project_id,
                        "mcp_id": None,
                        "agent_id": None,
                        "user_id": user_id,
                        "type": s.type,
                        "name": s.name,
                        "method": s.method,
                        "input": redact_secrets(s.input) if s.input else s.input,
                        "output": redact_secrets(s.output) if s.output else s.output,
                        "error": redact_secrets(s.error) if s.error else s.error,
                        "start_time": s.start_time,
                        "end_time": s.end_time,
                        "latency_ms": s.latency_ms,
                        "status": s.status,
                        "ide": s.ide,
                        "environment": environment,
                        "metadata": s.metadata,
                        "token_count_input": s.token_count_input,
                        "token_count_output": s.token_count_output,
                        "token_count_total": s.token_count_total,
                        "cost": s.cost,
                        "cpu_ms": s.cpu_ms,
                        "memory_mb": s.memory_mb,
                        "hop_count": s.hop_count,
                        "entities_retrieved": s.entities_retrieved,
                        "relationships_used": s.relationships_used,
                        "retry_count": s.retry_count,
                        "tools_available": s.tools_available,
                        "tool_schema_valid": (int(s.tool_schema_valid) if s.tool_schema_valid is not None else None),
                        "container_id": s.container_id,
                        "exit_code": s.exit_code,
                        "network_bytes_in": s.network_bytes_in,
                        "network_bytes_out": s.network_bytes_out,
                        "disk_read_bytes": s.disk_read_bytes,
                        "disk_write_bytes": s.disk_write_bytes,
                        "oom_killed": (int(s.oom_killed) if s.oom_killed is not None else None),
                        "query_interface": s.query_interface,
                        "relevance_score": s.relevance_score,
                        "chunks_returned": s.chunks_returned,
                        "embedding_latency_ms": s.embedding_latency_ms,
                        "hook_event": s.hook_event,
                        "hook_scope": s.hook_scope,
                        "hook_action": s.hook_action,
                        "hook_blocked": (int(s.hook_blocked) if s.hook_blocked is not None else None),
                        "variables_provided": s.variables_provided,
                        "template_tokens": s.template_tokens,
                        "rendered_tokens": s.rendered_tokens,
                    }
                )
            await insert_spans(rows)
            ingested += len(rows)
        except Exception:
            logger.exception("Failed to insert spans")
            errors += len(batch.spans)

    # --- Mirror shim spans into otel_logs for unified session view ---
    if batch.spans and batch.traces:
        try:
            # Build a lookup of trace metadata for session_id / mcp_id
            trace_meta: dict[str, dict] = {}
            for t in batch.traces:
                trace_meta[t.trace_id] = {
                    "session_id": t.session_id or "",
                    "mcp_id": t.mcp_id or "",
                    "agent_id": t.agent_id or "",
                    "ide": t.ide or "",
                }

            otel_rows = []
            for s in batch.spans:
                meta = trace_meta.get(s.trace_id, {})
                session_id = meta.get("session_id", "")
                if not session_id:
                    continue  # Can't place in a session — skip

                event_name = _SHIM_EVENT_NAMES.get(s.type or "", "shim_other")
                mcp_id = meta.get("mcp_id", "")
                tool_name = s.name or ""

                # Build a human-readable body
                latency_label = f" ({s.latency_ms}ms)" if s.latency_ms else ""
                body_text = f"shim: {s.type} {tool_name}{latency_label}"

                attrs: dict[str, str] = {
                    "session.id": session_id,
                    "event.name": event_name,
                    "source": "shim",
                    "tool_name": tool_name,
                    "mcp_id": mcp_id,
                    "mcp_method": s.method or "",
                    "mcp_span_id": s.span_id or "",
                    "mcp_trace_id": s.trace_id or "",
                }
                if s.latency_ms is not None:
                    attrs["mcp_latency_ms"] = str(s.latency_ms)
                if s.tool_schema_valid is not None:
                    attrs["tool_schema_valid"] = str(int(s.tool_schema_valid))
                if s.tools_available is not None:
                    attrs["tools_available"] = str(s.tools_available)
                if s.input:
                    attrs["mcp_input"] = redact_secrets(s.input)
                if s.output:
                    attrs["mcp_output"] = redact_secrets(s.output)
                if s.error:
                    attrs["mcp_error"] = redact_secrets(s.error)
                if s.status:
                    attrs["mcp_status"] = s.status
                if meta.get("agent_id"):
                    attrs["agent_id"] = meta["agent_id"]
                if meta.get("ide"):
                    attrs["terminal.type"] = meta["ide"]

                otel_rows.append(
                    {
                        "Timestamp": s.start_time or now,
                        "Body": body_text,
                        "LogAttributes": attrs,
                        "ServiceName": meta.get("ide") or "claude-code",
                        "SeverityText": "ERROR" if s.status == "error" else "INFO",
                        "SeverityNumber": 17 if s.status == "error" else 9,
                        "TraceId": s.trace_id or "",
                        "SpanId": s.span_id or "",
                    }
                )

            if otel_rows:
                await insert_otel_logs(otel_rows)

                # Notify subscribers so session detail updates live
                session_ids_seen: set[str] = set()
                for row in otel_rows:
                    sid = row["LogAttributes"].get("session.id", "")
                    if sid and sid not in session_ids_seen:
                        session_ids_seen.add(sid)
                        task = asyncio.create_task(
                            publish("sessions:updated", {"session_id": sid, "event_name": "shim_ingest"})
                        )
                        _background_tasks.add(task)
                        task.add_done_callback(_background_tasks.discard)
        except Exception:
            logger.exception("Failed to mirror shim spans to otel_logs")

    # --- Scores ---
    if batch.scores:
        try:
            rows = []
            for sc in batch.scores:
                rows.append(
                    {
                        "score_id": sc.score_id,
                        "trace_id": sc.trace_id,
                        "span_id": sc.span_id,
                        "project_id": project_id,
                        "mcp_id": sc.mcp_id,
                        "agent_id": sc.agent_id,
                        "user_id": user_id,
                        "name": sc.name,
                        "source": sc.source,
                        "data_type": sc.data_type,
                        "value": sc.value,
                        "string_value": sc.string_value,
                        "comment": sc.comment,
                        "metadata": sc.metadata,
                        "timestamp": now,
                    }
                )
            await insert_scores(rows)
            ingested += len(rows)
        except Exception:
            logger.exception("Failed to insert scores")
            errors += len(batch.scores)

    return IngestResponse(ingested=ingested, errors=errors)


@router.get("/status", response_model=TelemetryStatusResponse)
async def telemetry_status(current_user: User = Depends(require_role(UserRole.admin))):
    counts = await query_recent_events(60)
    return TelemetryStatusResponse(
        tool_call_events=counts["tool_call_events"],
        agent_interaction_events=counts["agent_interaction_events"],
        status="ok",
    )


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
            logger.warning("hook_insert_failed", extra={"status_code": r.status_code, "response": r.text[:200]})
            return {"ingested": 0, "error": "insert failed"}
    except Exception:
        logger.exception("hook_insert_failed")
        return {"ingested": 0, "error": "insert failed"}

    # Notify subscribers (fire-and-forget — don't block the response)
    if session_id:
        task = asyncio.create_task(publish("sessions:updated", {"session_id": session_id, "event_name": hook_event}))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

    return {"ingested": 1, "session_id": session_id, "event": hook_event}


# ---------------------------------------------------------------------------
# OTLP HTTP receiver
# ---------------------------------------------------------------------------
# Accepts standard OTLP JSON on /v1/traces, /v1/logs, /v1/metrics and converts
# to Observal's internal ClickHouse format.  Authentication is optional: callers
# may pass ``Authorization: Bearer <key>`` but unauthenticated requests are
# accepted by default (OTLP exporters rarely carry API keys).

_DEFAULT_PROJECT = "default"
_DT_FMT = "%Y-%m-%d %H:%M:%S.%f"

# OTLP status codes
_STATUS_MAP = {0: "success", 1: "success", 2: "error"}

# IDE detection from resource attributes
_IDE_HINTS = {
    "claude-code": "claude-code",
    "claude code": "claude-code",
    "gemini": "gemini-cli",
    "copilot": "copilot",
    "cursor": "cursor",
    "kiro": "kiro",
    "kiro-cli": "kiro",
    "amazon-kiro": "kiro",
    "aws-kiro": "kiro",
    "codex": "codex",
    "opencode": "opencode",
    "vscode": "vscode",
}


# ---------------------------------------------------------------------------
# OTLP Helpers
# ---------------------------------------------------------------------------


def _nanos_to_dt(nanos: str | int) -> str:
    """Convert nanosecond unix timestamp to datetime string."""
    ts = int(nanos) / 1e9
    return datetime.fromtimestamp(ts, tz=UTC).strftime(_DT_FMT)[:-3]


def _nanos_to_ms(start: str | int, end: str | int) -> int | None:
    """Calculate latency in ms from two nano timestamps."""
    try:
        return max(0, int((int(end) - int(start)) / 1_000_000))
    except (ValueError, TypeError):
        return None


def _extract_attrs(attributes: list[dict]) -> dict[str, str]:
    """Flatten OTLP attribute list to a simple dict."""
    out: dict[str, str] = {}
    for attr in attributes:
        key = attr.get("key", "")
        val = attr.get("value", {})
        if "stringValue" in val:
            out[key] = val["stringValue"]
        elif "intValue" in val:
            out[key] = str(val["intValue"])
        elif "doubleValue" in val:
            out[key] = str(val["doubleValue"])
        elif "boolValue" in val:
            out[key] = str(val["boolValue"]).lower()
        elif "arrayValue" in val:
            out[key] = json.dumps(val["arrayValue"].get("values", []))
    return out


def _detect_ide(attrs: dict[str, str]) -> str:
    """Best-effort IDE detection from resource/span attributes."""
    for field in ("service.name", "telemetry.sdk.name", "process.runtime.name", "terminal.type"):
        val = attrs.get(field, "").lower()
        for hint, ide in _IDE_HINTS.items():
            if hint in val:
                return ide
    return attrs.get("terminal.type", "")


def _safe_int(val: str | None) -> int | None:
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _safe_float(val: str | None) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _now_ms() -> str:
    return datetime.now(UTC).strftime(_DT_FMT)[:-3]


_REDACT_FIELDS = {"input", "output", "error"}


def _redact_rows(rows: list[dict]) -> None:
    """Redact secrets from input/output/error fields in place."""
    for row in rows:
        for field in _REDACT_FIELDS:
            val = row.get(field)
            if val and isinstance(val, str):
                row[field] = redact_secrets(val)


async def _resolve_project_id(request: Request) -> str:
    """Derive project_id from an optional ``Authorization: Bearer`` header.

    Returns ``"default"`` when the header is absent, malformed, or the user
    has no org.
    """
    auth = request.headers.get("authorization")
    if not auth or not auth.startswith("Bearer "):
        return _DEFAULT_PROJECT
    token = auth.removeprefix("Bearer ").strip()
    try:
        payload = decode_access_token(token)
    except jwt.InvalidTokenError:
        return _DEFAULT_PROJECT

    user_id = payload.get("sub")
    if not user_id:
        return _DEFAULT_PROJECT

    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        return _DEFAULT_PROJECT

    try:
        async with async_session() as session:
            result = await session.execute(select(User.org_id).where(User.id == uid))
            org_id = result.scalar_one_or_none()
            return str(org_id) if org_id else _DEFAULT_PROJECT
    except Exception:
        logger.debug("OTLP: failed to resolve project_id from auth header", exc_info=True)
        return _DEFAULT_PROJECT


# ---------------------------------------------------------------------------
# OTLP Trace conversion
# ---------------------------------------------------------------------------


def _convert_resource_spans(body: dict, project_id: str = _DEFAULT_PROJECT) -> tuple[list[dict], list[dict]]:
    """Parse OTLP resourceSpans into Observal trace and span rows."""
    traces: list[dict] = []
    spans: list[dict] = []
    seen_traces: dict[str, dict] = {}

    for rs in body.get("resourceSpans", []):
        res_attrs = _extract_attrs(rs.get("resource", {}).get("attributes", []))
        ide = _detect_ide(res_attrs)

        for ss in rs.get("scopeSpans", []):
            for span in ss.get("spans", []):
                try:
                    span_attrs = _extract_attrs(span.get("attributes", []))
                    all_attrs = {**res_attrs, **span_attrs}

                    trace_id = span.get("traceId", "")
                    span_id = span.get("spanId", "")
                    parent_span_id = span.get("parentSpanId") or None
                    name = span.get("name", "")
                    start_nano = span.get("startTimeUnixNano", "0")
                    end_nano = span.get("endTimeUnixNano", "0")
                    start_time = _nanos_to_dt(start_nano)
                    end_time = _nanos_to_dt(end_nano) if int(end_nano) > 0 else None
                    latency_ms = _nanos_to_ms(start_nano, end_nano)

                    status_code = span.get("status", {}).get("code", 0)
                    status = _STATUS_MAP.get(status_code, "success")
                    error_msg = span.get("status", {}).get("message") if status == "error" else None

                    user_id = (
                        all_attrs.get("user.id")
                        or all_attrs.get("user.email")
                        or all_attrs.get("user.account_uuid")
                        or "otlp"
                    )
                    session_id = all_attrs.get("session.id")

                    # GenAI semantic conventions (redact secrets)
                    input_text = redact_secrets(all_attrs.get("gen_ai.prompt") or "") or None
                    output_text = redact_secrets(all_attrs.get("gen_ai.completion") or "") or None
                    tok_in = _safe_int(all_attrs.get("gen_ai.usage.input_tokens"))
                    tok_out = _safe_int(all_attrs.get("gen_ai.usage.output_tokens"))
                    tok_total = (tok_in or 0) + (tok_out or 0) if (tok_in is not None or tok_out is not None) else None
                    cost = _safe_float(all_attrs.get("gen_ai.usage.cost"))

                    # Metadata: carry over interesting attributes
                    metadata: dict[str, str] = {}
                    prompt_id = all_attrs.get("prompt.id")
                    if prompt_id:
                        metadata["prompt_id"] = prompt_id
                    model = all_attrs.get("gen_ai.request.model") or all_attrs.get("gen_ai.response.model")
                    if model:
                        metadata["model"] = model

                    span_type = "otlp"
                    kind = span.get("kind", 0)
                    if kind == 3:  # CLIENT
                        span_type = "llm" if model else "client"
                    elif kind == 2:  # SERVER
                        span_type = "server"
                    elif kind == 1:  # INTERNAL
                        span_type = "internal"

                    span_row = {
                        "span_id": span_id,
                        "trace_id": trace_id,
                        "parent_span_id": parent_span_id,
                        "project_id": project_id,
                        "mcp_id": None,
                        "agent_id": None,
                        "user_id": user_id,
                        "type": span_type,
                        "name": name,
                        "method": "",
                        "input": input_text,
                        "output": output_text,
                        "error": error_msg,
                        "start_time": start_time,
                        "end_time": end_time,
                        "latency_ms": latency_ms,
                        "status": status,
                        "ide": ide,
                        "environment": "default",
                        "metadata": metadata,
                        "token_count_input": tok_in,
                        "token_count_output": tok_out,
                        "token_count_total": tok_total,
                        "cost": cost,
                    }
                    spans.append(span_row)

                    # Process span events (Claude Code specifics)
                    _process_span_events(span, trace_id, span_id, all_attrs, ide, user_id, spans, project_id)

                    # Collect root-level trace (no parent = root span)
                    if not parent_span_id and trace_id not in seen_traces:
                        seen_traces[trace_id] = {
                            "trace_id": trace_id,
                            "project_id": project_id,
                            "user_id": user_id,
                            "session_id": session_id,
                            "ide": ide,
                            "environment": "default",
                            "start_time": start_time,
                            "end_time": end_time,
                            "trace_type": "otlp",
                            "name": name,
                            "metadata": metadata,
                            "tags": [],
                            "input": input_text,
                            "output": output_text,
                        }
                except Exception:
                    logger.warning("Failed to convert OTLP span", exc_info=True)

    traces = list(seen_traces.values())
    return traces, spans


def _process_span_events(
    span: dict,
    trace_id: str,
    parent_span_id: str,
    all_attrs: dict[str, str],
    ide: str,
    user_id: str,
    spans_out: list[dict],
    project_id: str = _DEFAULT_PROJECT,
):
    """Extract Claude Code span events into child spans."""
    for event in span.get("events", []):
        try:
            event_name = event.get("name", "")
            event_attrs = _extract_attrs(event.get("attributes", []))
            event_time = event.get("timeUnixNano", "0")
            dt = _nanos_to_dt(event_time) if int(event_time) > 0 else _now_ms()

            if event_name in ("claude_code.user_prompt", "kiro.user_prompt", "user_prompt"):
                # Captured as trace input via log handler; also emit a span
                spans_out.append(
                    {
                        "span_id": uuid.uuid4().hex,
                        "trace_id": trace_id,
                        "parent_span_id": parent_span_id,
                        "project_id": project_id,
                        "user_id": user_id,
                        "type": "user_prompt",
                        "name": "user_prompt",
                        "input": event_attrs.get("prompt") or event_attrs.get("content"),
                        "start_time": dt,
                        "end_time": dt,
                        "status": "success",
                        "ide": ide,
                        "environment": "default",
                        "metadata": {},
                    }
                )
            elif event_name in ("claude_code.tool_result", "kiro.tool_result", "tool_result"):
                dur = _safe_int(event_attrs.get("duration_ms"))
                spans_out.append(
                    {
                        "span_id": uuid.uuid4().hex,
                        "trace_id": trace_id,
                        "parent_span_id": parent_span_id,
                        "project_id": project_id,
                        "user_id": user_id,
                        "type": "tool_result",
                        "name": event_attrs.get("tool_name", "tool"),
                        "output": event_attrs.get("result"),
                        "start_time": dt,
                        "end_time": dt,
                        "latency_ms": dur,
                        "status": "success" if event_attrs.get("success", "true") == "true" else "error",
                        "ide": ide,
                        "environment": "default",
                        "metadata": {},
                    }
                )
            elif event_name in ("claude_code.api_request", "kiro.api_request", "api_request"):
                tok_in = (
                    _safe_int(event_attrs.get("input_tokens"))
                    or _safe_int(event_attrs.get("gen_ai.usage.input_tokens"))
                    or _safe_int(event_attrs.get("aws.bedrock.invocation.input_tokens"))
                )
                tok_out = (
                    _safe_int(event_attrs.get("output_tokens"))
                    or _safe_int(event_attrs.get("gen_ai.usage.output_tokens"))
                    or _safe_int(event_attrs.get("aws.bedrock.invocation.output_tokens"))
                )
                tok_total = (tok_in or 0) + (tok_out or 0) if (tok_in is not None or tok_out is not None) else None
                meta: dict[str, str] = {}
                model = (
                    event_attrs.get("model")
                    or event_attrs.get("gen_ai.request.model")
                    or event_attrs.get("aws.bedrock.model_id")
                )
                if model:
                    meta["model"] = model
                spans_out.append(
                    {
                        "span_id": uuid.uuid4().hex,
                        "trace_id": trace_id,
                        "parent_span_id": parent_span_id,
                        "project_id": project_id,
                        "user_id": user_id,
                        "type": "llm",
                        "name": event_attrs.get("model", "api_request"),
                        "start_time": dt,
                        "end_time": dt,
                        "latency_ms": _safe_int(event_attrs.get("duration_ms")),
                        "status": "success",
                        "ide": ide,
                        "environment": "default",
                        "metadata": meta,
                        "token_count_input": tok_in,
                        "token_count_output": tok_out,
                        "token_count_total": tok_total,
                        "cost": _safe_float(event_attrs.get("cost")),
                    }
                )
        except Exception:
            logger.warning("Failed to process span event %s", event.get("name"), exc_info=True)


# ---------------------------------------------------------------------------
# OTLP Log conversion
# ---------------------------------------------------------------------------


def _convert_resource_logs(body: dict, project_id: str = _DEFAULT_PROJECT) -> tuple[list[dict], list[dict]]:
    """Parse OTLP resourceLogs into Observal trace and span rows."""
    traces: list[dict] = []
    spans: list[dict] = []
    # Group by prompt_id to build traces
    prompt_traces: dict[str, dict] = {}

    for rl in body.get("resourceLogs", []):
        res_attrs = _extract_attrs(rl.get("resource", {}).get("attributes", []))
        ide = _detect_ide(res_attrs)

        for sl in rl.get("scopeLogs", []):
            for rec in sl.get("logRecords", []):
                try:
                    log_attrs = _extract_attrs(rec.get("attributes", []))
                    all_attrs = {**res_attrs, **log_attrs}
                    event_name = all_attrs.get("event.name", "")
                    time_nano = rec.get("timeUnixNano", "0")
                    dt = _nanos_to_dt(time_nano) if int(time_nano) > 0 else _now_ms()

                    user_id = (
                        all_attrs.get("user.id")
                        or all_attrs.get("user.email")
                        or all_attrs.get("user.account_uuid")
                        or "otlp"
                    )
                    session_id = all_attrs.get("session.id")
                    prompt_id = all_attrs.get("prompt.id")
                    # Use prompt_id as trace grouping key, fall back to a new UUID
                    trace_id = prompt_id or uuid.uuid4().hex

                    body_val = rec.get("body", {})
                    body_text = body_val.get("stringValue", "") if isinstance(body_val, dict) else str(body_val)

                    if event_name in ("claude_code.user_prompt", "kiro.user_prompt", "user_prompt"):
                        prompt_text = (
                            all_attrs.get("prompt")
                            or body_text
                            or all_attrs.get("content")
                            or all_attrs.get("prompt_length")
                        )
                        logger.info(
                            "OTLP user_prompt: prompt_text=%s, body_text=%s, attrs=%s",
                            repr(prompt_text)[:200],
                            repr(body_text)[:200],
                            {
                                k: repr(v)[:80]
                                for k, v in all_attrs.items()
                                if k.startswith("prompt") or k == "event.name"
                            },
                        )
                        # Create or update trace with user prompt as input
                        if trace_id not in prompt_traces:
                            prompt_traces[trace_id] = {
                                "trace_id": trace_id,
                                "project_id": project_id,
                                "user_id": user_id,
                                "session_id": session_id,
                                "ide": ide,
                                "environment": "default",
                                "start_time": dt,
                                "trace_type": "otlp",
                                "name": "user_prompt",
                                "metadata": {"prompt_id": prompt_id} if prompt_id else {},
                                "tags": [],
                                "input": prompt_text,
                            }
                        else:
                            prompt_traces[trace_id]["input"] = prompt_text

                    elif event_name in ("claude_code.tool_result", "kiro.tool_result", "tool_result"):
                        # Ensure trace exists
                        if trace_id not in prompt_traces:
                            prompt_traces[trace_id] = {
                                "trace_id": trace_id,
                                "project_id": project_id,
                                "user_id": user_id,
                                "session_id": session_id,
                                "ide": ide,
                                "environment": "default",
                                "start_time": dt,
                                "trace_type": "otlp",
                                "name": "session",
                                "metadata": {"prompt_id": prompt_id} if prompt_id else {},
                                "tags": [],
                            }
                        dur = _safe_int(all_attrs.get("duration_ms"))
                        spans.append(
                            {
                                "span_id": uuid.uuid4().hex,
                                "trace_id": trace_id,
                                "project_id": project_id,
                                "user_id": user_id,
                                "type": "tool_result",
                                "name": all_attrs.get("tool_name", "tool"),
                                "output": body_text or all_attrs.get("result"),
                                "start_time": dt,
                                "end_time": dt,
                                "latency_ms": dur,
                                "status": "success" if all_attrs.get("success", "true") == "true" else "error",
                                "ide": ide,
                                "environment": "default",
                                "metadata": {},
                            }
                        )

                    elif event_name in ("claude_code.api_request", "kiro.api_request", "api_request"):
                        if trace_id not in prompt_traces:
                            prompt_traces[trace_id] = {
                                "trace_id": trace_id,
                                "project_id": project_id,
                                "user_id": user_id,
                                "session_id": session_id,
                                "ide": ide,
                                "environment": "default",
                                "start_time": dt,
                                "trace_type": "otlp",
                                "name": "session",
                                "metadata": {"prompt_id": prompt_id} if prompt_id else {},
                                "tags": [],
                            }
                        tok_in = (
                            _safe_int(all_attrs.get("input_tokens"))
                            or _safe_int(all_attrs.get("gen_ai.usage.input_tokens"))
                            or _safe_int(all_attrs.get("aws.bedrock.invocation.input_tokens"))
                        )
                        tok_out = (
                            _safe_int(all_attrs.get("output_tokens"))
                            or _safe_int(all_attrs.get("gen_ai.usage.output_tokens"))
                            or _safe_int(all_attrs.get("aws.bedrock.invocation.output_tokens"))
                        )
                        tok_total = (
                            (tok_in or 0) + (tok_out or 0) if (tok_in is not None or tok_out is not None) else None
                        )
                        meta: dict[str, str] = {}
                        model = (
                            all_attrs.get("model")
                            or all_attrs.get("gen_ai.request.model")
                            or all_attrs.get("aws.bedrock.model_id")
                        )
                        if model:
                            meta["model"] = model
                        spans.append(
                            {
                                "span_id": uuid.uuid4().hex,
                                "trace_id": trace_id,
                                "project_id": project_id,
                                "user_id": user_id,
                                "type": "llm",
                                "name": all_attrs.get("model", "api_request"),
                                "start_time": dt,
                                "end_time": dt,
                                "latency_ms": _safe_int(all_attrs.get("duration_ms")),
                                "status": "success",
                                "ide": ide,
                                "environment": "default",
                                "metadata": meta,
                                "token_count_input": tok_in,
                                "token_count_output": tok_out,
                                "token_count_total": tok_total,
                                "cost": _safe_float(all_attrs.get("cost")),
                            }
                        )
                    else:
                        # Generic log record -> span
                        spans.append(
                            {
                                "span_id": uuid.uuid4().hex,
                                "trace_id": trace_id,
                                "project_id": project_id,
                                "user_id": user_id,
                                "type": "log",
                                "name": event_name or "log",
                                "input": body_text or None,
                                "start_time": dt,
                                "end_time": dt,
                                "status": "success",
                                "ide": ide,
                                "environment": "default",
                                "metadata": {"severity": str(rec.get("severityNumber", ""))}
                                if rec.get("severityNumber")
                                else {},
                            }
                        )
                except Exception:
                    logger.warning("Failed to convert OTLP log record", exc_info=True)

    traces = list(prompt_traces.values())
    return traces, spans


# ---------------------------------------------------------------------------
# OTLP Endpoints
# ---------------------------------------------------------------------------

_OTLP_OK = {"partialSuccess": {}}


@otlp_router.post("/v1/traces")
async def otlp_traces(request: Request):
    """Receive OTLP trace export (JSON)."""
    try:
        body = await request.json()
    except Exception:
        logger.warning("OTLP /v1/traces: malformed JSON body")
        return Response(
            content=json.dumps({"partialSuccess": {"rejectedSpans": 1, "errorMessage": "malformed JSON"}}),
            status_code=400,
            media_type="application/json",
        )

    project_id = await _resolve_project_id(request)

    try:
        trace_rows, span_rows = _convert_resource_spans(body, project_id)
    except Exception:
        logger.warning("OTLP /v1/traces: conversion failed", exc_info=True)
        return Response(content=json.dumps(_OTLP_OK), status_code=200, media_type="application/json")

    get_and_reset_redaction_count()
    _redact_rows(trace_rows)
    _redact_rows(span_rows)
    redacted = get_and_reset_redaction_count()
    if redacted:
        await emit_security_event(
            SecurityEvent(
                event_type=EventType.SECRETS_REDACTED,
                severity=Severity.INFO,
                outcome="success",
                detail=f"Redacted {redacted} secrets in OTLP traces batch",
            )
        )

    errors = 0
    if trace_rows:
        try:
            await insert_traces(trace_rows)
        except Exception:
            logger.exception("OTLP: insert_traces failed")
            errors += len(trace_rows)
    if span_rows:
        try:
            await insert_spans(span_rows)
        except Exception:
            logger.exception("OTLP: insert_spans failed")
            errors += len(span_rows)

    if errors:
        return Response(
            content=json.dumps({"partialSuccess": {"rejectedSpans": errors}}),
            status_code=200,
            media_type="application/json",
        )
    return Response(content=json.dumps(_OTLP_OK), status_code=200, media_type="application/json")


@otlp_router.post("/v1/logs")
async def otlp_logs(request: Request):
    """Receive OTLP log export (JSON)."""
    try:
        body = await request.json()
    except Exception:
        logger.warning("OTLP /v1/logs: malformed JSON body")
        return Response(
            content=json.dumps({"partialSuccess": {"rejectedLogRecords": 1, "errorMessage": "malformed JSON"}}),
            status_code=400,
            media_type="application/json",
        )

    rl_count = len(body.get("resourceLogs", []))
    logger.debug("OTLP /v1/logs: %d resourceLogs", rl_count)

    project_id = await _resolve_project_id(request)

    try:
        trace_rows, span_rows = _convert_resource_logs(body, project_id)
    except Exception:
        logger.warning("OTLP /v1/logs: conversion failed", exc_info=True)
        return Response(content=json.dumps(_OTLP_OK), status_code=200, media_type="application/json")

    _redact_rows(trace_rows)
    _redact_rows(span_rows)

    errors = 0
    if trace_rows:
        try:
            await insert_traces(trace_rows)
        except Exception:
            logger.exception("OTLP: insert_traces from logs failed")
            errors += len(trace_rows)
    if span_rows:
        try:
            await insert_spans(span_rows)
        except Exception:
            logger.exception("OTLP: insert_spans from logs failed")
            errors += len(span_rows)

    if errors:
        return Response(
            content=json.dumps({"partialSuccess": {"rejectedLogRecords": errors}}),
            status_code=200,
            media_type="application/json",
        )
    return Response(content=json.dumps(_OTLP_OK), status_code=200, media_type="application/json")


@otlp_router.post("/v1/metrics")
async def otlp_metrics(request: Request):
    """Receive OTLP metrics export (JSON). Best-effort: extract token/cost counters."""
    try:
        body = await request.json()
    except Exception:
        logger.warning("OTLP /v1/metrics: malformed JSON body")
        return Response(
            content=json.dumps({"partialSuccess": {"rejectedDataPoints": 1, "errorMessage": "malformed JSON"}}),
            status_code=400,
            media_type="application/json",
        )

    project_id = await _resolve_project_id(request)

    span_rows: list[dict] = []
    now = _now_ms()

    for rm in body.get("resourceMetrics", []):
        res_attrs = _extract_attrs(rm.get("resource", {}).get("attributes", []))
        ide = _detect_ide(res_attrs)
        user_id = res_attrs.get("user.id") or res_attrs.get("user.email") or "otlp"

        for sm in rm.get("scopeMetrics", []):
            for metric in sm.get("metrics", []):
                try:
                    name = metric.get("name", "")
                    # Extract data points from sum, gauge, or histogram
                    points = []
                    for kind in ("sum", "gauge"):
                        if kind in metric:
                            points.extend(metric[kind].get("dataPoints", []))
                    if "histogram" in metric:
                        points.extend(metric["histogram"].get("dataPoints", []))

                    for dp in points:
                        dp_attrs = _extract_attrs(dp.get("attributes", []))
                        val = dp.get("asDouble") or dp.get("asInt") or dp.get("sum")
                        if val is None:
                            continue
                        meta = {"metric_name": name, **dp_attrs}
                        tok_in = (
                            _safe_int(dp_attrs.get("gen_ai.usage.input_tokens")) if "token" in name.lower() else None
                        )
                        tok_out = (
                            _safe_int(dp_attrs.get("gen_ai.usage.output_tokens")) if "token" in name.lower() else None
                        )
                        span_rows.append(
                            {
                                "span_id": uuid.uuid4().hex,
                                "trace_id": uuid.uuid4().hex,
                                "project_id": project_id,
                                "user_id": user_id,
                                "type": "metric",
                                "name": name,
                                "start_time": now,
                                "end_time": now,
                                "status": "success",
                                "ide": ide,
                                "environment": "default",
                                "metadata": {k: str(v) for k, v in meta.items()},
                                "token_count_input": tok_in,
                                "token_count_output": tok_out,
                                "cost": _safe_float(dp_attrs.get("cost")),
                            }
                        )
                except Exception:
                    logger.warning("Failed to convert OTLP metric %s", metric.get("name"), exc_info=True)

    if span_rows:
        try:
            await insert_spans(span_rows)
        except Exception:
            logger.exception("OTLP: insert_spans from metrics failed")
            return Response(
                content=json.dumps({"partialSuccess": {"rejectedDataPoints": len(span_rows)}}),
                status_code=200,
                media_type="application/json",
            )

    return Response(content=json.dumps(_OTLP_OK), status_code=200, media_type="application/json")
