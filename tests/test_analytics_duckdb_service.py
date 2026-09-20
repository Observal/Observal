# SPDX-FileCopyrightText: 2026 Observal contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for the DuckDB analytics service, store, and migrations."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import httpx
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from services.analytics.duckdb.client import _normalize_ts
from services.analytics.duckdb.migrations import MigrationError, run_migrations
from services.analytics.duckdb.service import ServiceSettings, create_app
from services.analytics.duckdb.storage import AnalyticsStore

TOKEN = "test-analytics-token"


class _StoreResponse:
    def __init__(self, columns, rows):
        self.status_code = 200
        self._data = [dict(zip(columns, row, strict=True)) for row in rows]

    def raise_for_status(self):
        return None

    def json(self):
        return {"data": self._data, "row_count": len(self._data)}


def _store_query(store):
    async def query(sql, params=None):
        columns, rows = await store.query(sql, params)
        return _StoreResponse(columns, rows)

    return query


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def _settings(tmp_path) -> ServiceSettings:
    return ServiceSettings(
        DUCKDB_PATH=str(tmp_path / "analytics.duckdb"),
        DUCKDB_ANALYTICS_TOKEN=TOKEN,
        DUCKDB_THREADS=2,
        DUCKDB_READ_CONNECTIONS=2,
        DUCKDB_QUERY_TIMEOUT=10.0,
    )


@pytest.fixture()
def client(tmp_path):
    with TestClient(create_app(settings=_settings(tmp_path))) as test_client:
        yield test_client


def _session_event(**overrides) -> dict:
    row = {
        "session_id": "sess-1",
        "project_id": "default",
        "user_id": "user-1",
        "harness": "claude-code",
        "line_offset": 0,
        "event_type": "user_prompt",
        "timestamp": "2026-09-17 09:00:00.000",
        "content_preview": "hello",
        "content_length": 5,
        "raw_line": json.dumps({"type": "user_prompt"}),
        "ingested_at": "2026-09-17 09:00:01.000",
    }
    row.update(overrides)
    return row


async def test_session_manifest_paginates_beyond_service_result_limit(monkeypatch):
    import services.analytics.duckdb.query as query_module

    first_page = [
        {"line_offset": index, "source_end_offset": index + 1, "source_sha256": str(index)} for index in range(50_000)
    ]
    query = AsyncMock(
        side_effect=[
            _StoreResponse(
                ["line_offset", "source_end_offset", "source_sha256"], [tuple(row.values()) for row in first_page]
            ),
            _StoreResponse(["line_offset", "source_end_offset", "source_sha256"], [(50_000, 50_001, "50000")]),
        ]
    )
    monkeypatch.setattr(query_module._client, "_query", query)

    manifest = await query_module.query_session_source_manifest("session", "project", "user", "pi")

    assert len(manifest) == 50_001
    assert query.await_count == 2
    assert query.await_args_list[1].args[1]["after"] == "49999"


def test_timestamp_normalization_accepts_offsets_and_converts_to_utc():
    assert _normalize_ts("2026-09-18T03:12:00.123456+02:00") == "2026-09-18 01:12:00.123"
    assert _normalize_ts("2026-09-18T01:12:00Z") == "2026-09-18 01:12:00.000"


def test_service_refuses_to_start_without_token(tmp_path):
    settings = ServiceSettings(
        DUCKDB_PATH=str(tmp_path / "analytics.duckdb"),
        DUCKDB_STAGING_DIR=str(tmp_path / "staging"),
        DUCKDB_ANALYTICS_TOKEN="",
        DUCKDB_ALLOW_ANONYMOUS=False,
    )

    with (
        pytest.raises(RuntimeError, match="DUCKDB_ANALYTICS_TOKEN is required"),
        TestClient(create_app(settings=settings)),
    ):
        pass


def test_health_reports_schema_version(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["schema_version"] == "001_baseline"


def test_queries_require_a_token(client):
    assert client.post("/query", json={"sql": "SELECT 1"}).status_code == 401
    assert client.post("/query", json={"sql": "SELECT 1"}, headers={"Authorization": "Bearer nope"}).status_code == 401


def test_timestamptz_results_serialize_with_clickhouse_timestamp_shape(client):
    response = client.post(
        "/query",
        headers=_auth(),
        json={"sql": "SELECT TIMESTAMPTZ '2026-05-28 15:24:08.054+00' AS timestamp"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"] == [{"timestamp": "2026-05-28 15:24:08.054"}]


def test_query_round_trip_with_parameters(client):
    resp = client.post(
        "/query",
        headers=_auth(),
        json={"sql": "SELECT CAST($a AS INTEGER) + CAST($b AS INTEGER) AS total", "params": {"a": "1", "b": "2"}},
    )
    assert resp.status_code == 200
    assert resp.json()["data"] == [{"total": 3}]


def test_insert_session_events_accepts_ms_timestamps(client):
    resp = client.post(
        "/insert",
        headers=_auth(),
        json={
            "table": "session_events",
            "rows": [
                _session_event(),
                _session_event(line_offset=1, event_type="tool_call", tool_name="Bash"),
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["row_count"] == 2

    rows = client.post(
        "/query",
        headers=_auth(),
        json={
            "sql": (
                "SELECT event_type, tool_name, timestamp FROM session_events "
                "WHERE session_id = $sid ORDER BY line_offset"
            ),
            "params": {"sid": "sess-1"},
        },
    ).json()["data"]
    assert [row["event_type"] for row in rows] == ["user_prompt", "tool_call"]
    assert rows[1]["tool_name"] == "Bash"
    assert rows[0]["timestamp"] == "2026-09-17 09:00:00.000"


def test_reinserting_a_line_replaces_the_row(client):
    client.post("/insert", headers=_auth(), json={"table": "session_events", "rows": [_session_event()]})
    client.post(
        "/insert",
        headers=_auth(),
        json={
            "table": "session_events",
            "rows": [_session_event(content_preview="edited", ingested_at="2026-09-17 09:05:00.000")],
        },
    )
    rows = client.post(
        "/query",
        headers=_auth(),
        json={
            "sql": "SELECT content_preview FROM session_events WHERE session_id = $sid",
            "params": {"sid": "sess-1"},
        },
    ).json()["data"]
    assert rows == [{"content_preview": "edited"}]


async def test_upsert_batch_avoids_duckdb_insert_or_replace_crash_path():
    class RecordingConnection:
        def __init__(self):
            self.sql = []

        def register(self, *_args):
            return None

        def unregister(self, *_args):
            return None

        def execute(self, sql, *_args):
            self.sql.append(sql)
            assert "INSERT OR REPLACE" not in sql
            return self

    store = AnalyticsStore(path=":memory:", read_connections=1)
    connection = RecordingConnection()
    store._writer = connection

    assert await store.insert("session_events", [_session_event()]) == 1
    assert connection.sql[0] == "BEGIN TRANSACTION"
    assert connection.sql[-1] == "COMMIT"
    assert any(sql.startswith("DELETE FROM session_events") for sql in connection.sql)
    assert any(sql.startswith("INSERT INTO session_events") for sql in connection.sql)


async def test_duplicate_identities_inside_one_batch_keep_final_payload(tmp_path):
    store = AnalyticsStore(path=tmp_path / "analytics.duckdb", read_connections=1)
    await store.start()
    try:
        await run_migrations(store)
        first = _session_event(line_offset=7)
        first["raw_line"] = "first"
        second = _session_event(line_offset=7)
        second["raw_line"] = "second"

        assert await store.insert("session_events", [first, second]) == 2
        _, rows = await store.query("SELECT raw_line FROM session_events WHERE line_offset = 7")
        assert rows == [("second",)]
    finally:
        await store.close()


async def test_overlapping_batch_replay_remains_stable_under_read_pressure(tmp_path):
    store = AnalyticsStore(path=tmp_path / "analytics.duckdb", threads=2, read_connections=4, query_timeout=10.0)
    await store.start()
    try:
        await run_migrations(store)
        rows = [_session_event(line_offset=index) for index in range(1_000)]

        async def replay() -> None:
            for _ in range(3):
                assert await store.insert("session_events", rows) == len(rows)

        async def read() -> None:
            for _ in range(20):
                await store.query("SELECT count(*), max(line_offset) FROM session_events")

        await asyncio.gather(replay(), *(read() for _ in range(4)))
        _, result = await store.query("SELECT count(*), max(line_offset) FROM session_events")
        assert result == [(1_000, 999)]
    finally:
        await store.close()


def test_insert_rejects_unknown_tables(client):
    resp = client.post("/insert", headers=_auth(), json={"table": "pg_users", "rows": [{"id": 1}]})
    assert resp.status_code == 400


def test_stored_checkpoints_upsert_by_key(client):
    row = {
        "session_id": "sess-1",
        "project_id": "default",
        "user_id": "user-1",
        "harness": "claude-code",
        "acknowledged_line": 4,
        "acknowledged_offset": 120,
        "checkpoint_version": 1,
    }
    client.post("/insert", headers=_auth(), json={"table": "session_checkpoints", "rows": [row]})
    client.post(
        "/insert",
        headers=_auth(),
        json={
            "table": "session_checkpoints",
            "rows": [{**row, "acknowledged_line": 9, "acknowledged_offset": 400, "checkpoint_version": 2}],
        },
    )
    rows = client.post(
        "/query",
        headers=_auth(),
        json={
            "sql": "SELECT acknowledged_line, acknowledged_offset FROM session_checkpoints WHERE session_id = $sid",
            "params": {"sid": "sess-1"},
        },
    ).json()["data"]
    assert rows == [{"acknowledged_line": 9, "acknowledged_offset": 400}]


def test_execute_and_checkpoint(client):
    client.post("/insert", headers=_auth(), json={"table": "session_events", "rows": [_session_event()]})
    deleted = client.post(
        "/execute",
        headers=_auth(),
        json={"sql": "DELETE FROM session_events WHERE session_id = $sid", "params": {"sid": "sess-1"}},
    )
    assert deleted.status_code == 200
    assert client.post("/admin/checkpoint", headers=_auth()).json() == {"status": "ok"}
    remaining = client.post("/query", headers=_auth(), json={"sql": "SELECT count(*) AS n FROM session_events"})
    assert remaining.json()["data"] == [{"n": 0}]


def test_backup_exports_parquet(client, tmp_path):
    client.post("/insert", headers=_auth(), json={"table": "session_events", "rows": [_session_event()]})
    destination = tmp_path / "backup"
    resp = client.post("/admin/backup", headers=_auth(), json={"destination": str(destination)})
    assert resp.status_code == 200, resp.text
    assert any(destination.glob("*.parquet"))


class TestStagingDownloads:
    """Export downloads are limited to files that already live in staging."""

    @pytest.fixture()
    def staging_client(self, tmp_path):
        staging = tmp_path / "staging"
        staging.mkdir()
        settings = ServiceSettings(
            DUCKDB_PATH=str(tmp_path / "analytics.duckdb"),
            DUCKDB_ANALYTICS_TOKEN=TOKEN,
            DUCKDB_STAGING_DIR=str(staging),
            DUCKDB_THREADS=2,
            DUCKDB_READ_CONNECTIONS=2,
            DUCKDB_QUERY_TIMEOUT=10.0,
        )
        with TestClient(create_app(settings=settings)) as test_client:
            yield test_client, staging

    def test_startup_removes_stale_staging_artifacts(self, staging_client):
        _client, staging = staging_client
        assert list(staging.iterdir()) == []

    def test_serves_a_file_below_the_staging_root(self, staging_client):
        client, staging = staging_client
        exported = staging / "export-20260917T000000" / "session_events_2026-09.parquet"
        exported.parent.mkdir(parents=True)
        exported.write_bytes(b"PAR1payload")

        response = client.get("/admin/file", headers=_auth(), params={"path": str(exported)})

        assert response.status_code == 200
        assert response.content == b"PAR1payload"
        assert not exported.exists()
        assert not exported.parent.exists()

    @pytest.mark.parametrize(
        "candidate",
        ["../../etc/passwd", "/etc/passwd", "export-20260917T000000/../../escape.parquet"],
    )
    def test_refuses_paths_outside_the_staging_root(self, staging_client, candidate):
        from pathlib import Path

        client, staging = staging_client
        outside = Path(staging).parent / "escape.parquet"
        outside.write_bytes(b"secret")

        response = client.get("/admin/file", headers=_auth(), params={"path": candidate})

        assert response.status_code == 404


async def test_export_covers_every_telemetry_table_including_summaries(tmp_path):
    """Instance moves must carry session_stats_agg; it is not rebuilt on import."""
    store = AnalyticsStore(path=tmp_path / "analytics.duckdb", threads=2, read_connections=2, query_timeout=10.0)
    await store.start()
    try:
        await run_migrations(store)
        await store.insert(
            "session_events",
            [
                {
                    "session_id": "sess-1",
                    "project_id": "default",
                    "user_id": "user-1",
                    "harness": "claude-code",
                    "line_offset": 0,
                    "event_type": "user_prompt",
                    "timestamp": "2026-09-01 10:00:00.000",
                    "raw_line": "{}",
                }
            ],
        )
        await store.insert(
            "session_stats_agg",
            [
                {
                    "project_id": "default",
                    "session_id": "sess-1",
                    "user_id": "user-1",
                    "harness": "claude-code",
                    "first_event_time": "2026-09-01 10:00:00.000",
                    "last_event_time": "2026-09-01 10:00:00.000",
                    "event_count": 1,
                    "prompt_count": 1,
                    "summary_version": 1,
                }
            ],
        )

        destination = tmp_path / "export"
        counts = await store.export_parquet(str(destination))

        assert counts["session_events"] == 1
        assert counts["session_stats_agg"] == 1
        assert (destination / "session_events_2026-09.parquet").exists()
        assert (destination / "session_stats_agg_2026-09.parquet").exists()
    finally:
        await store.close()


async def test_export_scans_each_table_once_and_ignores_the_query_timeout(tmp_path, monkeypatch):
    """Multi-month exports must not re-scan the table per month, and are unbounded.

    Regression: the export used to run under the interactive query deadline and
    re-scanned the source table once per month plus a count and a NULL check.
    """
    executed: list[str] = []
    guard_calls: list[bool] = []
    original_guard = AnalyticsStore._guard

    async def _spy_guard(self, con, work, *, enforce_timeout: bool = True):
        guard_calls.append(enforce_timeout)
        return await original_guard(self, con, work, enforce_timeout=enforce_timeout)

    class _RecordingConnection:
        def __init__(self, con):
            self._con = con

        def execute(self, sql, *args, **kwargs):
            executed.append(sql)
            return self._con.execute(sql, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._con, name)

    monkeypatch.setattr(AnalyticsStore, "_guard", _spy_guard)
    store = AnalyticsStore(path=tmp_path / "analytics.duckdb", read_connections=1)
    await store.start()
    try:
        await run_migrations(store)
        rows = []
        for month in ("2026-01", "2026-02", "2026-03"):
            for offset in range(3):
                rows.append(
                    {
                        "session_id": f"sess-{month}-{offset}",
                        "project_id": "default",
                        "user_id": "user-1",
                        "harness": "pi",
                        "line_offset": offset,
                        "event_type": "user_prompt",
                        "timestamp": f"{month}-01 10:00:0{offset}.000",
                        "raw_line": "{}",
                    }
                )
        await store.insert("session_events", rows)
        store._writer = _RecordingConnection(store._writer)

        destination = tmp_path / "export"
        guard_calls.clear()
        counts = await store.export_parquet(str(destination), ["session_events"])

        assert counts == {"session_events": 9}
        assert guard_calls == [False], "administrative exports must not be time-boxed"
        table_reads = [sql for sql in executed if "FROM session_events" in sql]
        assert len(table_reads) == 1, f"table scanned {len(table_reads)} times: {table_reads}"
        assert [p.name for p in sorted(destination.glob("*.parquet"))] == [
            "session_events_2026-01.parquet",
            "session_events_2026-02.parquet",
            "session_events_2026-03.parquet",
        ]
        assert not list(destination.glob(".*")), "partition staging directory must be removed"
    finally:
        await store.close()


async def test_export_round_trips_into_a_fresh_store(tmp_path):
    """Exported files load back with the same rows, partition column and all."""
    source = AnalyticsStore(path=tmp_path / "source.duckdb", read_connections=1)
    target = AnalyticsStore(path=tmp_path / "target.duckdb", read_connections=1)
    await source.start()
    await target.start()
    try:
        await run_migrations(source)
        await run_migrations(target)
        await source.insert(
            "session_events",
            [
                {
                    "session_id": f"sess-{month}",
                    "project_id": "default",
                    "user_id": "user-1",
                    "harness": "pi",
                    "line_offset": 0,
                    "event_type": "user_prompt",
                    "timestamp": f"{month}-01 10:00:00.000",
                    "raw_line": '{"type":"user"}',
                }
                for month in ("2026-01", "2026-02", "2026-03")
            ],
        )
        destination = tmp_path / "export"
        counts = await source.export_parquet(str(destination), ["session_events"])

        loaded = await target.load_parquet(
            "session_events", [str(path) for path in sorted(destination.glob("*.parquet"))]
        )
        assert counts == {"session_events": 3}
        assert loaded == 3
        _, rows = await target.query("SELECT session_id, raw_line FROM session_events ORDER BY session_id")
        assert rows == [
            ("sess-2026-01", '{"type":"user"}'),
            ("sess-2026-02", '{"type":"user"}'),
            ("sess-2026-03", '{"type":"user"}'),
        ]
    finally:
        await source.close()
        await target.close()


async def test_export_writes_null_time_rows_to_their_own_file(tmp_path):
    store = AnalyticsStore(path=tmp_path / "analytics.duckdb", read_connections=1)
    await store.start()
    try:
        await run_migrations(store)
        await store.insert(
            "session_stats_agg",
            [
                {
                    "project_id": "default",
                    "session_id": "sess-1",
                    "user_id": "user-1",
                    "harness": "pi",
                    "first_event_time": None,
                    "event_count": 1,
                    "summary_version": 0,
                }
            ],
        )
        destination = tmp_path / "export"
        counts = await store.export_parquet(str(destination), ["session_stats_agg"])

        assert counts == {"session_stats_agg": 1}
        assert (destination / "session_stats_agg_null.parquet").exists()
        assert list(destination.glob("session_stats_agg_20*.parquet")) == []
    finally:
        await store.close()


async def test_bulk_load_preserves_store_owned_timestamps(tmp_path):
    checkpoint_path = tmp_path / "session_checkpoints_2026-09.parquet"
    pq.write_table(
        pa.table(
            {
                "project_id": ["default"],
                "user_id": ["user-1"],
                "harness": ["pi"],
                "session_id": ["sess-1"],
                "acknowledged_line": [4],
                "acknowledged_offset": [100],
                "checkpoint_version": [2],
                "updated_at": ["2024-02-03 04:05:06.000"],
            }
        ),
        checkpoint_path,
    )
    store = AnalyticsStore(path=tmp_path / "analytics.duckdb", read_connections=1)
    await store.start()
    try:
        await run_migrations(store)
        assert await store.load_parquet("session_checkpoints", [str(checkpoint_path)]) == 1
        _, rows = await store.query("SELECT strftime(updated_at, '%Y-%m-%d %H:%M:%S') FROM session_checkpoints")
        assert rows == [("2024-02-03 04:05:06",)]
    finally:
        await store.close()


async def test_bulk_load_is_unbounded_and_rolls_back_dedupe_on_insert_failure(tmp_path, monkeypatch):
    invalid_path = tmp_path / "audit_log_2026-09.parquet"
    pq.write_table(pa.table({"event_id": ["event-1"]}), invalid_path)
    store = AnalyticsStore(path=tmp_path / "analytics.duckdb", read_connections=1, query_timeout=5.0)
    await store.start()
    try:
        await run_migrations(store)
        await store.execute(
            "INSERT INTO audit_log (event_id, timestamp) VALUES ('event-1', TIMESTAMP '2026-09-01 10:00:00')"
        )
        store.query_timeout = 0.001
        original_guard = store._guard
        timeouts = []

        async def record_guard(con, work, *, enforce_timeout=True):
            timeouts.append(enforce_timeout)
            return await original_guard(con, work, enforce_timeout=enforce_timeout)

        monkeypatch.setattr(store, "_guard", record_guard)
        with pytest.raises(Exception, match="NOT NULL"):
            await store.load_parquet("audit_log", [str(invalid_path)])

        assert timeouts[-1] is False
        monkeypatch.setattr(store, "_guard", original_guard)
        store.query_timeout = 5.0
        _, rows = await store.query("SELECT event_id FROM audit_log")
        assert rows == [("event-1",)]
    finally:
        await store.close()


async def test_insight_queries_execute_against_duckdb(tmp_path, monkeypatch):
    from services.insights import batch, session_meta_extractor, version_impact

    store = AnalyticsStore(path=tmp_path / "analytics.duckdb", read_connections=1)
    await store.start()
    try:
        await run_migrations(store)
        for index in range(3):
            await store.execute(
                "INSERT INTO session_stats_agg (project_id, session_id, agent_id, agent_version, user_id, "
                "harness, layer_hash, first_event_time, last_event_time, event_count, prompt_count, "
                "tool_call_count, tool_result_count, input_tokens, output_tokens, total_credits, summary_version) "
                "VALUES ('default', $sid, 'agent-1', '1.0.0', $uid, 'pi', 'abc123', "
                "TIMESTAMP '2026-09-01 10:00:00', TIMESTAMP '2026-09-01 10:05:00', 8, 2, 3, 3, 10, 5, 0.1, 1)",
                {"sid": f"sess-{index}", "uid": f"user-{index}"},
            )
            await store.execute(
                "INSERT INTO session_events (session_id, project_id, user_id, harness, line_offset, event_type, "
                "timestamp, raw_line) VALUES ($sid, 'default', $uid, 'pi', 0, 'user_prompt', "
                "TIMESTAMP '2026-09-01 10:00:00', $raw)",
                {"sid": f"sess-{index}", "uid": f"user-{index}", "raw": f'{{"session": {index}}}'},
            )
        await store.execute(
            "INSERT INTO layer_snapshots (hash, project_id, user_id, harness, content) "
            "VALUES ('abc123', 'default', 'user-1', 'pi', '{\"files\": []}')"
        )
        query = _store_query(store)
        monkeypatch.setattr(version_impact, "get_query", lambda: query)
        monkeypatch.setattr(session_meta_extractor, "get_query", lambda: query)
        monkeypatch.setattr(batch, "_query", query)

        groups = await version_impact.detect_layer_groups("agent-1", "2026-09-01", "2026-09-02", "agent", "1.0.0")
        snapshots = await version_impact.fetch_layer_snapshots_for_groups("default", ["abc123"])
        transcripts = await session_meta_extractor.fetch_all_session_transcripts(
            "agent-1", "2026-09-01", "2026-09-02", agent_version="1.0.0"
        )
        count = await batch._count_agent_sessions("agent-1", "agent", "2026-09-01", "1.0.0")

        assert groups[0]["sessions"] == 3
        assert snapshots == {"abc123": {"files": []}}
        assert len(transcripts) == 3
        assert count == 3
    finally:
        await store.close()


async def test_migrations_are_idempotent_and_checksum_guarded(tmp_path):
    store = AnalyticsStore(
        path=tmp_path / "analytics.duckdb",
        threads=2,
        read_connections=2,
        query_timeout=10.0,
    )
    await store.start()
    try:
        assert await run_migrations(store) == ["001_baseline"]
        assert await run_migrations(store) == []
        await store.execute(
            "UPDATE analytics_schema_migrations SET checksum = 'tampered' WHERE version = '001_baseline'"
        )
        with pytest.raises(MigrationError):
            await run_migrations(store)
    finally:
        await store.close()


async def test_query_rejects_results_above_configured_limit(tmp_path):
    store = AnalyticsStore(
        path=tmp_path / "analytics.duckdb",
        threads=1,
        read_connections=1,
        query_timeout=5.0,
        max_result_rows=2,
    )
    await store.start()
    try:
        with pytest.raises(ValueError, match="exceeds the 2-row response limit"):
            await store.query("SELECT * FROM range(3)")
    finally:
        await store.close()


async def test_store_rejects_writes_after_close(tmp_path):
    store = AnalyticsStore(path=tmp_path / "analytics.duckdb", threads=2, read_connections=1, query_timeout=5.0)
    await store.start()
    await store.close()
    with pytest.raises(RuntimeError):
        await store.query("SELECT 1")


async def test_second_service_cannot_open_the_same_database(tmp_path):
    """The single-writer guard fails fast with an actionable error."""
    path = tmp_path / "analytics.duckdb"
    first = AnalyticsStore(path=path, threads=1, read_connections=1, query_timeout=5.0)
    second = AnalyticsStore(path=path, threads=1, read_connections=1, query_timeout=5.0)
    await first.start()
    try:
        with pytest.raises(RuntimeError, match="already owns the analytics database"):
            await second.start()
    finally:
        await first.close()

    # After the owner closes, the next process can take over.
    await second.start()
    await second.close()


async def test_client_insert_query_helpers_round_trip(tmp_path, monkeypatch):
    """The real client, insert, and query helpers against the in-process service."""
    import services.analytics.duckdb.client as client_mod
    from services.analytics.duckdb.insert import (
        insert_session_checkpoint,
        insert_session_events,
        refresh_session_summary,
    )
    from services.analytics.duckdb.query import (
        query_existing_for_dedup,
        query_recent_events,
        query_session_checkpoint,
        query_source_records_after,
    )

    app = create_app(settings=_settings(tmp_path))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://analytics") as async_client:
            monkeypatch.setattr(client_mod, "_client", async_client)
            monkeypatch.setattr(client_mod, "ANALYTICS_TOKEN", TOKEN)

            assert await query_session_checkpoint("sess-1", "default", "user-1", "claude-code") == (-1, 0)

            live_ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            await insert_session_events(
                [
                    _session_event(
                        line_offset=0,
                        line_hash="h0",
                        is_source_record=1,
                        rendered=1,
                        timestamp=live_ts,
                        ingested_at=live_ts,
                    ),
                    _session_event(
                        line_offset=1,
                        line_hash="h1",
                        is_source_record=0,
                        rendered=0,
                        event_type="kiro_credits",
                    ),
                ]
            )
            await insert_session_checkpoint("sess-1", "default", "user-1", "claude-code", 1, 42)
            await refresh_session_summary("sess-1", "default", "user-1", "claude-code")

            assert await query_session_checkpoint("sess-1", "default", "user-1", "claude-code") == (1, 42)
            assert await query_source_records_after("sess-1", "default", "user-1", "claude-code", -1) == [(0, 0)]
            assert await query_existing_for_dedup("sess-1", "default", "user-1", "claude-code", 0, 10) == {0: "h0"}

            recent = await query_recent_events(minutes=60)
            assert recent["agent_interaction_events"] == 1

            summary = (
                await client_mod._query(
                    "SELECT event_count, prompt_count, tool_call_count, total_credits "
                    "FROM session_stats_agg WHERE session_id = $sid",
                    {"sid": "sess-1"},
                )
            ).json()["data"]
            assert summary == [{"event_count": 1, "prompt_count": 1, "tool_call_count": 0, "total_credits": 0.0}]
