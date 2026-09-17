# SPDX-FileCopyrightText: 2026 Observal contributors
# SPDX-FileCopyrightText: 2026 Srihari <sriharilegend23@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Tests for analytics startup wiring.

DuckDB has no per-table TTL; retention is enforced by ``run_retention_purge``
(covered in test_retention*.py). These tests pin the startup contract: the
application refuses to start when the analytics service is unreachable and
pushes resource settings when it is healthy.
"""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_init_analytics_requires_a_healthy_service():
    with patch("services.analytics.duckdb.client.analytics_health", new=AsyncMock(return_value=False)):
        from services.analytics.duckdb import init_analytics

        with pytest.raises(RuntimeError, match="unreachable"):
            await init_analytics()


@pytest.mark.asyncio
async def test_init_analytics_applies_resource_settings_when_healthy():
    import services.dynamic_settings as ds

    with (
        patch("services.analytics.duckdb.client.analytics_health", new=AsyncMock(return_value=True)),
        patch("services.analytics.duckdb.schema.apply_resource_settings", new_callable=AsyncMock) as apply,
        patch.object(ds, "get_int", new=AsyncMock(return_value=90)),
    ):
        from services.analytics.duckdb import init_analytics

        await init_analytics()

    apply.assert_awaited_once()


@pytest.mark.asyncio
async def test_init_analytics_skips_resource_push_when_retention_is_disabled():
    import services.dynamic_settings as ds

    with (
        patch("services.analytics.duckdb.client.analytics_health", new=AsyncMock(return_value=True)),
        patch("services.analytics.duckdb.schema.apply_resource_settings", new_callable=AsyncMock) as apply,
        patch.object(ds, "get_int", new=AsyncMock(return_value=0)),
    ):
        from services.analytics.duckdb import init_analytics

        await init_analytics()

    apply.assert_awaited_once()
