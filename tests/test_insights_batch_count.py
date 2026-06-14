# SPDX-License-Identifier: AGPL-3.0-only

"""Step 0: _count_agent_sessions must also count session_stats_agg by agent_id.

This guards the Cursor-bridge case: agents whose sessions arrive via transcript
ingest (session_stats_agg, no otel_logs) must still be discoverable by the
weekly insights cron. Tests are falsifiable — if the session_stats_agg branch is
removed, test_agg_only_agent_is_counted fails (count drops to 0).
"""

from unittest.mock import AsyncMock, MagicMock, patch

from services.insights.batch import _count_agent_sessions


def _resp(cnt: int) -> MagicMock:
    """A fake ClickHouse HTTP response returning a single cnt row."""
    r = MagicMock()
    r.raise_for_status = MagicMock(return_value=None)
    r.json = MagicMock(return_value={"data": [{"cnt": cnt}]})
    return r


def _query_side_effect(otel_cnt: int, agg_cnt: int):
    """Dispatch canned counts by which table the SQL targets."""

    async def _fake_query(sql: str, params: dict):
        if "otel_logs" in sql:
            return _resp(otel_cnt)
        if "session_stats_agg" in sql:
            return _resp(agg_cnt)
        raise AssertionError(f"unexpected SQL: {sql[:60]}")

    return _fake_query


async def test_agg_only_agent_is_counted():
    """Agent with 0 otel_logs but 7 session_stats_agg rows is discovered."""
    with patch(
        "services.insights.batch._query",
        new=AsyncMock(side_effect=_query_side_effect(otel_cnt=0, agg_cnt=7)),
    ):
        count = await _count_agent_sessions("cursor-usage", "2026-06-01 00:00:00", agent_id="abc")
    assert count == 7


async def test_agg_not_queried_without_agent_id():
    """Without agent_id the agg branch is skipped — proves it's what enables discovery."""
    fake = AsyncMock(side_effect=_query_side_effect(otel_cnt=0, agg_cnt=7))
    with patch("services.insights.batch._query", new=fake):
        count = await _count_agent_sessions("cursor-usage", "2026-06-01 00:00:00")
    assert count == 0
    # only the otel_logs query ran, not the session_stats_agg query
    assert fake.await_count == 1
    assert "otel_logs" in fake.await_args_list[0].args[0]


async def test_returns_max_not_sum():
    """When both pipelines have rows, return max (no double counting)."""
    with patch(
        "services.insights.batch._query",
        new=AsyncMock(side_effect=_query_side_effect(otel_cnt=4, agg_cnt=9)),
    ):
        count = await _count_agent_sessions("a", "2026-06-01 00:00:00", agent_id="abc")
    assert count == 9


async def test_otel_wins_when_larger():
    """Symmetric check: otel-larger returns otel count."""
    with patch(
        "services.insights.batch._query",
        new=AsyncMock(side_effect=_query_side_effect(otel_cnt=11, agg_cnt=2)),
    ):
        count = await _count_agent_sessions("a", "2026-06-01 00:00:00", agent_id="abc")
    assert count == 11
