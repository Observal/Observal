# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Focused tests for deployment-wide retention purging."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _response(status_code=200, data=None):
    response = MagicMock(status_code=status_code, text="error")
    response.json.return_value = {"data": data or []}
    return response


@pytest.mark.asyncio
async def test_delete_batch_reports_clickhouse_failure():
    with patch("services.clickhouse._query", new=AsyncMock(return_value=_response(500))):
        from services.retention import _delete_batch

        assert await _delete_batch("session_events", "timestamp", "default", "2026-01-01") == 0


@pytest.mark.asyncio
async def test_delete_batch_reports_success():
    with patch("services.clickhouse._query", new=AsyncMock(return_value=_response())):
        from services.retention import _delete_batch

        assert await _delete_batch("session_events", "timestamp", "default", "2026-01-01") == 1


@pytest.mark.asyncio
async def test_has_data_fails_closed_on_clickhouse_error():
    with patch("services.clickhouse._query", new=AsyncMock(return_value=_response(500))):
        from services.retention import _has_data

        assert await _has_data("default") is False


@pytest.mark.asyncio
async def test_has_inflight_insights_checks_all_reports():
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = "report-id"
    db.execute.return_value = result
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=db)
    session.__aexit__ = AsyncMock(return_value=False)

    with patch("services.retention.async_session", return_value=session):
        from services.retention import _has_inflight_insights

        assert await _has_inflight_insights() is True


@pytest.mark.asyncio
async def test_purge_time_based_reports_each_table():
    with patch("services.retention._delete_batch", new=AsyncMock(return_value=1)) as delete_batch:
        from services.retention import _purge_time_based

        result = await _purge_time_based("default", "2026-01-01", {"session_events": "timestamp"})

    assert result == {"session_events": 1}
    delete_batch.assert_awaited_once_with("session_events", "timestamp", "default", "2026-01-01")


@pytest.mark.asyncio
async def test_purge_insight_reports_deletes_completed_and_stuck_rows():
    db = AsyncMock()
    completed = MagicMock(rowcount=3)
    stuck = MagicMock(rowcount=1)
    db.execute.side_effect = [completed, stuck]
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=db)
    session.__aexit__ = AsyncMock(return_value=False)

    with patch("services.retention.async_session", return_value=session):
        from services.retention import _purge_insight_reports

        result = await _purge_insight_reports(datetime.now(UTC))

    assert result == 4
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_purge_count_based_does_nothing_under_limit():
    with patch(
        "services.clickhouse._query",
        new=AsyncMock(return_value=_response(data=[{"day": "2026-05-11", "cnt": "2"}])),
    ):
        from services.retention import _purge_count_based

        assert await _purge_count_based("default", 10) == 0


@pytest.mark.asyncio
async def test_purge_count_based_deletes_old_sessions():
    query = AsyncMock(
        side_effect=[
            _response(data=[{"day": "2026-05-11", "cnt": "6"}, {"day": "2026-05-10", "cnt": "6"}]),
            _response(),
            _response(),
        ]
    )
    with patch("services.clickhouse._query", new=query):
        from services.retention import _purge_count_based

        assert await _purge_count_based("default", 10) == 1
    assert query.await_count == 3


@pytest.mark.asyncio
async def test_run_retention_purge_skips_when_disabled():
    with patch("services.retention.ds.get_bool", new=AsyncMock(return_value=False)):
        from services.retention import run_retention_purge

        await run_retention_purge()


@pytest.mark.asyncio
async def test_run_retention_purge_uses_default_project_and_settings():
    int_values = {
        "retention.trace_days": 14,
        "retention.score_days": 30,
        "retention.max_trace_count": 5000,
    }
    with (
        patch("services.retention.ds.get_bool", new=AsyncMock(return_value=True)),
        patch(
            "services.retention.ds.get_int",
            new=AsyncMock(side_effect=lambda key, default=0: int_values.get(key, default)),
        ),
        patch("services.retention._has_data", new=AsyncMock(return_value=True)),
        patch("services.retention._has_inflight_insights", new=AsyncMock(return_value=False)),
        patch("services.retention._purge_time_based", new=AsyncMock(return_value={})) as purge_time,
        patch("services.retention._purge_session_stats_orphans", new=AsyncMock()),
        patch("services.retention._purge_count_based", new=AsyncMock(return_value=1)) as purge_count,
        patch("services.retention._purge_insight_reports", new=AsyncMock(return_value=2)) as purge_reports,
    ):
        from services.retention import run_retention_purge

        await run_retention_purge()

    assert purge_time.await_args.args[0] == "default"
    purge_count.assert_awaited_once_with("default", 5000)
    purge_reports.assert_awaited_once()
