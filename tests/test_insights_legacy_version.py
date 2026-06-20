# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


class _Response:
    status_code = 200

    def json(self) -> dict:
        return {"data": [{"cnt": "2"}]}


def test_agent_version_filter_treats_unversioned_as_v1() -> None:
    from services.insight_version_filters import agent_version_filter

    condition = agent_version_filter(nullable=True)

    assert "coalesce(agent_version, '') = {agent_version:String}" in condition
    assert "{agent_version:String} = '1.0.0'" in condition
    assert "coalesce(agent_version, '') = ''" in condition


@pytest.mark.asyncio
async def test_count_insight_sessions_matches_legacy_v1_rows() -> None:
    from api.routes.insights import _count_insight_sessions

    query = AsyncMock(return_value=_Response())
    agent = SimpleNamespace(id="agent-id", name="agent-name")

    with patch("services.clickhouse._query", new=query):
        count = await _count_insight_sessions(
            agent=agent,
            period_start=datetime(2026, 1, 1, tzinfo=UTC),
            period_end=datetime(2026, 1, 2, tzinfo=UTC),
            agent_version="1.0.0",
        )

    assert count == 2
    sql = query.await_args.args[0]
    assert "agent_version = {agent_version:String}" in sql
    assert "{agent_version:String} = '1.0.0'" in sql
    assert "agent_version = ''" in sql


@pytest.mark.asyncio
async def test_count_insight_sessions_fallback_matches_nullable_legacy_rows() -> None:
    from api.routes.insights import _count_insight_sessions

    query = AsyncMock(side_effect=[RuntimeError("aggregate failed"), _Response()])
    agent = SimpleNamespace(id="agent-id", name="agent-name")

    with patch("services.clickhouse._query", new=query):
        count = await _count_insight_sessions(
            agent=agent,
            period_start=datetime(2026, 1, 1, tzinfo=UTC),
            period_end=datetime(2026, 1, 2, tzinfo=UTC),
            agent_version="1.0.0",
        )

    assert count == 2
    fallback_sql = query.await_args_list[1].args[0]
    assert "coalesce(agent_version, '') = {agent_version:String}" in fallback_sql
    assert "{agent_version:String} = '1.0.0'" in fallback_sql
    assert "coalesce(agent_version, '') = ''" in fallback_sql
