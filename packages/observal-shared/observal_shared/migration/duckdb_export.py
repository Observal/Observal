# SPDX-FileCopyrightText: 2026 Observal contributors
# SPDX-License-Identifier: Apache-2.0

"""Telemetry export from the DuckDB analytics service.

Instance moves (Admin -> Data Migration) previously exported ClickHouse
telemetry. This module produces the same artifact shape from DuckDB: monthly
Parquet partitions plus a checksummed ``telemetry_manifest.json`` that the
existing importer and validator consume unchanged.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from loguru import logger as optic

from observal_shared.migration.archive import write_manifest
from observal_shared.migration.constants import CLICKHOUSE_TABLES
from observal_shared.migration.exceptions import ConnectionFailedError, MigrationError, PrerequisiteError
from observal_shared.migration.results import TelemetryExportResult

if TYPE_CHECKING:
    from pathlib import Path

    import httpx

    from observal_shared.migration.duckdb_import import DuckDBConnParams
    from observal_shared.migration.progress import ProgressReporter

MANIFEST_FILENAME = "telemetry_manifest.json"


async def export_duckdb_telemetry(
    duckdb: DuckDBConnParams,
    output_dir: Path,
    reporter: ProgressReporter,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> TelemetryExportResult:
    """Export every telemetry table to Parquet under *output_dir*.

    The destination must not already exist: a failed export removes the whole
    directory rather than leaving partial artifacts behind.
    """
    import httpx as _httpx

    if output_dir.exists():
        raise PrerequisiteError(f"export directory already exists: {output_dir}")

    start = time.monotonic()
    owns_client = http_client is None
    client = http_client or _httpx.AsyncClient(timeout=_httpx.Timeout(600.0, connect=10.0))
    migration_id = str(uuid.uuid4())

    try:
        await reporter.update(phase="duckdb_export", pct=0, message="Requesting analytics export")
        try:
            response = await client.post(f"{duckdb.http_base()}/admin/export", json={}, headers=duckdb.headers())
        except _httpx.HTTPError as e:
            raise ConnectionFailedError(f"analytics service unreachable at {duckdb.http_base()}: {e}") from e
        if response.status_code != 200:
            raise MigrationError(f"export request failed: HTTP {response.status_code} {response.text[:200]}")

        payload = response.json()
        files = payload.get("files") or []
        row_counts: dict[str, int] = payload.get("row_counts") or {}

        output_dir.mkdir(parents=True, mode=0o700)
        table_meta: dict[str, dict] = {
            cfg["name"]: {"files": [], "row_count": 0, "checksum": {}} for cfg in CLICKHOUSE_TABLES
        }
        total_rows = 0
        total_size = 0

        for index, entry in enumerate(files):
            name = entry["name"]
            pct = int((index / max(len(files), 1)) * 90) + 5
            await reporter.update(phase="duckdb_export", pct=pct, message=f"Downloading {name}")
            target = output_dir / name
            hasher = hashlib.sha256()
            async with client.stream(
                "GET",
                f"{duckdb.http_base()}/admin/file",
                params={"path": f"{payload['destination']}/{name}"},
                headers=duckdb.headers(),
            ) as download:
                if download.status_code != 200:
                    raise MigrationError(f"download of {name} failed: HTTP {download.status_code}")
                with target.open("wb") as handle:
                    async for chunk in download.aiter_bytes(chunk_size=65536):
                        handle.write(chunk)
                        hasher.update(chunk)
            target.chmod(0o600)
            digest = hasher.hexdigest()
            if digest != entry.get("sha256"):
                raise MigrationError(f"checksum mismatch while downloading {name}")
            total_size += target.stat().st_size

            table = next((cfg["name"] for cfg in CLICKHOUSE_TABLES if name.startswith(f"{cfg['name']}_")), None)
            if table is None:
                optic.warning("exported file {} does not match a known telemetry table", name)
                continue
            table_meta[table]["files"].append(name)
            table_meta[table]["checksum"][name] = digest

        for cfg in CLICKHOUSE_TABLES:
            table = cfg["name"]
            table_meta[table]["row_count"] = int(row_counts.get(table, 0))
            total_rows += table_meta[table]["row_count"]

        manifest = {
            "migration_id": migration_id,
            "generated_at": datetime.now(UTC).isoformat(),
            "source": "duckdb",
            "tables": {table: meta for table, meta in table_meta.items() if meta["files"]},
        }
        write_manifest(output_dir / MANIFEST_FILENAME, manifest)
        await reporter.update(phase="duckdb_export", pct=100, message="Analytics export complete")
    except Exception:
        import shutil

        shutil.rmtree(output_dir, ignore_errors=True)
        raise
    finally:
        if owns_client:
            await client.aclose()

    return TelemetryExportResult(
        output_dir=str(output_dir),
        migration_id=migration_id,
        table_results=manifest["tables"],
        total_rows=total_rows,
        total_size_bytes=total_size,
        duration_seconds=time.monotonic() - start,
    )
