# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""FK-safe PostgreSQL import: session_replication_role='replica', ON CONFLICT DO NOTHING."""

from __future__ import annotations

import json
import os
import shutil
import tarfile
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger as optic

from observal_shared.migration.archive import _safe_tar_extract, _sha256_file, read_manifest
from observal_shared.migration.connections import PgConnParams, connect_pg
from observal_shared.migration.constants import CHUNK_SIZE, INSERT_ORDER
from observal_shared.migration.encoding import _build_insert, _coerce_value
from observal_shared.migration.exceptions import ChecksumMismatchError, MigrationError
from observal_shared.migration.results import ImportResult

if TYPE_CHECKING:
    import asyncpg

    from observal_shared.migration.progress import ProgressReporter


async def _get_column_types(conn: asyncpg.Connection, table: str) -> dict[str, str]:
    """Get column name -> PostgreSQL type mapping for a table."""
    rows = await conn.fetch(
        "SELECT column_name, udt_name FROM information_schema.columns WHERE table_name = $1 ORDER BY ordinal_position",
        table,
    )
    return {row["column_name"]: row["udt_name"] for row in rows}


async def _get_org_fk_columns(conn: asyncpg.Connection) -> set[str]:
    """Discover all columns that FK-reference organizations.id from information_schema."""
    rows = await conn.fetch(
        """
        SELECT DISTINCT kcu.column_name
        FROM information_schema.referential_constraints rc
        JOIN information_schema.key_column_usage kcu
            ON kcu.constraint_name = rc.constraint_name
            AND kcu.constraint_schema = rc.constraint_schema
        JOIN information_schema.key_column_usage ccu
            ON ccu.constraint_name = rc.unique_constraint_name
            AND ccu.constraint_schema = rc.unique_constraint_schema
        WHERE ccu.table_name = 'organizations'
            AND ccu.column_name = 'id'
            AND rc.constraint_schema = 'public'
        """
    )
    return {row["column_name"] for row in rows}


async def _get_notnull_json_defaults(conn: asyncpg.Connection, table: str) -> dict[str, str]:
    """Discover NOT NULL columns with defaults for a table.

    Handles JSON/JSONB columns (empty objects), boolean columns (false fallback),
    and all other NOT NULL columns with explicit column_default values.
    """
    rows = await conn.fetch(
        """
        SELECT column_name, column_default, udt_name
        FROM information_schema.columns
        WHERE table_name = $1
            AND table_schema = 'public'
            AND is_nullable = 'NO'
            AND (udt_name IN ('json', 'jsonb', 'bool') OR column_default IS NOT NULL)
        """,
        table,
    )
    defaults: dict[str, str] = {}
    for row in rows:
        col_name = row["column_name"]
        col_default = row["column_default"]
        udt_name = row["udt_name"]

        if col_default:
            clean = col_default.split("::")[0].strip().strip("'")
            defaults[col_name] = clean
        elif udt_name in ("json", "jsonb"):
            defaults[col_name] = "{}"
        elif udt_name == "bool":
            defaults[col_name] = "false"
    return defaults


async def _flush_batch(
    conn: asyncpg.Connection,
    table: str,
    columns: list[str],
    col_types: dict[str, str],
    batch: list[dict],
    notnull_defaults: dict[str, str] | None = None,
) -> tuple[int, int, list[str]]:
    """Flush a batch of rows to the database. Returns (inserted, skipped, warnings)."""
    import asyncpg as _asyncpg

    if not batch:
        return 0, 0, []

    query = _build_insert(table, columns, col_types)

    inserted = 0
    skipped = 0
    batch_warnings: list[str] = []
    defaulted_cols: set[str] = set()

    for row in batch:
        # Apply NOT NULL defaults for columns that are NULL in the archive
        if notnull_defaults:
            for col, default_val in notnull_defaults.items():
                if col in columns and row.get(col) is None:
                    row[col] = default_val
                    if col not in defaulted_cols:
                        optic.debug("{}: substituting default for NULL in NOT NULL column '{}'", table, col)
                        defaulted_cols.add(col)

        values = [_coerce_value(row.get(col), col_types.get(col, "")) for col in columns]
        try:
            status = await conn.execute(query, *values)
            count = int(status.split()[-1])
            if count > 0:
                inserted += 1
            else:
                skipped += 1
        except _asyncpg.ForeignKeyViolationError as e:
            row_id = row.get("id", "unknown")
            optic.warning("FK violation in {}, row {}: {}", table, row_id, e.constraint_name)
            skipped += 1
        except _asyncpg.UniqueViolationError as e:
            row_id = row.get("id", "unknown")
            msg = f"{table}: unique conflict on row {row_id} ({e.constraint_name})"
            optic.warning("Unique conflict in {}, row {}: {}", table, row_id, e.constraint_name)
            batch_warnings.append(msg)
            skipped += 1

    return inserted, skipped, batch_warnings


async def _insert_table(
    conn: asyncpg.Connection,
    table: str,
    jsonl_path: Path,
    col_types: dict[str, str],
    org_rewrite_map: dict[str, str] | None = None,
    org_columns: set[str] | None = None,
    notnull_defaults: dict[str, str] | None = None,
) -> tuple[int, int, list[str]]:
    """Insert rows from a JSONL file into a table. Returns (inserted, skipped, warnings)."""
    inserted = 0
    skipped = 0
    table_warnings: list[str] = []
    batch: list[dict] = []
    columns = sorted(col_types.keys())
    logged_skipped = False

    # Determine which columns in this table need org rewriting
    rewrite_cols = (org_columns & set(columns)) if org_rewrite_map and org_columns else set()

    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)

            if not logged_skipped:
                skipped_cols = set(row) - set(columns)
                if skipped_cols:
                    optic.debug(
                        "{}: skipping archive columns not in target: {}",
                        jsonl_path.stem,
                        ", ".join(sorted(skipped_cols)),
                    )
                    logged_skipped = True

            # Rewrite org IDs if normalization is active
            if rewrite_cols and org_rewrite_map:
                for col in rewrite_cols:
                    val = row.get(col)
                    if val and val in org_rewrite_map:
                        row[col] = org_rewrite_map[val]

            batch.append(row)

            if len(batch) >= CHUNK_SIZE:
                ins, sk, bw = await _flush_batch(conn, table, columns, col_types, batch, notnull_defaults)
                inserted += ins
                skipped += sk
                table_warnings.extend(bw)
                batch = []

    if batch and columns:
        ins, sk, bw = await _flush_batch(conn, table, columns, col_types, batch, notnull_defaults)
        inserted += ins
        skipped += sk
        table_warnings.extend(bw)

    return inserted, skipped, table_warnings


async def import_pg(
    params: PgConnParams,
    archive_path: Path,
    reporter: ProgressReporter,
    normalize_org_id: str | None = None,
) -> ImportResult:
    """Import a migration archive into the target database.

    Verifies checksums before loading any data. Uses session_replication_role='replica'
    to disable FK triggers during bulk insert. Raises ChecksumMismatchError if
    verification fails before any data load.
    """
    t0 = time.monotonic()
    warnings: list[str] = []

    staging_dir = Path(tempfile.mkdtemp())
    os.chmod(staging_dir, 0o700)
    try:
        await reporter.update(phase="pg_import", pct=0, message="Extracting archive")

        # Extract archive
        with tarfile.open(archive_path, "r:gz") as tar:
            _safe_tar_extract(tar, staging_dir)

        # Read manifest
        manifest_path = staging_dir / "manifest.json"
        if not manifest_path.exists():
            raise MigrationError("Archive does not contain manifest.json")
        manifest = read_manifest(manifest_path)
        migration_id = manifest["migration_id"]

        await reporter.update(phase="pg_import", pct=5, message="Verifying checksums")

        # Verify checksums BEFORE any DB operations
        failed_checksums: list[str] = []
        for table in INSERT_ORDER:
            jsonl_path = staging_dir / "pg" / f"{table}.jsonl"
            if not jsonl_path.exists():
                if table not in manifest["tables"]:
                    continue
                failed_checksums.append(f"{table} (file missing)")
                continue
            if table not in manifest["tables"]:
                continue
            expected = manifest["tables"][table]["checksum"]
            actual = _sha256_file(jsonl_path)
            if actual != expected:
                failed_checksums.append(table)

        if failed_checksums:
            raise ChecksumMismatchError(
                f"Checksum verification failed for: {', '.join(failed_checksums)}. "
                "Archive may be corrupted or tampered. Re-export from source."
            )

        await reporter.update(phase="pg_import", pct=10, message="Connecting to target database")

        # Connect and verify schema version
        conn = await connect_pg(params)
        try:
            target_version = await conn.fetchval("SELECT version_num FROM alembic_version LIMIT 1")
            source_version = manifest["source_alembic_version"]
            if target_version != source_version:
                optic.info(
                    "Schema version mismatch (non-fatal): archive={}, target={}",
                    source_version,
                    target_version,
                )
                warnings.append(f"Schema version mismatch: archive={source_version}, target={target_version}")

            rows_inserted: dict[str, int] = {}
            rows_skipped: dict[str, int] = {}

            # Discover which tables exist on the target
            existing_tables = {
                row["table_name"]
                for row in await conn.fetch(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
                )
            }

            # Org ID normalization: detect source org(s) and build rewrite map
            org_rewrite_map: dict[str, str] = {}
            source_org_ids: set[str] = set()
            org_jsonl = staging_dir / "pg" / "organizations.jsonl"
            if org_jsonl.exists():
                with open(org_jsonl, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        row = json.loads(line)
                        src_id = row.get("id")
                        if src_id:
                            source_org_ids.add(src_id)

            if normalize_org_id:
                for src_id in source_org_ids:
                    if src_id != normalize_org_id:
                        org_rewrite_map[src_id] = normalize_org_id
                if org_rewrite_map:
                    optic.info("Normalizing {} source org(s) to: {}", len(org_rewrite_map), normalize_org_id)
            elif source_org_ids:
                target_org_ids = {str(row["id"]) for row in await conn.fetch('SELECT "id" FROM "organizations"')}
                foreign_orgs = source_org_ids - target_org_ids
                if foreign_orgs:
                    warnings.append(f"Archive contains {len(foreign_orgs)} org(s) not on target; use org_id to remap")

            # Derive org FK columns from schema
            org_columns = await _get_org_fk_columns(conn)

            # Disable all user-defined triggers (including FK constraint triggers)
            await conn.execute("SET session_replication_role = 'replica'")
            try:
                total_tables = len(INSERT_ORDER)
                for idx, table in enumerate(INSERT_ORDER):
                    pct = int((idx / total_tables) * 80) + 15  # 15-95%
                    await reporter.update(phase="pg_import", pct=pct, message=f"Importing {table}")

                    jsonl_path = staging_dir / "pg" / f"{table}.jsonl"

                    # Skip tables that don't exist on target
                    if table not in existing_tables:
                        optic.debug("Skipping {} (table does not exist on target)", table)
                        rows_inserted[table] = 0
                        rows_skipped[table] = 0
                        continue

                    # Skip tables not present in the archive
                    if not jsonl_path.exists() or jsonl_path.stat().st_size == 0:
                        rows_inserted[table] = 0
                        rows_skipped[table] = 0
                        continue

                    # Get column types for proper coercion
                    col_types = await _get_column_types(conn, table)

                    # Get NOT NULL defaults from schema
                    notnull_defaults = await _get_notnull_json_defaults(conn, table)

                    ins, sk, tw = await _insert_table(
                        conn,
                        table,
                        jsonl_path,
                        col_types,
                        org_rewrite_map=org_rewrite_map,
                        org_columns=org_columns,
                        notnull_defaults=notnull_defaults,
                    )
                    rows_inserted[table] = ins
                    rows_skipped[table] = sk
                    warnings.extend(tw)
            finally:
                # Always restore default trigger behavior
                await conn.execute("SET session_replication_role = 'origin'")

            await reporter.update(phase="pg_import", pct=96, message="Running post-import fixups")

            # Post-import fixup: backfill NULL owner_org_id from creator's org
            _org_backfill: list[tuple[str, str]] = [
                ("agents", "created_by"),
                ("mcp_listings", "submitted_by"),
                ("skill_listings", "submitted_by"),
                ("hook_listings", "submitted_by"),
                ("prompt_listings", "submitted_by"),
                ("sandbox_listings", "submitted_by"),
            ]
            for tbl, creator_col in _org_backfill:
                if tbl not in existing_tables:
                    continue
                tbl_cols = await _get_column_types(conn, tbl)
                if "owner_org_id" not in tbl_cols:
                    continue
                result = await conn.execute(
                    f'UPDATE "{tbl}" SET "owner_org_id" = "u"."org_id" '
                    f'FROM "users" "u" '
                    f'WHERE "{tbl}"."{creator_col}" = "u"."id" '
                    f'AND "{tbl}"."owner_org_id" IS NULL '
                    f'AND "u"."org_id" IS NOT NULL'
                )
                count = int(result.split()[-1])
                if count > 0:
                    optic.info("Fixed {} row(s) in {} with NULL owner_org_id", count, tbl)
                    warnings.append(f"{tbl}: backfilled owner_org_id for {count} row(s)")

        finally:
            await conn.close()

        elapsed = time.monotonic() - t0
        await reporter.update(phase="pg_import", pct=100, message="Import complete")

        return ImportResult(
            migration_id=migration_id,
            tables_imported=len(INSERT_ORDER),
            rows_inserted=rows_inserted,
            rows_skipped=rows_skipped,
            duration_seconds=round(elapsed, 2),
            warnings=warnings,
        )

    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)
