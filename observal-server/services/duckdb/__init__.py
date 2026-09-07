# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""DuckDB analytics subpackage.

Replaces services.clickhouse. The legacy package remains as a thin shim that
re-exports these symbols under the old names, so existing callers keep
working during the transition.
"""

from services.duckdb._settings import _resource_overrides
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
from services.duckdb.insert import (
    _insert_webhook_deliveries,
    insert_audit_log,
    insert_layer_snapshot,
    insert_rows,
    insert_session_checkpoint,
    insert_session_events,
    refresh_session_summary,
)
from services.duckdb.migrations import run_duckdb_migrations
from services.duckdb.query import (
    query_existing_for_dedup,
    query_recent_events,
    query_session_checkpoint,
    query_session_source_manifest,
    query_source_records_after,
)
from services.duckdb.schema import (
    DEFAULT_QUERY_SETTINGS,
    RESOURCE_SETTINGS_MAP,
    apply_resource_settings,
    init_duckdb,
)

__all__ = [
    "DEFAULT_QUERY_SETTINGS",
    "RESOURCE_SETTINGS_MAP",
    "AnalyticsQueryError",
    "QueryResult",
    "_get_con",
    "_insert_webhook_deliveries",
    "_invalidate_cache",
    "_normalize_ts",
    "_now_ms",
    "_query",
    "_resource_overrides",
    "apply_resource_settings",
    "close_con",
    "duckdb_health",
    "init_duckdb",
    "insert_audit_log",
    "insert_layer_snapshot",
    "insert_rows",
    "insert_session_checkpoint",
    "insert_session_events",
    "query_existing_for_dedup",
    "query_recent_events",
    "query_session_checkpoint",
    "query_session_source_manifest",
    "query_source_records_after",
    "refresh_session_summary",
    "run_duckdb_migrations",
]
