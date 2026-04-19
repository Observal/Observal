"""observal migrate: PostgreSQL shallow-copy migration tools."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import tarfile
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import typer

if TYPE_CHECKING:
    import asyncpg
from rich import print as rprint

from observal_cli import client
from observal_cli.render import spinner

# ── Constants ────────────────────────────────────────────

CHUNK_SIZE = 500

INSERT_ORDER: list[str] = [
    # Tier 0 — no FK dependencies
    "organizations",
    "enterprise_config",
    "component_sources",
    "penalty_definitions",
    # Tier 1 — FK to organizations
    "users",
    "exporter_configs",
    # Tier 1.5 — FK to users
    "component_bundles",
    # Tier 2 — FK to orgs + users + component_bundles
    "mcp_listings",
    "skill_listings",
    "hook_listings",
    "prompt_listings",
    "sandbox_listings",
    "agents",
    # Tier 3 — FK to listings/users
    "mcp_validation_results",
    "mcp_downloads",
    "skill_downloads",
    "hook_downloads",
    "prompt_downloads",
    "sandbox_downloads",
    "submissions",
    "alert_rules",
    # Tier 4 — FK to agents
    "agent_goal_templates",
    "agent_download_records",
    "component_download_records",
    "dimension_weights",
    # Tier 5 — FK to agent_goal_templates
    "agent_goal_sections",
    # Tier 6 — FK to agents (polymorphic component_id)
    "agent_components",
    # Tier 7 — FK to users (polymorphic listing_id)
    "feedback",
    # Tier 8 — FK to alert_rules
    "alert_history",
    # Tier 9 — FK to agents + users
    "eval_runs",
    # Tier 10 — FK to eval_runs
    "scorecards",
    # Tier 11 — FK to scorecards + penalty_definitions
    "scorecard_dimensions",
    "trace_penalties",
]

JSONB_COLUMNS: dict[str, list[str]] = {
    "agents": ["model_config_json", "external_mcps", "supported_ides"],
    "mcp_listings": ["tools_schema", "environment_variables", "supported_ides"],
    "skill_listings": ["supported_ides", "target_agents", "triggers", "mcp_server_config", "activation_keywords"],
    "hook_listings": ["supported_ides", "handler_config", "input_schema", "output_schema"],
    "prompt_listings": ["variables", "model_hints", "tags", "supported_ides"],
    "sandbox_listings": ["resource_limits", "allowed_mounts", "env_vars", "supported_ides"],
    "scorecards": ["raw_output", "dimension_scores", "scoring_recommendations", "dimensions_skipped", "warnings"],
    "agent_components": ["config_override"],
    "exporter_configs": ["config"],
}


# ── PGEncoder ────────────────────────────────────────────


class PGEncoder(json.JSONEncoder):
    """Custom JSON encoder for PostgreSQL row data."""

    def default(self, obj: object) -> object:
        if isinstance(obj, uuid.UUID):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, timedelta):
            return obj.total_seconds()
        return super().default(obj)


# ── Dataclasses ──────────────────────────────────────────


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
    warnings: list[str]


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


# ── Helper functions ─────────────────────────────────────


def _require_admin() -> None:
    """Verify the current user has admin or super_admin role. Exit if not."""
    try:
        user = client.get("/api/v1/auth/whoami")
    except SystemExit:
        rprint("[red]Authentication required.[/red]")
        rprint("[dim]  Run [bold]observal auth login[/bold] first.[/dim]")
        raise typer.Exit(1)
    role = user.get("role", "")
    if role not in ("admin", "super_admin"):
        rprint("[red]Permission denied.[/red] The migrate command requires admin or super_admin role.")
        rprint(f"[dim]  Current role: {role}[/dim]")
        raise typer.Exit(1)


def _build_select(table: str, columns: list[str]) -> str:
    """Build SELECT query, casting JSONB columns to ::text."""
    jsonb_cols = JSONB_COLUMNS.get(table, [])
    if not jsonb_cols:
        return f"SELECT * FROM {table}"
    parts = []
    for col in columns:
        if col in jsonb_cols:
            parts.append(f"{col}::text AS {col}")
        else:
            parts.append(col)
    return f"SELECT {', '.join(parts)} FROM {table}"


def _sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# ── Async helpers ────────────────────────────────────────


async def _connect(db_url: str) -> asyncpg.Connection:
    """Establish asyncpg connection, verify alembic_version table exists."""
    import asyncpg

    # Strip SQLAlchemy dialect suffixes (e.g. postgresql+asyncpg:// → postgresql://)
    clean_url = (
        db_url.split("+")[0] + db_url[db_url.index("://") :] if "+asyncpg" in db_url or "+psycopg" in db_url else db_url
    )
    try:
        conn = await asyncpg.connect(clean_url)
    except (asyncpg.InvalidCatalogNameError, asyncpg.InvalidPasswordError, OSError, Exception) as e:
        rprint(f"[red]Database connection failed:[/red] {type(e).__name__}: {e}")
        raise typer.Exit(1)
    # Verify this is an Observal database
    result = await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name = 'alembic_version')"
    )
    if not result:
        await conn.close()
        rprint("[red]Database does not contain an Observal schema[/red] (alembic_version table not found).")
        rprint("[dim]  Is this the right database?[/dim]")
        raise typer.Exit(1)
    return conn


async def _get_column_types(conn: asyncpg.Connection, table: str) -> dict[str, str]:
    """Get column name -> PostgreSQL type mapping for a table."""
    rows = await conn.fetch(
        "SELECT column_name, udt_name FROM information_schema.columns WHERE table_name = $1 ORDER BY ordinal_position",
        table,
    )
    return {row["column_name"]: row["udt_name"] for row in rows}


def _coerce_value(value: object, pg_type: str) -> object:
    """Coerce a JSON-deserialized value to the correct Python type for asyncpg."""
    if value is None:
        return None
    if pg_type == "uuid" and isinstance(value, str):
        return uuid.UUID(value)
    if pg_type in ("timestamptz", "timestamp") and isinstance(value, str):
        return datetime.fromisoformat(value)
    if pg_type == "interval" and isinstance(value, (int, float)):
        return timedelta(seconds=value)
    if pg_type in ("bool",) and isinstance(value, bool):
        return value
    if pg_type in ("int4", "int8", "int2") and isinstance(value, (int, float)):
        return int(value)
    if pg_type in ("float4", "float8", "numeric") and isinstance(value, (int, float)):
        return float(value)
    return value


def _build_insert(table: str, columns: list[str], col_types: dict[str, str]) -> str:
    """Build INSERT query with proper type casts for JSONB columns."""
    cols_str = ", ".join(f'"{col}"' for col in columns)
    parts = []
    for i, col in enumerate(columns):
        pg_type = col_types.get(col, "")
        if pg_type in ("json", "jsonb"):
            parts.append(f"${i + 1}::jsonb")
        else:
            parts.append(f"${i + 1}")
    placeholders = ", ".join(parts)
    return f'INSERT INTO {table} ({cols_str}) VALUES ({placeholders}) ON CONFLICT ("id") DO NOTHING'


async def _flush_batch(
    conn: asyncpg.Connection,
    table: str,
    columns: list[str],
    col_types: dict[str, str],
    batch: list[dict],
) -> tuple[int, int]:
    """Flush a batch of rows to the database. Returns (inserted, skipped)."""
    import asyncpg

    if not batch:
        return 0, 0

    query = _build_insert(table, columns, col_types)

    inserted = 0
    skipped = 0

    for row in batch:
        values = [_coerce_value(row.get(col), col_types.get(col, "")) for col in columns]
        try:
            status = await conn.execute(query, *values)
            # status is like "INSERT 0 1" (inserted) or "INSERT 0 0" (conflict)
            count = int(status.split()[-1])
            if count > 0:
                inserted += 1
            else:
                skipped += 1
        except asyncpg.ForeignKeyViolationError as e:
            row_id = row.get("id", "unknown")
            rprint(f"[yellow]  FK violation in {table}, row {row_id}: {e.constraint_name}[/yellow]")
            skipped += 1

    return inserted, skipped


async def _insert_table(
    conn: asyncpg.Connection,
    table: str,
    jsonl_path: Path,
    col_types: dict[str, str],
) -> tuple[int, int]:
    """Insert rows from a JSONL file into a table. Returns (inserted, skipped)."""
    inserted = 0
    skipped = 0
    batch: list[dict] = []
    columns: list[str] | None = None

    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)

            if columns is None:
                columns = list(row.keys())

            batch.append(row)

            if len(batch) >= CHUNK_SIZE:
                ins, sk = await _flush_batch(conn, table, columns, col_types, batch)
                inserted += ins
                skipped += sk
                batch = []

    if batch and columns:
        ins, sk = await _flush_batch(conn, table, columns, col_types, batch)
        inserted += ins
        skipped += sk

    return inserted, skipped


async def _import_archive(db_url: str, archive_path: Path) -> ImportResult:
    """Import a migration archive into the target database."""
    t0 = time.monotonic()
    warnings: list[str] = []

    staging_dir = Path(tempfile.mkdtemp())
    os.chmod(staging_dir, 0o700)
    try:
        # Extract archive
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(staging_dir, filter="data")

        # Read manifest
        manifest_path = staging_dir / "manifest.json"
        if not manifest_path.exists():
            rprint("[red]Archive does not contain manifest.json[/red]")
            raise typer.Exit(1)
        manifest = json.loads(manifest_path.read_text())
        migration_id = manifest["migration_id"]

        # Verify checksums BEFORE any DB operations
        failed_checksums: list[str] = []
        for table in INSERT_ORDER:
            jsonl_path = staging_dir / "pg" / f"{table}.jsonl"
            if not jsonl_path.exists():
                failed_checksums.append(f"{table} (file missing)")
                continue
            expected = manifest["tables"][table]["checksum"]
            actual = _sha256_file(jsonl_path)
            if actual != expected:
                failed_checksums.append(table)

        if failed_checksums:
            rprint("[red]Checksum verification failed:[/red]")
            for name in failed_checksums:
                rprint(f"  [red]✗[/red] {name}")
            rprint("\n[dim]Archive may be corrupted or tampered. Re-export from source.[/dim]")
            raise typer.Exit(1)

        # Connect and verify schema version
        conn = await _connect(db_url)
        try:
            target_version = await conn.fetchval("SELECT version_num FROM alembic_version LIMIT 1")
            source_version = manifest["source_alembic_version"]
            if target_version != source_version:
                rprint("[red]Schema version mismatch:[/red]")
                rprint(f"  Archive: {source_version}")
                rprint(f"  Target:  {target_version}")
                rprint("\n[dim]  Run: cd observal-server && alembic upgrade head[/dim]")
                raise typer.Exit(1)

            rows_inserted: dict[str, int] = {}
            rows_skipped: dict[str, int] = {}

            # Discover which tables exist on the target
            existing_tables = {
                row["table_name"]
                for row in await conn.fetch(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
                )
            }

            for table in INSERT_ORDER:
                jsonl_path = staging_dir / "pg" / f"{table}.jsonl"

                # Skip tables that don't exist on target
                if table not in existing_tables:
                    rprint(f"[dim]  Skipping {table} (table does not exist on target)[/dim]")
                    rows_inserted[table] = 0
                    rows_skipped[table] = 0
                    continue

                # Get column types for proper coercion
                col_types = await _get_column_types(conn, table)

                ins, sk = await _insert_table(conn, table, jsonl_path, col_types)
                rows_inserted[table] = ins
                rows_skipped[table] = sk

        finally:
            await conn.close()

        elapsed = time.monotonic() - t0
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


async def _validate_archive(archive_path: Path, db_url: str | None) -> ValidationResult:
    """Validate archive checksums and optionally compare against a database."""
    staging_dir = Path(tempfile.mkdtemp())
    os.chmod(staging_dir, 0o700)
    try:
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(staging_dir, filter="data")

        manifest_path = staging_dir / "manifest.json"
        if not manifest_path.exists():
            rprint("[red]Archive does not contain manifest.json[/red]")
            raise typer.Exit(1)
        manifest = json.loads(manifest_path.read_text())

        # Verify checksums
        checksum_results: list[ChecksumResult] = []
        for table in INSERT_ORDER:
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
        if db_url:
            conn = await _connect(db_url)
            try:
                existing_tables = {
                    row["table_name"]
                    for row in await conn.fetch(
                        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
                    )
                }
                cross_db_results = {}
                for table in INSERT_ORDER:
                    archive_count = manifest["tables"][table]["row_count"]
                    if table not in existing_tables:
                        cross_db_results[table] = (archive_count, -1)  # -1 signals table missing
                        continue
                    db_count = await conn.fetchval(f"SELECT count(*) FROM {table}")
                    cross_db_results[table] = (archive_count, db_count)
            finally:
                await conn.close()

        return ValidationResult(
            archive_valid=all_ok,
            checksum_results=checksum_results,
            cross_db_results=cross_db_results,
        )

    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)


async def _export_database(db_url: str, output_path: Path) -> ExportResult:
    """Export all tables to JSONL files and pack into a tar.gz archive."""
    t0 = time.monotonic()
    migration_id = str(uuid.uuid4())

    staging_dir = Path(tempfile.mkdtemp())
    os.chmod(staging_dir, 0o700)
    try:
        pg_dir = staging_dir / "pg"
        pg_dir.mkdir()

        conn = await _connect(db_url)
        try:
            # Read alembic version
            alembic_version = await conn.fetchval("SELECT version_num FROM alembic_version LIMIT 1")
            if not alembic_version:
                rprint("[red]Could not read alembic version from source database.[/red]")
                raise typer.Exit(1)

            table_counts: dict[str, int] = {}
            file_hashes: dict[str, str] = {}
            uuid_ranges: dict[str, dict[str, str]] = {}

            # Open REPEATABLE READ transaction for consistent snapshot
            async with conn.transaction(isolation="repeatable_read", readonly=True):
                # Discover which tables actually exist in the database
                existing_tables = {
                    row["table_name"]
                    for row in await conn.fetch(
                        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
                    )
                }

                for table in INSERT_ORDER:
                    dest = pg_dir / f"{table}.jsonl"

                    # Skip tables that don't exist yet (DB on older migration)
                    if table not in existing_tables:
                        rprint(f"[dim]  Skipping {table} (table does not exist)[/dim]")
                        # Write empty JSONL file so archive structure is consistent
                        dest.write_text("")
                        table_counts[table] = 0
                        file_hashes[table] = _sha256_file(dest)
                        continue

                    # Discover columns via prepared statement
                    stmt = await conn.prepare(f"SELECT * FROM {table} LIMIT 0")
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

        # Write manifest.json
        exported_at = datetime.now(UTC).isoformat()
        manifest = {
            "schema_version": "1.0",
            "migration_id": migration_id,
            "exported_at": exported_at,
            "source_alembic_version": alembic_version,
            "tables": {
                table: {"checksum": file_hashes[table], "row_count": table_counts[table]} for table in INSERT_ORDER
            },
        }
        manifest_path = staging_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

        # Write migration_manifest.json
        db_url_hash = hashlib.sha256(db_url.encode()).hexdigest()
        migration_manifest = {
            "migration_id": migration_id,
            "phase1_completed_at": exported_at,
            "source_db_url_hash": db_url_hash,
            "table_row_counts": dict(table_counts),
            "uuid_ranges": uuid_ranges,
        }
        migration_manifest_path = staging_dir / "migration_manifest.json"
        migration_manifest_path.write_text(json.dumps(migration_manifest, indent=2) + "\n")

        # Ensure output parent directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Pack archive
        with tarfile.open(output_path, "w:gz") as tar:
            tar.add(str(manifest_path), arcname="manifest.json")
            tar.add(str(migration_manifest_path), arcname="migration_manifest.json")
            for table in INSERT_ORDER:
                jsonl_file = pg_dir / f"{table}.jsonl"
                tar.add(str(jsonl_file), arcname=f"pg/{table}.jsonl")

        elapsed = time.monotonic() - t0
        total_rows = sum(table_counts.values())

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


# ── Typer app ────────────────────────────────────────────

migrate_app = typer.Typer(help="PostgreSQL shallow-copy migration tools")


@migrate_app.command("export")
def export_cmd(
    db_url: str = typer.Option(..., "--db-url", help="Source PostgreSQL connection string"),
    output: str | None = typer.Option(None, "--output", "-o", help="Output archive path"),
) -> None:
    """Export all PostgreSQL registry data to a portable archive."""
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

    rprint(f"[bold]Exporting to:[/bold] {output_path}")
    with spinner("Connecting to source database..."):
        result = asyncio.run(_export_database(db_url, output_path))

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


@migrate_app.command("import")
def import_cmd(
    db_url: str = typer.Option(..., "--db-url", help="Target PostgreSQL connection string"),
    archive: str = typer.Option(..., "--archive", "-a", help="Path to .tar.gz archive"),
) -> None:
    """Import a migration archive into the target database."""
    _require_admin()

    archive_path = Path(archive)
    if not archive_path.exists():
        rprint(f"[red]Archive not found:[/red] {archive_path}")
        raise typer.Exit(1)

    if not tarfile.is_tarfile(archive_path):
        rprint(f"[red]Invalid archive format:[/red] {archive_path}")
        rprint("[dim]  Expected a .tar.gz file.[/dim]")
        raise typer.Exit(1)

    rprint(f"[bold]Importing from:[/bold] {archive_path}")
    with spinner("Importing..."):
        result = asyncio.run(_import_archive(db_url, archive_path))

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


@migrate_app.command("validate")
def validate_cmd(
    archive: str = typer.Option(..., "--archive", "-a", help="Path to .tar.gz archive"),
    db_url: str | None = typer.Option(None, "--db-url", help="Optional database for cross-validation"),
) -> None:
    """Validate archive integrity and optionally compare against a database."""
    _require_admin()

    archive_path = Path(archive)
    if not archive_path.exists():
        rprint(f"[red]Archive not found:[/red] {archive_path}")
        raise typer.Exit(1)

    if not tarfile.is_tarfile(archive_path):
        rprint(f"[red]Invalid archive format:[/red] {archive_path}")
        raise typer.Exit(1)

    with spinner("Validating archive..."):
        result = asyncio.run(_validate_archive(archive_path, db_url))

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
