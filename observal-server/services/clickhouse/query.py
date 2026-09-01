# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""DEPRECATED compatibility shim. The analytics store is DuckDB now.

Re-exports services.duckdb.query under the legacy module path.
New code must import from services.duckdb.
"""

from services.duckdb.query import (
    query_existing_for_dedup,
    query_recent_events,
    query_session_checkpoint,
    query_session_source_manifest,
    query_source_records_after,
)

__all__ = [
    "query_existing_for_dedup",
    "query_recent_events",
    "query_session_checkpoint",
    "query_session_source_manifest",
    "query_source_records_after",
]
