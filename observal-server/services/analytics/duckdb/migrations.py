# SPDX-FileCopyrightText: 2026 Observal contributors
# SPDX-License-Identifier: Apache-2.0
"""Versioned DuckDB analytics migrations."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from loguru import logger as optic

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "analytics" / "migrations"
MIGRATIONS_TABLE = "analytics_schema_migrations"
CREATE_MIGRATIONS_TABLE = (
    f"CREATE TABLE IF NOT EXISTS {MIGRATIONS_TABLE} ("
    "version VARCHAR PRIMARY KEY, "
    "name VARCHAR NOT NULL, "
    "checksum VARCHAR NOT NULL, "
    "applied_at TIMESTAMP DEFAULT now() NOT NULL)"
)


class MigrationError(RuntimeError):
    """Raised when a migration cannot be applied safely."""


def _strip_sql_comments(sql: str) -> str:
    return "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith(("#", "--")))


def _split_sql(sql: str) -> list[str]:
    """Split a migration file into statements, respecting quotes and comments."""
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


def _checksum(text: str) -> str:
    # SPDX and explanatory comment-only edits do not change a migration's
    # executable content and must not invalidate already-applied migrations.
    normalized = _strip_sql_comments(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


async def _applied_migrations(store) -> dict[str, str]:
    _, rows = await store.query(f"SELECT version, checksum FROM {MIGRATIONS_TABLE}")
    return {str(version): str(checksum) for version, checksum in rows}


async def run_migrations(store) -> list[str]:
    """Apply pending migrations.  Returns the versions applied this run."""
    await store.execute(CREATE_MIGRATIONS_TABLE)
    applied = await _applied_migrations(store)
    newly_applied: list[str] = []

    for path in _migration_files():
        text = path.read_text(encoding="utf-8")
        version = path.stem
        checksum = _checksum(text)
        if version in applied:
            # Builds before comment-normalized checksums stored the raw file
            # digest. Accept that exact legacy value so this safety fix does
            # not strand an already-running deployment.
            legacy_checksum = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if applied[version] not in {checksum, legacy_checksum}:
                raise MigrationError(
                    f"analytics migration {version} changed after it was applied "
                    f"(expected {applied[version][:12]}, found {checksum[:12]})"
                )
            if applied[version] == legacy_checksum and legacy_checksum != checksum:
                await store.execute(
                    f"UPDATE {MIGRATIONS_TABLE} SET checksum = $checksum WHERE version = $version",
                    {"checksum": checksum, "version": version},
                )
            continue
        optic.info("applying analytics migration {} ({})", version, path.name)
        for statement in _split_sql(text):
            await store.execute(statement)
        await store.execute(
            f"INSERT INTO {MIGRATIONS_TABLE} (version, name, checksum) VALUES ($version, $name, $checksum)",
            {"version": version, "name": path.name, "checksum": checksum},
        )
        newly_applied.append(version)

    if newly_applied:
        optic.info("applied {} analytics migrations: {}", len(newly_applied), ", ".join(newly_applied))
    else:
        optic.debug("analytics schema is up to date")
    return newly_applied


async def _main() -> None:
    from services.analytics.duckdb.service import ServiceSettings, create_store

    settings = ServiceSettings()
    store = create_store(settings)
    await store.start()
    try:
        await run_migrations(store)
    finally:
        await store.close()


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    asyncio.run(_main())
