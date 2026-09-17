# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Shared Migration Service: export, import, and validation.

Public API entry points:
    export_pg   — PostgreSQL snapshot export to .tar.gz archive
    import_pg   — Import PG archive into target database
    validate_pg — Validate PG archive checksums and row counts
    export_ch   — ClickHouse telemetry export (used by the one-way DuckDB migration)
    export_duckdb_telemetry / load_telemetry_into_duckdb / verify_duckdb_telemetry
                — DuckDB telemetry instance moves

This module contains NO typer, NO rich, and NO typer.Exit.
Progress is reported through an injected ProgressReporter protocol.
Errors are raised as plain domain exceptions.
"""

from observal_shared.migration.ch_export import export_ch
from observal_shared.migration.connections import ChConnParams, PgConnParams
from observal_shared.migration.constants import DEFAULT_PROJECT_ID
from observal_shared.migration.duckdb_export import export_duckdb_telemetry
from observal_shared.migration.duckdb_import import (
    DuckDBConnParams,
    load_telemetry_into_duckdb,
    parse_duckdb_url,
    verify_artifact_checksums,
    verify_duckdb_telemetry,
)
from observal_shared.migration.exceptions import (
    ArtifactValidationError,
    ChecksumMismatchError,
    ConnectionFailedError,
    MigrationError,
    PrerequisiteError,
)
from observal_shared.migration.pg_export import export_pg
from observal_shared.migration.pg_import import import_pg
from observal_shared.migration.progress import NullReporter, ProgressReporter
from observal_shared.migration.results import (
    ChecksumResult,
    ExportResult,
    ImportResult,
    TelemetryExportResult,
    TelemetryImportResult,
    TelemetryValidationResult,
    ValidationResult,
)
from observal_shared.migration.validation import validate_pg

__all__ = [
    "DEFAULT_PROJECT_ID",
    "ArtifactValidationError",
    "ChConnParams",
    "ChecksumMismatchError",
    "ChecksumResult",
    "ConnectionFailedError",
    # DuckDB destination
    "DuckDBConnParams",
    # Results
    "ExportResult",
    "ImportResult",
    # Exceptions
    "MigrationError",
    "NullReporter",
    # Connection params
    "PgConnParams",
    "PrerequisiteError",
    # Progress
    "ProgressReporter",
    "TelemetryExportResult",
    "TelemetryImportResult",
    "TelemetryValidationResult",
    "ValidationResult",
    "export_ch",
    "export_duckdb_telemetry",
    # Entry points
    "export_pg",
    "import_pg",
    "load_telemetry_into_duckdb",
    "parse_duckdb_url",
    "validate_pg",
    "verify_artifact_checksums",
    "verify_duckdb_telemetry",
]
