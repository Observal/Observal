# SPDX-FileCopyrightText: 2026 Subramania Raja <dhanpraja231@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-FileCopyrightText: 2026 tsitu0 <tomsitu0102@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Session reconcile endpoint.

Receives enrichment payloads from the CLI Stop hook and crash-recovery
subprocess.  Checks for duplicate reconcile records (by subagent_id for
subagents, session_id for top-level) and stores enrichment metadata to
``otel_logs`` so it never overwrites raw transcript rows.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import get_current_user
from services.clickhouse import _query, insert_otel_logs

if TYPE_CHECKING:
    from models.user import User

router = APIRouter(prefix="/api/v1/telemetry", tags=["reconcile"])


class ReconcilePayload(BaseModel):
    session_id: str
    # Subagent attribution
    is_subagent: bool = False
    parent_session_id: str | None = None
    subagent_id: str | None = None
    agent_type: str | None = None
    agent_description: str | None = None
    # Enrichment counters
    conversation_turns: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_cache_creation_tokens: int = 0
    models_used: list[str] = []
    primary_model: str | None = None
    tool_use_count: int = 0
    thinking_turns: int = 0
    completeness_score: float = 1.0
    crash_recovered: bool = False


async def _session_has_data(session_id: str) -> bool:
    """Return True if session_events contains at least one row for this session.

    Intentionally omits FINAL: an existence check does not need full deduplication
    and FINAL on ReplacingMergeTree forces an expensive cross-part merge just to
    count rows.  An approximate count (potentially including not-yet-merged dupes)
    is correct for the reconcile gate — we only need to know the session exists.
    """
    sql = "SELECT count() AS cnt FROM session_events WHERE session_id = {sid:String} FORMAT JSON"
    try:
        r = await _query(sql, {"param_sid": session_id})
        r.raise_for_status()
        data = r.json().get("data", [{}])
        return int(data[0].get("cnt", 0)) > 0
    except Exception:
        return False


async def _already_reconciled(dedup_key: str, key_field: str, user_id: str) -> bool:
    """Return True if this user already has a reconcile_enrichment row for dedup_key."""
    sql = (
        "SELECT count() AS cnt FROM otel_logs "
        f"WHERE LogAttributes['event.name'] = 'reconcile_enrichment' "
        f"AND LogAttributes['{key_field}'] = {{key:String}} "
        "AND LogAttributes['user_id'] = {uid:String} FORMAT JSON"
    )
    try:
        r = await _query(sql, {"param_key": dedup_key, "param_uid": user_id})
        r.raise_for_status()
        data = r.json().get("data", [{}])
        return int(data[0].get("cnt", 0)) > 0
    except Exception:
        return False


async def _session_owned_by_user(session_id: str, user_id: str) -> bool:
    """Return True if session_events has at least one row owned by this user."""
    sql = (
        "SELECT count() AS cnt FROM session_events "
        "WHERE session_id = {sid:String} AND user_id = {uid:String} FORMAT JSON"
    )
    try:
        r = await _query(sql, {"param_sid": session_id, "param_uid": user_id})
        r.raise_for_status()
        data = r.json().get("data", [{}])
        return int(data[0].get("cnt", 0)) > 0
    except Exception:
        return False


@router.post("/reconcile")
async def reconcile_session(payload: ReconcilePayload, current_user: User = Depends(get_current_user)):
    """Store reconcile enrichment for a session, skipping duplicates.

    Dedup key:
    - Subagents: ``subagent_id`` (each agent run is unique)
    - Top-level sessions: ``session_id``

    Returns ``{"status": "reconciled"}`` on first write,
    ``{"status": "skipped"}`` if the record was already present,
    ``{"status": "no_data"}`` if the session has no transcript rows yet.
    """
    if not await _session_has_data(payload.session_id):
        return {"status": "no_data"}

    if not await _session_owned_by_user(payload.session_id, str(current_user.id)):
        raise HTTPException(status_code=403, detail="Session not found")

    if payload.is_subagent and payload.subagent_id:
        dedup_key = payload.subagent_id
        key_field = "subagent_id"
    else:
        dedup_key = payload.session_id
        key_field = "session_id"

    user_id = str(current_user.id)

    if await _already_reconciled(dedup_key, key_field, user_id):
        return {"status": "skipped"}

    attrs: dict[str, str] = {
        "event.name": "reconcile_enrichment",
        "session_id": payload.session_id,
        "user_id": user_id,
        "conversation_turns": str(payload.conversation_turns),
        "total_input_tokens": str(payload.total_input_tokens),
        "total_output_tokens": str(payload.total_output_tokens),
        "total_cache_read_tokens": str(payload.total_cache_read_tokens),
        "total_cache_creation_tokens": str(payload.total_cache_creation_tokens),
        "tool_use_count": str(payload.tool_use_count),
        "thinking_turns": str(payload.thinking_turns),
        "completeness_score": str(payload.completeness_score),
        "crash_recovered": str(payload.crash_recovered).lower(),
    }
    if payload.primary_model:
        attrs["primary_model"] = payload.primary_model
    if payload.models_used:
        attrs["models_used"] = ",".join(payload.models_used)
    if payload.is_subagent:
        attrs["is_subagent"] = "true"
        if payload.subagent_id:
            attrs["subagent_id"] = payload.subagent_id
        if payload.parent_session_id:
            attrs["parent_session_id"] = payload.parent_session_id
        if payload.agent_type:
            attrs["agent_type"] = payload.agent_type
        if payload.agent_description:
            attrs["agent_description"] = payload.agent_description

    row = {
        "Timestamp": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:23],
        "TraceId": "",
        "SpanId": "",
        "SeverityText": "INFO",
        "Body": f"reconcile_enrichment:{dedup_key}",
        "ResourceAttributes": {},
        "LogAttributes": attrs,
        "session_id": payload.session_id,
    }

    await insert_otel_logs([row])
    return {"status": "reconciled"}
