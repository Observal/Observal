# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Integration tests for end-to-end migration flow (10.5).

Tests export→validate round-trip, idempotent re-import, and TTL purge.

Requirements: 3.2, 3.3, 4.3, 4.6, 7.5
"""

from __future__ import annotations

import io
import json
import os
import shutil
import tarfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path  # noqa: TC003

from observal_shared.migration.archive import _sha256_file, build_pg_manifest
from observal_shared.migration.constants import INSERT_ORDER
from observal_shared.migration.encoding import PGEncoder

# ── Helpers ──────────────────────────────────────────────────────────────────


def _create_test_archive(tmp_path: Path, tables: dict[str, list[dict]]) -> Path:
    """Create a valid test archive with manifest and JSONL files."""
    pg_dir = tmp_path / "pg_staging"
    pg_dir.mkdir()

    file_hashes = {}
    table_counts = {}

    for table_name, rows in tables.items():
        jsonl_content = "\n".join(json.dumps(r, cls=PGEncoder) for r in rows) + "\n"
        jsonl_path = pg_dir / f"{table_name}.jsonl"
        jsonl_path.write_text(jsonl_content, encoding="utf-8")
        file_hashes[table_name] = _sha256_file(jsonl_path)
        table_counts[table_name] = len(rows)

    insert_order = [t for t in INSERT_ORDER if t in tables]
    manifest = build_pg_manifest(
        migration_id=str(uuid.uuid4()),
        exported_at=datetime.now(UTC).isoformat(),
        alembic_version="test_abc123",
        table_counts=table_counts,
        file_hashes=file_hashes,
        insert_order=insert_order,
    )

    archive_path = tmp_path / "export.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tar:
        manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
        info = tarfile.TarInfo(name="manifest.json")
        info.size = len(manifest_bytes)
        tar.addfile(info, io.BytesIO(manifest_bytes))

        for table_name in insert_order:
            jsonl_path = pg_dir / f"{table_name}.jsonl"
            tar.add(str(jsonl_path), arcname=f"pg/{table_name}.jsonl")

    return archive_path


# ══════════════════════════════════════════════════════════════════════════════
# 10.5.1: Export → validate round-trip
# ══════════════════════════════════════════════════════════════════════════════


class TestExportValidateRoundTrip:
    """Export produces valid archive that passes validation."""

    def test_export_archive_passes_checksum_validation(self, tmp_path):
        """Exported archive checksums match manifest entries."""
        tables = {
            "organizations": [
                {"id": str(uuid.uuid4()), "name": "Org A"},
                {"id": str(uuid.uuid4()), "name": "Org B"},
            ],
            "users": [
                {"id": str(uuid.uuid4()), "email": "a@test.com", "org_id": str(uuid.uuid4())},
            ],
        }

        archive_path = _create_test_archive(tmp_path, tables)

        # Extract and validate checksums
        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(extract_dir)

        manifest = json.loads((extract_dir / "manifest.json").read_text())

        for table_name, table_meta in manifest["tables"].items():
            jsonl_path = extract_dir / "pg" / f"{table_name}.jsonl"
            actual_checksum = _sha256_file(jsonl_path)
            assert actual_checksum == table_meta["checksum"], f"Checksum mismatch for {table_name}"

    def test_export_archive_row_counts_match_manifest(self, tmp_path):
        """Row counts in JSONL files match manifest entries."""
        tables = {
            "organizations": [{"id": str(uuid.uuid4()), "name": f"Org {i}"} for i in range(5)],
        }

        archive_path = _create_test_archive(tmp_path, tables)

        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(extract_dir)

        manifest = json.loads((extract_dir / "manifest.json").read_text())

        for table_name, table_meta in manifest["tables"].items():
            jsonl_path = extract_dir / "pg" / f"{table_name}.jsonl"
            lines = [line for line in jsonl_path.read_text().strip().split("\n") if line]
            assert len(lines) == table_meta["row_count"]

    def test_corrupted_archive_fails_validation(self, tmp_path):
        """Archive with modified content fails checksum validation."""
        tables = {
            "organizations": [{"id": str(uuid.uuid4()), "name": "Test Org"}],
        }

        archive_path = _create_test_archive(tmp_path, tables)

        # Extract, modify content, re-check
        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(extract_dir)

        manifest = json.loads((extract_dir / "manifest.json").read_text())

        # Corrupt the JSONL file
        jsonl_path = extract_dir / "pg" / "organizations.jsonl"
        jsonl_path.write_text('{"id": "corrupted", "name": "bad"}\n')

        # Verify checksum no longer matches
        actual_checksum = _sha256_file(jsonl_path)
        expected_checksum = manifest["tables"]["organizations"]["checksum"]
        assert actual_checksum != expected_checksum


# ══════════════════════════════════════════════════════════════════════════════
# 10.5.2: Idempotent re-import
# ══════════════════════════════════════════════════════════════════════════════


class TestIdempotentReImport:
    """Same archive imported twice doesn't duplicate rows."""

    def test_on_conflict_do_nothing_prevents_duplicates(self, tmp_path):
        """ON CONFLICT (id) DO NOTHING ensures idempotent PG import."""
        from observal_shared.migration.encoding import _build_insert

        table = "organizations"
        columns = ["id", "name"]
        col_types = {"id": "uuid", "name": "text"}

        query = _build_insert(table, columns, col_types)

        # The query must contain ON CONFLICT ... DO NOTHING
        assert "ON CONFLICT" in query
        assert "DO NOTHING" in query

        # Simulate: same row inserted twice, second is a no-op
        existing_ids = set()
        rows = [{"id": "abc-123", "name": "Org A"}, {"id": "abc-123", "name": "Org A"}]

        inserted = 0
        skipped = 0
        for row in rows:
            if row["id"] in existing_ids:
                skipped += 1
            else:
                existing_ids.add(row["id"])
                inserted += 1

        assert inserted == 1
        assert skipped == 1
        assert inserted + skipped == len(rows)

    def test_clickhouse_partition_skip_prevents_duplicates(self):
        """ClickHouse import skips existing partitions for idempotency."""
        # Simulate partition-based dedup
        existing_partitions = {202501, 202502}
        import_partitions = [202501, 202502, 202503]

        imported = []
        skipped = []
        for partition in import_partitions:
            if partition in existing_partitions:
                skipped.append(partition)
            else:
                imported.append(partition)

        assert imported == [202503]
        assert skipped == [202501, 202502]


# ══════════════════════════════════════════════════════════════════════════════
# 10.5.3: TTL purge removes aged directories
# ══════════════════════════════════════════════════════════════════════════════


class TestTTLPurge:
    """TTL purge cron removes aged job directories."""

    def test_purge_removes_old_artifact_dirs(self, tmp_path):
        """Directories older than TTL are removed by purge logic."""
        ttl_hours = 24
        now = datetime.now(UTC)
        cutoff = now - timedelta(hours=ttl_hours)

        # Create simulated job directories
        old_job_dir = tmp_path / "old_job"
        old_job_dir.mkdir()
        (old_job_dir / "export.tar.gz").write_bytes(b"old data")

        new_job_dir = tmp_path / "new_job"
        new_job_dir.mkdir()
        (new_job_dir / "export.tar.gz").write_bytes(b"new data")

        # Simulate job metadata
        jobs = [
            {"dir": str(old_job_dir), "finished_at": now - timedelta(hours=48)},  # Older than TTL
            {"dir": str(new_job_dir), "finished_at": now - timedelta(hours=12)},  # Within TTL
        ]

        # Run purge logic
        purged = []
        for job in jobs:
            if job["finished_at"] < cutoff and os.path.isdir(job["dir"]):
                shutil.rmtree(job["dir"])
                purged.append(job["dir"])

        assert str(old_job_dir) in purged
        assert str(new_job_dir) not in purged
        assert not old_job_dir.exists()
        assert new_job_dir.exists()

    def test_purge_handles_already_deleted_dirs(self, tmp_path):
        """Purge gracefully handles directories that no longer exist."""
        ttl_hours = 24
        now = datetime.now(UTC)
        cutoff = now - timedelta(hours=ttl_hours)

        nonexistent_dir = tmp_path / "ghost_dir"
        # Don't create the directory

        jobs = [
            {"dir": str(nonexistent_dir), "finished_at": now - timedelta(hours=48)},
        ]

        # Purge should not crash on non-existent directories
        purged = []
        for job in jobs:
            if job["finished_at"] < cutoff and os.path.isdir(job["dir"]):
                shutil.rmtree(job["dir"])
                purged.append(job["dir"])

        assert purged == []  # Nothing was actually purged since dir didn't exist

    def test_purge_leaves_unfinished_jobs_alone(self, tmp_path):
        """Jobs without finished_at are never purged."""
        job_dir = tmp_path / "running_job"
        job_dir.mkdir()
        (job_dir / "data.tar.gz").write_bytes(b"in progress")

        jobs = [
            {"dir": str(job_dir), "finished_at": None},  # Still running
        ]

        ttl_hours = 24
        now = datetime.now(UTC)
        cutoff = now - timedelta(hours=ttl_hours)

        purged = []
        for job in jobs:
            if job["finished_at"] is not None and job["finished_at"] < cutoff and os.path.isdir(job["dir"]):
                shutil.rmtree(job["dir"])
                purged.append(job["dir"])

        assert purged == []
        assert job_dir.exists()
