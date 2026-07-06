# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Archive utilities: tar extraction, checksums, manifest I/O, and helpers."""

from __future__ import annotations

import hashlib
import json
import sys
import tarfile
from typing import TYPE_CHECKING

from loguru import logger as optic

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path


def _sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_tar_extract(tar: tarfile.TarFile, dest: Path) -> None:
    """Extract tar archive safely, preventing path traversal on all Python versions.

    On Python 3.12+ uses the built-in ``filter="data"`` parameter.
    On older versions, manually validates each member path.
    """
    if sys.version_info >= (3, 12):
        tar.extractall(dest, filter="data")
    else:
        # Manual path traversal protection for Python < 3.12
        dest_resolved = dest.resolve()
        for member in tar.getmembers():
            member_path = (dest / member.name).resolve()
            if not member_path.is_relative_to(dest_resolved):
                msg = f"Tar member {member.name!r} would escape destination directory"
                raise ValueError(msg)
            if member.issym() or member.islnk():
                msg = f"Tar member {member.name!r} is a symlink (rejected for safety)"
                raise ValueError(msg)
        tar.extractall(dest)  # nosec B202 - path traversal validated above


def _is_empty_parquet(path: Path) -> bool:
    """Return True if the file is empty or a Parquet file with zero rows."""
    if path.stat().st_size == 0:
        return True
    try:
        import pyarrow.parquet as pq

        meta = pq.read_metadata(path)
        return meta.num_rows == 0
    except ImportError:
        # pyarrow not available — can't check row count, assume non-empty
        return False
    except Exception:
        # ArrowInvalid, ArrowIOError, or any other read failure
        return True


def _month_range(min_dt: datetime, max_dt: datetime) -> list[int]:
    """Generate list of YYYYMM integers from min to max datetime, inclusive."""
    months: list[int] = []
    current = min_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = max_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    while current <= end:
        months.append(current.year * 100 + current.month)
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)
    return months


def build_pg_manifest(
    *,
    migration_id: str,
    exported_at: str,
    alembic_version: str,
    table_counts: dict[str, int],
    file_hashes: dict[str, str],
    insert_order: list[str],
) -> dict:
    """Build the manifest.json content for a PG export."""
    return {
        "schema_version": "1.0",
        "migration_id": migration_id,
        "exported_at": exported_at,
        "source_alembic_version": alembic_version,
        "tables": {table: {"checksum": file_hashes[table], "row_count": table_counts[table]} for table in insert_order},
    }


def build_migration_manifest(
    *,
    migration_id: str,
    exported_at: str,
    db_url_hash: str,
    table_counts: dict[str, int],
    uuid_ranges: dict[str, dict[str, str]],
) -> dict:
    """Build migration_manifest.json for Phase 2 consumption."""
    return {
        "migration_id": migration_id,
        "phase1_completed_at": exported_at,
        "source_db_url_hash": db_url_hash,
        "table_row_counts": dict(table_counts),
        "uuid_ranges": uuid_ranges,
    }


def read_manifest(path: Path) -> dict:
    """Read and parse a JSON manifest file."""
    optic.debug("Reading manifest from {}", path)
    return json.loads(path.read_text(encoding="utf-8"))


def write_manifest(path: Path, data: dict) -> None:
    """Write a JSON manifest file."""
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def pack_pg_archive(
    *,
    output_path: Path,
    staging_dir: Path,
    manifest_path: Path,
    migration_manifest_path: Path,
    insert_order: list[str],
    pg_dir: Path,
) -> None:
    """Pack PG export files into a tar.gz archive."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output_path, "w:gz") as tar:
        tar.add(str(manifest_path), arcname="manifest.json")
        tar.add(str(migration_manifest_path), arcname="migration_manifest.json")
        for table in insert_order:
            jsonl_file = pg_dir / f"{table}.jsonl"
            tar.add(str(jsonl_file), arcname=f"pg/{table}.jsonl")
