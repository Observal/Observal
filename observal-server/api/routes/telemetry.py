# SPDX-FileCopyrightText: 2026 Subramania Raja <dhanpraja231@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Telemetry ingestion endpoint for shim/proxy structured spans.

The legacy /hooks and OTLP /v1/{traces,logs,metrics} endpoints have been
removed — session telemetry now flows through /api/v1/ingest/session
(session JSONL push) and this endpoint (MCP shim spans).
"""

import asyncio
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header
from loguru import logger as optic

from api.deps import get_project_id, require_role
from models.user import User, UserRole
from schemas.telemetry import (
    IngestBatch,
    IngestResponse,
    TelemetryStatusResponse,
)
from services.clickhouse import (
    insert_otel_logs,
    insert_scores,
    insert_spans,
    insert_traces,
    query_recent_events,
)
from services.redis import publish
from services.secrets_redactor import redact_secrets

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/telemetry", tags=["telemetry"])

# Background tasks that must survive until completion (prevent GC)
_background_tasks: set[asyncio.Task] = set()

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
    """Ingestion endpoint for shim/proxy telemetry (traces, spans, scores)."""
    optic.debug(
        "telemetry ingest: traces={}, spans={}, scores={}",
        len(batch.traces) if batch.traces else 0,
        len(batch.spans) if batch.spans else 0,
        len(batch.scores) if batch.scores else 0,
    )
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
                    continue

                event_name = _SHIM_EVENT_NAMES.get(s.type or "", "shim_other")
                mcp_id = meta.get("mcp_id", "")
                tool_name = s.name or ""

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

    optic.info("telemetry ingest completed: ingested={}, errors={}", ingested, errors)
    return IngestResponse(ingested=ingested, errors=errors)


@router.get("/status", response_model=TelemetryStatusResponse)
async def telemetry_status(current_user: User = Depends(require_role(UserRole.admin))):
    optic.debug("telemetry_status: user_id={}", current_user.id)
    counts = await query_recent_events(60)
    return TelemetryStatusResponse(
        tool_call_events=counts["tool_call_events"],
        agent_interaction_events=counts["agent_interaction_events"],
        status="ok",
    )
