# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Idempotent ClickHouse import: partition-skip and project_id rewrite."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from loguru import logger as optic

from observal_shared.migration.archive import _sha256_file, read_manifest
from observal_shared.migration.ch_export import _ch_query
from observal_shared.migration.connections import ChConnParams, parse_clickhouse_url
from observal_shared.migration.constants import CLICKHOUSE_TABLES
from observal_shared.migration.exceptions import ChecksumMismatchError, ConnectionFailedError, MigrationError
from observal_shared.migration.results import TelemetryImportResult

if TYPE_CHECKING:
    from pathlib import Path

    from observal_shared.migration.progress import ProgressReporter


async def _ch_existing_tables(
    http_url: str,
    db: str,
    user: str,
    password: str,
) -> set[str]:
    """Query system.tables to discover which tables exist on target ClickHouse."""
    sql = "SELECT name FROM system.tables WHERE database = {db:String} FORMAT JSON"
    resp = await _ch_query(http_url, db, user, password, sql, extra_params={"param_db": db})
    return {r["name"] for r in resp.json().get("data", [])}


async def _ch_partition_has_data(
    http_url: str,
    db: str,
    user: str,
    password: str,
    table_cfg: dict,
    yyyymm: int,
) -> bool:
    """Check if a table already has data in a given month partition."""
    name = table_cfg["name"]
    time_col = table_cfg["time_col"]
    if table_cfg["engine"] == "replacing":
        sql = (
            f"SELECT 1 AS has_data FROM {name} FINAL "
            f"WHERE is_deleted = 0 AND toYYYYMM({time_col}) = {yyyymm} LIMIT 1 FORMAT JSON"
        )
    else:
        sql = f"SELECT 1 AS has_data FROM {name} WHERE toYYYYMM({time_col}) = {yyyymm} LIMIT 1 FORMAT JSON"
    resp = await _ch_query(http_url, db, user, password, sql)
    return len(resp.json().get("data", [])) > 0


def _rewrite_project_id(parquet_path: Path, target_project_id: str) -> Path:
    """Rewrite project_id column in a Parquet file, return path to temp file."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pq.read_table(parquet_path)
    if "project_id" not in table.column_names:
        return parquet_path
    idx = table.column_names.index("project_id")
    new_col = pa.nulls(len(table), type=pa.string()).fill_null(target_project_id)
    table = table.set_column(idx, "project_id", new_col)
    tmp_path = parquet_path.with_suffix(".tmp.parquet")
    pq.write_table(table, tmp_path)
    return tmp_path


async def _ch_import(
    http_url: str,
    db: str,
    user: str,
    password: str,
    table: str,
    parquet_path: Path,
) -> None:
    """Import a Parquet file into ClickHouse via INSERT ... FORMAT Parquet."""
    import httpx as _httpx

    sql_prefix = f"INSERT INTO {table} FORMAT Parquet"
    params = {
        "database": db,
        "query": sql_prefix,
        "max_memory_usage": "2000000000",  # 2 GB
    }

    async def _file_stream():
        with open(parquet_path, "rb") as f:
            while chunk := f.read(65536):
                yield chunk

    try:
        async with _httpx.AsyncClient(timeout=_httpx.Timeout(600.0, connect=10.0)) as c:
            resp = await c.post(http_url, content=_file_stream(), auth=(user, password), params=params)
            resp.raise_for_status()
    except _httpx.HTTPStatusError as exc:
        optic.error("ClickHouse returned HTTP {}", exc.response.status_code)
        raise MigrationError(f"ClickHouse returned HTTP {exc.response.status_code}: {exc.response.text[:500]}") from exc
    except _httpx.RequestError as exc:
        optic.error("ClickHouse unreachable: {}", exc)
        raise ConnectionFailedError(f"ClickHouse unreachable: {exc}") from exc


async def import_ch(
    params: ChConnParams,
    input_dir: Path,
    reporter: ProgressReporter,
    normalize_project_id: str | None = None,
) -> TelemetryImportResult:
    """Import Parquet files into target ClickHouse.

    Verifies checksums before importing. Skips partitions that already contain
    data for idempotent re-runs. Raises ChecksumMismatchError if verification fails.
    """
    import httpx as _httpx

    t0 = time.monotonic()
    warnings: list[str] = []

    # Read telemetry manifest
    manifest_path = input_dir / "telemetry_manifest.json"
    if not manifest_path.exists():
        raise MigrationError("Telemetry manifest not found in input directory.")
    manifest = read_manifest(manifest_path)
    migration_id = manifest["migration_id"]

    await reporter.update(phase="ch_import", pct=0, message="Verifying checksums")

    # Verify checksums before any imports
    failed: list[str] = []
    for table_cfg in CLICKHOUSE_TABLES:
        table_name = table_cfg["name"]
        table_info = manifest["tables"].get(table_name, {})
        for filename, expected_hash in table_info.get("checksum", {}).items():
            filepath = input_dir / filename
            if not filepath.exists():
                failed.append(f"{filename} (missing)")
                continue
            actual = _sha256_file(filepath)
            if actual != expected_hash:
                failed.append(filename)

    if failed:
        raise ChecksumMismatchError(f"Checksum verification failed for: {', '.join(failed)}")

    # Connect and discover existing tables
    http_url, db, user, password = parse_clickhouse_url(params.url)
    try:
        async with _httpx.AsyncClient(timeout=_httpx.Timeout(30.0, connect=10.0)) as hc:
            resp = await hc.post(http_url, content="SELECT 1", auth=(user, password), params={"database": db})
            resp.raise_for_status()
    except (_httpx.HTTPStatusError, _httpx.RequestError) as exc:
        raise ConnectionFailedError(f"ClickHouse health check failed: {exc}") from exc

    await reporter.update(phase="ch_import", pct=5, message="Connected to ClickHouse")

    existing = await _ch_existing_tables(http_url, db, user, password)
    rows_imported: dict[str, int] = {}
    tables_skipped: list[str] = []

    # Resume state
    state_path = input_dir / ".import_state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        completed_tables: set[str] = set(state.get("completed", []))
    else:
        completed_tables = set()

    # Validate resume state: check that "completed" tables actually have data
    if completed_tables:
        invalidated: list[str] = []
        for table_cfg in CLICKHOUSE_TABLES:
            tname = table_cfg["name"]
            if tname not in completed_tables:
                continue
            if tname not in existing:
                invalidated.append(tname)
                continue
            if table_cfg["engine"] == "replacing":
                sql = f"SELECT 1 FROM {tname} FINAL WHERE is_deleted = 0 LIMIT 1 FORMAT JSON"
            else:
                sql = f"SELECT 1 FROM {tname} LIMIT 1 FORMAT JSON"
            resp = await _ch_query(http_url, db, user, password, sql)
            if not resp.json().get("data"):
                invalidated.append(tname)
        if invalidated:
            for name in invalidated:
                completed_tables.discard(name)
            optic.warning(
                "Resume state invalidated for {} table(s) (no data found): {}",
                len(invalidated),
                ", ".join(sorted(invalidated)),
            )
            warnings.append(f"Resume state invalidated for: {', '.join(sorted(invalidated))}")
            state_path.write_text(
                json.dumps({"completed": sorted(completed_tables)}, indent=2),
                encoding="utf-8",
            )

    total_tables = len(CLICKHOUSE_TABLES)
    for t_idx, table_cfg in enumerate(CLICKHOUSE_TABLES):
        table_name = table_cfg["name"]
        table_info = manifest["tables"].get(table_name, {})
        files = table_info.get("files", [])
        pct = int((t_idx / total_tables) * 85) + 10

        if not files:
            rows_imported[table_name] = 0
            continue

        if table_name not in existing:
            optic.info("Skipping {} (table does not exist on target)", table_name)
            tables_skipped.append(table_name)
            warnings.append(f"{table_name}: table does not exist on target")
            rows_imported[table_name] = 0
            continue

        if table_name in completed_tables:
            optic.debug("Skipping {} (already imported)", table_name)
            rows_imported[table_name] = table_info.get("row_count", 0)
            continue

        await reporter.update(phase="ch_import", pct=pct, message=f"Importing {table_name}")

        for filename in files:
            filepath = input_dir / filename

            # Idempotency: check if partition already has data
            parts = filename.replace(".parquet", "").split("_")
            date_part = parts[-1]  # "2025-01"
            year, month = date_part.split("-")
            yyyymm = int(year) * 100 + int(month)
            if await _ch_partition_has_data(http_url, db, user, password, table_cfg, yyyymm):
                optic.debug("Skipping {} (partition already has data)", filename)
                warnings.append(f"{filename}: partition already has data")
                continue

            optic.info("Importing {}", filename)
            import_path = filepath
            if normalize_project_id is not None:
                import_path = _rewrite_project_id(filepath, normalize_project_id)
            try:
                await _ch_import(http_url, db, user, password, table_name, import_path)
            finally:
                if import_path != filepath:
                    import_path.unlink(missing_ok=True)

        rows_imported[table_name] = table_info.get("row_count", 0)
        optic.info("{}: {} rows", table_name, rows_imported[table_name])

        # Persist resume state after each successful table
        completed_tables.add(table_name)
        state_path.write_text(
            json.dumps({"completed": sorted(completed_tables)}, indent=2),
            encoding="utf-8",
        )

    elapsed = time.monotonic() - t0
    await reporter.update(phase="ch_import", pct=100, message="Telemetry import complete")

    return TelemetryImportResult(
        migration_id=migration_id,
        tables_imported=sum(1 for v in rows_imported.values() if v > 0),
        tables_skipped=tables_skipped,
        rows_imported=rows_imported,
        duration_seconds=round(elapsed, 2),
        warnings=warnings,
    )
