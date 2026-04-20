"""observal migrate: PostgreSQL shallow-copy migration tools."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import tarfile
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypedDict

import typer

if TYPE_CHECKING:
    import asyncpg
    import httpx
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

# ── Phase 2: ClickHouse telemetry constants ──────────────

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


class TableCfg(TypedDict):
    name: str
    engine: Literal["replacing", "mergetree"]
    time_col: str
    fk_cols: list[str]


CLICKHOUSE_TABLES: list[TableCfg] = [
    {"name": "traces", "engine": "replacing", "time_col": "start_time", "fk_cols": ["agent_id", "mcp_id", "user_id"]},
    {"name": "spans", "engine": "replacing", "time_col": "start_time", "fk_cols": ["agent_id", "mcp_id", "user_id"]},
    {"name": "scores", "engine": "replacing", "time_col": "timestamp", "fk_cols": ["agent_id", "mcp_id", "user_id"]},
    {"name": "audit_log", "engine": "mergetree", "time_col": "timestamp", "fk_cols": ["actor_id"]},
    {"name": "mcp_tool_calls", "engine": "mergetree", "time_col": "timestamp", "fk_cols": ["mcp_server_id", "user_id"]},
    {"name": "agent_interactions", "engine": "mergetree", "time_col": "timestamp", "fk_cols": ["agent_id", "user_id"]},
]

FK_PG_TABLE_MAP: dict[str, str] = {
    "agent_id": "agents",
    "mcp_id": "mcp_listings",
    "mcp_server_id": "mcp_listings",
    "user_id": "users",
    "actor_id": "users",
}

EPOCH_SENTINELS: set[str | None] = {None, "", "1970-01-01 00:00:00.000", "1970-01-01 00:00:00"}


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
    warnings: list[str]


@dataclass
class TelemetryValidationResult:
    checksums_valid: bool
    checksum_results: dict[str, bool]
    fk_results: dict[str, list[str]] | None
    row_count_results: dict[str, tuple[int, int]] | None


# ── Helper functions ─────────────────────────────────────


def _require_admin() -> None:
    """Verify the current user has admin or super_admin role. Exit if not."""
    try:
        user = client.get("/api/v1/auth/whoami")
    except SystemExit as exc:
        rprint("[red]Authentication required.[/red]")
        rprint("[dim]  Run [bold]observal auth login[/bold] first.[/dim]")
        raise typer.Exit(1) from exc
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


def _parse_clickhouse_url(url: str) -> tuple[str, str, str, str]:
    """Parse clickhouse://user:pass@host:port/db -> (http_url, db, user, password).

    Supports ``clickhouses://`` for TLS (maps to https, default port 8443).
    """
    from urllib.parse import urlparse

    if url.startswith("clickhouses://"):
        raw = "https://" + url[len("clickhouses://") :]
        default_port = 8443
    elif url.startswith("clickhouse://"):
        raw = "http://" + url[len("clickhouse://") :]
        default_port = 8123
    else:
        raw = url
        default_port = 8123
    parsed = urlparse(raw)
    scheme = "https" if raw.startswith("https") else "http"
    http_url = f"{scheme}://{parsed.hostname}:{parsed.port or default_port}"
    db = (parsed.path or "/").strip("/") or "default"
    user = parsed.username or "default"
    password = parsed.password or ""
    return http_url, db, user, password


# ── Async helpers ────────────────────────────────────────


async def _connect(db_url: str) -> asyncpg.Connection:
    """Establish asyncpg connection, verify alembic_version table exists."""
    try:
        import asyncpg
    except ImportError:
        rprint(
            "[red]asyncpg not found.[/red] Install the migrate extra: [bold]pip install 'observal-cli[migrate]'[/bold]"
        )
        raise typer.Exit(1)

    # Strip SQLAlchemy dialect suffixes (e.g. postgresql+asyncpg:// → postgresql://)
    clean_url = (
        db_url.split("+")[0] + db_url[db_url.index("://") :] if "+asyncpg" in db_url or "+psycopg" in db_url else db_url
    )
    try:
        conn = await asyncpg.connect(clean_url)
    except (asyncpg.InvalidCatalogNameError, asyncpg.InvalidPasswordError, OSError, Exception) as exc:
        rprint(f"[red]Database connection failed:[/red] {type(exc).__name__}: {exc}")
        raise typer.Exit(1) from exc
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
    try:
        import asyncpg
    except ImportError:
        rprint(
            "[red]asyncpg not found.[/red] Install the migrate extra: [bold]pip install 'observal-cli[migrate]'[/bold]"
        )
        raise typer.Exit(1)

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


# ── Phase 2: ClickHouse HTTP helpers ─────────────────────


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

    If stream_to is provided, streams response body to disk atomically via a
    ``.tmp`` sibling file.  An optional pre-existing *http_client* avoids
    creating new connections per call.  *extra_params* are merged into the
    query-string (used for ClickHouse parameterized queries).
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
        rprint(f"[red]ClickHouse returned HTTP {exc.response.status_code}[/red]")
        rprint(f"[dim]{exc.response.text[:500]}[/dim]")
        raise typer.Exit(1) from exc
    except _httpx.RequestError as exc:
        rprint("[red]ClickHouse unreachable.[/red]")
        raise typer.Exit(1) from exc
    finally:
        if owns_client:
            await http_client.aclose()


async def _ch_import(
    http_url: str,
    db: str,
    user: str,
    password: str,
    table: str,
    parquet_path: Path,
) -> None:
    """Import a Parquet file into ClickHouse via INSERT ... FORMAT Parquet."""
    import httpx as _httpx

    sql_prefix = f"INSERT INTO {table} FORMAT Parquet"
    params = {"database": db, "query": sql_prefix}

    async def _file_stream():
        with open(parquet_path, "rb") as f:
            while chunk := f.read(65536):
                yield chunk

    try:
        async with _httpx.AsyncClient(timeout=_httpx.Timeout(600.0, connect=10.0)) as c:
            resp = await c.post(http_url, content=_file_stream(), auth=(user, password), params=params)
            resp.raise_for_status()
    except _httpx.HTTPStatusError as exc:
        rprint(f"[red]ClickHouse returned HTTP {exc.response.status_code}[/red]")
        rprint(f"[dim]{exc.response.text[:500]}[/dim]")
        raise typer.Exit(1) from exc
    except _httpx.RequestError as exc:
        rprint("[red]ClickHouse unreachable.[/red]")
        raise typer.Exit(1) from exc


async def _ch_existing_tables(
    http_url: str,
    db: str,
    user: str,
    password: str,
) -> set[str]:
    """Query system.tables to discover which tables exist on target ClickHouse."""
    sql = "SELECT name FROM system.tables WHERE database = {db:String} FORMAT JSON"
    resp = await _ch_query(http_url, db, user, password, sql, extra_params={"param_db": db})
    return {r["name"] for r in resp.json().get("data", [])}


async def _ch_partition_has_data(
    http_url: str,
    db: str,
    user: str,
    password: str,
    table_cfg: TableCfg,
    yyyymm: int,
) -> bool:
    """Check if a table already has data in a given month partition."""
    name = table_cfg["name"]
    time_col = table_cfg["time_col"]
    if table_cfg["engine"] == "replacing":
        sql = (
            f"SELECT 1 AS has_data FROM {name} FINAL "
            f"WHERE is_deleted = 0 AND toYYYYMM({time_col}) = {yyyymm} LIMIT 1 FORMAT JSON"
        )
    else:
        sql = f"SELECT 1 AS has_data FROM {name} WHERE toYYYYMM({time_col}) = {yyyymm} LIMIT 1 FORMAT JSON"
    resp = await _ch_query(http_url, db, user, password, sql)
    return len(resp.json().get("data", [])) > 0


# ── Phase 2: Query builders and utilities ────────────────


def _build_ch_export_query(table_cfg: TableCfg, yyyymm: int, *, cutoff: str | None = None) -> str:
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


def _build_ch_count_query(table_cfg: TableCfg, yyyymm: int, *, cutoff: str | None = None) -> str:
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


def _build_ch_time_range_query(table_cfg: TableCfg) -> str:
    """Build a time range query to discover partition months."""
    name = table_cfg["name"]
    time_col = table_cfg["time_col"]
    if table_cfg["engine"] == "replacing":
        return (
            f"SELECT min({time_col}) AS min_t, max({time_col}) AS max_t "
            f"FROM {name} FINAL WHERE is_deleted = 0 FORMAT JSON"
        )
    return f"SELECT min({time_col}) AS min_t, max({time_col}) AS max_t FROM {name} FORMAT JSON"


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


def _is_empty_parquet(path: Path) -> bool:
    """Return True if the file is empty or a Parquet file with zero rows."""
    if path.stat().st_size == 0:
        return True
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq

        meta = pq.read_metadata(path)
        return meta.num_rows == 0
    except (pa.lib.ArrowInvalid, pa.lib.ArrowIOError):
        return True


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
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
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
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

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
                        dest.write_text("", encoding="utf-8")
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
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

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
        migration_manifest_path.write_text(json.dumps(migration_manifest, indent=2) + "\n", encoding="utf-8")

        # Ensure output parent directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Write sidecar manifest for Phase 2 consumption
        sidecar_stem = output_path.name.removesuffix(".tar.gz").removesuffix(".tgz")
        sidecar_path = output_path.parent / f"{sidecar_stem}.manifest.json"

        # Pack archive
        with tarfile.open(output_path, "w:gz") as tar:
            tar.add(str(manifest_path), arcname="manifest.json")
            tar.add(str(migration_manifest_path), arcname="migration_manifest.json")
            for table in INSERT_ORDER:
                jsonl_file = pg_dir / f"{table}.jsonl"
                tar.add(str(jsonl_file), arcname=f"pg/{table}.jsonl")

        # Compute archive hash and write sidecar
        archive_hash = _sha256_file(output_path)
        migration_manifest["archive_sha256"] = archive_hash
        sidecar_path.write_text(json.dumps(migration_manifest, indent=2) + "\n", encoding="utf-8")

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


# ── Phase 2: Core async functions ────────────────────────


async def _export_telemetry(
    clickhouse_url: str,
    manifest_path: Path,
    output_dir: Path,
) -> TelemetryExportResult:
    """Export ClickHouse telemetry tables to monthly Parquet files."""
    import httpx as _httpx

    t0 = time.monotonic()

    # Phase gate: read Phase 1 manifest
    if not manifest_path.exists():
        rprint(f"[red]Phase 1 manifest not found:[/red] {manifest_path}")
        raise typer.Exit(1)
    p1_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not p1_manifest.get("phase1_completed_at"):
        rprint("[red]Phase 1 has not completed.[/red]")
        rprint("[dim]  Run 'observal migrate export' and 'observal migrate import' first.[/dim]")
        raise typer.Exit(1)
    migration_id = p1_manifest["migration_id"]

    # Record cutoff before any queries — use ClickHouse-compatible DateTime64 format
    export_time_cutoff = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    # Parse ClickHouse URL
    http_url, db, user, password = _parse_clickhouse_url(clickhouse_url)

    # Health check
    try:
        await _ch_query(http_url, db, user, password, "SELECT 1")
    except typer.Exit:
        raise
    except Exception as exc:
        rprint("[red]ClickHouse health check failed.[/red]")
        raise typer.Exit(1) from exc

    # Create output directory
    if output_dir.exists() and any(output_dir.iterdir()):
        rprint(f"[red]Output directory is not empty:[/red] {output_dir}")
        raise typer.Exit(1)
    dir_existed = output_dir.exists()
    os.makedirs(output_dir, mode=0o700, exist_ok=True)
    os.chmod(output_dir, 0o700)

    try:
        table_meta: dict[str, dict] = {}
        total_rows = 0
        total_size = 0

        async with _httpx.AsyncClient(timeout=_httpx.Timeout(300.0, connect=10.0)) as http_client:
            for table_cfg in CLICKHOUSE_TABLES:
                table_name = table_cfg["name"]

                # Query time range
                tr_sql = _build_ch_time_range_query(table_cfg)
                tr_resp = await _ch_query(http_url, db, user, password, tr_sql, http_client=http_client)
                tr_data = tr_resp.json().get("data", [{}])[0]
                min_t = tr_data.get("min_t")
                max_t = tr_data.get("max_t")

                if min_t in EPOCH_SENTINELS or max_t in EPOCH_SENTINELS:
                    table_meta[table_name] = {"files": [], "row_count": 0, "checksum": {}, "time_range": None}
                    rprint(f"  [dim]{table_name}: empty[/dim]")
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

                    # Get row count first for progress display
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

                    rprint(f"  Exporting {filename} ({partition_count:,} rows)...")

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
                rprint(f"  [green]✓[/green] {table_name}: {table_row_count:,} rows in {len(files)} file(s)")

        # Write telemetry manifest
        ch_url_hash = hashlib.sha256(clickhouse_url.encode()).hexdigest()
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
                "orphaned_mcp_ids": [],
                "orphaned_mcp_ids_truncated": False,
                "orphaned_user_ids": [],
                "orphaned_user_ids_truncated": False,
                "validated_at": None,
            },
        }
        manifest_out = output_dir / "telemetry_manifest.json"
        manifest_out.write_text(json.dumps(telemetry_manifest, indent=2) + "\n", encoding="utf-8")

        elapsed = time.monotonic() - t0
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


async def _import_telemetry(
    clickhouse_url: str,
    input_dir: Path,
) -> TelemetryImportResult:
    """Import Parquet files into target ClickHouse."""
    t0 = time.monotonic()
    warnings: list[str] = []

    # Read telemetry manifest
    manifest_path = input_dir / "telemetry_manifest.json"
    if not manifest_path.exists():
        rprint("[red]Telemetry manifest not found in input directory.[/red]")
        raise typer.Exit(1)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    migration_id = manifest["migration_id"]

    # Verify checksums before any imports
    failed: list[str] = []
    for table_cfg in CLICKHOUSE_TABLES:
        table_name = table_cfg["name"]
        table_info = manifest["tables"].get(table_name, {})
        for filename, expected_hash in table_info.get("checksum", {}).items():
            filepath = input_dir / filename
            if not filepath.exists():
                failed.append(f"{filename} (missing)")
                continue
            actual = _sha256_file(filepath)
            if actual != expected_hash:
                failed.append(filename)

    if failed:
        rprint("[red]Checksum verification failed:[/red]")
        for f in failed:
            rprint(f"  [red]✗[/red] {f}")
        raise typer.Exit(1)

    # Connect and discover existing tables
    http_url, db, user, password = _parse_clickhouse_url(clickhouse_url)
    try:
        await _ch_query(http_url, db, user, password, "SELECT 1")
    except typer.Exit:
        raise
    except Exception as exc:
        rprint("[red]ClickHouse health check failed.[/red]")
        raise typer.Exit(1) from exc

    existing = await _ch_existing_tables(http_url, db, user, password)
    rows_imported: dict[str, int] = {}
    tables_skipped: list[str] = []

    # Resume state
    state_path = input_dir / ".import_state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        completed_tables: set[str] = set(state.get("completed", []))
    else:
        completed_tables = set()

    for table_cfg in CLICKHOUSE_TABLES:
        table_name = table_cfg["name"]
        table_info = manifest["tables"].get(table_name, {})
        files = table_info.get("files", [])

        if not files:
            rows_imported[table_name] = 0
            continue

        if table_name not in existing:
            rprint(f"  [yellow]Skipping {table_name} (table does not exist on target)[/yellow]")
            tables_skipped.append(table_name)
            warnings.append(f"{table_name}: table does not exist on target")
            rows_imported[table_name] = 0
            continue

        if table_name in completed_tables:
            rprint(f"  [dim]Skipping {table_name} (already imported)[/dim]")
            rows_imported[table_name] = table_info.get("row_count", 0)
            continue

        for filename in files:
            filepath = input_dir / filename

            # Idempotency: check if partition already has data
            # Extract YYYYMM from filename like "traces_2025-01.parquet"
            parts = filename.replace(".parquet", "").split("_")
            date_part = parts[-1]  # "2025-01"
            year, month = date_part.split("-")
            yyyymm = int(year) * 100 + int(month)
            if await _ch_partition_has_data(http_url, db, user, password, table_cfg, yyyymm):
                rprint(f"  [dim]Skipping {filename} (partition already has data)[/dim]")
                warnings.append(f"{filename}: partition already has data")
                continue

            rprint(f"  Importing {filename}...")
            await _ch_import(http_url, db, user, password, table_name, filepath)

        rows_imported[table_name] = table_info.get("row_count", 0)
        rprint(f"  [green]✓[/green] {table_name}: {rows_imported[table_name]:,} rows")

        # Persist resume state after each successful table
        completed_tables.add(table_name)
        state_path.write_text(
            json.dumps({"completed": sorted(completed_tables)}, indent=2),
            encoding="utf-8",
        )

    elapsed = time.monotonic() - t0
    return TelemetryImportResult(
        migration_id=migration_id,
        tables_imported=sum(1 for v in rows_imported.values() if v > 0),
        tables_skipped=tables_skipped,
        rows_imported=rows_imported,
        duration_seconds=round(elapsed, 2),
        warnings=warnings,
    )


async def _validate_fk_references(
    parquet_dir: Path,
    manifest: dict,
    db_url: str,
) -> dict[str, list[str] | bool]:
    """Read FK columns from Parquet files and check against PostgreSQL."""
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    fk_values: dict[str, set[str]] = {
        "agent_id": set(),
        "mcp_id": set(),
        "mcp_server_id": set(),
        "user_id": set(),
        "actor_id": set(),
    }

    for table_cfg in CLICKHOUSE_TABLES:
        table_name = table_cfg["name"]
        fk_cols = table_cfg["fk_cols"]
        files = manifest["tables"].get(table_name, {}).get("files", [])
        for filename in files:
            filepath = parquet_dir / filename
            if not filepath.exists():
                continue
            cols_to_read = [c for c in fk_cols if c in fk_values]
            if not cols_to_read:
                continue
            table = pq.read_table(filepath, columns=cols_to_read)
            for col in cols_to_read:
                if col in table.column_names:
                    unique = pc.unique(table.column(col))
                    for val in unique.to_pylist():
                        if val is not None and val != "":
                            fk_values[col].add(str(val))

    # Merge aliases
    fk_values["mcp_id"] |= fk_values.pop("mcp_server_id", set())
    fk_values["user_id"] |= fk_values.pop("actor_id", set())

    # Filter to valid UUIDs only — ClickHouse stores these as String,
    # so non-UUID values like "filesystem" or "default" can appear.
    # Normalize to lowercase to match PostgreSQL's canonical form.
    for key in list(fk_values):
        fk_values[key] = {v.lower() for v in fk_values[key] if _UUID_RE.match(v)}

    # Check against PostgreSQL
    conn = await _connect(db_url)
    try:
        orphaned: dict[str, list[str] | bool] = {}
        for fk_col, pg_table in [("agent_id", "agents"), ("mcp_id", "mcp_listings"), ("user_id", "users")]:
            ids = fk_values.get(fk_col, set())
            if not ids:
                orphaned[f"orphaned_{fk_col}s"] = []
                orphaned[f"orphaned_{fk_col}s_truncated"] = False
                continue
            existing = set()
            id_list = list(ids)
            # Batch in chunks of 1000 to avoid query size limits
            for i in range(0, len(id_list), 1000):
                batch = id_list[i : i + 1000]
                rows = await conn.fetch(
                    f"SELECT id::text FROM {pg_table} WHERE id = ANY($1::uuid[])",
                    batch,
                )
                existing.update(row["id"] for row in rows)
            missing = sorted(ids - existing)
            orphaned[f"orphaned_{fk_col}s"] = missing[:10_000]
            orphaned[f"orphaned_{fk_col}s_truncated"] = len(missing) > 10_000
        return orphaned
    finally:
        await conn.close()


async def _validate_telemetry(
    input_dir: Path,
    clickhouse_url: str | None,
    target_db_url: str | None,
) -> TelemetryValidationResult:
    """Validate telemetry Parquet files: checksums, row counts, FK references."""
    manifest_path = input_dir / "telemetry_manifest.json"
    if not manifest_path.exists():
        rprint("[red]Telemetry manifest not found.[/red]")
        raise typer.Exit(1)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Checksum verification
    checksum_results: dict[str, bool] = {}
    for table_cfg in CLICKHOUSE_TABLES:
        table_name = table_cfg["name"]
        table_info = manifest["tables"].get(table_name, {})
        for filename, expected in table_info.get("checksum", {}).items():
            filepath = input_dir / filename
            if not filepath.exists():
                checksum_results[filename] = False
                continue
            actual = _sha256_file(filepath)
            checksum_results[filename] = actual == expected

    checksums_valid = all(checksum_results.values()) if checksum_results else True

    # Optional row count comparison
    row_count_results: dict[str, tuple[int, int]] | None = None
    if clickhouse_url:
        http_url, db, user, password = _parse_clickhouse_url(clickhouse_url)
        try:
            await _ch_query(http_url, db, user, password, "SELECT 1")
        except typer.Exit:
            raise
        except Exception as exc:
            rprint("[red]ClickHouse health check failed.[/red]")
            raise typer.Exit(1) from exc

        existing = await _ch_existing_tables(http_url, db, user, password)
        row_count_results = {}
        for table_cfg in CLICKHOUSE_TABLES:
            table_name = table_cfg["name"]
            manifest_count = manifest["tables"].get(table_name, {}).get("row_count", 0)
            if table_name not in existing:
                row_count_results[table_name] = (manifest_count, -1)
                continue
            # Use FINAL for ReplacingMergeTree
            if table_cfg["engine"] == "replacing":
                sql = f"SELECT count() AS cnt FROM {table_name} FINAL WHERE is_deleted = 0 FORMAT JSON"
            else:
                sql = f"SELECT count() AS cnt FROM {table_name} FORMAT JSON"
            resp = await _ch_query(http_url, db, user, password, sql)
            db_count = _read_count(resp)
            row_count_results[table_name] = (manifest_count, db_count)

    # Optional FK validation
    fk_results: dict[str, list[str]] | None = None
    if target_db_url:
        fk_results = await _validate_fk_references(input_dir, manifest, target_db_url)
        # Update manifest with FK results
        manifest["fk_validation"] = {**fk_results, "validated_at": datetime.now(UTC).isoformat()}
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    return TelemetryValidationResult(
        checksums_valid=checksums_valid,
        checksum_results=checksum_results,
        fk_results=fk_results,
        row_count_results=row_count_results,
    )


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


# ── Phase 2: Telemetry CLI commands ─────────────────────


@migrate_app.command("export-telemetry")
def export_telemetry_cmd(
    clickhouse_url: str = typer.Option(..., "--clickhouse-url", help="Source ClickHouse connection string"),
    manifest: str = typer.Option(..., "--manifest", help="Path to Phase 1 migration_manifest.json"),
    output_dir: str = typer.Option(..., "--output-dir", help="Directory for exported Parquet files"),
) -> None:
    """Export ClickHouse telemetry data to Parquet files."""
    _require_admin()
    logging.getLogger("httpx").setLevel(logging.WARNING)

    rprint(f"[bold]Exporting telemetry to:[/bold] {output_dir}")
    result = asyncio.run(_export_telemetry(clickhouse_url, Path(manifest), Path(output_dir)))

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


@migrate_app.command("import-telemetry")
def import_telemetry_cmd(
    clickhouse_url: str = typer.Option(..., "--clickhouse-url", help="Target ClickHouse connection string"),
    input_dir: str = typer.Option(..., "--input-dir", help="Directory containing Parquet files"),
) -> None:
    """Import Parquet telemetry files into target ClickHouse."""
    _require_admin()
    logging.getLogger("httpx").setLevel(logging.WARNING)

    input_path = Path(input_dir)
    if not input_path.exists():
        rprint(f"[red]Directory not found:[/red] {input_path}")
        raise typer.Exit(1)

    rprint(f"[bold]Importing telemetry from:[/bold] {input_path}")
    result = asyncio.run(_import_telemetry(clickhouse_url, input_path))

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


@migrate_app.command("validate-telemetry")
def validate_telemetry_cmd(
    input_dir: str = typer.Option(..., "--input-dir", help="Directory containing Parquet files"),
    clickhouse_url: str | None = typer.Option(
        None, "--clickhouse-url", help="Target ClickHouse for row count comparison"
    ),
    target_db_url: str | None = typer.Option(None, "--target-db-url", help="Target PostgreSQL for FK validation"),
) -> None:
    """Validate telemetry Parquet files and optionally check FK references."""
    _require_admin()
    logging.getLogger("httpx").setLevel(logging.WARNING)

    input_path = Path(input_dir)
    if not input_path.exists():
        rprint(f"[red]Directory not found:[/red] {input_path}")
        raise typer.Exit(1)

    rprint(f"[bold]Validating telemetry in:[/bold] {input_path}")
    result = asyncio.run(_validate_telemetry(input_path, clickhouse_url, target_db_url))

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
