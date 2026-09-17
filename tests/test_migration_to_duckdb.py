# SPDX-FileCopyrightText: 2026 Observal contributors
# SPDX-FileCopyrightText: 2026 Srihari <sriharilegend23@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Tests for the one-way ClickHouse -> DuckDB telemetry migration."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import httpx
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from observal_shared.migration.duckdb_export import export_duckdb_telemetry
from observal_shared.migration.duckdb_import import (
    DuckDBConnParams,
    load_telemetry_into_duckdb,
    parse_duckdb_url,
    verify_duckdb_telemetry,
)
from observal_shared.migration.exceptions import MigrationError, PrerequisiteError
from observal_shared.migration.progress import NullReporter
from services.analytics.duckdb.service import ServiceSettings, create_app

if TYPE_CHECKING:
    from pathlib import Path

TOKEN = "migration-test-token"


def _write_export(tmp_path: Path) -> Path:
    export_dir = tmp_path / "telemetry-export"
    export_dir.mkdir()

    events = pa.table(
        {
            "session_id": ["sess-1", "sess-1"],
            "project_id": ["default", "default"],
            "user_id": ["user-1", "user-1"],
            "harness": ["claude-code", "claude-code"],
            "line_offset": [0, 1],
            "event_type": ["user_prompt", "tool_call"],
            "timestamp": ["2026-09-01 10:00:00.000", "2026-09-01 10:00:01.000"],
            "content_preview": ["hi", "ls"],
            "content_length": [2, 2],
            "raw_line": ["{}", "{}"],
        }
    )
    events_path = export_dir / "session_events_2026-09.parquet"
    pq.write_table(events, events_path)

    audit = pa.table(
        {
            "event_id": ["e1"],
            "timestamp": ["2026-09-01 10:00:05.000"],
            "action": ["user.created"],
            "resource_type": ["user"],
        }
    )
    audit_path = export_dir / "audit_log_2026-09.parquet"
    pq.write_table(audit, audit_path)

    manifest = {
        "migration_id": "mig-test",
        "tables": {
            "session_events": {
                "files": [events_path.name],
                "row_count": 2,
                "checksum": {events_path.name: _sha256(events_path)},
            },
            "audit_log": {
                "files": [audit_path.name],
                "row_count": 1,
                "checksum": {audit_path.name: _sha256(audit_path)},
            },
        },
    }
    (export_dir / "telemetry_manifest.json").write_text(json.dumps(manifest))
    return export_dir


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_parse_duckdb_url_defaults_to_service_port():
    assert parse_duckdb_url("duckdb://analytics-host:9000/observal") == "http://analytics-host:9000"
    assert parse_duckdb_url("duckdb://analytics-host/observal") == "http://analytics-host:8484"


async def test_load_and_verify_against_a_live_service(tmp_path):
    export_dir = _write_export(tmp_path)
    settings = ServiceSettings(
        DUCKDB_PATH=str(tmp_path / "analytics.duckdb"),
        DUCKDB_STAGING_DIR=str(tmp_path / "staging"),
        DUCKDB_ANALYTICS_TOKEN=TOKEN,
        DUCKDB_THREADS=2,
        DUCKDB_READ_CONNECTIONS=2,
        DUCKDB_QUERY_TIMEOUT=10.0,
    )
    app = create_app(settings=settings)
    params = DuckDBConnParams(url="duckdb://analytics:8484/observal", token=TOKEN)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://analytics") as client:
            result = await load_telemetry_into_duckdb(params, export_dir, NullReporter(), http_client=client)
            assert result.tables_imported == 2
            assert result.rows_imported == {"session_events": 2, "audit_log": 1}
            assert "session_checkpoints" in result.tables_skipped

            validation = await verify_duckdb_telemetry(params, export_dir, http_client=client)
            assert validation.checksums_valid is True
            assert validation.row_count_results == {
                "session_events": (2, 2),
                "audit_log": (1, 1),
            }

            # Re-running the migration is idempotent for every table: keyed
            # tables replace by primary key, append-only tables delete the
            # incoming identities first.
            again = await load_telemetry_into_duckdb(params, export_dir, NullReporter(), http_client=client)
            assert again.rows_imported == {"session_events": 0, "audit_log": 0}
            for table, expected in (("session_events", 2), ("audit_log", 1)):
                response = await client.post(
                    "/query",
                    json={"sql": f"SELECT count(*) AS cnt FROM {table}"},
                    headers={"Authorization": f"Bearer {TOKEN}"},
                )
                assert response.json()["data"][0]["cnt"] == expected


async def test_verify_detects_row_count_drift(tmp_path):
    export_dir = _write_export(tmp_path)
    settings = ServiceSettings(
        DUCKDB_PATH=str(tmp_path / "analytics.duckdb"),
        DUCKDB_STAGING_DIR=str(tmp_path / "staging"),
        DUCKDB_ANALYTICS_TOKEN=TOKEN,
        DUCKDB_THREADS=2,
        DUCKDB_READ_CONNECTIONS=2,
        DUCKDB_QUERY_TIMEOUT=10.0,
    )
    app = create_app(settings=settings)
    params = DuckDBConnParams(url="duckdb://analytics:8484/observal", token=TOKEN)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://analytics") as client:
            await load_telemetry_into_duckdb(params, export_dir, NullReporter(), http_client=client)
            # Corrupt the manifest expectation and re-verify.
            manifest_path = export_dir / "telemetry_manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["tables"]["session_events"]["row_count"] = 99
            manifest_path.write_text(json.dumps(manifest))

            validation = await verify_duckdb_telemetry(params, export_dir, http_client=client)
            assert validation.row_count_results["session_events"] == (99, 2)


async def test_load_rejects_missing_manifest_before_contacting_service(tmp_path):
    export_dir = tmp_path / "broken-export"
    export_dir.mkdir()
    params = DuckDBConnParams(url="duckdb://analytics:8484/observal", token=TOKEN)

    with pytest.raises(PrerequisiteError, match="manifest not found"):
        await load_telemetry_into_duckdb(params, export_dir, NullReporter())


async def test_load_rejects_corrupt_partition_before_contacting_service(tmp_path):
    export_dir = _write_export(tmp_path)
    (export_dir / "session_events_2026-09.parquet").write_bytes(b"corrupt")
    params = DuckDBConnParams(url="duckdb://analytics:8484/observal", token=TOKEN)

    with pytest.raises(MigrationError, match="checksum failed"):
        await load_telemetry_into_duckdb(params, export_dir, NullReporter())


async def test_load_requires_a_healthy_service(tmp_path):
    export_dir = _write_export(tmp_path)
    params = DuckDBConnParams(url="duckdb://analytics:8484/observal", token=TOKEN)
    transport = httpx.MockTransport(lambda request: httpx.Response(503, json={"status": "error"}))
    async with httpx.AsyncClient(transport=transport, base_url="http://analytics") as client:
        with pytest.raises(Exception, match=r"unhealthy|unreachable"):
            await load_telemetry_into_duckdb(params, export_dir, NullReporter(), http_client=client)


async def test_export_then_import_round_trip_between_services(tmp_path):
    """Instance move: export from one analytics service and load into another."""
    params = DuckDBConnParams(url="duckdb://analytics:8484/observal", token=TOKEN)

    source_settings = ServiceSettings(
        DUCKDB_PATH=str(tmp_path / "source.duckdb"),
        DUCKDB_STAGING_DIR=str(tmp_path / "source-staging"),
        DUCKDB_ANALYTICS_TOKEN=TOKEN,
        DUCKDB_THREADS=2,
        DUCKDB_READ_CONNECTIONS=2,
        DUCKDB_QUERY_TIMEOUT=10.0,
    )
    target_settings = ServiceSettings(
        DUCKDB_PATH=str(tmp_path / "target.duckdb"),
        DUCKDB_STAGING_DIR=str(tmp_path / "target-staging"),
        DUCKDB_ANALYTICS_TOKEN=TOKEN,
        DUCKDB_THREADS=2,
        DUCKDB_READ_CONNECTIONS=2,
        DUCKDB_QUERY_TIMEOUT=10.0,
    )
    export_dir = tmp_path / "instance-export"

    source_app = create_app(settings=source_settings)
    async with source_app.router.lifespan_context(source_app):
        transport = httpx.ASGITransport(app=source_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://analytics") as client:
            seed_dir = tmp_path / "seed"
            seed_dir.mkdir()
            await load_telemetry_into_duckdb(params, _write_export(seed_dir), NullReporter(), http_client=client)
            export_result = await export_duckdb_telemetry(params, export_dir, NullReporter(), http_client=client)

    assert export_result.total_rows == 3
    assert (export_dir / "telemetry_manifest.json").exists()
    assert sorted(p.name for p in export_dir.glob("*.parquet")) == [
        "audit_log_2026-09.parquet",
        "session_events_2026-09.parquet",
    ]

    target_app = create_app(settings=target_settings)
    async with target_app.router.lifespan_context(target_app):
        transport = httpx.ASGITransport(app=target_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://analytics") as client:
            loaded = await load_telemetry_into_duckdb(params, export_dir, NullReporter(), http_client=client)
            assert loaded.rows_imported == {"session_events": 2, "audit_log": 1}
            validation = await verify_duckdb_telemetry(params, export_dir, http_client=client)
            assert validation.checksums_valid is True
            assert validation.row_count_results == {"session_events": (2, 2), "audit_log": (1, 1)}
