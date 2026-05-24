# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Loguru audit sink: buffers records and batch-inserts to ClickHouse."""

from __future__ import annotations

import asyncio
import json
from collections import deque
from datetime import UTC, datetime

from loguru import logger as optic

_buffer: deque[dict] = deque()
_buffer_lock = asyncio.Lock()
_FLUSH_INTERVAL = 2.0
_FLUSH_THRESHOLD = 500


async def audit_sink(message: str) -> None:
    """Async loguru sink. Receives serialized JSON messages."""
    try:
        record = json.loads(str(message))
    except (json.JSONDecodeError, TypeError):
        return

    extra = record.get("record", {}).get("extra", {})
    if not extra.get("audit"):
        return

    # Format timestamp for ClickHouse DateTime64 (no timezone suffix)
    ts_float = record["record"]["time"].get("timestamp", 0)
    if ts_float:
        dt = datetime.fromtimestamp(ts_float, tz=UTC)
        timestamp = dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:23]
    else:
        timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:23]

    row = {
        "event_id": extra.get("event_id", ""),
        "timestamp": timestamp,
        "actor_id": extra.get("actor_id", ""),
        "actor_email": extra.get("actor_email", ""),
        "actor_role": extra.get("actor_role", "anonymous"),
        "action": extra.get("action", ""),
        "resource_type": extra.get("resource_type", ""),
        "resource_id": extra.get("resource_id", ""),
        "resource_name": extra.get("resource_name", ""),
        "http_method": extra.get("http_method", ""),
        "http_path": extra.get("http_path", ""),
        "status_code": extra.get("status_code", 0),
        "ip_address": extra.get("ip_address", ""),
        "user_agent": extra.get("user_agent", ""),
        "detail": extra.get("detail", ""),
        "org_id": extra.get("org_id", ""),
        "sensitivity": extra.get("sensitivity", "standard"),
        "request_id": extra.get("request_id", ""),
        "outcome": extra.get("outcome", ""),
        "duration_ms": extra.get("duration_ms", 0.0),
        "chain_hash": extra.get("_chain_hash", ""),
        "source": extra.get("source", "server"),
    }

    async with _buffer_lock:
        _buffer.append(row)
        if len(_buffer) >= _FLUSH_THRESHOLD:
            await _flush()


async def _flush() -> None:
    """Flush the buffer to ClickHouse. Must be called under _buffer_lock."""
    if not _buffer:
        return
    batch = list(_buffer)
    _buffer.clear()
    try:
        from services.clickhouse import insert_audit_log

        await insert_audit_log(batch)
        optic.debug("audit sink flushed {} rows", len(batch))
    except Exception as e:
        optic.debug("audit sink flush failed, {} rows lost: {}", len(batch), e)
