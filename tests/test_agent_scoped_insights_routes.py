# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_agent_scoped_report_route_rejects_cross_agent_report():
    from api.routes.agent.insights import get_agent_insight_report
    from models.user import UserRole

    agent_id = uuid.uuid4()
    report_agent_id = uuid.uuid4()
    user = SimpleNamespace(id=uuid.uuid4(), org_id=None, role=UserRole.user)
    db = AsyncMock()
    agent = SimpleNamespace(id=agent_id)
    report = SimpleNamespace(agent_id=report_agent_id)

    with (
        patch("api.routes.insights._resolve_insights_agent", new=AsyncMock(return_value=agent)),
        patch("api.routes.insights.get_report", new=AsyncMock(return_value=report)),
        pytest.raises(HTTPException) as exc,
    ):
        await get_agent_insight_report("ultra-pi", str(uuid.uuid4()), db, user)

    assert exc.value.status_code == 404
    assert exc.value.detail == "Report not found for agent"


@pytest.mark.asyncio
async def test_agent_scoped_report_route_returns_matching_report():
    from api.routes.agent.insights import get_agent_insight_report
    from models.user import UserRole

    agent_id = uuid.uuid4()
    user = SimpleNamespace(id=uuid.uuid4(), org_id=None, role=UserRole.user)
    db = AsyncMock()
    agent = SimpleNamespace(id=agent_id)
    report = SimpleNamespace(agent_id=agent_id)

    with (
        patch("api.routes.insights._resolve_insights_agent", new=AsyncMock(return_value=agent)),
        patch("api.routes.insights.get_report", new=AsyncMock(return_value=report)),
    ):
        result = await get_agent_insight_report("ultra-pi", str(uuid.uuid4()), db, user)

    assert result is report


@pytest.mark.asyncio
async def test_agent_scoped_list_delegates_to_existing_insights_logic():
    from api.routes.agent.insights import list_agent_insight_reports
    from models.user import UserRole

    user = SimpleNamespace(id=uuid.uuid4(), org_id=None, role=UserRole.user)
    db = AsyncMock()
    reports = [{"id": str(uuid.uuid4())}]

    with patch("api.routes.insights.list_reports", new=AsyncMock(return_value=reports)) as list_reports:
        result = await list_agent_insight_reports("ultra-pi", db, user)

    assert result is reports
    list_reports.assert_awaited_once_with("ultra-pi", db, user)
