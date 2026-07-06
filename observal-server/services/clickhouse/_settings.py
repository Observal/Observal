# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Shared ClickHouse query settings - imported by both client and schema modules."""

# Safety floor applied to every ClickHouse query (SEC-026).
DEFAULT_QUERY_SETTINGS: dict[str, str] = {
    "max_execution_time": "300",  # 5 min ceiling
}

# Per-query overrides injected into every HTTP request.
# Populated from enterprise_config on startup and when admin clicks "Apply".
# NOTE: Mutated in-place by apply_resource_settings() in schema.py via .clear()/.update().
_resource_overrides: dict[str, str] = {}
