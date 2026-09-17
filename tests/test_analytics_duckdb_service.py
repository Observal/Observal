# SPDX-FileCopyrightText: 2026 Observal contributors
# SPDX-License-Identifier: Apache-2.0
"""Tests for the DuckDB analytics service, store, and migrations."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from services.analytics.duckdb.migrations import MigrationError, run_migrations
from services.analytics.duckdb.service import ServiceSettings, create_app
from services.analytics.duckdb.storage import AnalyticsStore

TOKEN = "test-analytics-token"


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


def test_health_reports_schema_version(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["schema_version"] == "002_query_indexes"


def test_queries_require_a_token(client):
    assert client.post("/query", json={"sql": "SELECT 1"}).status_code == 401
    assert client.post("/query", json={"sql": "SELECT 1"}, headers={"Authorization": "Bearer nope"}).status_code == 401


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
    assert rows[0]["timestamp"].startswith("2026-09-17T09:00:00")


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

    def test_serves_a_file_below_the_staging_root(self, staging_client):
        client, staging = staging_client
        exported = staging / "export-20260917T000000" / "session_events_2026-09.parquet"
        exported.parent.mkdir(parents=True)
        exported.write_bytes(b"PAR1payload")

        response = client.get("/admin/file", headers=_auth(), params={"path": str(exported)})

        assert response.status_code == 200
        assert response.content == b"PAR1payload"

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
    from services.analytics.duckdb.storage import AnalyticsStore

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
        await store.execute(
            "INSERT OR REPLACE INTO session_stats_agg (project_id, session_id, user_id, harness, "
            "first_event_time, last_event_time, event_count, prompt_count, summary_version) "
            "VALUES ('default', 'sess-1', 'user-1', 'claude-code', "
            "TIMESTAMP '2026-09-01 10:00:00', TIMESTAMP '2026-09-01 10:00:00', 1, 1, 1)"
        )

        destination = tmp_path / "export"
        counts = await store.export_parquet(str(destination))

        assert counts["session_events"] == 1
        assert counts["session_stats_agg"] == 1
        assert (destination / "session_events_2026-09.parquet").exists()
        assert (destination / "session_stats_agg_2026-09.parquet").exists()
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
        assert await run_migrations(store) == ["001_baseline", "002_query_indexes"]
        assert await run_migrations(store) == []
        await store.execute(
            "UPDATE analytics_schema_migrations SET checksum = 'tampered' WHERE version = '001_baseline'"
        )
        with pytest.raises(MigrationError):
            await run_migrations(store)
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
