# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only
"""Shared ClickHouse query settings — imported by both client and schema modules."""

# Safety floor applied to every ClickHouse query (SEC-026).
DEFAULT_QUERY_SETTINGS: dict[str, str] = {
    "max_execution_time": "300",  # 5 min ceiling
}

# Per-query overrides injected into every HTTP request.
# Populated from enterprise_config on startup and when admin clicks "Apply".
_resource_overrides: dict[str, str] = {}
