# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""DEPRECATED compatibility shim. The analytics store is DuckDB now."""

from services.duckdb._settings import DEFAULT_QUERY_SETTINGS, _resource_overrides

__all__ = ["DEFAULT_QUERY_SETTINGS", "_resource_overrides"]
