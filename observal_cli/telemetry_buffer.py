# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Lightweight SQLite buffer for offline telemetry events.

Stores telemetry events locally when the Observal server is unreachable,
and provides methods to flush them when connectivity is restored.

Database location: ~/.observal/telemetry_buffer.db
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

DB_PATH = Path.home() / ".observal" / "telemetry_buffer.db"
MAX_EVENTS = 10_000
SENT_TTL_HOURS = 24
MAX_RETRIES = 3
BATCH_SIZE = 50


def _connect() -> sqlite3.Connection:
    """Open (or create) the telemetry buffer database with WAL mode."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=3000")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pending_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            event_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            last_attempt TEXT,
            status TEXT NOT NULL DEFAULT 'pending'
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON pending_events(status)")
    conn.commit()
    return conn


def buffer_event(payload: str, event_type: str = "hook") -> None:
    """Write a single event to the local buffer.

    Enforces the FIFO cap: if the buffer exceeds MAX_EVENTS, the oldest
    pending rows are deleted to make room.
    """
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO pending_events (event_type, payload) VALUES (?, ?)",
            (event_type, payload),
        )
        conn.commit()
        _enforce_cap(conn)
    finally:
        conn.close()


def get_pending(limit: int = BATCH_SIZE) -> list[dict]:
    """Return up to *limit* pending events ordered oldest-first."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, event_type, payload FROM pending_events "
            "WHERE status = 'pending' AND attempts < ? "
            "ORDER BY id ASC LIMIT ?",
            (MAX_RETRIES, limit),
        ).fetchall()
        return [{"id": r[0], "event_type": r[1], "payload": r[2]} for r in rows]
    finally:
        conn.close()


def mark_sent(event_ids: list[int]) -> None:
    """Mark events as successfully sent."""
    if not event_ids:
        return
    conn = _connect()
    try:
        placeholders = ",".join("?" for _ in event_ids)
        conn.execute(
            f"UPDATE pending_events SET status = 'sent', last_attempt = datetime('now') WHERE id IN ({placeholders})",
            event_ids,
        )
        conn.commit()
    finally:
        conn.close()


def mark_failed(event_ids: list[int]) -> None:
    """Increment attempt counter for events that failed to send."""
    if not event_ids:
        return
    conn = _connect()
    try:
        placeholders = ",".join("?" for _ in event_ids)
        conn.execute(
            f"UPDATE pending_events SET attempts = attempts + 1, "
            f"last_attempt = datetime('now'), "
            f"status = CASE WHEN attempts + 1 >= {MAX_RETRIES} THEN 'failed' ELSE 'pending' END "
            f"WHERE id IN ({placeholders})",
            event_ids,
        )
        conn.commit()
    finally:
        conn.close()


def cleanup() -> int:
    """Delete sent events older than SENT_TTL_HOURS. Returns rows deleted."""
    conn = _connect()
    try:
        cutoff = (datetime.now(UTC) - timedelta(hours=SENT_TTL_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
        cur = conn.execute(
            "DELETE FROM pending_events WHERE status = 'sent' AND created_at < ?",
            (cutoff,),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def stats() -> dict:
    """Return buffer statistics for the status command."""
    conn = _connect()
    try:
        pending = conn.execute("SELECT COUNT(*) FROM pending_events WHERE status = 'pending'").fetchone()[0]
        failed = conn.execute("SELECT COUNT(*) FROM pending_events WHERE status = 'failed'").fetchone()[0]
        sent = conn.execute("SELECT COUNT(*) FROM pending_events WHERE status = 'sent'").fetchone()[0]
        oldest_row = conn.execute(
            "SELECT created_at FROM pending_events WHERE status = 'pending' ORDER BY id ASC LIMIT 1"
        ).fetchone()
        last_sync_row = conn.execute(
            "SELECT last_attempt FROM pending_events WHERE status = 'sent' ORDER BY last_attempt DESC LIMIT 1"
        ).fetchone()
        return {
            "pending": pending,
            "failed": failed,
            "sent": sent,
            "total": pending + failed + sent,
            "oldest_pending": oldest_row[0] if oldest_row else None,
            "last_sync": last_sync_row[0] if last_sync_row else None,
        }
    finally:
        conn.close()


def _enforce_cap(conn: sqlite3.Connection) -> None:
    """Delete oldest pending events when buffer exceeds MAX_EVENTS."""
    count = conn.execute("SELECT COUNT(*) FROM pending_events").fetchone()[0]
    if count > MAX_EVENTS:
        excess = count - MAX_EVENTS
        conn.execute(
            "DELETE FROM pending_events WHERE id IN (  SELECT id FROM pending_events ORDER BY id ASC LIMIT ?)",
            (excess,),
        )
        conn.commit()
