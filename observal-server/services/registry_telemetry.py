"""Fire-and-forget telemetry for registry actions (agent create/update/delete/install).

Writes a trace + span to the existing ClickHouse tables and an audit_log entry.
Uses asyncio.create_task so the API response is never blocked.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from services.clickhouse import insert_audit_log, insert_spans, insert_traces

logger = logging.getLogger(__name__)

# prevent GC of fire-and-forget tasks (same pattern as telemetry.py)
_background_tasks: set[asyncio.Task] = set()


async def _emit(trace: dict, span: dict, audit: dict):
    """Insert a trace + span + audit_log entry. Swallows errors."""
    try:
        await insert_traces([trace])
        await insert_spans([span])
        await insert_audit_log([audit])
    except Exception:
        logger.exception("Registry telemetry write failed")


def emit_registry_event(
    *,
    action: str,
    user_id: str,
    user_email: str = "",
    user_role: str = "",
    agent_id: str | None = None,
    resource_name: str = "",
    metadata: dict[str, str] | None = None,
) -> None:
    """Fire-and-forget a registry trace + span + audit_log entry into ClickHouse."""
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    trace_id = str(uuid.uuid4())
    span_id = str(uuid.uuid4())
    meta = metadata or {}

    trace = {
        "trace_id": trace_id,
        "parent_trace_id": None,
        "project_id": "default",
        "mcp_id": None,
        "agent_id": agent_id,
        "user_id": user_id,
        "session_id": None,
        "ide": "",
        "environment": "default",
        "start_time": now,
        "end_time": now,
        "trace_type": "registry",
        "name": action,
        "metadata": meta,
        "tags": ["registry", action.split(".")[0]],
        "input": None,
        "output": None,
    }

    span = {
        "span_id": span_id,
        "trace_id": trace_id,
        "parent_span_id": None,
        "project_id": "default",
        "mcp_id": None,
        "agent_id": agent_id,
        "user_id": user_id,
        "type": "registry",
        "name": action,
        "method": "",
        "input": None,
        "output": None,
        "error": None,
        "start_time": now,
        "end_time": now,
        "latency_ms": None,
        "status": "success",
        "ide": "",
        "environment": "default",
        "metadata": meta,
    }

    audit = {
        "event_id": str(uuid.uuid4()),
        "timestamp": now,
        "actor_id": user_id,
        "actor_email": user_email,
        "actor_role": user_role,
        "action": action,
        "resource_type": "agent",
        "resource_id": agent_id or "",
        "resource_name": resource_name,
        "detail": ", ".join(f"{k}={v}" for k, v in meta.items()) if meta else "",
    }

    task = asyncio.create_task(_emit(trace, span, audit))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
