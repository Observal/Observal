# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Integration tests for the DuckDB analytics store.

Unlike the legacy ClickHouse tests these run against a real DuckDB file
(tmp_path) rather than mocking the transport - the whole point of the port is
that the engine is in-process and cheap to test for real.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest


@pytest.fixture()
def duckdb_db(tmp_path, monkeypatch):
    """Point the analytics store at a fresh DuckDB file per test."""
    from config import settings
    from services.duckdb import close_con
    from services.duckdb.migrations import run_duckdb_migrations

    close_con()
    monkeypatch.setattr(settings, "DUCKDB_PATH", str(tmp_path / "test.duckdb"))
    monkeypatch.setattr(settings, "DUCKDB_READ_ONLY", False)
    asyncio.run(run_duckdb_migrations())
    yield tmp_path / "test.duckdb"
    close_con()


def _event(session_id: str, line_offset: int, **overrides) -> dict:
    row = {
        "session_id": session_id,
        "project_id": "p1",
        "user_id": "u1",
        "harness": "claude_code",
        "line_offset": line_offset,
        "event_type": "user_prompt",
        "timestamp": "2026-08-01 12:00:00.000",
        "line_hash": f"h{line_offset}",
        "source_sha256": f"sha{line_offset}",
        "content_preview": "preview",
        "content_length": 7,
        "raw_line": '{"type":"user","text":"hello"}',
        "credits": 1.5,
        "input_tokens": 10,
        "output_tokens": 5,
        "cache_read_tokens": 2,
        "cache_write_tokens": 1,
        "model": "claude-4",
        "uuid": None,
        "parent_uuid": None,
        "tool_name": None,
        "tool_id": None,
        "agent_id": "agent-1",
        "agent_version": "1.0.0",
        "layer_hash": "lh",
        "parent_session_id": None,
    }
    row.update(overrides)
    return row


# ── Schema & migrations ──────────────────────────────────────────────────────


def test_migrations_create_all_tables(duckdb_db):
    from services.duckdb import _query

    resp = asyncio.run(_query("SELECT table_name FROM information_schema.tables WHERE table_schema='main'"))
    resp.raise_for_status()
    tables = {r["table_name"] for r in resp.json()["data"]}
    assert {
        "security_events",
        "audit_log",
        "webhook_deliveries",
        "session_events",
        "session_checkpoints",
        "session_stats_agg",
        "layer_snapshots",
        "duckdb_schema_migrations",
    } <= tables


def test_migrations_are_idempotent(duckdb_db):
    from services.duckdb import _query
    from services.duckdb.migrations import run_duckdb_migrations

    asyncio.run(run_duckdb_migrations())  # second run must be a no-op
    resp = asyncio.run(_query("SELECT version FROM duckdb_schema_migrations"))
    versions = [r["version"] for r in resp.json()["data"]]
    assert versions == ["001_baseline"]


def test_split_sql_keeps_quoted_semicolons_and_strips_comments():
    from services.duckdb.migrations import _split_sql

    sql = "-- comment\n# SPDX tag\nSELECT 'a;b';\nSELECT 2;\n"
    assert _split_sql(sql) == ["SELECT 'a;b'", "SELECT 2"]


# ── Insert & dedup semantics (ReplacingMergeTree -> INSERT OR REPLACE) ───────


def test_session_events_dedup_on_reingest(duckdb_db):
    from services.duckdb import _query, insert_session_events

    rows = [_event("s1", i) for i in range(10)]
    asyncio.run(insert_session_events(rows))
    # Re-ingest the first 5 with mutated payloads: same PK must replace.
    mutated = [_event("s1", i, content_preview="v2") for i in range(5)]
    asyncio.run(insert_session_events(mutated))

    resp = asyncio.run(_query("SELECT count(*) AS c FROM session_events"))
    assert resp.json()["data"][0]["c"] == 10
    resp = asyncio.run(
        _query("SELECT content_preview AS cp FROM session_events WHERE line_offset = 0")
    )
    assert resp.json()["data"][0]["cp"] == "v2"


def test_checkpoint_upsert_and_rewind(duckdb_db):
    from services.duckdb import insert_session_checkpoint, query_session_checkpoint

    asyncio.run(insert_session_checkpoint("s1", "p1", "u1", "claude_code", 50, 1000))
    assert asyncio.run(query_session_checkpoint("s1", "p1", "u1", "claude_code")) == (50, 1000)
    # Rewind (audit flow): older line, newer checkpoint_version.
    asyncio.run(insert_session_checkpoint("s1", "p1", "u1", "claude_code", 20, 400))
    assert asyncio.run(query_session_checkpoint("s1", "p1", "u1", "claude_code")) == (20, 400)


def test_layer_snapshot_replace(duckdb_db):
    from services.duckdb import _query, insert_layer_snapshot

    row = {
        "hash": "abc",
        "project_id": "p1",
        "user_id": "u1",
        "harness": "pi",
        "content": '{"v": 1}',
        "file_count": 3,
        "total_size": 100,
        "lockfile_hash": "lock",
    }
    asyncio.run(insert_layer_snapshot(row))
    asyncio.run(insert_layer_snapshot({**row, "content": '{"v": 2}'}))
    resp = asyncio.run(_query("SELECT count(*) AS c, any_value(content) AS content FROM layer_snapshots"))
    data = resp.json()["data"][0]
    assert data["c"] == 1
    assert data["content"] == '{"v": 2}'


# ── Rollup (replaces the materialized view) ──────────────────────────────────


def test_refresh_session_summary_aggregates(duckdb_db):
    from services.duckdb import _query, insert_session_events, refresh_session_summary

    rows = [
        _event("s1", 0, event_type="user_prompt", credits=1.5),
        _event("s1", 1, event_type="tool_call", credits=2.5),
        _event("s1", 2, event_type="tool_result", credits=2.5),
    ]
    asyncio.run(insert_session_events(rows))
    asyncio.run(refresh_session_summary("s1", "p1", "u1", "claude_code"))

    resp = asyncio.run(_query("SELECT * FROM session_stats_agg WHERE session_id = 's1'"))
    row = resp.json()["data"][0]
    assert row["event_count"] == 3
    assert row["prompt_count"] == 1
    assert row["tool_call_count"] == 1
    assert row["tool_result_count"] == 1
    assert row["total_credits"] == 2.5  # max(), not sum()
    assert row["model"] == "claude-4"
    assert row["agent_id"] == "agent-1"
    assert row["input_tokens"] == 30
    # Refresh again after adding an event: summary must reflect the new state.
    asyncio.run(insert_session_events([_event("s1", 3, event_type="user_prompt")]))
    asyncio.run(refresh_session_summary("s1", "p1", "u1", "claude_code"))
    row = asyncio.run(_query("SELECT * FROM session_stats_agg WHERE session_id = 's1'")).json()["data"][0]
    assert row["event_count"] == 4
    assert row["prompt_count"] == 2


def test_refresh_session_summary_ignores_unrendered_rows(duckdb_db):
    from services.duckdb import _query, insert_session_events, refresh_session_summary

    rows = [
        _event("s1", 0, event_type="user_prompt"),
        _event("s1", 1, event_type="tool_call", rendered=0),
    ]
    asyncio.run(insert_session_events(rows))
    asyncio.run(refresh_session_summary("s1", "p1", "u1", "claude_code"))
    row = asyncio.run(_query("SELECT * FROM session_stats_agg WHERE session_id = 's1'")).json()["data"][0]
    assert row["event_count"] == 1
    assert row["tool_call_count"] == 0


# ── Query helpers ────────────────────────────────────────────────────────────


def test_source_records_after_and_manifest(duckdb_db):
    from services.duckdb import (
        insert_session_events,
        query_existing_for_dedup,
        query_session_source_manifest,
        query_source_records_after,
    )

    rows = [
        _event("s1", i, source_end_offset=(i + 1) * 100, is_source_record=1 if i % 2 == 0 else 0)
        for i in range(10)
    ]
    asyncio.run(insert_session_events(rows))

    after = asyncio.run(query_source_records_after("s1", "p1", "u1", "claude_code", 4))
    assert after == [(6, 700), (8, 900)]
    manifest = asyncio.run(query_session_source_manifest("s1", "p1", "u1", "claude_code"))
    assert manifest[0] == (0, 100, "sha0")
    assert len(manifest) == 5
    dedup = asyncio.run(query_existing_for_dedup("s1", "p1", "u1", "claude_code", 2, 6))
    assert dedup == {2: "h2", 4: "h4", 6: "h6"}


def test_recent_events_rollup(duckdb_db):
    from services.duckdb import insert_session_events, query_recent_events, refresh_session_summary

    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.000")
    rows = [_event("s1", i, event_type="tool_call", timestamp=now) for i in range(3)]
    asyncio.run(insert_session_events(rows))
    asyncio.run(refresh_session_summary("s1", "p1", "u1", "claude_code"))
    result = asyncio.run(query_recent_events(60))
    assert result == {"tool_call_events": 3, "agent_interaction_events": 1}


def test_query_recent_events_empty_db(duckdb_db):
    from services.duckdb import query_recent_events

    assert asyncio.run(query_recent_events(60)) == {"tool_call_events": 0, "agent_interaction_events": 0}


# ── Compatibility layer (legacy ClickHouse syntax safety net) ────────────────


def test_compat_final_placeholders_format_json(duckdb_db):
    from services.duckdb import _query, insert_session_events

    asyncio.run(insert_session_events([_event("s1", 0)]))
    resp = asyncio.run(
        _query(
            "SELECT count() AS c FROM session_events FINAL WHERE session_id = {sid:String} FORMAT JSON",
            {"param_sid": "s1"},
        )
    )
    resp.raise_for_status()
    assert resp.json()["data"][0]["c"] == 1


def test_compat_scalar_functions(duckdb_db):
    from services.duckdb import _query

    resp = asyncio.run(_query("SELECT now64(3) AS ts, toUInt64(toUnixTimestamp64Milli(now64(3))) AS ms"))
    row = resp.json()["data"][0]
    assert isinstance(row["ts"], str)  # json() returns CH-style timestamp strings
    assert isinstance(row["ms"], int) and row["ms"] > 0


def test_compat_interval_param_and_settings_clause(duckdb_db):
    from services.duckdb import _query, insert_session_events

    asyncio.run(insert_session_events([_event("s1", 0)]))
    resp = asyncio.run(
        _query(
            "SELECT count() AS c FROM session_events "
            "WHERE timestamp < now() - INTERVAL {days:UInt32} DAY SETTINGS max_execution_time = 300 FORMAT JSON",
            {"param_days": "1"},
        )
    )
    resp.raise_for_status()
    assert resp.json()["data"][0]["c"] == 1


def test_unused_params_are_dropped(duckdb_db):
    from services.duckdb import _query

    resp = asyncio.run(_query("SELECT 0 AS error_rate", {"param_lookback": "5"}))
    resp.raise_for_status()
    assert resp.json()["data"][0]["error_rate"] == 0


def test_error_result_shape_and_raise_for_status(duckdb_db):
    from services.duckdb import AnalyticsQueryError, _query

    resp = asyncio.run(_query("SELECT * FROM table_that_does_not_exist"))
    assert resp.status_code >= 400
    assert resp.text
    with pytest.raises(AnalyticsQueryError):
        resp.raise_for_status()


def test_timestamps_serialize_as_clickhouse_strings(duckdb_db):
    """Downstream code (json.dumps, str slicing) depends on CH-style strings."""
    from services.duckdb import _query, insert_session_events

    asyncio.run(insert_session_events([_event("s1", 0)]))
    resp = asyncio.run(_query("SELECT timestamp AS ts FROM session_events"))
    assert resp.json()["data"][0]["ts"] == "2026-08-01 12:00:00.000"


# ── Retention (replaces ClickHouse DDL TTLs) ─────────────────────────────────


def test_global_retention_purge(duckdb_db):
    from services.duckdb import _query, insert_session_events
    from services.duckdb.insert import _AUDIT_COLUMNS
    from services.duckdb.insert import _insert as raw_insert
    from services.retention import _purge_global_tables

    old = (datetime.now(UTC) - timedelta(days=800)).strftime("%Y-%m-%d %H:%M:%S.000")
    new = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.000")
    for ts, eid in [(old, "old"), (new, "new")]:
        row = {c: "" for c in _AUDIT_COLUMNS}
        row.update(
            {
                "event_id": eid,
                "timestamp": ts,
                "actor_id": "u",
                "actor_email": "e",
                "actor_role": "r",
                "action": "a",
                "resource_type": "t",
                "status_code": 0,
                "duration_ms": 0.0,
            }
        )
        asyncio.run(asyncio.to_thread(raw_insert, "audit_log", _AUDIT_COLUMNS, [row]))

    # session_events: one old row with a raw_line that must be scrubbed
    asyncio.run(insert_session_events([_event("s1", 0, timestamp=old)]))
    asyncio.run(insert_session_events([_event("s1", 1, timestamp=new)]))

    asyncio.run(_purge_global_tables())

    resp = asyncio.run(_query("SELECT event_id FROM audit_log ORDER BY event_id"))
    assert [r["event_id"] for r in resp.json()["data"]] == ["new"]

    resp = asyncio.run(_query("SELECT line_offset, raw_line FROM session_events ORDER BY line_offset"))
    rows = resp.json()["data"]
    assert rows[0]["raw_line"] == ""  # older than 30d: scrubbed
    assert rows[1]["raw_line"] != ""  # fresh: kept


# ── Concurrency ──────────────────────────────────────────────────────────────


def test_concurrent_reads_and_writes(duckdb_db):
    """Many coroutines mixing inserts and queries must not corrupt or deadlock."""
    from services.duckdb import _query, insert_session_events

    async def writer(session: str):
        await insert_session_events([_event(session, i) for i in range(20)])

    async def reader():
        r = await _query("SELECT count(*) AS c FROM session_events")
        r.raise_for_status()

    async def main():
        await asyncio.gather(
            *(writer(f"s{n}") for n in range(10)),
            *(reader() for _ in range(20)),
        )

    asyncio.run(main())
    resp = asyncio.run(_query("SELECT count(*) AS c FROM session_events"))
    assert resp.json()["data"][0]["c"] == 200
