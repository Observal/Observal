# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Versioned DuckDB SQL migrations.

Same runner contract as the legacy ClickHouse migrations: numbered .sql
files under ``observal-server/duckdb/migrations`` applied in order, tracked
in a migrations table, idempotent across restarts.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger as optic

import services.duckdb.client as _client

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "duckdb" / "migrations"
MIGRATIONS_TABLE = "duckdb_schema_migrations"
BASELINE_VERSION = "001_baseline"
BASELINE_NAME = f"{BASELINE_VERSION}.sql"
BASELINE_TABLES = frozenset(
    {
        "audit_log",
        "layer_snapshots",
        "security_events",
        "session_checkpoints",
        "session_events",
        "session_stats_agg",
        "webhook_deliveries",
    }
)


def _strip_sql_comments(sql: str) -> str:
    return "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith(("#", "--")))


def _split_sql(sql: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []
    quote: str | None = None
    escaped = False

    for char in _strip_sql_comments(sql):
        current.append(char)
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
            continue
        if char == ";":
            stmt = "".join(current).strip().rstrip(";").strip()
            if stmt:
                statements.append(stmt)
            current = []

    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


async def _ensure_migrations_table() -> None:
    resp = await _client._query(
        f"""CREATE TABLE IF NOT EXISTS {MIGRATIONS_TABLE} (
            version VARCHAR,
            name VARCHAR,
            applied_at TIMESTAMP DEFAULT now()::TIMESTAMP
        )"""
    )
    resp.raise_for_status()


async def _applied_versions() -> set[str]:
    resp = await _client._query(f"SELECT version FROM {MIGRATIONS_TABLE}")
    resp.raise_for_status()
    return {str(row["version"]) for row in resp.json().get("data", [])}


async def _record_applied(version: str, name: str) -> None:
    resp = await _client._query(
        f"INSERT INTO {MIGRATIONS_TABLE} (version, name) VALUES ($version, $name)",
        {"version": version, "name": name},
    )
    resp.raise_for_status()


async def _existing_tables() -> set[str]:
    names = ", ".join(f"'{table}'" for table in sorted(BASELINE_TABLES))
    resp = await _client._query(f"SELECT table_name FROM information_schema.tables WHERE table_name IN ({names})")
    resp.raise_for_status()
    return {str(row["table_name"]) for row in resp.json().get("data", [])}


async def _stamp_baseline_if_present(applied: set[str]) -> set[str]:
    if applied or not (MIGRATIONS_DIR / BASELINE_NAME).exists():
        return applied

    existing = await _existing_tables()
    if not BASELINE_TABLES.issubset(existing):
        return applied

    optic.info("stamping existing DuckDB baseline as applied")
    await _record_applied(BASELINE_VERSION, BASELINE_NAME)
    return {BASELINE_VERSION}


async def _run_file(path: Path) -> None:
    version = path.stem
    statements = _split_sql(path.read_text())
    optic.info("applying DuckDB migration {} ({} statements)", path.name, len(statements))
    for stmt in statements:
        resp = await _client._query(stmt)
        if resp.status_code >= 400:
            raise RuntimeError(f"DuckDB migration {path.name} failed: {resp.text[:200]}")
    await _record_applied(version, path.name)


async def run_duckdb_migrations() -> None:
    """Apply pending DuckDB migrations from ``observal-server/duckdb/migrations``."""
    if not await _client.duckdb_health():
        raise RuntimeError("DuckDB health check failed")

    await _ensure_migrations_table()
    applied = await _stamp_baseline_if_present(await _applied_versions())
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.stem in applied:
            continue
        await _run_file(path)
    optic.info("DuckDB migrations complete")


if __name__ == "__main__":
    import asyncio

    asyncio.run(run_duckdb_migrations())
