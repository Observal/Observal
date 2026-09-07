# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Shared DuckDB runtime settings - imported by both client and schema modules."""

# DuckDB applies memory/thread limits at the connection level (SET), not per
# query. DEFAULT_QUERY_SETTINGS is kept as an empty mapping for API
# compatibility with the legacy ClickHouse per-query settings dict.
DEFAULT_QUERY_SETTINGS: dict[str, str] = {}

# Connection-level overrides applied via SET statements.
# NOTE: Mutated in-place by apply_resource_settings() in schema.py.
_resource_overrides: dict[str, str] = {}
