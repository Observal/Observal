# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""DEPRECATED compatibility shim. The analytics store is DuckDB now.

Re-exports services.duckdb.insert under the legacy module path.
New code must import from services.duckdb.
"""

from services.duckdb.insert import (
    _insert_webhook_deliveries,
    insert_audit_log,
    insert_layer_snapshot,
    insert_rows,
    insert_session_checkpoint,
    insert_session_events,
    refresh_session_summary,
)

__all__ = [
    "_insert_webhook_deliveries",
    "insert_audit_log",
    "insert_layer_snapshot",
    "insert_rows",
    "insert_session_checkpoint",
    "insert_session_events",
    "refresh_session_summary",
]
