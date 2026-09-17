# SPDX-FileCopyrightText: 2026 Observal contributors
# SPDX-FileCopyrightText: 2026 Srihari <sriharilegend23@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""One-way ClickHouse -> DuckDB telemetry loader.

Consumes the Parquet telemetry export produced by
``observal_shared.migration.ch_export`` and loads it into the DuckDB analytics
service (the container that owns the analytics database).  The flow is:

    ClickHouse --export_ch--> Parquet + telemetry_manifest.json
              --this module--> DuckDB service (upload + load_parquet)
              --verify--> row-count parity against the manifest

There is deliberately no reverse direction: DuckDB is the destination store.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from loguru import logger as optic

from observal_shared.migration.archive import _sha256_file, read_manifest
from observal_shared.migration.constants import CLICKHOUSE_TABLES
from observal_shared.migration.exceptions import ConnectionFailedError, MigrationError, PrerequisiteError
from observal_shared.migration.results import TelemetryImportResult, TelemetryValidationResult

if TYPE_CHECKING:
    from pathlib import Path

    import httpx

    from observal_shared.migration.progress import ProgressReporter

MANIFEST_FILENAME = "telemetry_manifest.json"
DEFAULT_HTTP_PORT = 8484


@dataclass(frozen=True)
class DuckDBConnParams:
    """Connection parameters for the DuckDB analytics service."""

    url: str
    token: str = ""

    def http_base(self) -> str:
        parsed = urlparse(self.url.replace("duckdb://", "http://"))
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or DEFAULT_HTTP_PORT
        return f"http://{host}:{port}"

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}


def parse_duckdb_url(url: str) -> str:
    """Return the HTTP base URL for a ``duckdb://host:port/db`` connection string."""
    return DuckDBConnParams(url=url).http_base()


def _table_files(export_dir: Path, table: str) -> list[Path]:
    return sorted(export_dir.glob(f"{table}_*.parquet"))


def _verify_artifact_checksums(export_dir: Path, manifest: dict) -> dict[str, bool]:
    results: dict[str, bool] = {}
    for table_meta in manifest.get("tables", {}).values():
        for filename, expected in (table_meta.get("checksum") or {}).items():
            path = export_dir / filename
            if not path.exists():
                results[filename] = False
                continue
            results[filename] = _sha256_file(path) == expected
    return results


async def verify_artifact_checksums(export_dir: Path) -> TelemetryValidationResult:
    """Check the export's manifest checksums without contacting the service."""
    manifest_path = export_dir / MANIFEST_FILENAME
    if not manifest_path.exists():
        raise PrerequisiteError(f"telemetry manifest not found: {manifest_path}")
    manifest = read_manifest(manifest_path)
    results = _verify_artifact_checksums(export_dir, manifest)
    return TelemetryValidationResult(
        checksums_valid=all(results.values()) if results else True,
        checksum_results=results,
        fk_results=None,
        row_count_results=None,
    )


async def load_telemetry_into_duckdb(
    duckdb: DuckDBConnParams,
    export_dir: Path,
    reporter: ProgressReporter,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> TelemetryImportResult:
    """Upload Parquet partitions and load them into DuckDB.

    Raises:
        PrerequisiteError: export directory or manifest is missing/incomplete.
        ConnectionFailedError: the DuckDB service cannot be reached.
        MigrationError: the service rejected an upload or load.
    """
    import httpx as _httpx

    if not export_dir.is_dir():
        raise PrerequisiteError(f"telemetry export directory not found: {export_dir}")

    manifest_path = export_dir / MANIFEST_FILENAME
    manifest = read_manifest(manifest_path) if manifest_path.exists() else {}
    migration_id = str(manifest.get("migration_id") or uuid.uuid4())

    start = time.monotonic()
    owns_client = http_client is None
    client = http_client or _httpx.AsyncClient(timeout=_httpx.Timeout(600.0, connect=10.0))
    rows_imported: dict[str, int] = {}
    pre_rows: dict[str, int] = {}
    tables_skipped: list[str] = []
    warnings: list[str] = []

    try:
        await reporter.update(phase="duckdb_import", pct=0, message="Checking analytics service")
        try:
            health = await client.get(f"{duckdb.http_base()}/health")
        except _httpx.HTTPError as e:
            raise ConnectionFailedError(f"analytics service unreachable at {duckdb.http_base()}: {e}") from e
        if health.status_code != 200 or health.json().get("status") != "ok":
            raise ConnectionFailedError(f"analytics service unhealthy: HTTP {health.status_code}")

        tables = [cfg["name"] for cfg in CLICKHOUSE_TABLES]
        for index, table in enumerate(tables):
            pct = int((index / len(tables)) * 90) + 5
            files = _table_files(export_dir, table)
            if not files:
                tables_skipped.append(table)
                await reporter.update(phase="duckdb_import", pct=pct, message=f"Skipping {table} (no files)")
                continue

            await reporter.update(
                phase="duckdb_import", pct=pct, message=f"Uploading {len(files)} partition(s) for {table}"
            )
            try:
                existing = await client.post(
                    f"{duckdb.http_base()}/query",
                    json={"sql": f"SELECT count(*) AS cnt FROM {table}"},
                    headers=duckdb.headers(),
                )
            except _httpx.HTTPError as e:
                raise ConnectionFailedError(f"pre-count of {table} failed: {e}") from e
            if existing.status_code == 200:
                pre_rows[table] = int(((existing.json().get("data") or [{}])[0]).get("cnt") or 0)
            responses = await _upload_partitions(client, duckdb, files)
            paths: list[str] = []
            for upload in responses:
                if upload.status_code != 200:
                    raise MigrationError(f"upload of {table} failed: HTTP {upload.status_code} {upload.text[:200]}")
                paths.extend(upload.json().get("paths", []))
            await reporter.update(phase="duckdb_import", pct=pct, message=f"Loading {table}")
            try:
                load = await client.post(
                    f"{duckdb.http_base()}/admin/load_parquet",
                    json={"table": table, "paths": paths, "replace": True},
                    headers=duckdb.headers(),
                )
            except _httpx.HTTPError as e:
                raise ConnectionFailedError(f"load of {table} failed: {e}") from e
            if load.status_code != 200:
                raise MigrationError(f"load of {table} failed: HTTP {load.status_code} {load.text[:200]}")
            rows_imported[table] = int(load.json().get("rows_loaded") or 0)
            optic.debug("{}: loaded {} new row(s)", table, rows_imported[table])

        await reporter.update(phase="duckdb_import", pct=100, message="DuckDB telemetry load complete")
    finally:
        if owns_client:
            await client.aclose()

    return TelemetryImportResult(
        migration_id=migration_id,
        tables_imported=len(rows_imported),
        tables_skipped=tables_skipped,
        rows_imported=rows_imported,
        duration_seconds=time.monotonic() - start,
        warnings=warnings,
        pre_rows=pre_rows,
    )


UPLOAD_BATCH_SIZE = 4


async def _upload_partitions(
    client: httpx.AsyncClient, duckdb: DuckDBConnParams, files: list[Path]
) -> list[httpx.Response]:
    """Upload partitions in bounded batches.

    Each file is read as it is sent, and only a few partitions are in flight at
    once, so a large table does not have to fit in memory in one request.
    """
    import httpx as _httpx

    responses: list[httpx.Response] = []
    for start in range(0, len(files), UPLOAD_BATCH_SIZE):
        batch = files[start : start + UPLOAD_BATCH_SIZE]
        multipart = [("files", (path.name, path.read_bytes(), "application/octet-stream")) for path in batch]
        try:
            responses.append(
                await client.post(f"{duckdb.http_base()}/admin/upload", files=multipart, headers=duckdb.headers())
            )
        except _httpx.HTTPError as e:
            raise ConnectionFailedError(f"upload of {len(batch)} partition(s) failed: {e}") from e
    return responses


async def verify_duckdb_telemetry(
    duckdb: DuckDBConnParams,
    export_dir: Path,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> TelemetryValidationResult:
    """Compare manifest row counts and checksums with what DuckDB now holds."""
    import httpx as _httpx

    manifest_path = export_dir / MANIFEST_FILENAME
    if not manifest_path.exists():
        raise PrerequisiteError(f"telemetry manifest not found: {manifest_path}")
    manifest = read_manifest(manifest_path)

    owns_client = http_client is None
    client = http_client or _httpx.AsyncClient(timeout=_httpx.Timeout(120.0, connect=10.0))
    try:
        checksum_results = _verify_artifact_checksums(export_dir, manifest)
        row_count_results: dict[str, tuple[int, int]] = {}
        for table, table_meta in manifest.get("tables", {}).items():
            expected = int(table_meta.get("row_count") or 0)
            try:
                response = await client.post(
                    f"{duckdb.http_base()}/query",
                    json={"sql": f"SELECT count(*) AS cnt FROM {table}"},
                    headers=duckdb.headers(),
                )
            except _httpx.HTTPError as e:
                raise ConnectionFailedError(f"row-count check for {table} failed: {e}") from e
            if response.status_code != 200:
                # -1 marks an unverifiable table so the caller reports a mismatch
                # instead of silently treating it as "nothing to report".
                optic.warning("{}: row-count query failed: HTTP {}", table, response.status_code)
                row_count_results[table] = (expected, -1)
                continue
            rows = response.json().get("data") or [{}]
            row_count_results[table] = (expected, int(rows[0].get("cnt") or 0))
    finally:
        if owns_client:
            await client.aclose()

    return TelemetryValidationResult(
        checksums_valid=all(checksum_results.values()) if checksum_results else True,
        checksum_results=checksum_results,
        fk_results=None,
        row_count_results=row_count_results,
    )
