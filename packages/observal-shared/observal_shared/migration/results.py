# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Pure dataclasses for migration operation results."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ExportResult:
    archive_path: str
    migration_id: str
    table_counts: dict[str, int]
    checksums: dict[str, str]
    duration_seconds: float
    total_rows: int


@dataclass
class ImportResult:
    migration_id: str
    tables_imported: int
    rows_inserted: dict[str, int]
    rows_skipped: dict[str, int]
    duration_seconds: float
    warnings: list[str] = field(default_factory=list)


@dataclass
class ChecksumResult:
    table_name: str
    expected_checksum: str
    actual_checksum: str
    passed: bool


@dataclass
class ValidationResult:
    archive_valid: bool
    checksum_results: list[ChecksumResult]
    cross_db_results: dict[str, tuple[int, int]] | None


@dataclass
class TelemetryExportResult:
    output_dir: str
    migration_id: str
    table_results: dict[str, dict]
    total_rows: int
    total_size_bytes: int
    duration_seconds: float


@dataclass
class TelemetryImportResult:
    migration_id: str
    tables_imported: int
    tables_skipped: list[str]
    rows_imported: dict[str, int]
    duration_seconds: float
    warnings: list[str] = field(default_factory=list)


@dataclass
class TelemetryValidationResult:
    checksums_valid: bool
    checksum_results: dict[str, bool]
    fk_results: dict[str, list[str]] | None
    row_count_results: dict[str, tuple[int, int]] | None
