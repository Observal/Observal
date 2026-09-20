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

import contextlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from loguru import logger as optic

from observal_shared.migration.archive import _sha256_file, read_manifest
from observal_shared.migration.constants import CLICKHOUSE_TABLES, TELEMETRY_MANIFEST_VERSION
from observal_shared.migration.exceptions import ConnectionFailedError, MigrationError, PrerequisiteError
from observal_shared.migration.results import TelemetryImportResult, TelemetryValidationResult
from observal_shared.migration.telemetry_manifest import validate_telemetry_manifest

if TYPE_CHECKING:
    import httpx

    from observal_shared.migration.progress import ProgressReporter

MANIFEST_FILENAME = "telemetry_manifest.json"
DEFAULT_HTTP_PORT = 8484
ALLOWED_TELEMETRY_TABLES = frozenset(cfg["name"] for cfg in CLICKHOUSE_TABLES)


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


def _validated_manifest_artifacts(export_dir: Path, manifest: dict) -> dict[str, list[Path]]:
    """Validate manifest filenames before any artifact is opened or hashed."""
    tables = manifest.get("tables")
    if not isinstance(tables, dict):
        raise PrerequisiteError("telemetry manifest has no valid tables map")

    root = export_dir.resolve()
    artifacts: dict[str, list[Path]] = {}
    for table, table_meta in tables.items():
        if table not in ALLOWED_TELEMETRY_TABLES:
            raise PrerequisiteError(f"telemetry manifest contains unknown table: {table!r}")
        if not isinstance(table_meta, dict):
            raise PrerequisiteError(f"telemetry manifest is incomplete for {table}")
        filenames = table_meta.get("files") or []
        checksums = table_meta.get("checksum") or {}
        if (
            not isinstance(filenames, list)
            or not all(isinstance(filename, str) for filename in filenames)
            or not isinstance(checksums, dict)
        ):
            raise PrerequisiteError(f"telemetry manifest is incomplete for {table}")
        if len(filenames) != len(set(filenames)) or set(checksums) != set(filenames):
            raise PrerequisiteError(f"telemetry manifest file/checksum mismatch for {table}")
        if int(table_meta.get("row_count") or 0) > 0 and not filenames:
            raise PrerequisiteError(f"telemetry manifest has no files for non-empty table {table}")

        paths: list[Path] = []
        for filename in filenames:
            if not isinstance(filename, str) or not filename or Path(filename).name != filename:
                raise PrerequisiteError(f"telemetry manifest has unsafe filename for {table}: {filename!r}")
            candidate = export_dir / filename
            try:
                resolved = candidate.resolve(strict=True)
            except OSError as exc:
                raise PrerequisiteError(f"telemetry artifact is missing for {table}: {filename}") from exc
            if (
                candidate.is_symlink()
                or not resolved.is_relative_to(root)
                or resolved.parent != root
                or not resolved.is_file()
            ):
                raise PrerequisiteError(f"telemetry manifest has unsafe artifact for {table}: {filename}")
            paths.append(resolved)
        artifacts[table] = paths
    return artifacts


def _verify_artifact_checksums(
    export_dir: Path, manifest: dict, artifacts: dict[str, list[Path]] | None = None
) -> dict[str, bool]:
    validated = artifacts if artifacts is not None else _validated_manifest_artifacts(export_dir, manifest)
    results: dict[str, bool] = {}
    for table, paths in validated.items():
        checksums = manifest["tables"][table]["checksum"]
        for path in paths:
            results[path.name] = _sha256_file(path) == checksums[path.name]
    return results


async def verify_artifact_checksums(export_dir: Path) -> TelemetryValidationResult:
    """Check the export's manifest checksums without contacting the service."""
    manifest_path = export_dir / MANIFEST_FILENAME
    if not manifest_path.exists():
        raise PrerequisiteError(f"telemetry manifest not found: {manifest_path}")
    manifest = read_manifest(manifest_path)
    artifacts = _validated_manifest_artifacts(export_dir, manifest)
    results = _verify_artifact_checksums(export_dir, manifest, artifacts)
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
    if not manifest_path.exists():
        raise PrerequisiteError(f"telemetry manifest not found: {manifest_path}")
    manifest = read_manifest(manifest_path)
    migration_id = str(manifest.get("migration_id") or "")
    if not migration_id or not isinstance(manifest.get("tables"), dict):
        raise PrerequisiteError(f"telemetry manifest is incomplete: {manifest_path}")
    if manifest.get("schema_version") == TELEMETRY_MANIFEST_VERSION:
        # Chunked ClickHouse exports carry per-chunk metadata; reject any manifest
        # whose chunk list, checksums, and row counts disagree before opening files.
        validate_telemetry_manifest(manifest)
    manifest_artifacts = _validated_manifest_artifacts(export_dir, manifest)
    checksum_results = _verify_artifact_checksums(export_dir, manifest, manifest_artifacts)
    invalid = sorted(name for name, valid in checksum_results.items() if not valid)
    if invalid:
        raise MigrationError(f"telemetry artifact checksum failed: {', '.join(invalid)}")

    start = time.monotonic()
    owns_client = http_client is None
    client = http_client or _httpx.AsyncClient(timeout=_httpx.Timeout(600.0, connect=10.0))
    rows_imported: dict[str, int] = {}
    pre_rows: dict[str, int] = {}
    tables_skipped: list[str] = []

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
            files = manifest_artifacts.get(table, [])
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
            if existing.status_code != 200:
                raise MigrationError(f"pre-count of {table} failed: HTTP {existing.status_code} {existing.text[:200]}")
            pre_rows[table] = int(((existing.json().get("data") or [{}])[0]).get("cnt") or 0)
            responses = await _upload_partitions(client, duckdb, files)
            upload_ids: list[str] = []
            uploaded_count = 0
            for upload in responses:
                if upload.status_code != 200:
                    raise MigrationError(f"upload of {table} failed: HTTP {upload.status_code} {upload.text[:200]}")
                body = upload.json()
                upload_id = body.get("upload_id")
                if not isinstance(upload_id, str) or not upload_id:
                    raise MigrationError(f"upload of {table} did not return an upload id")
                upload_ids.append(upload_id)
                uploaded_count += int(body.get("count") or 0)
            if uploaded_count != len(files):
                raise MigrationError(f"upload of {table} accepted {uploaded_count} files for {len(files)} partitions")
            await reporter.update(phase="duckdb_import", pct=pct, message=f"Loading {table}")
            try:
                load = await client.post(
                    f"{duckdb.http_base()}/admin/load_parquet",
                    json={"table": table, "upload_ids": upload_ids, "replace": True},
                    headers=duckdb.headers(),
                    timeout=_httpx.Timeout(None, connect=10.0),
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
        with contextlib.ExitStack() as stack:
            multipart = [
                ("files", (path.name, stack.enter_context(path.open("rb")), "application/octet-stream"))
                for path in batch
            ]
            try:
                responses.append(
                    await client.post(
                        f"{duckdb.http_base()}/admin/upload",
                        files=multipart,
                        headers=duckdb.headers(),
                        timeout=_httpx.Timeout(None, connect=10.0),
                    )
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
