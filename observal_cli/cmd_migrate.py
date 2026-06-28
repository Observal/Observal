# SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""observal migrate: PostgreSQL shallow-copy migration tools.

This module provides the CLI commands for data migration. All core logic is
delegated to the shared `observal_shared.migration` package. This module handles
only CLI-specific concerns: rich output, typer.Exit error handling, and progress
reporting via a RichProgressReporter.
"""

from __future__ import annotations

import asyncio
import logging
import tarfile
from datetime import UTC, datetime
from pathlib import Path

import typer
from rich import print as rprint

from observal_cli import client
from observal_cli.render import spinner

# ── Shared service imports ───────────────────────────────
from observal_shared.migration import (
    ChConnParams,
    ChecksumMismatchError,
    ConnectionFailedError,
    ExportResult,
    ImportResult,
    MigrationError,
    PgConnParams,
    PrerequisiteError,
    TelemetryExportResult,
    TelemetryImportResult,
    TelemetryValidationResult,
    ValidationResult,
    export_ch,
    export_pg,
    import_ch,
    import_pg,
    validate_ch,
    validate_pg,
)
from observal_shared.migration.connections import parse_clickhouse_url
from observal_shared.migration.constants import _UUID_RE  # noqa: F401, re-exported for backward compat

# ── RichProgressReporter ─────────────────────────────────


class RichProgressReporter:
    """CLI progress reporter that uses rich console output.

    Satisfies the ProgressReporter protocol defined in observal_shared.migration.progress.
    """

    def __init__(self) -> None:
        self._last_phase: str | None = None

    async def update(self, *, phase: str, pct: int, message: str) -> None:
        """Report progress via rich console output."""
        if phase != self._last_phase:
            if self._last_phase is not None:
                rprint()  # Blank line between phases
            self._last_phase = phase
        rprint(f"  [dim][{pct:3d}%][/dim] {message}")


# ── CLI-specific helpers ─────────────────────────────────


def _require_admin() -> None:
    """Verify the current user has super_admin role. Exit if not."""
    try:
        user = client.get("/api/v1/auth/whoami")
    except SystemExit as exc:
        rprint("[red]Authentication required.[/red]")
        rprint("[dim]  Run [bold]observal auth login[/bold] first.[/dim]")
        raise typer.Exit(1) from exc
    role = user.get("role", "")
    if role != "super_admin":
        rprint("[red]Permission denied.[/red] The migrate command requires super_admin role.")
        rprint(f"[dim]  Current role: {role}[/dim]")
        raise typer.Exit(1)


def _require_pyarrow() -> None:
    """pyarrow is an optional dependency; tell the user how to install it."""
    try:
        import pyarrow  # noqa: F401
    except ImportError as exc:
        raise typer.BadParameter(
            "The migrate commands require pyarrow. Install with: pip install 'observal-cli[migrate]'"
        ) from exc


def _handle_migration_error(exc: MigrationError) -> None:
    """Convert a domain exception to rich output + typer.Exit(1)."""
    if isinstance(exc, ChecksumMismatchError):
        rprint(f"[red]Checksum verification failed:[/red] {exc}")
        rprint("[dim]Archive may be corrupted or tampered. Re-export from source.[/dim]")
    elif isinstance(exc, ConnectionFailedError):
        rprint(f"[red]Connection failed:[/red] {exc}")
    elif isinstance(exc, PrerequisiteError):
        rprint(f"[red]Prerequisite not met:[/red] {exc}")
    else:
        rprint(f"[red]Migration error:[/red] {exc}")
    raise typer.Exit(1)


def _warn_clickhouse_cleartext(url: str) -> None:
    """Emit a warning when using unencrypted HTTP transport with credentials."""
    http_url, _db, _user, password = parse_clickhouse_url(url)
    if http_url.startswith("http://") and password:
        rprint(
            "[yellow]⚠  ClickHouse credentials will be sent over unencrypted HTTP.[/yellow]\n"
            "[yellow]   Use clickhouses:// (TLS) for production environments.[/yellow]"
        )


# ── Typer app ────────────────────────────────────────────

migrate_app = typer.Typer(help="PostgreSQL shallow-copy migration tools")


@migrate_app.callback()
def _migrate_callback() -> None:
    _require_pyarrow()


# ── Export command ───────────────────────────────────────


@migrate_app.command("export")
def export_cmd(
    db_url: str = typer.Option(..., "--db-url", help="Source PostgreSQL connection string"),
    output: str | None = typer.Option(None, "--output", "-o", help="Output archive path"),
) -> None:
    """Export all PostgreSQL registry data to a portable archive.

    Connects to the source database, reads all tables in a consistent
    REPEATABLE READ snapshot, and writes JSONL files packed into a
    checksummed .tar.gz archive. Requires super_admin role.

    The archive includes a manifest with SHA-256 checksums and the source
    Alembic migration version for compatibility verification on import.

    Examples:
        observal migrate export --db-url postgresql://user:pass@host/observal
        observal migrate export --db-url $DATABASE_URL -o backup.tar.gz
    """
    _require_admin()

    # Default output filename
    if output is None:
        ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        output = f"observal-export-{ts}.tar.gz"

    output_path = Path(output)
    if output_path.exists():
        rprint(f"[red]Output file already exists:[/red] {output_path}")
        rprint("[dim]  Choose a different path or remove the existing file.[/dim]")
        raise typer.Exit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    rprint(f"[bold]Exporting to:[/bold] {output_path}")

    params = PgConnParams(dsn=db_url)
    reporter = RichProgressReporter()

    try:
        with spinner("Connecting to source database..."):
            result: ExportResult = asyncio.run(export_pg(params, output_path, reporter))
    except MigrationError as exc:
        _handle_migration_error(exc)

    # Summary
    archive_size = output_path.stat().st_size
    size_mb = archive_size / (1024 * 1024)
    rprint("\n[bold green]✓ Export complete[/bold green]")
    rprint(f"  Archive:    {result.archive_path}")
    rprint(f"  Migration:  {result.migration_id}")
    rprint(f"  Tables:     {len(result.table_counts)}")
    rprint(f"  Rows:       {result.total_rows:,}")
    rprint(f"  Size:       {size_mb:.1f} MB")
    rprint(f"  Duration:   {result.duration_seconds:.1f}s")

    # Security warning
    rprint()
    rprint("[yellow]⚠  Archive contains hashed credentials (passwords, API keys).[/yellow]")
    rprint("[yellow]   Store securely and delete after import.[/yellow]")


# ── Import command ───────────────────────────────────────


@migrate_app.command("import")
def import_cmd(
    db_url: str = typer.Option(..., "--db-url", help="Target PostgreSQL connection string"),
    archive: str = typer.Option(..., "--archive", "-a", help="Path to .tar.gz archive"),
    org_id: str | None = typer.Option(
        None,
        "--org-id",
        help="Rewrite all org references to this UUID (use target org ID when source/target orgs differ)",
    ),
) -> None:
    """Import a migration archive into the target database.

    Verifies checksums before inserting any data. Uses ON CONFLICT DO NOTHING
    for idempotent imports: existing rows are skipped, not overwritten.
    Requires super_admin role.

    When migrating between instances with different organizations, use
    --org-id to remap all organization references to the target org UUID.

    Examples:
        observal migrate import --db-url postgresql://user:pass@host/observal --archive backup.tar.gz
        observal migrate import --db-url $DATABASE_URL -a backup.tar.gz --org-id 550e8400-...
    """
    _require_admin()

    archive_path = Path(archive)
    if not archive_path.exists():
        rprint(f"[red]Archive not found:[/red] {archive_path}")
        raise typer.Exit(1)

    if not tarfile.is_tarfile(archive_path):
        rprint(f"[red]Invalid archive format:[/red] {archive_path}")
        rprint("[dim]  Expected a .tar.gz file.[/dim]")
        raise typer.Exit(1)

    if org_id:
        rprint(f"[dim]  Normalizing org references to: {org_id}[/dim]")

    rprint(f"[bold]Importing from:[/bold] {archive_path}")

    params = PgConnParams(dsn=db_url)
    reporter = RichProgressReporter()

    try:
        with spinner("Importing..."):
            result: ImportResult = asyncio.run(import_pg(params, archive_path, reporter, normalize_org_id=org_id))
    except MigrationError as exc:
        _handle_migration_error(exc)

    total_inserted = sum(result.rows_inserted.values())
    total_skipped = sum(result.rows_skipped.values())

    rprint("\n[bold green]✓ Import complete[/bold green]")
    rprint(f"  Migration:  {result.migration_id}")
    rprint(f"  Tables:     {result.tables_imported}")
    rprint(f"  Inserted:   {total_inserted:,}")
    rprint(f"  Skipped:    {total_skipped:,}")
    rprint(f"  Duration:   {result.duration_seconds:.1f}s")

    if result.warnings:
        rprint("\n[yellow]Warnings:[/yellow]")
        for w in result.warnings:
            rprint(f"  [yellow]⚠[/yellow]  {w}")


# ── Validate command ─────────────────────────────────────


@migrate_app.command("validate")
def validate_cmd(
    archive: str = typer.Option(..., "--archive", "-a", help="Path to .tar.gz archive"),
    db_url: str | None = typer.Option(None, "--db-url", help="Optional database for cross-validation"),
) -> None:
    """Validate archive integrity and optionally compare against a database.

    Checks SHA-256 checksums for every table file in the archive. If --db-url
    is provided, also compares row counts between the archive and the live
    database to detect drift or partial imports. Requires super_admin role.

    Examples:
        observal migrate validate --archive backup.tar.gz
        observal migrate validate -a backup.tar.gz --db-url $DATABASE_URL
    """
    _require_admin()

    archive_path = Path(archive)
    if not archive_path.exists():
        rprint(f"[red]Archive not found:[/red] {archive_path}")
        raise typer.Exit(1)

    if not tarfile.is_tarfile(archive_path):
        rprint(f"[red]Invalid archive format:[/red] {archive_path}")
        raise typer.Exit(1)

    pg_params = PgConnParams(dsn=db_url) if db_url else None
    reporter = RichProgressReporter()

    try:
        with spinner("Validating archive..."):
            result: ValidationResult = asyncio.run(validate_pg(pg_params, archive_path, reporter))
    except MigrationError as exc:
        _handle_migration_error(exc)

    # Print checksum results
    rprint("\n[bold]Checksum verification:[/bold]")
    for cr in result.checksum_results:
        status = "[green]✓[/green]" if cr.passed else "[red]✗[/red]"
        rprint(f"  {status} {cr.table_name}")

    if not result.archive_valid:
        rprint("\n[red]Archive validation failed.[/red]")
        raise typer.Exit(1)

    rprint("\n[green]✓ All checksums valid[/green]")

    # Cross-database comparison
    if result.cross_db_results:
        rprint("\n[bold]Row count comparison:[/bold]")
        mismatches = 0
        for table, (archive_count, db_count) in result.cross_db_results.items():
            if db_count == -1:
                rprint(f"  [dim]-[/dim] {table}: [dim]table not in database[/dim]")
            elif archive_count == db_count:
                rprint(f"  [green]✓[/green] {table}: {archive_count}")
            else:
                rprint(f"  [yellow]≠[/yellow] {table}: archive={archive_count}, db={db_count}")
                mismatches += 1

        if mismatches == 0:
            rprint("\n[green]✓ All row counts match[/green]")
        else:
            rprint(f"\n[yellow]⚠  {mismatches} table(s) have different row counts[/yellow]")


# ── Export telemetry command ─────────────────────────────


@migrate_app.command("export-telemetry")
def export_telemetry_cmd(
    clickhouse_url: str = typer.Option(..., "--clickhouse-url", help="Source ClickHouse connection string"),
    manifest: str = typer.Option(..., "--manifest", help="Path to Phase 1 migration_manifest.json"),
    output_dir: str = typer.Option(..., "--output-dir", help="Directory for exported Parquet files"),
) -> None:
    """Export ClickHouse telemetry data to Parquet files.

    Phase 2 of migration: exports traces, spans, scores, and other telemetry
    tables as monthly Parquet partitions. Requires a completed Phase 1 export
    (the migration_manifest.json produced by 'observal migrate export').

    Uses a time cutoff recorded at export start for consistency. The output
    directory must be empty or non-existent. Requires super_admin role.

    Examples:
        observal migrate export-telemetry \\
            --clickhouse-url clickhouse://default:@localhost:8123/observal \\
            --manifest ./observal-export-20260101-120000.manifest.json \\
            --output-dir ./telemetry-export
    """
    _require_admin()
    logging.getLogger("httpx").setLevel(logging.WARNING)

    _warn_clickhouse_cleartext(clickhouse_url)

    rprint(f"[bold]Exporting telemetry to:[/bold] {output_dir}")

    ch_params = ChConnParams(url=clickhouse_url)
    reporter = RichProgressReporter()

    try:
        result: TelemetryExportResult = asyncio.run(export_ch(ch_params, Path(manifest), Path(output_dir), reporter))
    except MigrationError as exc:
        _handle_migration_error(exc)

    size_mb = result.total_size_bytes / (1024 * 1024)
    rprint("\n[bold green]✓ Telemetry export complete[/bold green]")
    rprint(f"  Directory:  {result.output_dir}")
    rprint(f"  Migration:  {result.migration_id}")
    rprint(f"  Rows:       {result.total_rows:,}")
    rprint(f"  Size:       {size_mb:.1f} MB")
    rprint(f"  Duration:   {result.duration_seconds:.1f}s")
    rprint()
    rprint("[yellow]⚠  Parquet files may contain PII in trace input/output fields.[/yellow]")
    rprint("[yellow]   Store securely and delete after import.[/yellow]")


# ── Import telemetry command ─────────────────────────────


@migrate_app.command("import-telemetry")
def import_telemetry_cmd(
    clickhouse_url: str = typer.Option(..., "--clickhouse-url", help="Target ClickHouse connection string"),
    input_dir: str = typer.Option(..., "--input-dir", help="Directory containing Parquet files"),
    project_id: str | None = typer.Option(
        None, "--project-id", help="Rewrite project_id in all tables to this value (use when source/target orgs differ)"
    ),
) -> None:
    """Import Parquet telemetry files into target ClickHouse.

    Phase 2 import: loads monthly Parquet partitions into the target ClickHouse.
    Verifies checksums before importing. Skips partitions that already contain
    data for idempotent re-runs. Persists resume state so interrupted imports
    can continue where they left off. Requires super_admin role.

    Use --project-id to normalize the project_id column when migrating between
    instances with different organization identifiers.

    Examples:
        observal migrate import-telemetry \\
            --clickhouse-url clickhouse://default:@localhost:8123/observal \\
            --input-dir ./telemetry-export
        observal migrate import-telemetry \\
            --clickhouse-url $CLICKHOUSE_URL \\
            --input-dir ./telemetry-export --project-id my-new-org-id
    """
    _require_admin()
    logging.getLogger("httpx").setLevel(logging.WARNING)

    _warn_clickhouse_cleartext(clickhouse_url)

    input_path = Path(input_dir)
    if not input_path.exists():
        rprint(f"[red]Directory not found:[/red] {input_path}")
        raise typer.Exit(1)

    if project_id:
        rprint(f"[dim]  Normalizing project_id to: {project_id}[/dim]")

    rprint(f"[bold]Importing telemetry from:[/bold] {input_path}")

    ch_params = ChConnParams(url=clickhouse_url)
    reporter = RichProgressReporter()

    try:
        result: TelemetryImportResult = asyncio.run(
            import_ch(ch_params, input_path, reporter, normalize_project_id=project_id)
        )
    except MigrationError as exc:
        _handle_migration_error(exc)

    total = sum(result.rows_imported.values())
    rprint("\n[bold green]✓ Telemetry import complete[/bold green]")
    rprint(f"  Migration:  {result.migration_id}")
    rprint(f"  Tables:     {result.tables_imported}")
    rprint(f"  Rows:       {total:,}")
    rprint(f"  Duration:   {result.duration_seconds:.1f}s")
    if result.tables_skipped:
        rprint(f"  Skipped:    {', '.join(result.tables_skipped)}")
    if result.warnings:
        rprint("\n[yellow]Warnings:[/yellow]")
        for w in result.warnings:
            rprint(f"  [yellow]⚠[/yellow]  {w}")


# ── Validate telemetry command ───────────────────────────


@migrate_app.command("validate-telemetry")
def validate_telemetry_cmd(
    input_dir: str = typer.Option(..., "--input-dir", help="Directory containing Parquet files"),
    clickhouse_url: str | None = typer.Option(
        None, "--clickhouse-url", help="Target ClickHouse for row count comparison"
    ),
    target_db_url: str | None = typer.Option(None, "--target-db-url", help="Target PostgreSQL for FK validation"),
) -> None:
    """Validate telemetry Parquet files and optionally check FK references.

    Verifies SHA-256 checksums for all Parquet files in the export directory.
    Optionally compares row counts against a live ClickHouse instance and
    checks foreign key references (agent_id, mcp_id, user_id) against
    PostgreSQL to detect orphaned telemetry records. Requires super_admin role.

    Examples:
        observal migrate validate-telemetry --input-dir ./telemetry-export
        observal migrate validate-telemetry \\
            --input-dir ./telemetry-export \\
            --clickhouse-url $CLICKHOUSE_URL \\
            --target-db-url $DATABASE_URL
    """
    _require_admin()
    logging.getLogger("httpx").setLevel(logging.WARNING)

    input_path = Path(input_dir)
    if not input_path.exists():
        rprint(f"[red]Directory not found:[/red] {input_path}")
        raise typer.Exit(1)

    if clickhouse_url:
        _warn_clickhouse_cleartext(clickhouse_url)

    rprint(f"[bold]Validating telemetry in:[/bold] {input_path}")

    ch_params = ChConnParams(url=clickhouse_url) if clickhouse_url else None
    pg_params = PgConnParams(dsn=target_db_url) if target_db_url else None
    reporter = RichProgressReporter()

    try:
        result: TelemetryValidationResult = asyncio.run(validate_ch(ch_params, pg_params, input_path, reporter))
    except MigrationError as exc:
        _handle_migration_error(exc)

    # Checksum results
    rprint("\n[bold]Checksum verification:[/bold]")
    for filename, passed in result.checksum_results.items():
        status = "[green]✓[/green]" if passed else "[red]✗[/red]"
        rprint(f"  {status} {filename}")

    if not result.checksums_valid:
        rprint("\n[red]Checksum validation failed.[/red]")
        raise typer.Exit(1)
    rprint("\n[green]✓ All checksums valid[/green]")

    # Row count comparison
    if result.row_count_results:
        rprint("\n[bold]Row count comparison:[/bold]")
        mismatches = 0
        for table, (manifest_count, db_count) in result.row_count_results.items():
            if db_count == -1:
                rprint(f"  [dim]-[/dim] {table}: [dim]table not on target[/dim]")
            elif manifest_count == db_count:
                rprint(f"  [green]✓[/green] {table}: {manifest_count:,}")
            else:
                rprint(f"  [yellow]≠[/yellow] {table}: manifest={manifest_count:,}, db={db_count:,}")
                mismatches += 1
        if mismatches == 0:
            rprint("\n[green]✓ All row counts match[/green]")
        else:
            rprint(f"\n[yellow]⚠  {mismatches} table(s) have different row counts[/yellow]")

    # FK validation results
    if result.fk_results:
        rprint("\n[bold]FK validation:[/bold]")
        has_orphans = False
        for key, value in result.fk_results.items():
            if key.endswith("_truncated"):
                continue
            if isinstance(value, list) and value:
                has_orphans = True
                truncated = result.fk_results.get(f"{key}_truncated", False)
                suffix = " (truncated)" if truncated else ""
                rprint(f"  [yellow]⚠[/yellow] {key}: {len(value)} orphaned{suffix}")
            elif isinstance(value, list):
                rprint(f"  [green]✓[/green] {key}: 0 orphaned")
        if not has_orphans:
            rprint("\n[green]✓ All FK references valid[/green]")
        else:
            rprint("\n[yellow]⚠  Orphaned references found (see above)[/yellow]")
