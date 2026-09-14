# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""DEPRECATED compatibility shim. The analytics store is DuckDB now.

Re-exports services.duckdb.schema under the legacy module path.
New code must import from services.duckdb.
"""

from services.duckdb.schema import (
    DEFAULT_QUERY_SETTINGS,
    RESOURCE_SETTINGS_MAP,
    _resource_overrides,
    apply_resource_settings,
    init_duckdb,
)


async def _materialize_if_needed():
    """No-op. DuckDB maintains indexes automatically; there is no
    projection/part materialization step."""
    return None


init_clickhouse = init_duckdb

__all__ = [
    "DEFAULT_QUERY_SETTINGS",
    "RESOURCE_SETTINGS_MAP",
    "_materialize_if_needed",
    "_resource_overrides",
    "apply_resource_settings",
    "init_clickhouse",
    "init_duckdb",
]
