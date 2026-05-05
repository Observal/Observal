"""Session reconciliation endpoint — accepts full JSONL records from CLI
after parsing local session files. Stores everything: assistant messages,
user prompts, system messages, tool results, attachments."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Header, Request
from pydantic import BaseModel

from services.clickhouse import _query, insert_otel_logs

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/telemetry", tags=["telemetry"])


class ReconcilePayload(BaseModel):
    """Enrichment data for a single session."""

    session_id: str
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_cache_creation_tokens: int = 0
    models_used: list[str] = []
    primary_model: str | None = None
    total_cost_usd: float = 0.0
    service_tier: str | None = None
    conversation_turns: int = 0
    tool_use_count: int = 0
    thinking_turns: int = 0
    stop_reasons: dict[str, int] = {}
    completeness_score: float = 1.0
    per_turn: list[dict] = []
    records: list[dict] = []
    # Subagent attribution
    is_subagent: bool = False
    parent_session_id: str | None = None
    subagent_id: str | None = None
    agent_type: str | None = None
    agent_description: str | None = None


@router.post("/reconcile")
async def reconcile_session(
    payload: ReconcilePayload,
    request: Request,
    x_observal_user_id: str | None = Header(None),
):
    """Accept full session JSONL records and store in ClickHouse.

    Stores every record from the session file: assistant messages (with full
    text, thinking, tool_use), user prompts, system messages, attachments,
    and metadata. Also writes a summary enrichment event.
    """
    session_id = payload.session_id
    user_id = x_observal_user_id or "unknown"

    # Check if session exists in ClickHouse
    check_sql = """
        SELECT count() as cnt
        FROM otel_logs
        WHERE LogAttributes['session.id'] = {sid:String}
        LIMIT 1
        FORMAT JSON
    """
    try:
        resp = await _query(check_sql, {"param_sid": session_id})
        resp.raise_for_status()
        data = resp.json().get("data", [])
        existing_count = int(data[0]["cnt"]) if data else 0
    except Exception as e:
        logger.warning("reconcile_check_failed", session_id=session_id, error=str(e))
        existing_count = 0

    if existing_count == 0:
        logger.info("reconcile_no_existing_session", session_id=session_id)
        return {"status": "skipped", "reason": "no existing session data found"}

    # Check if already reconciled (avoid duplicates).
    if payload.is_subagent and payload.subagent_id:
        recon_check_sql = """
            SELECT count() as cnt
            FROM otel_logs
            WHERE LogAttributes['session.id'] = {sid:String}
              AND LogAttributes['event.name'] = 'reconcile_enrichment'
              AND LogAttributes['subagent_id'] = {subagent_id:String}
            LIMIT 1
            FORMAT JSON
        """
        recon_params = {"param_sid": session_id, "param_subagent_id": payload.subagent_id}
    else:
        recon_check_sql = """
            SELECT count() as cnt
            FROM otel_logs
            WHERE LogAttributes['session.id'] = {sid:String}
              AND LogAttributes['event.name'] = 'reconcile_enrichment'
              AND (LogAttributes['is_subagent'] = '' OR LogAttributes['is_subagent'] = 'false')
            LIMIT 1
            FORMAT JSON
        """
        recon_params = {"param_sid": session_id}

    try:
        resp = await _query(recon_check_sql, recon_params)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        already_reconciled = int(data[0]["cnt"]) if data else 0
    except Exception:
        already_reconciled = 0

    if already_reconciled > 0:
        return {"status": "skipped", "reason": "session already reconciled"}

    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")

    # Summary enrichment row
    enrichment_row = {
        "Timestamp": now,
        "TraceId": "",
        "SpanId": "",
        "SeverityText": "INFO",
        "SeverityNumber": 9,
        "ServiceName": "reconcile",
        "Body": f"Session reconciliation: {payload.conversation_turns} turns, {payload.primary_model or 'unknown'}",
        "LogAttributes": {
            "session.id": session_id,
            "event.name": "reconcile_enrichment",
            "user.id": user_id,
            "input_tokens": str(payload.total_input_tokens),
            "output_tokens": str(payload.total_output_tokens),
            "cache_read_tokens": str(payload.total_cache_read_tokens),
            "cache_creation_tokens": str(payload.total_cache_creation_tokens),
            "model": payload.primary_model or "",
            "models_used": ",".join(payload.models_used),
            "total_cost_usd": f"{payload.total_cost_usd:.6f}",
            "service_tier": payload.service_tier or "",
            "conversation_turns": str(payload.conversation_turns),
            "tool_use_count": str(payload.tool_use_count),
            "thinking_turns": str(payload.thinking_turns),
            "stop_reasons": json.dumps(payload.stop_reasons),
            "completeness_score": f"{payload.completeness_score:.2f}",
            "records_count": str(len(payload.records)),
            "reconciled": "true",
            "is_subagent": "true" if payload.is_subagent else "false",
            "subagent_id": payload.subagent_id or "",
            "parent_session_id": payload.parent_session_id or "",
            "agent_type": payload.agent_type or "",
            "agent_description": payload.agent_description or "",
        },
    }

    rows = [enrichment_row]

    # Store JSONL records — only types with content not captured by hooks.
    # Hooks already capture: api_request (tokens), tool_result, tool_decision,
    # hook_stop, user_prompt. JSONL uniquely provides: full assistant text,
    # thinking/CoT, tool_use inputs, and system messages.
    # Skip: metadata-only types (last-prompt, agent-setting, permission-mode,
    # file-history-snapshot, queue-operation, attachment) to reduce storage.
    content_types = {"assistant", "user", "system"}

    for seq, record in enumerate(payload.records, 1):
        record_type = record.get("type", "unknown")
        if record_type not in content_types:
            continue

        timestamp = record.get("timestamp") or now
        message = record.get("message", {})
        content = message.get("content", [])
        usage = message.get("usage", {}) or record.get("usage", {})

        # Extract content blocks
        text_parts = []
        thinking_parts = []
        tool_uses = []
        tool_use_details = []

        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    btype = block.get("type", "")
                    if btype == "text":
                        text_parts.append(block.get("text", ""))
                    elif btype == "thinking":
                        thinking_parts.append(block.get("thinking", ""))
                    elif btype == "tool_use":
                        tool_uses.append(block.get("name", "unknown"))
                        tool_use_details.append(
                            {
                                "name": block.get("name", ""),
                                "input": block.get("input", {}),
                            }
                        )
                    elif btype == "tool_result":
                        text_parts.append(str(block.get("content", ""))[:10000])
                elif isinstance(block, str):
                    text_parts.append(block)

        text = "\n".join(text_parts)
        thinking = "\n".join(thinking_parts)

        # Skip empty records (no text, no thinking, no tool use)
        if not text and not thinking and not tool_uses:
            continue

        # Build concise body for display
        if record_type == "assistant":
            if thinking:
                body = f"[thinking] {thinking[:300]}"
            elif text:
                body = text[:500]
            else:
                body = f"Tool use: {', '.join(tool_uses)}"
        elif record_type == "user":
            body = text[:500] if text else "User message"
        else:
            body = text[:500] if text else record_type

        attrs = {
            "session.id": session_id,
            "event.name": f"reconcile_{record_type}",
            "user.id": user_id,
            "record_type": record_type,
            "sequence": str(seq),
            "reconciled": "true",
        }

        # Store content
        if text:
            attrs["text"] = text
        if thinking:
            attrs["thinking"] = thinking
        if tool_uses:
            attrs["tool_uses"] = ",".join(tool_uses)
        if tool_use_details:
            attrs["tool_use_details"] = json.dumps(tool_use_details)

        # Token metadata for assistant records
        if record_type == "assistant":
            attrs["model"] = record.get("model") or message.get("model") or ""
            attrs["stop_reason"] = record.get("stop_reason") or message.get("stop_reason") or ""
            attrs["input_tokens"] = str(usage.get("input_tokens", 0))
            attrs["output_tokens"] = str(usage.get("output_tokens", 0))
            attrs["cache_read_tokens"] = str(usage.get("cache_read_input_tokens", 0))
            attrs["cache_creation_tokens"] = str(usage.get("cache_creation_input_tokens", 0))

        # Subagent attribution
        if payload.is_subagent:
            attrs["is_subagent"] = "true"
            attrs["subagent_id"] = payload.subagent_id or ""
            attrs["agent_type"] = payload.agent_type or ""

        row = {
            "Timestamp": timestamp if isinstance(timestamp, str) and len(timestamp) > 10 else now,
            "TraceId": "",
            "SpanId": "",
            "SeverityText": "INFO",
            "SeverityNumber": 9,
            "ServiceName": "reconcile",
            "Body": body,
            "LogAttributes": attrs,
        }
        rows.append(row)

    try:
        await insert_otel_logs(rows)
        logger.info(
            "reconcile_success",
            session_id=session_id,
            turns=payload.conversation_turns,
            records=len(payload.records),
            rows_inserted=len(rows),
        )
    except Exception as e:
        logger.error("reconcile_insert_failed", session_id=session_id, error=str(e))
        return {"status": "error", "reason": str(e)}

    return {
        "status": "reconciled",
        "session_id": session_id,
        "turns_ingested": payload.conversation_turns,
        "records_ingested": len(payload.records),
        "total_cost_usd": payload.total_cost_usd,
    }
