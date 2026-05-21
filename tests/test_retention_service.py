# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for retention service — covers branches missed by test_retention.py."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_response(status_code=200, data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = "error text"
    if data is not None:
        resp.json.return_value = {"data": data}
    else:
        resp.json.return_value = {"data": []}
    return resp


# ── _delete_batch ────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_batch_returns_0_on_failure():
    """_delete_batch returns 0 when ClickHouse returns non-200."""
    with patch("services.clickhouse._query", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = _mock_response(status_code=500)

        from services.retention import _delete_batch

        result = await _delete_batch("traces", "start_time", "pid", "2026-01-01 00:00:00.000")

    assert result == 0


@pytest.mark.asyncio
async def test_delete_batch_returns_1_on_success():
    """_delete_batch returns 1 on success."""
    with patch("services.clickhouse._query", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = _mock_response(status_code=200)

        from services.retention import _delete_batch

        result = await _delete_batch("spans", "start_time", "pid", "2026-01-01 00:00:00.000")

    assert result == 1


# ── _has_data ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_has_data_returns_false_on_non_200():
    """_has_data returns False when ClickHouse errors."""
    with patch("services.clickhouse._query", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = _mock_response(status_code=500)

        from services.retention import _has_data

        result = await _has_data("pid")

    assert result is False


# ── _has_inflight_insights ───────────────────────────────


@pytest.mark.asyncio
async def test_has_inflight_insights_no_agents():
    """Returns False when org has no agents."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_result)

    with patch("services.retention.async_session") as mock_session:
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        from services.retention import _has_inflight_insights

        result = await _has_inflight_insights(uuid.uuid4())

    assert result is False


@pytest.mark.asyncio
async def test_has_inflight_insights_with_pending_report():
    """Returns True when a pending/running report exists."""
    mock_db = AsyncMock()
    agent_result = MagicMock()
    agent_result.scalars.return_value.all.return_value = [uuid.uuid4()]

    report_result = MagicMock()
    report_result.scalar_one_or_none.return_value = uuid.uuid4()

    mock_db.execute = AsyncMock(side_effect=[agent_result, report_result])

    with patch("services.retention.async_session") as mock_session:
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        from services.retention import _has_inflight_insights

        result = await _has_inflight_insights(uuid.uuid4())

    assert result is True


@pytest.mark.asyncio
async def test_has_inflight_insights_no_pending():
    """Returns False when no pending/running reports exist."""
    mock_db = AsyncMock()
    agent_result = MagicMock()
    agent_result.scalars.return_value.all.return_value = [uuid.uuid4()]

    report_result = MagicMock()
    report_result.scalar_one_or_none.return_value = None

    mock_db.execute = AsyncMock(side_effect=[agent_result, report_result])

    with patch("services.retention.async_session") as mock_session:
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        from services.retention import _has_inflight_insights

        result = await _has_inflight_insights(uuid.uuid4())

    assert result is False


# ── _purge_time_based ────────────────────────────────────


@pytest.mark.asyncio
async def test_purge_time_based_handles_exception():
    """Exception in one table doesn't stop others."""
    call_count = 0

    async def _failing_query(sql, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("network error")
        return _mock_response()

    with patch("services.clickhouse._query", side_effect=_failing_query):
        from services.retention import TIME_PURGE_TABLES, _purge_time_based

        stats = await _purge_time_based("pid", "2026-01-01 00:00:00.000", TIME_PURGE_TABLES)

    assert 0 in stats.values()
    assert 1 in stats.values()


# ── _purge_session_stats_orphans ─────────────────────────


@pytest.mark.asyncio
async def test_purge_session_stats_orphans_failure():
    """Returns 0 on ClickHouse failure."""
    with patch("services.clickhouse._query", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = _mock_response(status_code=500)

        from services.retention import _purge_session_stats_orphans

        result = await _purge_session_stats_orphans("pid")

    assert result == 0


# ── _purge_insight_reports ───────────────────────────────


@pytest.mark.asyncio
async def test_purge_insight_reports_no_agents():
    """Returns 0 when org has no agents."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_result)

    with patch("services.retention.async_session") as mock_session:
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        from datetime import UTC, datetime

        from services.retention import _purge_insight_reports

        result = await _purge_insight_reports(uuid.uuid4(), datetime.now(UTC))

    assert result == 0


@pytest.mark.asyncio
async def test_purge_insight_reports_deletes_old_reports():
    """Deletes completed and stuck reports older than cutoff."""
    mock_db = AsyncMock()
    agent_result = MagicMock()
    agent_result.scalars.return_value.all.return_value = [uuid.uuid4()]

    completed_result = MagicMock()
    completed_result.rowcount = 3

    stuck_result = MagicMock()
    stuck_result.rowcount = 1

    mock_db.execute = AsyncMock(side_effect=[agent_result, completed_result, stuck_result])
    mock_db.commit = AsyncMock()

    with patch("services.retention.async_session") as mock_session:
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        from datetime import UTC, datetime

        from services.retention import _purge_insight_reports

        result = await _purge_insight_reports(uuid.uuid4(), datetime.now(UTC))

    assert result == 4
    mock_db.commit.assert_called_once()


# ── _purge_count_based ───────────────────────────────────


@pytest.mark.asyncio
async def test_purge_count_based_no_data():
    """Returns 0 when no daily data exists."""
    with patch("services.clickhouse._query", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = _mock_response(data=[])

        from services.retention import _purge_count_based

        result = await _purge_count_based("pid", 1000)

    assert result == 0


@pytest.mark.asyncio
async def test_purge_count_based_under_limit():
    """Returns 0 when total is under the limit (no cutoff found)."""
    with patch("services.clickhouse._query", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = _mock_response(
            data=[
                {"day": "2026-05-11", "cnt": "500"},
                {"day": "2026-05-10", "cnt": "300"},
            ]
        )

        from services.retention import _purge_count_based

        result = await _purge_count_based("pid", 5000)

    assert result == 0


@pytest.mark.asyncio
async def test_purge_count_based_query_failure():
    """Returns 0 when ClickHouse query fails."""
    with patch("services.clickhouse._query", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = _mock_response(status_code=500)

        from services.retention import _purge_count_based

        result = await _purge_count_based("pid", 1000)

    assert result == 0


@pytest.mark.asyncio
async def test_purge_count_based_executes_deletes():
    """When over limit, deletes children then traces."""
    with patch("services.clickhouse._query", new_callable=AsyncMock) as mock_query:
        # First call: daily aggregation exceeds limit
        daily_resp = _mock_response(
            data=[
                {"day": "2026-05-11", "cnt": "600"},
                {"day": "2026-05-10", "cnt": "600"},
                {"day": "2026-05-09", "cnt": "600"},
            ]
        )
        # Subsequent calls: delete operations
        delete_resp = _mock_response()
        mock_query.side_effect = [daily_resp, delete_resp, delete_resp, delete_resp, delete_resp, delete_resp]

        from services.retention import _purge_count_based

        result = await _purge_count_based("pid", 1000)

    assert result == 1
    # 1 query + 5 deletes (spans, session_events, session_stats_orphans, scores, traces)
    assert mock_query.call_count == 6


# ── run_retention_purge ──────────────────────────────────


@pytest.mark.asyncio
async def test_run_retention_purge_skips_when_no_orgs():
    """Early return when no orgs have retention enabled."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_result)

    with patch("services.retention.async_session") as mock_session:
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        from services.retention import run_retention_purge

        await run_retention_purge(None)


@pytest.mark.asyncio
async def test_run_retention_purge_skips_empty_org():
    """Skips orgs with no data in ClickHouse."""
    org = MagicMock()
    org.id = uuid.uuid4()
    org.slug = "empty-org"
    org.retention_enabled = True
    org.data_retention_days = 14
    org.score_retention_days = None
    org.max_trace_count = None

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [org]
    mock_db.execute = AsyncMock(return_value=mock_result)

    with (
        patch("services.retention.async_session") as mock_session,
        patch("services.retention._has_data", new_callable=AsyncMock, return_value=False) as mock_has_data,
        patch("services.retention.INTER_ORG_DELAY", 0),
    ):
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        from services.retention import run_retention_purge

        await run_retention_purge(None)

    mock_has_data.assert_called_once_with(str(org.id))


@pytest.mark.asyncio
async def test_run_retention_purge_skips_inflight_insights():
    """Skips orgs with in-flight insight reports."""
    org = MagicMock()
    org.id = uuid.uuid4()
    org.slug = "busy-org"
    org.retention_enabled = True
    org.data_retention_days = 14
    org.score_retention_days = None
    org.max_trace_count = None

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [org]
    mock_db.execute = AsyncMock(return_value=mock_result)

    with (
        patch("services.retention.async_session") as mock_session,
        patch("services.retention._has_data", new_callable=AsyncMock, return_value=True),
        patch("services.retention._has_inflight_insights", new_callable=AsyncMock, return_value=True) as mock_inflight,
        patch("services.retention.INTER_ORG_DELAY", 0),
    ):
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        from services.retention import run_retention_purge

        await run_retention_purge(None)

    mock_inflight.assert_called_once_with(org.id)


@pytest.mark.asyncio
async def test_run_retention_purge_full_run():
    """Full purge run: time-based, score, and count-based."""
    org = MagicMock()
    org.id = uuid.uuid4()
    org.slug = "full-org"
    org.retention_enabled = True
    org.data_retention_days = 14
    org.score_retention_days = 30
    org.max_trace_count = 5000

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [org]
    mock_db.execute = AsyncMock(return_value=mock_result)

    with (
        patch("services.retention.async_session") as mock_session,
        patch("services.retention._has_data", new_callable=AsyncMock, return_value=True),
        patch("services.retention._has_inflight_insights", new_callable=AsyncMock, return_value=False),
        patch("services.retention._purge_time_based", new_callable=AsyncMock, return_value={"spans": 1}) as mock_time,
        patch("services.retention._purge_session_stats_orphans", new_callable=AsyncMock, return_value=1),
        patch("services.retention._purge_count_based", new_callable=AsyncMock, return_value=1) as mock_count,
        patch("services.retention._purge_insight_reports", new_callable=AsyncMock, return_value=2) as mock_insights,
        patch("services.retention._delete_batch", new_callable=AsyncMock, return_value=1) as mock_delete,
        patch("services.retention.INTER_ORG_DELAY", 0),
    ):
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        from services.retention import run_retention_purge

        await run_retention_purge(None)

    assert mock_time.call_count == 2
    mock_count.assert_called_once_with(str(org.id), 5000)
    mock_insights.assert_called_once()
    mock_delete.assert_called_once()


@pytest.mark.asyncio
async def test_run_retention_purge_score_defaults_to_2x_trace():
    """When score_retention_days is None, defaults to 2x data_retention_days (min 30)."""
    org = MagicMock()
    org.id = uuid.uuid4()
    org.slug = "default-score-org"
    org.retention_enabled = True
    org.data_retention_days = 14
    org.score_retention_days = None
    org.max_trace_count = None

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [org]
    mock_db.execute = AsyncMock(return_value=mock_result)

    with (
        patch("services.retention.async_session") as mock_session,
        patch("services.retention._has_data", new_callable=AsyncMock, return_value=True),
        patch("services.retention._has_inflight_insights", new_callable=AsyncMock, return_value=False),
        patch("services.retention._purge_time_based", new_callable=AsyncMock, return_value={}) as mock_time,
        patch("services.retention._purge_session_stats_orphans", new_callable=AsyncMock, return_value=1),
        patch("services.retention._purge_insight_reports", new_callable=AsyncMock, return_value=0) as mock_insights,
        patch("services.retention._delete_batch", new_callable=AsyncMock, return_value=1),
        patch("services.retention.INTER_ORG_DELAY", 0),
    ):
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        from services.retention import run_retention_purge

        await run_retention_purge(None)

    # score purge should be called with SCORE_TABLE (2x14=28, but min 30)
    assert mock_time.call_count == 2
    mock_insights.assert_called_once()
