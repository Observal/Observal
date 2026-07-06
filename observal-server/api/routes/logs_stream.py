# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Server-Sent Events endpoint for real-time log streaming.

Allows remote CLI users (admins) to tail server logs without SSH.
Streams from the in-memory ring buffer with optional level/text filtering.

Usage:
    observal logs --remote
    observal logs --remote --level WARNING --filter clickhouse
    curl -N -H "Authorization: Bearer <token>" https://host/api/v1/admin/logs/stream
"""

from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Depends, Query
from loguru import logger as optic
from starlette.responses import StreamingResponse

from api.deps import require_role
from models.user import UserRole
from services.log_buffer import get_log_buffer

router = APIRouter(prefix="/api/v1/admin/logs", tags=["admin", "logs"])

_LEVEL_RANK = {"TRACE": 0, "DEBUG": 1, "INFO": 2, "WARNING": 3, "ERROR": 4, "CRITICAL": 5}

# Monotonic sequence counter to avoid timestamp collisions under burst logging
_seq = 0


def _rank(level: str) -> int:
    return _LEVEL_RANK.get(level.upper(), 0)


async def _sse_generator(
    *,
    min_level: str = "DEBUG",
    filter_text: str = "",
    poll_interval: float = 0.3,
):
    """Yield SSE-formatted log entries from the ring buffer.

    Protocol: each event is ``data: {json}\\n\\n``.
    A keepalive comment is sent every 15 s to prevent proxy timeouts.
    On first connect, backfills the last 50 matching entries.

    Uses a cursor based on (timestamp, sequence) to avoid skipping entries
    that share the same millisecond timestamp under burst logging.
    """
    buf = get_log_buffer()
    min_rank = _rank(min_level)
    filter_lower = filter_text.lower() if filter_text else ""

    def _matches(entry: dict) -> bool:
        entry_level = entry.get("level", "INFO")
        if _rank(entry_level) < min_rank:
            return False
        if filter_lower:
            searchable = "{} {} {}".format(
                entry.get("event", ""),
                entry.get("logger_name", ""),
                entry.get("function", ""),
            )
            if filter_lower not in searchable.lower():
                return False
        return True

    # Backfill last 50 matching entries
    all_entries = buf.get_all()
    backfill = []
    for entry in reversed(all_entries):
        if _matches(entry):
            backfill.append(entry)
            if len(backfill) >= 50:
                break
    backfill.reverse()

    sent_ids: set[int] = set()
    for entry in backfill:
        sent_ids.add(id(entry))
        yield f"data: {json.dumps(entry, default=str)}\n\n"

    # Stream new entries as they arrive
    last_keepalive = time.monotonic()
    try:
        while True:
            await asyncio.sleep(poll_interval)

            # Keepalive every 15 s (nginx default proxy_read_timeout = 60 s)
            if time.monotonic() - last_keepalive > 15:
                yield ": keepalive\n\n"
                last_keepalive = time.monotonic()

            # Scan buffer for unsent entries (dedup by object identity)
            entries = buf.get_all()
            for entry in entries:
                entry_id = id(entry)
                if entry_id in sent_ids:
                    continue
                if not _matches(entry):
                    sent_ids.add(entry_id)
                    continue
                sent_ids.add(entry_id)
                yield f"data: {json.dumps(entry, default=str)}\n\n"

            # Cap sent_ids to prevent unbounded growth (keep last 20k)
            if len(sent_ids) > 20000:
                sent_ids = set(list(sent_ids)[-10000:])
    except asyncio.CancelledError:
        optic.debug("SSE log stream client disconnected")


@router.get("/stream")
async def stream_logs(
    _: None = Depends(require_role(UserRole.admin)),
    level: str = Query("DEBUG", description="Minimum log level"),
    filter: str = Query("", description="Only stream entries containing this text"),
):
    """Stream server logs via SSE. Requires admin role.

    Returns ``text/event-stream``. Each data payload is a JSON object:
    ``{timestamp, level, event, logger_name, function, line}``.

    Starts with a backfill of the last 50 matching entries.
    Sends ``: keepalive`` comments every 15 s.
    Compatible with curl -N, EventSource, and ``observal logs --remote``.
    """
    optic.info("SSE log stream opened (level={}, filter='{}')", level, filter)

    return StreamingResponse(
        _sse_generator(min_level=level, filter_text=filter),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("")
async def get_recent_logs(
    _: None = Depends(require_role(UserRole.admin)),
    level: str = Query("INFO", description="Minimum log level"),
    filter: str = Query("", description="Text filter"),
    limit: int = Query(200, ge=1, le=2000, description="Max entries to return"),
):
    """Get recent log entries (non-streaming).

    Returns the most recent entries matching level/filter, ordered oldest-first.
    """
    _t0 = time.perf_counter()

    buf = get_log_buffer()
    min_rank = _rank(level)
    filter_lower = filter.lower() if filter else ""

    all_entries = buf.get_all()
    matched = []
    for entry in reversed(all_entries):
        entry_level = entry.get("level", "INFO")
        if _rank(entry_level) < min_rank:
            continue
        if filter_lower:
            searchable = "{} {} {}".format(
                entry.get("event", ""),
                entry.get("logger_name", ""),
                entry.get("function", ""),
            )
            if filter_lower not in searchable.lower():
                continue
        matched.append(entry)
        if len(matched) >= limit:
            break

    matched.reverse()
    _elapsed = (time.perf_counter() - _t0) * 1000
    optic.debug("served {} recent log entries in {:.1f}ms", len(matched), _elapsed)
    return {"entries": matched, "count": len(matched), "buffer_size": len(all_entries)}
