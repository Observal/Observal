# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Monthly Parquet export from ClickHouse + telemetry_manifest generation."""

from __future__ import annotations

import hashlib
import os
import shutil
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from loguru import logger as optic

from observal_shared.migration.archive import (
    _is_empty_parquet,
    _month_range,
    _sha256_file,
    read_manifest,
    write_manifest,
)
from observal_shared.migration.connections import ChConnParams, parse_clickhouse_url
from observal_shared.migration.constants import CLICKHOUSE_TABLES, EPOCH_SENTINELS
from observal_shared.migration.exceptions import ConnectionFailedError, MigrationError, PrerequisiteError
from observal_shared.migration.results import TelemetryExportResult

if TYPE_CHECKING:
    from pathlib import Path

    import httpx

    from observal_shared.migration.progress import ProgressReporter


async def _ch_query(
    http_url: str,
    db: str,
    user: str,
    password: str,
    sql: str,
    *,
    stream_to: Path | None = None,
    http_client: httpx.AsyncClient | None = None,
    extra_params: dict[str, str] | None = None,
) -> httpx.Response:
    """Execute a ClickHouse query via HTTP.

    If stream_to is provided, streams response body to disk atomically.
    Raises MigrationError on HTTP or connection errors.
    """
    import httpx as _httpx

    params: dict[str, str] = {"database": db}
    if extra_params:
        params.update(extra_params)
    owns_client = http_client is None
    if owns_client:
        http_client = _httpx.AsyncClient(timeout=_httpx.Timeout(300.0, connect=10.0))
    try:
        if stream_to:
            tmp = stream_to.with_suffix(stream_to.suffix + ".tmp")
            try:
                async with http_client.stream(
                    "POST", http_url, content=sql, auth=(user, password), params=params
                ) as resp:
                    resp.raise_for_status()
                    with open(tmp, "wb") as f:
                        async for chunk in resp.aiter_bytes(chunk_size=65536):
                            f.write(chunk)
                os.replace(tmp, stream_to)
                return resp
            except Exception:
                tmp.unlink(missing_ok=True)
                raise
        else:
            resp = await http_client.post(http_url, content=sql, auth=(user, password), params=params)
            resp.raise_for_status()
            return resp
    except _httpx.HTTPStatusError as exc:
        optic.error("ClickHouse returned HTTP {}", exc.response.status_code)
        raise MigrationError(f"ClickHouse returned HTTP {exc.response.status_code}: {exc.response.text[:500]}") from exc
    except _httpx.RequestError as exc:
        optic.error("ClickHouse unreachable: {}", exc)
        raise ConnectionFailedError(f"ClickHouse unreachable: {exc}") from exc
    finally:
        if owns_client:
            await http_client.aclose()


def _build_ch_export_query(table_cfg: dict, yyyymm: int, *, cutoff: str | None = None) -> str:
    """Build a ClickHouse export query for a monthly partition."""
    name = table_cfg["name"]
    time_col = table_cfg["time_col"]
    where_parts: list[str] = []
    if table_cfg["engine"] == "replacing":
        final = " FINAL"
        where_parts.append("is_deleted = 0")
    else:
        final = ""
    where_parts.append(f"toYYYYMM({time_col}) = {yyyymm}")
    if cutoff:
        where_parts.append(f"{time_col} < {{cutoff:String}}")
    where = " AND ".join(where_parts)
    return f"SELECT * FROM {name}{final} WHERE {where} FORMAT Parquet"


def _build_ch_count_query(table_cfg: dict, yyyymm: int, *, cutoff: str | None = None) -> str:
    """Build a row count query for a monthly partition."""
    name = table_cfg["name"]
    time_col = table_cfg["time_col"]
    where_parts: list[str] = []
    if table_cfg["engine"] == "replacing":
        final = " FINAL"
        where_parts.append("is_deleted = 0")
    else:
        final = ""
    where_parts.append(f"toYYYYMM({time_col}) = {yyyymm}")
    if cutoff:
        where_parts.append(f"{time_col} < {{cutoff:String}}")
    where = " AND ".join(where_parts)
    return f"SELECT count() AS cnt FROM {name}{final} WHERE {where} FORMAT JSON"


def _read_count(resp: httpx.Response) -> int:
    """Parse a count query response."""
    return int(resp.json().get("data", [{}])[0].get("cnt", 0))


def _build_ch_time_range_query(table_cfg: dict) -> str:
    """Build a time range query to discover partition months."""
    name = table_cfg["name"]
    time_col = table_cfg["time_col"]
    if table_cfg["engine"] == "replacing":
        return (
            f"SELECT min({time_col}) AS min_t, max({time_col}) AS max_t "
            f"FROM {name} FINAL WHERE is_deleted = 0 FORMAT JSON"
        )
    return f"SELECT min({time_col}) AS min_t, max({time_col}) AS max_t FROM {name} FORMAT JSON"


async def export_ch(
    params: ChConnParams,
    manifest_path: Path,
    output_dir: Path,
    reporter: ProgressReporter,
) -> TelemetryExportResult:
    """Export ClickHouse telemetry tables to monthly Parquet files.

    Requires a Phase 1 PG manifest (migration_manifest.json) as prerequisite.
    Raises PrerequisiteError if manifest is missing or Phase 1 incomplete.
    """
    import httpx as _httpx

    t0 = time.monotonic()

    # Phase gate: read Phase 1 manifest
    if not manifest_path.exists():
        raise PrerequisiteError(f"Phase 1 manifest not found: {manifest_path}")
    p1_manifest = read_manifest(manifest_path)
    if not p1_manifest.get("phase1_completed_at"):
        raise PrerequisiteError("Phase 1 has not completed. Run PG export first.")
    migration_id = p1_manifest["migration_id"]

    # Record cutoff before any queries
    export_time_cutoff = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    # Parse ClickHouse URL
    http_url, db, user, password = parse_clickhouse_url(params.url)

    # Health check
    try:
        async with _httpx.AsyncClient(timeout=_httpx.Timeout(30.0, connect=10.0)) as hc:
            resp = await hc.post(http_url, content="SELECT 1", auth=(user, password), params={"database": db})
            resp.raise_for_status()
    except (_httpx.HTTPStatusError, _httpx.RequestError) as exc:
        raise ConnectionFailedError(f"ClickHouse health check failed: {exc}") from exc

    await reporter.update(phase="ch_export", pct=0, message="Connected to ClickHouse")

    # Create output directory
    if output_dir.exists() and any(output_dir.iterdir()):
        raise MigrationError(f"Output directory is not empty: {output_dir}")
    dir_existed = output_dir.exists()
    os.makedirs(output_dir, mode=0o700, exist_ok=True)
    os.chmod(output_dir, 0o700)

    try:
        table_meta: dict[str, dict] = {}
        total_rows = 0
        total_size = 0
        total_tables = len(CLICKHOUSE_TABLES)

        async with _httpx.AsyncClient(timeout=_httpx.Timeout(300.0, connect=10.0)) as http_client:
            # Pre-check which tables exist on the source
            existing_sql = "SELECT name FROM system.tables WHERE database = {db:String} FORMAT JSON"
            existing_resp = await _ch_query(
                http_url, db, user, password, existing_sql, http_client=http_client, extra_params={"param_db": db}
            )
            source_tables = {r["name"] for r in existing_resp.json().get("data", [])}

            for t_idx, table_cfg in enumerate(CLICKHOUSE_TABLES):
                table_name = table_cfg["name"]
                pct = int((t_idx / total_tables) * 90) + 5

                # Skip tables that don't exist on source
                if table_name not in source_tables:
                    table_meta[table_name] = {"files": [], "row_count": 0, "checksum": {}, "time_range": None}
                    optic.debug("{}: table not found on source (skipped)", table_name)
                    await reporter.update(phase="ch_export", pct=pct, message=f"Skipping {table_name} (not found)")
                    continue

                await reporter.update(phase="ch_export", pct=pct, message=f"Discovering time range for {table_name}")

                # Query time range
                tr_sql = _build_ch_time_range_query(table_cfg)
                tr_resp = await _ch_query(http_url, db, user, password, tr_sql, http_client=http_client)
                tr_data = tr_resp.json().get("data", [{}])[0]
                min_t = tr_data.get("min_t")
                max_t = tr_data.get("max_t")

                if min_t in EPOCH_SENTINELS or max_t in EPOCH_SENTINELS:
                    table_meta[table_name] = {"files": [], "row_count": 0, "checksum": {}, "time_range": None}
                    optic.debug("{}: empty", table_name)
                    continue

                # Parse time range
                min_dt = datetime.fromisoformat(str(min_t).replace(" ", "T"))
                max_dt = datetime.fromisoformat(str(max_t).replace(" ", "T"))
                months = _month_range(min_dt, max_dt)

                files: list[str] = []
                checksums: dict[str, str] = {}
                table_row_count = 0

                cutoff_params: dict[str, str] | None = (
                    {"param_cutoff": export_time_cutoff} if export_time_cutoff else None
                )

                for yyyymm in months:
                    filename = f"{table_name}_{yyyymm // 100}-{yyyymm % 100:02d}.parquet"
                    filepath = output_dir / filename

                    # Get row count first
                    count_sql = _build_ch_count_query(table_cfg, yyyymm, cutoff=export_time_cutoff)
                    count_resp = await _ch_query(
                        http_url,
                        db,
                        user,
                        password,
                        count_sql,
                        http_client=http_client,
                        extra_params=cutoff_params,
                    )
                    partition_count = _read_count(count_resp)

                    if partition_count == 0:
                        continue

                    await reporter.update(
                        phase="ch_export",
                        pct=pct,
                        message=f"Exporting {filename} ({partition_count:,} rows)",
                    )

                    # Stream Parquet to disk
                    export_sql = _build_ch_export_query(table_cfg, yyyymm, cutoff=export_time_cutoff)
                    await _ch_query(
                        http_url,
                        db,
                        user,
                        password,
                        export_sql,
                        stream_to=filepath,
                        http_client=http_client,
                        extra_params=cutoff_params,
                    )

                    # Check if file is actually empty (edge case)
                    if _is_empty_parquet(filepath):
                        filepath.unlink(missing_ok=True)
                        continue

                    checksum = _sha256_file(filepath)
                    files.append(filename)
                    checksums[filename] = checksum
                    table_row_count += partition_count
                    total_size += filepath.stat().st_size

                total_rows += table_row_count
                table_meta[table_name] = {
                    "files": files,
                    "row_count": table_row_count,
                    "checksum": checksums,
                    "time_range": {"min": str(min_t), "max": str(max_t)} if files else None,
                }
                optic.info("{}: {} rows in {} file(s)", table_name, table_row_count, len(files))

        await reporter.update(phase="ch_export", pct=95, message="Writing telemetry manifest")

        # Write telemetry manifest
        ch_url_hash = hashlib.sha256(params.url.encode()).hexdigest()
        telemetry_manifest = {
            "migration_id": migration_id,
            "phase": "deep_copy",
            "phase_status": "export_complete",
            "export_completed_at": datetime.now(UTC).isoformat(),
            "export_time_cutoff": export_time_cutoff,
            "source_clickhouse_url_hash": ch_url_hash,
            "tables": table_meta,
            "fk_validation": {
                "orphaned_agent_ids": [],
                "orphaned_agent_ids_truncated": False,
                "orphaned_user_ids": [],
                "orphaned_user_ids_truncated": False,
                "validated_at": None,
            },
        }
        manifest_out = output_dir / "telemetry_manifest.json"
        write_manifest(manifest_out, telemetry_manifest)

        elapsed = time.monotonic() - t0
        await reporter.update(phase="ch_export", pct=100, message="Telemetry export complete")

        return TelemetryExportResult(
            output_dir=str(output_dir),
            migration_id=migration_id,
            table_results=table_meta,
            total_rows=total_rows,
            total_size_bytes=total_size,
            duration_seconds=round(elapsed, 2),
        )

    except Exception:
        # Clean up on failure only if we created the directory
        if not dir_existed and output_dir.exists():
            shutil.rmtree(output_dir, ignore_errors=True)
        raise
