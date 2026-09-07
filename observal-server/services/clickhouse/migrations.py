# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""DEPRECATED compatibility shim. The analytics store is DuckDB now.

Re-exports the DuckDB migration runner under the legacy module path.
New code must import from services.duckdb.
"""

from services.duckdb.migrations import (
    BASELINE_NAME,
    BASELINE_TABLES,
    BASELINE_VERSION,
    MIGRATIONS_DIR,
    _split_sql,
    _strip_sql_comments,
    run_duckdb_migrations,
)

MIGRATIONS_TABLE = "duckdb_schema_migrations"

run_clickhouse_migrations = run_duckdb_migrations

__all__ = [
    "BASELINE_NAME",
    "BASELINE_TABLES",
    "BASELINE_VERSION",
    "MIGRATIONS_DIR",
    "MIGRATIONS_TABLE",
    "_split_sql",
    "_strip_sql_comments",
    "run_clickhouse_migrations",
    "run_duckdb_migrations",
]


if __name__ == "__main__":
    import asyncio

    asyncio.run(run_duckdb_migrations())
