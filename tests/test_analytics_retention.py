# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
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
async def test_init_analytics_requires_authenticated_analytics_access():
    health = AsyncMock(return_value=False)
    with patch("services.analytics.duckdb.client.analytics_health", new=health):
        from services.analytics.duckdb import init_analytics

        with pytest.raises(RuntimeError, match="authentication or connectivity failed"):
            await init_analytics()

    health.assert_awaited_once_with(authenticated=True)


@pytest.mark.asyncio
async def test_init_analytics_applies_resource_settings_when_healthy():
    import services.dynamic_settings as ds

    with (
        patch("services.analytics.duckdb.client.analytics_health", new=AsyncMock(return_value=True)) as health,
        patch("services.analytics.duckdb.schema.apply_resource_settings", new_callable=AsyncMock) as apply,
        patch.object(ds, "get_int", new=AsyncMock(return_value=90)),
    ):
        from services.analytics.duckdb import init_analytics

        await init_analytics()

    health.assert_awaited_once_with(authenticated=True)
    apply.assert_awaited_once()


@pytest.mark.asyncio
async def test_init_analytics_still_applies_resource_settings_when_retention_is_disabled():
    import services.dynamic_settings as ds

    with (
        patch("services.analytics.duckdb.client.analytics_health", new=AsyncMock(return_value=True)),
        patch("services.analytics.duckdb.schema.apply_resource_settings", new_callable=AsyncMock) as apply,
        patch.object(ds, "get_int", new=AsyncMock(return_value=0)),
    ):
        from services.analytics.duckdb import init_analytics

        await init_analytics()

    apply.assert_awaited_once()
