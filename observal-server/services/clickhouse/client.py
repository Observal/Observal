# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""DEPRECATED compatibility shim. The analytics store is DuckDB now.

Re-exports services.duckdb.client symbols under their legacy names so
existing callers keep working. New code must import from services.duckdb.
"""

from config import settings
from services.duckdb.client import (
    AnalyticsQueryError,
    QueryResult,
    _get_con,
    _invalidate_cache,
    _normalize_ts,
    _now_ms,
    _query,
    close_con,
    duckdb_health,
)

# Legacy connection constants, kept so imports don't break. DuckDB is
# embedded; there is no HTTP endpoint or credentials.
CLICKHOUSE_DB = "duckdb"
CLICKHOUSE_HTTP = f"duckdb://{settings.DUCKDB_PATH}"
CLICKHOUSE_USER = ""
CLICKHOUSE_PASSWORD = ""

clickhouse_health = duckdb_health
_get_client = _get_con

__all__ = [
    "CLICKHOUSE_DB",
    "CLICKHOUSE_HTTP",
    "CLICKHOUSE_PASSWORD",
    "CLICKHOUSE_USER",
    "AnalyticsQueryError",
    "QueryResult",
    "_get_client",
    "_get_con",
    "_invalidate_cache",
    "_normalize_ts",
    "_now_ms",
    "_query",
    "clickhouse_health",
    "close_con",
    "duckdb_health",
]
