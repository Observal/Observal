# SPDX-FileCopyrightText: 2026 Observal contributors
# SPDX-FileCopyrightText: 2026 Srihari <sriharilegend23@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""DuckDB analytics client package.

Re-exports the helpers every call site uses: query, execute, insert, health,
timestamp helpers, migrations, and resource tuning.
"""

from services.analytics.duckdb.client import (
    ANALYTICS_DB,
    ANALYTICS_HTTP,
    ANALYTICS_TOKEN,
    _apply_pragmas,
    _checkpoint,
    _execute,
    _get_client,
    _insert,
    _invalidate_cache,
    _normalize_ts,
    _now_ms,
    _query,
    analytics_health,
)
from services.analytics.duckdb.insert import (
    _insert_webhook_deliveries,
    insert_audit_log,
    insert_layer_snapshot,
    insert_security_events,
    insert_session_checkpoint,
    insert_session_events,
    refresh_session_summary,
)
from services.analytics.duckdb.migrations import run_migrations
from services.analytics.duckdb.query import (
    query_existing_for_dedup,
    query_recent_events,
    query_session_checkpoint,
    query_session_source_manifest,
    query_source_records_after,
)
from services.analytics.duckdb.schema import (
    RESOURCE_SETTINGS_MAP,
    apply_resource_settings,
    init_analytics,
)

__all__ = [
    "ANALYTICS_DB",
    "ANALYTICS_HTTP",
    "ANALYTICS_TOKEN",
    "RESOURCE_SETTINGS_MAP",
    "_apply_pragmas",
    "_checkpoint",
    "_execute",
    "_get_client",
    "_insert",
    "_insert_webhook_deliveries",
    "_invalidate_cache",
    "_normalize_ts",
    "_now_ms",
    "_query",
    "analytics_health",
    "apply_resource_settings",
    "init_analytics",
    "insert_audit_log",
    "insert_layer_snapshot",
    "insert_security_events",
    "insert_session_checkpoint",
    "insert_session_events",
    "query_existing_for_dedup",
    "query_recent_events",
    "query_session_checkpoint",
    "query_session_source_manifest",
    "query_source_records_after",
    "refresh_session_summary",
    "run_migrations",
]
