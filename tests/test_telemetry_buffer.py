# SPDX-FileCopyrightText: 2026 Sameer Saxena <saxena.same@northeastern.edu>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for the offline telemetry buffer (observal_cli.telemetry_buffer)."""

from __future__ import annotations

import sqlite3
from unittest.mock import patch

import pytest

from observal_cli import telemetry_buffer


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path):
    """Point the buffer at a throwaway SQLite file so tests never touch ~/.observal."""
    with patch.object(telemetry_buffer, "DB_PATH", tmp_path / "buf.db"):
        yield tmp_path / "buf.db"


def _row_count(db_path, status=None):
    conn = sqlite3.connect(str(db_path))
    if status:
        n = conn.execute(
            "SELECT COUNT(*) FROM pending_events WHERE status = ?", (status,)
        ).fetchone()[0]
    else:
        n = conn.execute("SELECT COUNT(*) FROM pending_events").fetchone()[0]
    conn.close()
    return n


def test_buffer_event_inserts_row(_isolated_db):
    """A buffered event creates exactly one pending row."""
    telemetry_buffer.buffer_event('{"session": "abc"}', event_type="hook")
    assert _row_count(_isolated_db) == 1


def test_buffer_event_default_type(_isolated_db):
    """event_type defaults to 'hook' when not specified."""
    telemetry_buffer.buffer_event('{"x": 1}')
    conn = sqlite3.connect(str(_isolated_db))
    row = conn.execute("SELECT event_type FROM pending_events").fetchone()
    conn.close()
    assert row[0] == "hook"


def test_buffer_event_custom_type(_isolated_db):
    """Caller can set a custom event_type."""
    telemetry_buffer.buffer_event('{"x": 1}', event_type="session")
    conn = sqlite3.connect(str(_isolated_db))
    row = conn.execute("SELECT event_type FROM pending_events").fetchone()
    conn.close()
    assert row[0] == "session"


def test_fifo_cap_drops_oldest(_isolated_db):
    """When the buffer exceeds MAX_EVENTS the oldest rows are pruned."""
    with patch.object(telemetry_buffer, "MAX_EVENTS", 3):
        for i in range(5):
            telemetry_buffer.buffer_event(f'{{"n": {i}}}')

    assert _row_count(_isolated_db) == 3
    conn = sqlite3.connect(str(_isolated_db))
    payloads = [
        r[0]
        for r in conn.execute(
            "SELECT payload FROM pending_events ORDER BY id"
        ).fetchall()
    ]
    conn.close()
    assert '{"n": 0}' not in payloads
    assert '{"n": 1}' not in payloads
    assert '{"n": 4}' in payloads


def test_get_pending_oldest_first(_isolated_db):
    """Events come back in insertion order."""
    telemetry_buffer.buffer_event('{"a": 1}')
    telemetry_buffer.buffer_event('{"a": 2}')
    results = telemetry_buffer.get_pending()
    assert len(results) == 2
    assert results[0]["payload"] == '{"a": 1}'


def test_get_pending_respects_limit(_isolated_db):
    """Limit caps the number of returned events."""
    for i in range(10):
        telemetry_buffer.buffer_event(f'{{"n": {i}}}')
    assert len(telemetry_buffer.get_pending(limit=3)) == 3


def test_get_pending_skips_exhausted_retries(_isolated_db):
    """Events that hit MAX_RETRIES no longer appear in get_pending."""
    telemetry_buffer.buffer_event('{"ok": true}')
    telemetry_buffer.buffer_event('{"doomed": true}')
    events = telemetry_buffer.get_pending()
    doomed_id = events[1]["id"]

    for _ in range(telemetry_buffer.MAX_RETRIES):
        telemetry_buffer.mark_failed([doomed_id])

    remaining = telemetry_buffer.get_pending()
    assert len(remaining) == 1
    assert remaining[0]["payload"] == '{"ok": true}'


def test_get_pending_empty_buffer(_isolated_db):
    """Empty buffer returns an empty list, not an error."""
    assert telemetry_buffer.get_pending() == []


def test_mark_sent(_isolated_db):
    """mark_sent flips status so the event no longer appears as pending."""
    telemetry_buffer.buffer_event('{"x": 1}')
    eid = telemetry_buffer.get_pending()[0]["id"]
    telemetry_buffer.mark_sent([eid])

    assert telemetry_buffer.get_pending() == []
    assert _row_count(_isolated_db, status="sent") == 1


def test_mark_sent_empty_list(_isolated_db):
    """Passing an empty list is a safe no-op."""
    telemetry_buffer.mark_sent([])


def test_mark_failed_increments_attempts(_isolated_db):
    """First failure keeps the event pending for retry."""
    telemetry_buffer.buffer_event('{"x": 1}')
    eid = telemetry_buffer.get_pending()[0]["id"]
    telemetry_buffer.mark_failed([eid])

    pending = telemetry_buffer.get_pending()
    assert len(pending) == 1


def test_mark_failed_exhausts_retries(_isolated_db):
    """After MAX_RETRIES failures the event moves to 'failed' status."""
    telemetry_buffer.buffer_event('{"x": 1}')
    eid = telemetry_buffer.get_pending()[0]["id"]

    for _ in range(telemetry_buffer.MAX_RETRIES):
        telemetry_buffer.mark_failed([eid])

    assert telemetry_buffer.get_pending() == []
    assert _row_count(_isolated_db, status="failed") == 1


def test_mark_failed_empty_list(_isolated_db):
    """Passing an empty list is a safe no-op."""
    telemetry_buffer.mark_failed([])


def test_cleanup_deletes_old_sent_events(_isolated_db):
    """Sent events older than SENT_TTL_HOURS are removed."""
    telemetry_buffer.buffer_event('{"old": true}')
    eid = telemetry_buffer.get_pending()[0]["id"]
    telemetry_buffer.mark_sent([eid])

    # backdate so it's past the 24-hour TTL
    conn = sqlite3.connect(str(_isolated_db))
    conn.execute(
        "UPDATE pending_events SET created_at = datetime('now', '-48 hours')"
    )
    conn.commit()
    conn.close()

    assert telemetry_buffer.cleanup() == 1
    assert _row_count(_isolated_db) == 0


def test_cleanup_keeps_recent_sent_events(_isolated_db):
    """Sent events within the TTL window are kept."""
    telemetry_buffer.buffer_event('{"recent": true}')
    eid = telemetry_buffer.get_pending()[0]["id"]
    telemetry_buffer.mark_sent([eid])

    assert telemetry_buffer.cleanup() == 0
    assert _row_count(_isolated_db) == 1


def test_cleanup_ignores_pending_events(_isolated_db):
    """Cleanup only touches sent rows, never pending ones."""
    telemetry_buffer.buffer_event('{"still_pending": true}')

    conn = sqlite3.connect(str(_isolated_db))
    conn.execute(
        "UPDATE pending_events SET created_at = datetime('now', '-48 hours')"
    )
    conn.commit()
    conn.close()

    assert telemetry_buffer.cleanup() == 0
    assert _row_count(_isolated_db) == 1


def test_stats_empty_buffer(_isolated_db):
    """Fresh buffer reports all zeros."""
    s = telemetry_buffer.stats()
    assert s["pending"] == 0
    assert s["failed"] == 0
    assert s["sent"] == 0
    assert s["total"] == 0
    assert s["oldest_pending"] is None
    assert s["last_sync"] is None


def test_stats_reflects_mixed_statuses(_isolated_db):
    """Stats accurately counts events across all three statuses."""
    for i in range(4):
        telemetry_buffer.buffer_event(f'{{"n": {i}}}')

    events = telemetry_buffer.get_pending()
    telemetry_buffer.mark_sent([events[0]["id"]])
    for _ in range(telemetry_buffer.MAX_RETRIES):
        telemetry_buffer.mark_failed([events[1]["id"]])

    s = telemetry_buffer.stats()
    assert s["sent"] == 1
    assert s["failed"] == 1
    assert s["pending"] == 2
    assert s["total"] == 4
    assert s["oldest_pending"] is not None
    assert s["last_sync"] is not None
