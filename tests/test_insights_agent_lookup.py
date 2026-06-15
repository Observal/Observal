# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_resolve_insights_agent_accepts_agent_name():
    from api.routes.insights import _resolve_insights_agent
    from models.user import UserRole

    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    user = SimpleNamespace(id=user_id, org_id=org_id, role=UserRole.user)
    agent = SimpleNamespace(id=uuid.uuid4(), name="ultra-pi", created_by=user_id, owner_org_id=org_id, co_authors=[])
    db = AsyncMock()

    with patch("api.routes.insights._load_agent", new=AsyncMock(return_value=agent)) as load_agent:
        resolved = await _resolve_insights_agent("ultra-pi", db, user)

    assert resolved is agent
    load_agent.assert_awaited_once_with(
        db,
        "ultra-pi",
        prefer_user_id=user_id,
        org_id=org_id,
        include_all_statuses=True,
    )


@pytest.mark.asyncio
async def test_resolve_insights_agent_raises_404_for_missing_name():
    from api.routes.insights import _resolve_insights_agent
    from models.user import UserRole

    user = SimpleNamespace(id=uuid.uuid4(), org_id=None, role=UserRole.user)
    db = AsyncMock()

    with (
        patch("api.routes.insights._load_agent", new=AsyncMock(return_value=None)),
        pytest.raises(HTTPException) as exc,
    ):
        await _resolve_insights_agent("ultra-pi", db, user)

    assert exc.value.status_code == 404
    assert exc.value.detail == "Agent not found"
