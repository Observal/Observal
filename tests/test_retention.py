# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for per-organization data retention purge service."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_response(status_code=200, data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = ""
    if data is not None:
        resp.json.return_value = {"data": data}
    else:
        resp.json.return_value = {"data": []}
    return resp


def _make_org(retention_enabled=True, data_retention_days=14, score_retention_days=None, max_trace_count=None):
    org = MagicMock()
    org.id = uuid.uuid4()
    org.slug = "test-org"
    org.retention_enabled = retention_enabled
    org.data_retention_days = data_retention_days
    org.score_retention_days = score_retention_days
    org.max_trace_count = max_trace_count
    return org


@pytest.mark.asyncio
async def test_delete_batch_uses_parameterized_query():
    """DELETE batch uses {pid:String} and {cutoff:String} placeholders."""
    with patch("services.clickhouse._query", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = _mock_response()

        from services.retention import _delete_batch

        await _delete_batch("traces", "start_time", "test-project-id", "2026-04-01 00:00:00.000")

        call_args = mock_query.call_args
        sql = call_args.args[0]
        params = call_args.args[1]

        assert "{pid:String}" in sql
        assert "{cutoff:String}" in sql
        assert "param_pid" in params
        assert "param_cutoff" in params
        assert params["param_pid"] == "test-project-id"
        assert params["param_cutoff"] == "2026-04-01 00:00:00.000"


@pytest.mark.asyncio
async def test_purge_time_based_correct_columns():
    """Time-based purge uses correct time columns per table."""
    with patch("services.clickhouse._query", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = _mock_response()

        from services.retention import TIME_PURGE_TABLES, _purge_time_based

        await _purge_time_based("pid", "2026-04-27 00:00:00.000", TIME_PURGE_TABLES)

        calls = mock_query.call_args_list
        sqls = [c.args[0] for c in calls]

        # Check that appropriate columns are used
        for sql in sqls:
            if "FROM spans" in sql:
                assert "start_time" in sql
            elif "FROM session_events" in sql:
                assert "timestamp" in sql


@pytest.mark.asyncio
async def test_session_stats_orphan_cleanup():
    """session_stats_agg cleanup uses NOT IN subquery, not time-based delete."""
    with patch("services.clickhouse._query", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = _mock_response()

        from services.retention import _purge_session_stats_orphans

        await _purge_session_stats_orphans("test-pid")

        sql = mock_query.call_args.args[0]
        assert "session_stats_agg" in sql
        assert "NOT IN" in sql
        assert "session_events" in sql


@pytest.mark.asyncio
async def test_count_based_purge_uses_daily_aggregation():
    """Count-based purge queries daily counts, not OFFSET."""
    with patch("services.clickhouse._query", new_callable=AsyncMock) as mock_query:
        # First call: daily aggregation returns data exceeding limit
        mock_query.return_value = _mock_response(
            data=[
                {"day": "2026-05-11", "cnt": "1000"},
                {"day": "2026-05-10", "cnt": "1000"},
                {"day": "2026-05-09", "cnt": "1000"},
            ]
        )

        from services.retention import _purge_count_based

        await _purge_count_based("test-pid", 1500)

        # First call should be the GROUP BY day query
        first_sql = mock_query.call_args_list[0].args[0]
        assert "GROUP BY day" in first_sql
        assert "ORDER BY day DESC" in first_sql
        assert "LIMIT 730" in first_sql
        assert "OFFSET" not in first_sql


@pytest.mark.asyncio
async def test_has_data_check():
    """_has_data uses parameterized query with LIMIT 1."""
    with patch("services.clickhouse._query", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = _mock_response(data=[{"1": 1}])

        from services.retention import _has_data

        result = await _has_data("test-pid")

        assert result is True
        sql = mock_query.call_args.args[0]
        assert "{pid:String}" in sql
        assert "LIMIT 1" in sql
        params = mock_query.call_args.args[1]
        assert params["param_pid"] == "test-pid"


@pytest.mark.asyncio
async def test_has_data_returns_false_when_empty():
    """_has_data returns False when no traces exist."""
    with patch("services.clickhouse._query", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = _mock_response(data=[])

        from services.retention import _has_data

        result = await _has_data("empty-pid")
        assert result is False
