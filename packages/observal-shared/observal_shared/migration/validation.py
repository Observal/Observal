# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Srihari <sriharilegend23@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Checksum verify and row-count comparison for migration artifacts."""

from __future__ import annotations

import os
import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from observal_shared.migration.archive import _safe_tar_extract, _sha256_file, read_manifest
from observal_shared.migration.connections import PgConnParams, connect_pg
from observal_shared.migration.constants import INSERT_ORDER
from observal_shared.migration.exceptions import MigrationError
from observal_shared.migration.results import ChecksumResult, ValidationResult

if TYPE_CHECKING:
    from observal_shared.migration.progress import ProgressReporter


async def validate_pg(
    params: PgConnParams | None,
    archive_path: Path,
    reporter: ProgressReporter,
) -> ValidationResult:
    """Validate archive checksums and optionally compare against a database.

    Raises ChecksumMismatchError if pre-import validation is desired and fails.
    For standalone validation, returns the result with archive_valid=False instead.
    """
    staging_dir = Path(tempfile.mkdtemp())
    os.chmod(staging_dir, 0o700)
    try:
        await reporter.update(phase="validate", pct=0, message="Extracting archive")

        with tarfile.open(archive_path, "r:gz") as tar:
            _safe_tar_extract(tar, staging_dir)

        manifest_path = staging_dir / "manifest.json"
        if not manifest_path.exists():
            raise MigrationError("Archive does not contain manifest.json")
        manifest = read_manifest(manifest_path)

        await reporter.update(phase="validate", pct=20, message="Verifying checksums")

        # Verify checksums
        checksum_results: list[ChecksumResult] = []
        for table in INSERT_ORDER:
            if table not in manifest["tables"]:
                continue
            jsonl_path = staging_dir / "pg" / f"{table}.jsonl"
            expected = manifest["tables"][table]["checksum"]
            if not jsonl_path.exists():
                checksum_results.append(ChecksumResult(table, expected, "", False))
                continue
            actual = _sha256_file(jsonl_path)
            checksum_results.append(ChecksumResult(table, expected, actual, actual == expected))

        all_ok = all(r.passed for r in checksum_results)

        # Optional cross-database validation
        cross_db_results: dict[str, tuple[int, int]] | None = None
        if params:
            await reporter.update(phase="validate", pct=50, message="Comparing row counts against database")
            conn = await connect_pg(params)
            try:
                existing_tables = {
                    row["table_name"]
                    for row in await conn.fetch(
                        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
                    )
                }
                cross_db_results = {}
                for table in INSERT_ORDER:
                    if table not in manifest["tables"]:
                        continue
                    archive_count = manifest["tables"][table]["row_count"]
                    if table not in existing_tables:
                        cross_db_results[table] = (archive_count, -1)
                        continue
                    db_count = await conn.fetchval(f'SELECT count(*) FROM "{table}"')
                    cross_db_results[table] = (archive_count, db_count)
            finally:
                await conn.close()

        await reporter.update(phase="validate", pct=100, message="Validation complete")

        return ValidationResult(
            archive_valid=all_ok,
            checksum_results=checksum_results,
            cross_db_results=cross_db_results,
        )

    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)
