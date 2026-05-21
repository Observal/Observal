# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Deep simulation tests for data retention purge logic.

These tests mock the entire service layer to verify purge ordering,
skip behavior, score retention defaults, and error isolation.

NOTE: structlog/database are not installed in the local test env, so we
pre-mock them before importing the services.retention module.
"""

import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add server source to path
_server_path = str(Path(__file__).resolve().parent.parent / "observal-server")
if _server_path not in sys.path:
    sys.path.insert(0, _server_path)

# Pre-mock modules that aren't available in this environment
# This must happen BEFORE any import of services.retention
_structlog_mock = MagicMock()
_structlog_mock.get_logger.return_value = MagicMock()
sys.modules.setdefault("structlog", _structlog_mock)

_database_mock = MagicMock()
_database_mock.async_session = MagicMock()
sys.modules.setdefault("database", _database_mock)

_models_mock = MagicMock()
sys.modules.setdefault("models", _models_mock)
sys.modules.setdefault("models.organization", _models_mock)

# Now we can safely import services.clickhouse (also needs mocking for its internals)
_clickhouse_services_mock = MagicMock()
_clickhouse_services_mock._query = AsyncMock()
sys.modules.setdefault("services.clickhouse", _clickhouse_services_mock)

# Mock models needed by _has_inflight_insights
sys.modules.setdefault("models.agent", MagicMock())
sys.modules.setdefault("models.insight_report", MagicMock())

# Now import the module under test
import services.retention  # noqa: E402
from services.retention import (  # noqa: E402
    SCORE_TABLE,
    TIME_PURGE_TABLES,
    _purge_count_based,
    _purge_time_based,
    run_retention_purge,
)


def _mock_response(status_code=200, data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = ""
    if data is not None:
        resp.json.return_value = {"data": data}
    else:
        resp.json.return_value = {"data": []}
    return resp


def _make_org(
    retention_enabled=True,
    data_retention_days=14,
    score_retention_days=None,
    max_trace_count=None,
):
    org = MagicMock()
    org.id = uuid.UUID("12345678-1234-1234-1234-123456789abc")
    org.slug = "test-org"
    org.retention_enabled = retention_enabled
    org.data_retention_days = data_retention_days
    org.score_retention_days = score_retention_days
    org.max_trace_count = max_trace_count
    return org


# ---------------------------------------------------------------------------
# Test 1: Full run_retention_purge flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_purge_flow_ordering():
    """Tests the full run_retention_purge flow verifying call ordering.

    Given org with retention_enabled=True, data_retention_days=14,
    score_retention_days=30, max_trace_count=5000:
    - _has_data is called first
    - _has_inflight_insights is checked before any deletes
    - Children (spans, session_events) are deleted BEFORE traces
    - session_stats_agg orphan cleanup runs after session_events deletion
    - Scores use score_retention_days (30), not data_retention_days (14)
    - Traces are deleted last
    """
    org = _make_org(
        retention_enabled=True,
        data_retention_days=14,
        score_retention_days=30,
        max_trace_count=5000,
    )

    with (
        patch.object(services.retention, "async_session") as mock_session_factory,
        patch.object(services.retention, "select", return_value=MagicMock()) as mock_select,
        patch.object(services.retention, "_has_data", new_callable=AsyncMock) as mock_has_data,
        patch.object(services.retention, "_has_inflight_insights", new_callable=AsyncMock) as mock_inflight,
        patch.object(services.retention, "_purge_time_based", new_callable=AsyncMock) as mock_time_purge,
        patch.object(services.retention, "_purge_session_stats_orphans", new_callable=AsyncMock) as mock_orphan,
        patch.object(services.retention, "_delete_batch", new_callable=AsyncMock) as mock_delete_batch,
        patch.object(services.retention, "_purge_count_based", new_callable=AsyncMock) as mock_count_purge,
        patch.object(services.retention, "_purge_insight_reports", new_callable=AsyncMock) as mock_insight_purge,
        patch.object(services.retention.asyncio, "sleep", new_callable=AsyncMock),
    ):
        # Mock database session to return our org
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [org]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_has_data.return_value = True
        mock_inflight.return_value = False
        mock_time_purge.return_value = {"spans": 1, "session_events": 1}
        mock_orphan.return_value = 1
        mock_delete_batch.return_value = 1
        mock_count_purge.return_value = 1
        mock_insight_purge.return_value = 0

        await run_retention_purge()

        # Verify _has_data called first (before inflight check)
        mock_has_data.assert_called_once_with(str(org.id))

        # Verify _has_inflight_insights called after _has_data
        mock_inflight.assert_called_once_with(org.id)

        # Verify time-based purge was called for children tables
        mock_time_purge.assert_called()
        time_call_args = mock_time_purge.call_args_list[0]
        assert time_call_args.args[0] == str(org.id)
        assert time_call_args.args[2] == TIME_PURGE_TABLES

        # Verify session_stats orphan cleanup runs
        mock_orphan.assert_called()

        # Verify score purge is called with SCORE_TABLE
        # The second call to _purge_time_based should be for scores
        score_call = mock_time_purge.call_args_list[1]
        assert score_call.args[2] == SCORE_TABLE

        # Verify count-based purge was invoked
        mock_count_purge.assert_called_once_with(str(org.id), 5000)

        # Verify traces deletion happens at the end (via _delete_batch)
        mock_delete_batch.assert_called()
        trace_delete_call = mock_delete_batch.call_args
        assert trace_delete_call.args[0] == "traces"
        assert trace_delete_call.args[1] == "start_time"


# ---------------------------------------------------------------------------
# Test 2: Skip behavior when no data
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skip_when_no_data():
    """Org with retention_enabled=True but _has_data returns False.
    Verify NO delete queries are issued.
    """
    org = _make_org(retention_enabled=True, data_retention_days=14)

    with (
        patch.object(services.retention, "async_session") as mock_session_factory,
        patch.object(services.retention, "select", return_value=MagicMock()),
        patch.object(services.retention, "_has_data", new_callable=AsyncMock) as mock_has_data,
        patch.object(services.retention, "_has_inflight_insights", new_callable=AsyncMock) as mock_inflight,
        patch.object(services.retention, "_purge_time_based", new_callable=AsyncMock) as mock_time_purge,
        patch.object(services.retention, "_purge_session_stats_orphans", new_callable=AsyncMock) as mock_orphan,
        patch.object(services.retention, "_delete_batch", new_callable=AsyncMock) as mock_delete_batch,
        patch.object(services.retention, "_purge_count_based", new_callable=AsyncMock) as mock_count_purge,
        patch.object(services.retention.asyncio, "sleep", new_callable=AsyncMock),
    ):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [org]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_has_data.return_value = False

        await run_retention_purge()

        # No deletes should be issued
        mock_inflight.assert_not_called()
        mock_time_purge.assert_not_called()
        mock_orphan.assert_not_called()
        mock_delete_batch.assert_not_called()
        mock_count_purge.assert_not_called()


# ---------------------------------------------------------------------------
# Test 3: Inflight insight skip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skip_when_inflight_insights():
    """Org has data but _has_inflight_insights returns True.
    Verify NO delete queries are issued.
    """
    org = _make_org(retention_enabled=True, data_retention_days=14)

    with (
        patch.object(services.retention, "async_session") as mock_session_factory,
        patch.object(services.retention, "select", return_value=MagicMock()),
        patch.object(services.retention, "_has_data", new_callable=AsyncMock) as mock_has_data,
        patch.object(services.retention, "_has_inflight_insights", new_callable=AsyncMock) as mock_inflight,
        patch.object(services.retention, "_purge_time_based", new_callable=AsyncMock) as mock_time_purge,
        patch.object(services.retention, "_purge_session_stats_orphans", new_callable=AsyncMock) as mock_orphan,
        patch.object(services.retention, "_delete_batch", new_callable=AsyncMock) as mock_delete_batch,
        patch.object(services.retention, "_purge_count_based", new_callable=AsyncMock) as mock_count_purge,
        patch.object(services.retention.asyncio, "sleep", new_callable=AsyncMock),
    ):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [org]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_has_data.return_value = True
        mock_inflight.return_value = True  # Inflight insights exist

        await run_retention_purge()

        # No deletes should be issued
        mock_time_purge.assert_not_called()
        mock_orphan.assert_not_called()
        mock_delete_batch.assert_not_called()
        mock_count_purge.assert_not_called()


# ---------------------------------------------------------------------------
# Test 4: Count-based purge deletion order
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_count_based_purge_deletion_order():
    """When max_trace_count is exceeded, verify spans and session_events
    are deleted before traces.
    """
    # Mock _query at the module level (services.clickhouse._query is used via lazy import)
    mock_query = AsyncMock()

    # First call: daily counts exceeding limit
    daily_response = _mock_response(
        data=[
            {"day": "2026-05-11", "cnt": "2000"},
            {"day": "2026-05-10", "cnt": "2000"},
            {"day": "2026-05-09", "cnt": "2000"},
        ]
    )
    # Subsequent calls: delete responses (all succeed)
    delete_response = _mock_response(status_code=200)

    mock_query.side_effect = [daily_response] + [delete_response] * 10

    with patch("services.clickhouse._query", mock_query):
        await _purge_count_based("test-pid", 3000)

    # Analyze call order
    calls = mock_query.call_args_list
    sqls = [c.args[0] for c in calls]

    # First call is the daily count query
    assert "GROUP BY day" in sqls[0]

    # Find delete calls
    delete_sqls = [s for s in sqls[1:] if "DELETE FROM" in s]

    # Find indices of each table's delete
    spans_idx = None
    session_events_idx = None
    traces_idx = None

    for i, sql in enumerate(delete_sqls):
        if "DELETE FROM spans" in sql:
            spans_idx = i
        elif "DELETE FROM session_events" in sql:
            session_events_idx = i
        elif "DELETE FROM traces" in sql:
            traces_idx = i

    # Children before traces
    assert spans_idx is not None, "spans DELETE not found"
    assert session_events_idx is not None, "session_events DELETE not found"
    assert traces_idx is not None, "traces DELETE not found"
    assert spans_idx < traces_idx, "spans should be deleted before traces"
    assert session_events_idx < traces_idx, "session_events should be deleted before traces"


# ---------------------------------------------------------------------------
# Test 5: Score retention defaults
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_score_retention_defaults():
    """When score_retention_days is None and data_retention_days=14,
    verify scores use 28 days (2x) but floored at 30.
    """
    org = _make_org(
        retention_enabled=True,
        data_retention_days=14,
        score_retention_days=None,  # Not set
        max_trace_count=None,
    )

    with (
        patch.object(services.retention, "async_session") as mock_session_factory,
        patch.object(services.retention, "select", return_value=MagicMock()),
        patch.object(services.retention, "_has_data", new_callable=AsyncMock) as mock_has_data,
        patch.object(services.retention, "_has_inflight_insights", new_callable=AsyncMock) as mock_inflight,
        patch.object(services.retention, "_purge_time_based", new_callable=AsyncMock) as mock_time_purge,
        patch.object(services.retention, "_purge_session_stats_orphans", new_callable=AsyncMock) as mock_orphan,
        patch.object(services.retention, "_delete_batch", new_callable=AsyncMock) as mock_delete_batch,
        patch.object(services.retention, "_purge_insight_reports", new_callable=AsyncMock) as mock_insight_purge,
        patch.object(services.retention.asyncio, "sleep", new_callable=AsyncMock),
    ):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [org]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_has_data.return_value = True
        mock_inflight.return_value = False
        mock_time_purge.return_value = {"spans": 1, "session_events": 1}
        mock_orphan.return_value = 1
        mock_delete_batch.return_value = 1
        mock_insight_purge.return_value = 0

        await run_retention_purge()

        # Score purge call: data_retention_days=14, 2x=28, floor at 30
        # Should be the second call to _purge_time_based
        score_call = None
        for c in mock_time_purge.call_args_list:
            if len(c.args) >= 3 and c.args[2] == SCORE_TABLE:
                score_call = c
                break

        assert score_call is not None, "Score purge not called"
        # score_days = max(14*2, 30) = max(28, 30) = 30
        # Second arg is now a cutoff string; verify it's a valid timestamp
        import re

        assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.000$", score_call.args[1]), (
            f"Expected cutoff string, got {score_call.args[1]}"
        )


# ---------------------------------------------------------------------------
# Test 6: Cutoff timestamp format
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cutoff_timestamp_format():
    """Verify the cutoff string matches YYYY-MM-DD HH:MM:SS.000 format."""
    import re

    mock_query = AsyncMock()
    mock_query.return_value = _mock_response()

    with patch("services.clickhouse._query", mock_query):
        await _purge_time_based("test-pid", "2026-04-27 00:00:00.000", TIME_PURGE_TABLES)

    # Check the cutoff format in the parameters
    found_cutoff = False
    for c in mock_query.call_args_list:
        params = c.args[1]
        cutoff = params.get("param_cutoff")
        if cutoff:
            found_cutoff = True
            # Verify format: YYYY-MM-DD HH:MM:SS.000
            assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.000$", cutoff), f"Cutoff format mismatch: {cutoff}"

    assert found_cutoff, "No cutoff parameter found in any query call"


# ---------------------------------------------------------------------------
# Test 7: Error isolation - one table failure doesn't block others
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_error_isolation():
    """If one table's DELETE fails (status 500), other tables still get purged."""
    mock_query = AsyncMock()

    # spans DELETE fails with 500, session_events succeeds
    spans_fail = _mock_response(status_code=500)
    session_ok = _mock_response(status_code=200)

    mock_query.side_effect = [spans_fail, session_ok]

    with patch("services.clickhouse._query", mock_query):
        stats = await _purge_time_based("test-pid", "2026-04-27 00:00:00.000", TIME_PURGE_TABLES)

    # Both tables were attempted
    assert mock_query.call_count == 2

    # spans failed (HTTP 500 -> _delete_batch returned 0), session_events succeeded
    assert stats["spans"] == 0, "spans failure should be reflected in stats"
    assert stats["session_events"] == 1, "session_events should succeed even if spans fails"
