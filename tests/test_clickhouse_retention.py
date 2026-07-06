# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Tests for ClickHouse data retention TTL configuration."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_response(status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    return resp


@pytest.mark.asyncio
async def test_retention_ttl_applied():
    """init_clickhouse applies TTL when DATA_RETENTION_DAYS > 0."""
    import services.dynamic_settings as ds

    with (
        patch.object(ds, "get_int", new=AsyncMock(return_value=90)),
        patch("services.clickhouse.client.clickhouse_health", new=AsyncMock(return_value=True)),
        patch("services.clickhouse.client._query", new_callable=AsyncMock) as mock_query,
    ):
        mock_query.return_value = _mock_response()

        from services.clickhouse import init_clickhouse

        await init_clickhouse()

        # Check TTL ALTER statements were called
        ttl_calls = [call for call in mock_query.call_args_list if "MODIFY TTL" in str(call)]
        assert len(ttl_calls) == 1, f"Expected 1 TTL statement, got {len(ttl_calls)}"

        # Verify retention days in the SQL
        for call in ttl_calls:
            assert "INTERVAL 90 DAY" in call.args[0]


@pytest.mark.asyncio
async def test_retention_disabled_when_zero():
    """init_clickhouse skips TTL when DATA_RETENTION_DAYS=0."""
    import services.dynamic_settings as ds

    with (
        patch.object(ds, "get_int", new=AsyncMock(return_value=0)),
        patch("services.clickhouse.client.clickhouse_health", new=AsyncMock(return_value=True)),
        patch("services.clickhouse.client._query", new_callable=AsyncMock) as mock_query,
    ):
        mock_query.return_value = _mock_response()

        from services.clickhouse import init_clickhouse

        await init_clickhouse()

        ttl_calls = [call for call in mock_query.call_args_list if "MODIFY TTL" in str(call)]
        assert len(ttl_calls) == 0


@pytest.mark.asyncio
async def test_retention_tables_covered():
    """The JSONL session table gets a TTL statement."""
    expected_tables = {"session_events"}

    import services.dynamic_settings as ds

    with (
        patch.object(ds, "get_int", new=AsyncMock(return_value=30)),
        patch("services.clickhouse.client.clickhouse_health", new=AsyncMock(return_value=True)),
        patch("services.clickhouse.client._query", new_callable=AsyncMock) as mock_query,
    ):
        mock_query.return_value = _mock_response()

        from services.clickhouse import init_clickhouse

        await init_clickhouse()

        ttl_tables = set()
        for call in mock_query.call_args_list:
            sql = call.args[0] if call.args else ""
            if "MODIFY TTL" in sql:
                # Extract table name: "ALTER TABLE <name> MODIFY TTL"
                parts = sql.split()
                table_idx = parts.index("TABLE") + 1
                ttl_tables.add(parts[table_idx])

        assert ttl_tables == expected_tables
