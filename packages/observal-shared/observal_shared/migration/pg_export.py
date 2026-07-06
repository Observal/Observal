# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""PostgreSQL snapshot-read export: REPEATABLE READ → JSONL + manifest."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger as optic

from observal_shared.migration.archive import (
    _sha256_file,
    build_migration_manifest,
    build_pg_manifest,
    pack_pg_archive,
    write_manifest,
)
from observal_shared.migration.connections import PgConnParams, connect_pg
from observal_shared.migration.constants import CHUNK_SIZE, INSERT_ORDER
from observal_shared.migration.encoding import PGEncoder, _build_select
from observal_shared.migration.exceptions import MigrationError
from observal_shared.migration.results import ExportResult

if TYPE_CHECKING:
    from observal_shared.migration.progress import ProgressReporter


async def export_pg(
    params: PgConnParams,
    output_path: Path,
    reporter: ProgressReporter,
) -> ExportResult:
    """Export all tables to JSONL files and pack into a tar.gz archive.

    Uses a REPEATABLE READ transaction for a consistent snapshot.
    Raises MigrationError or ConnectionFailedError on failure.
    """
    t0 = time.monotonic()
    migration_id = str(uuid.uuid4())

    staging_dir = Path(tempfile.mkdtemp())
    os.chmod(staging_dir, 0o700)
    try:
        pg_dir = staging_dir / "pg"
        pg_dir.mkdir()

        await reporter.update(phase="pg_export", pct=0, message="Connecting to source database")
        conn = await connect_pg(params)
        try:
            # Read alembic version
            alembic_version = await conn.fetchval("SELECT version_num FROM alembic_version LIMIT 1")
            if not alembic_version:
                raise MigrationError("Could not read alembic version from source database.")

            table_counts: dict[str, int] = {}
            file_hashes: dict[str, str] = {}
            uuid_ranges: dict[str, dict[str, str]] = {}

            total_tables = len(INSERT_ORDER)

            # Open REPEATABLE READ transaction for consistent snapshot
            async with conn.transaction(isolation="repeatable_read", readonly=True):
                # Discover which tables actually exist in the database
                existing_tables = {
                    row["table_name"]
                    for row in await conn.fetch(
                        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
                    )
                }

                for idx, table in enumerate(INSERT_ORDER):
                    pct = int((idx / total_tables) * 90) + 5  # 5-95%
                    await reporter.update(phase="pg_export", pct=pct, message=f"Exporting {table}")

                    dest = pg_dir / f"{table}.jsonl"

                    # Skip tables that don't exist yet (DB on older migration)
                    if table not in existing_tables:
                        optic.debug("Skipping {} (table does not exist)", table)
                        dest.write_text("", encoding="utf-8")
                        table_counts[table] = 0
                        file_hashes[table] = _sha256_file(dest)
                        continue

                    # Discover columns via prepared statement
                    stmt = await conn.prepare(f'SELECT * FROM "{table}" LIMIT 0')
                    columns = [attr.name for attr in stmt.get_attributes()]

                    query = _build_select(table, columns)

                    row_count = 0
                    min_id: str | None = None
                    max_id: str | None = None

                    with open(dest, "w", encoding="utf-8") as f:
                        async for record in conn.cursor(query, prefetch=CHUNK_SIZE):
                            row = dict(record)
                            line = json.dumps(row, cls=PGEncoder)
                            f.write(line + "\n")
                            row_count += 1

                            # Track UUID range
                            row_id = row.get("id")
                            if row_id is not None:
                                id_str = str(row_id)
                                if min_id is None or id_str < min_id:
                                    min_id = id_str
                                if max_id is None or id_str > max_id:
                                    max_id = id_str

                    table_counts[table] = row_count
                    file_hashes[table] = _sha256_file(dest)

                    if min_id is not None:
                        uuid_ranges[table] = {"min_id": min_id, "max_id": max_id}

        finally:
            await conn.close()

        await reporter.update(phase="pg_export", pct=95, message="Writing manifest and packing archive")

        # Write manifest.json
        exported_at = datetime.now(UTC).isoformat()
        manifest = build_pg_manifest(
            migration_id=migration_id,
            exported_at=exported_at,
            alembic_version=alembic_version,
            table_counts=table_counts,
            file_hashes=file_hashes,
            insert_order=INSERT_ORDER,
        )
        manifest_path = staging_dir / "manifest.json"
        write_manifest(manifest_path, manifest)

        # Write migration_manifest.json
        db_url_hash = hashlib.sha256(params.dsn.encode()).hexdigest()
        migration_manifest = build_migration_manifest(
            migration_id=migration_id,
            exported_at=exported_at,
            db_url_hash=db_url_hash,
            table_counts=table_counts,
            uuid_ranges=uuid_ranges,
        )
        migration_manifest_path = staging_dir / "migration_manifest.json"
        write_manifest(migration_manifest_path, migration_manifest)

        # Pack archive
        pack_pg_archive(
            output_path=output_path,
            staging_dir=staging_dir,
            manifest_path=manifest_path,
            migration_manifest_path=migration_manifest_path,
            insert_order=INSERT_ORDER,
            pg_dir=pg_dir,
        )

        # Compute archive hash and write sidecar
        archive_hash = _sha256_file(output_path)
        migration_manifest["archive_sha256"] = archive_hash
        sidecar_stem = output_path.name.removesuffix(".tar.gz").removesuffix(".tgz")
        sidecar_path = output_path.parent / f"{sidecar_stem}.manifest.json"
        write_manifest(sidecar_path, migration_manifest)

        elapsed = time.monotonic() - t0
        total_rows = sum(table_counts.values())

        await reporter.update(phase="pg_export", pct=100, message="Export complete")

        return ExportResult(
            archive_path=str(output_path),
            migration_id=migration_id,
            table_counts=table_counts,
            checksums=file_hashes,
            duration_seconds=round(elapsed, 2),
            total_rows=total_rows,
        )

    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)
