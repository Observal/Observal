# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

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
    with (
        patch("services.dynamic_settings") as mock_ds,
        patch("services.clickhouse.client._query", new_callable=AsyncMock) as mock_query,
    ):
        mock_ds.get_int = AsyncMock(return_value=90)
        mock_ds.get = AsyncMock(return_value="")

        mock_query.return_value = _mock_response()

        from services.clickhouse import init_clickhouse

        await init_clickhouse()

        # Check TTL ALTER statements were called
        ttl_calls = [call for call in mock_query.call_args_list if "MODIFY TTL" in str(call)]
        assert len(ttl_calls) == 5, f"Expected 5 TTL statements, got {len(ttl_calls)}"

        # Verify retention days in the SQL
        for call in ttl_calls:
            assert "INTERVAL 90 DAY" in call.args[0]


@pytest.mark.asyncio
async def test_retention_disabled_when_zero():
    """init_clickhouse skips TTL when DATA_RETENTION_DAYS=0."""
    with (
        patch("services.dynamic_settings") as mock_ds,
        patch("services.clickhouse.client._query", new_callable=AsyncMock) as mock_query,
    ):
        mock_ds.get_int = AsyncMock(return_value=0)
        mock_ds.get = AsyncMock(return_value="")

        mock_query.return_value = _mock_response()

        from services.clickhouse import init_clickhouse

        await init_clickhouse()

        ttl_calls = [call for call in mock_query.call_args_list if "MODIFY TTL" in str(call)]
        assert len(ttl_calls) == 0


@pytest.mark.asyncio
async def test_retention_tables_covered():
    """All four ClickHouse tables get TTL statements."""
    expected_tables = {"traces", "spans", "scores", "otel_logs", "session_events"}

    with (
        patch("services.dynamic_settings") as mock_ds,
        patch("services.clickhouse.client._query", new_callable=AsyncMock) as mock_query,
    ):
        mock_ds.get_int = AsyncMock(return_value=30)
        mock_ds.get = AsyncMock(return_value="")

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
