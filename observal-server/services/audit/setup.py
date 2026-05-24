# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Audit system initialization and teardown."""

from __future__ import annotations

import asyncio
import hashlib
import json

from loguru import logger

from .sink import _buffer_lock, _flush, audit_sink

_flush_task: asyncio.Task | None = None
_prev_hash: str = "0" * 64


def _chain_hash_patcher(record: dict) -> None:
    """Loguru patch: adds SHA-256 chain hash to audit records."""
    global _prev_hash
    if not record["extra"].get("audit"):
        return
    payload = _prev_hash + json.dumps(record["extra"], sort_keys=True, default=str)
    h = hashlib.sha256(payload.encode()).hexdigest()
    record["extra"]["_chain_hash"] = h
    _prev_hash = h


async def _periodic_flush() -> None:
    """Background task: flush audit buffer every 2 seconds."""
    while True:
        await asyncio.sleep(2.0)
        try:
            async with _buffer_lock:
                await _flush()
        except asyncio.CancelledError:
            raise
        except Exception:
            pass


def setup_audit() -> None:
    """Register the audit sink with loguru. Call once at server startup."""
    global _flush_task

    logger.configure(patcher=_chain_hash_patcher)

    logger.add(
        audit_sink,
        level="INFO",
        serialize=True,
        filter=lambda record: record["extra"].get("audit", False),
        enqueue=True,
    )

    try:
        loop = asyncio.get_running_loop()
        _flush_task = loop.create_task(_periodic_flush())
    except RuntimeError:
        pass


async def shutdown_audit() -> None:
    """Flush remaining buffer on shutdown."""
    global _flush_task
    if _flush_task:
        _flush_task.cancel()
        try:
            await _flush_task
        except asyncio.CancelledError:
            pass
        _flush_task = None

    async with _buffer_lock:
        await _flush()
