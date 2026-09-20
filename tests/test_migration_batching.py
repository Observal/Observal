# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Focused regression tests for bounded ClickHouse migration chunks."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import observal_shared.migration.ch_export as ch_export_module
from observal_shared.migration.ch_export import (
    EXPORT_QUERY_SETTINGS,
    MAX_SHARD_COUNT,
    TelemetryChunk,
    _build_ch_count_query,
    _build_ch_export_query,
    _ch_query,
    _chunk_params,
    _export_candidate,
    _month_windows,
    _split_chunk,
    _table_windows,
)
from observal_shared.migration.constants import CLICKHOUSE_TABLES
from observal_shared.migration.exceptions import MigrationError
from observal_shared.migration.progress import NullReporter
from observal_shared.migration.telemetry_manifest import validate_telemetry_manifest


class _StreamingError(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b"Code: 241. DB::Exception: Memory limit (for query) exceeded"


@pytest.mark.asyncio
async def test_streaming_clickhouse_error_body_is_read_before_reporting(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, stream=_StreamingError(), request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(MigrationError, match=r"Memory limit.*exceeded") as exc_info:
            await _ch_query(
                "http://clickhouse.invalid",
                "default",
                "user",
                "secret",
                "SELECT 1 FORMAT Parquet",
                stream_to=tmp_path / "chunk.parquet",
                http_client=client,
            )

    assert "ResponseNotRead" not in str(exc_info.value)
    assert "secret" not in str(exc_info.value)
    assert not (tmp_path / "chunk.parquet.tmp").exists()


def test_export_and_count_queries_share_the_exact_chunk_predicate():
    config = CLICKHOUSE_TABLES[0]
    chunk = TelemetryChunk(
        table=config["name"],
        start=datetime(2026, 1, 1, tzinfo=UTC),
        end=datetime(2026, 1, 2, tzinfo=UTC),
        bucket=7,
        shard_count=64,
    )
    export_predicate = _build_ch_export_query(config, chunk).split(" WHERE ", 1)[1].removesuffix(" FORMAT Parquet")
    count_predicate = _build_ch_count_query(config, chunk).split(" WHERE ", 1)[1].removesuffix(" FORMAT JSON")

    assert export_predicate == count_predicate
    params = _chunk_params(chunk, "2026-01-02 00:00:00.000")
    assert params["param_bucket"] == "7"
    assert params["param_shard_count"] == "64"
    assert params["max_threads"] == EXPORT_QUERY_SETTINGS["max_threads"] == "1"


def test_session_events_preserve_session_groups_across_batches():
    config = next(item for item in CLICKHOUSE_TABLES if item["name"] == "session_events")
    maximum = datetime(2026, 2, 1, 0, 0, 0, 123000, tzinfo=UTC)

    assert config["preserve_shard_group"] is True
    assert config["shard_expr"] == "sipHash64(project_id, user_id, harness, session_id)"
    assert _table_windows(
        config,
        datetime(2025, 1, 1, tzinfo=UTC),
        maximum,
        datetime(2026, 3, 1, tzinfo=UTC),
    ) == [(datetime(2025, 1, 1, tzinfo=UTC), maximum + timedelta(milliseconds=1))]


def test_chunk_ids_use_manifest_millisecond_precision():
    chunk = TelemetryChunk(
        table="security_events",
        start=datetime(2026, 9, 1, tzinfo=UTC),
        end=datetime(2026, 9, 18, 8, 23, 43, 949620, tzinfo=UTC),
        bucket=0,
        shard_count=1,
    )

    assert chunk.chunk_id.endswith("20260918T082343949000:0:1")


def test_adaptive_splits_are_non_overlapping():
    parent = TelemetryChunk(
        table="session_events",
        start=datetime(2026, 1, 1, tzinfo=UTC),
        end=datetime(2026, 1, 3, tzinfo=UTC),
        bucket=5,
        shard_count=64,
    )
    time_left, time_right = _split_chunk(parent, prefer_hash=False)
    assert time_left.start == parent.start
    assert time_left.end == time_right.start
    assert time_right.end == parent.end

    hash_left, hash_right = _split_chunk(parent, prefer_hash=True)
    assert hash_left.shard_count == hash_right.shard_count == 128
    assert hash_left.bucket == 5
    assert hash_right.bucket == 69

    short_hash_only = TelemetryChunk(
        table=parent.table,
        start=parent.start,
        end=parent.end,
        bucket=0,
        shard_count=MAX_SHARD_COUNT,
    )
    assert _split_chunk(short_hash_only, prefer_hash=True, allow_time=False) is None


def test_final_window_includes_the_discovered_maximum_timestamp():
    maximum = datetime(2026, 1, 15, 12, 30, 0, 123000, tzinfo=UTC)
    windows = _month_windows(
        datetime(2026, 1, 1, tzinfo=UTC),
        maximum,
        datetime(2026, 2, 1, tzinfo=UTC),
    )

    assert windows[-1][0] <= maximum < windows[-1][1]
    assert windows[-1][1] == datetime(2026, 2, 1, tzinfo=UTC)


@pytest.mark.asyncio
async def test_oversized_candidate_is_exported_as_smaller_time_chunks(tmp_path, monkeypatch):
    config = next(item for item in CLICKHOUSE_TABLES if item["name"] == "audit_log")
    parent = TelemetryChunk(
        table="audit_log",
        start=datetime(2026, 1, 1, tzinfo=UTC),
        end=datetime(2026, 1, 3, tzinfo=UTC),
        bucket=0,
        shard_count=1,
    )

    async def fake_query(_url, _db, _user, _password, sql, *, stream_to=None, **_kwargs):
        if "count()" in sql:
            duration = datetime.fromisoformat(_kwargs["extra_params"]["param_chunk_end"]) - datetime.fromisoformat(
                _kwargs["extra_params"]["param_chunk_start"]
            )
            count = 20 if duration > timedelta(days=1) else 5
            return httpx.Response(200, json={"data": [{"cnt": str(count)}]})
        pq.write_table(pa.table({"event_id": list(range(5))}), stream_to)
        return httpx.Response(200)

    monkeypatch.setattr(ch_export_module, "TARGET_CHUNK_ROWS", 10)
    monkeypatch.setattr(ch_export_module, "_ch_query", fake_query)
    chunks = await _export_candidate(
        table_cfg=config,
        chunk=parent,
        cutoff="2026-01-04 00:00:00.000",
        output_dir=tmp_path,
        connection=("http://example", "default", "user", "password"),
        http_client=None,
        reporter=NullReporter(),
        pct=50,
    )

    assert len(chunks) == 2
    assert sum(chunk["row_count"] for chunk in chunks) == 10
    assert all(chunk["file"] for chunk in chunks)
    assert chunks[0]["range_end"] == chunks[1]["range_start"]


def _manifest_with_one_chunk(tmp_path):
    parquet_path = tmp_path / "session_events_chunk.parquet"
    pq.write_table(pa.table({"project_id": ["source"], "value": [1]}), parquet_path)
    checksum = hashlib.sha256(parquet_path.read_bytes()).hexdigest()
    chunk = {
        "chunk_id": "session_events:20260101T000000000000:20260102T000000000000:0:64",
        "range_start": "2026-01-01 00:00:00.000",
        "range_end": "2026-01-02 00:00:00.000",
        "bucket": 0,
        "shard_count": 64,
        "row_count": 1,
        "file": parquet_path.name,
        "size_bytes": parquet_path.stat().st_size,
        "sha256": checksum,
    }
    tables = {
        config["name"]: {
            "files": [],
            "row_count": 0,
            "checksum": {},
            "time_range": None,
            "chunks": [],
        }
        for config in CLICKHOUSE_TABLES
    }
    tables["session_events"] = {
        "files": [parquet_path.name],
        "row_count": 1,
        "checksum": {parquet_path.name: checksum},
        "time_range": {"min": chunk["range_start"], "max": chunk["range_end"]},
        "chunks": [chunk],
    }
    return {
        "schema_version": "2.0",
        "migration_id": "migration-1",
        "phase_status": "export_complete",
        "export_time_cutoff": "2026-01-03 00:00:00.000",
        "tables": tables,
    }


def test_manifest_rejects_incomplete_checksum_map(tmp_path):
    manifest = _manifest_with_one_chunk(tmp_path)
    manifest["tables"]["session_events"]["checksum"] = {}

    with pytest.raises(MigrationError, match="checksum metadata disagrees"):
        validate_telemetry_manifest(manifest)


def test_manifest_accepts_complete_chunk_metadata(tmp_path):
    manifest = _manifest_with_one_chunk(tmp_path)

    chunks = validate_telemetry_manifest(manifest)

    assert chunks["session_events"][0]["row_count"] == 1


def test_manifest_normalizes_legacy_monthly_exports(tmp_path):
    parquet_path = tmp_path / "session_events_2026-09.parquet"
    pq.write_table(pa.table({"project_id": ["source"], "value": [1]}), parquet_path)
    checksum = hashlib.sha256(parquet_path.read_bytes()).hexdigest()
    tables = {
        config["name"]: {"files": [], "row_count": 0, "checksum": {}, "time_range": None}
        for config in CLICKHOUSE_TABLES
    }
    tables["session_events"] = {
        "files": [parquet_path.name],
        "row_count": 1,
        "checksum": {parquet_path.name: checksum},
        "time_range": {"min": "2026-09-01 00:00:00", "max": "2026-09-30 23:59:59"},
    }
    manifest = {
        "migration_id": "legacy-migration",
        "phase": "deep_copy",
        "phase_status": "export_complete",
        "export_time_cutoff": "2026-10-01 00:00:00.000",
        "tables": tables,
    }

    chunks = validate_telemetry_manifest(manifest, tmp_path)

    assert chunks["session_events"] == [
        {
            "chunk_id": "legacy:session_events:202609",
            "range_start": "2026-09-01 00:00:00",
            "range_end": "2026-10-01 00:00:00",
            "bucket": 0,
            "shard_count": 1,
            "row_count": 1,
            "file": parquet_path.name,
            "size_bytes": parquet_path.stat().st_size,
            "sha256": checksum,
            "legacy": True,
        }
    ]


def test_manifest_accepts_early_v2_sub_millisecond_chunk_ids(tmp_path):
    manifest = _manifest_with_one_chunk(tmp_path)
    chunk = manifest["tables"]["session_events"]["chunks"][0]
    chunk["chunk_id"] = "session_events:20260101T000000000999:20260102T000000000888:0:64"

    chunks = validate_telemetry_manifest(manifest)

    assert chunks["session_events"][0]["chunk_id"].endswith("000888:0:64")


def test_migration_upload_proxy_streams_large_request_bodies():
    root = Path(__file__).resolve().parents[1]
    for relative in (
        "docker/nginx.conf",
        "docker/nginx.production.conf",
        "docker/nginx.dev.conf",
        "docker/nginx-azure.conf",
    ):
        config = (root / relative).read_text(encoding="utf-8")
        assert "^/api/v1/admin/migrate/(import|validate)/?$" in config
        assert "client_max_body_size 6g" in config
        assert "limit_conn_zone $binary_remote_addr zone=migration_uploads:10m" in config
        assert "limit_conn migration_uploads 1" in config
        assert "proxy_request_buffering off" in config
        assert "proxy_send_timeout 3600s" in config
