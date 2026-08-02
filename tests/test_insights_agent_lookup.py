# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


def _result(value):
    """Mock a SQLAlchemy Result whose scalar_one_or_none yields *value*."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    result.scalars.return_value.all.return_value = [value] if value is not None else []
    return result


@pytest.mark.asyncio
async def test_resolve_insights_agent_accepts_agent_name():
    from api.routes.insights import _resolve_insights_agent
    from models.user import UserRole

    user_id = uuid.uuid4()
    user = SimpleNamespace(id=user_id, role=UserRole.user)
    agent = SimpleNamespace(id=uuid.uuid4(), name="ultra-pi", created_by=user_id, is_private=False, co_authors=[])
    db = AsyncMock()

    with patch("api.routes.insights._load_agent", new=AsyncMock(return_value=agent)) as load_agent:
        resolved = await _resolve_insights_agent("ultra-pi", db, user)

    assert resolved is agent
    # The loader evaluates team membership itself, so it takes the caller, not an
    # Registry visibility is governed by teams, not deployment scope.
    load_agent.assert_awaited_once_with(
        db,
        "ultra-pi",
        prefer_user_id=user_id,
        current_user=user,
        include_all_statuses=True,
    )


@pytest.mark.asyncio
async def test_resolve_insights_agent_hides_team_private_agent_from_non_member():
    """A non-member gets the not-found path, never a leak, for a team-private agent."""
    from api.routes.insights import _resolve_insights_agent
    from models.user import UserRole

    agent_id = uuid.uuid4()
    agent = SimpleNamespace(
        id=agent_id,
        name="team-only",
        created_by=uuid.uuid4(),
        is_private=True,
        team_id=uuid.uuid4(),
        co_authors=[],
    )
    outsider = SimpleNamespace(id=uuid.uuid4(), role=UserRole.user)

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_result(agent))
    db.scalar = AsyncMock(return_value=None)  # no team membership row

    with pytest.raises(HTTPException) as exc:
        await _resolve_insights_agent(str(agent_id), db, outsider)

    assert exc.value.status_code == 404
    assert exc.value.detail == "Agent not found"
    db.scalar.assert_awaited_once()


@pytest.mark.asyncio
async def test_resolve_insights_agent_denies_team_member_who_does_not_own_the_agent():
    """A team member clears visibility but is still refused insights on someone else's agent.

    Team membership decides whether the agent is visible (404 versus found). It is
    not an ownership axis, so the member gets 403 here and not 404: that split is
    the documented behaviour, and it proves the membership lookup actually ran.
    """
    from api.routes.insights import _resolve_insights_agent
    from models.user import UserRole

    agent_id = uuid.uuid4()
    agent = SimpleNamespace(
        id=agent_id,
        name="team-only",
        created_by=uuid.uuid4(),
        is_private=True,
        team_id=uuid.uuid4(),
        co_authors=[],
    )
    member = SimpleNamespace(id=uuid.uuid4(), role=UserRole.user)

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_result(agent))
    db.scalar = AsyncMock(return_value=uuid.uuid4())  # membership row exists

    with pytest.raises(HTTPException) as exc:
        await _resolve_insights_agent(str(agent_id), db, member)

    assert exc.value.status_code == 403
    assert exc.value.detail == "Insufficient permissions for this agent"
    db.scalar.assert_awaited_once()


@pytest.mark.asyncio
async def test_resolve_insights_agent_allows_creator_of_team_private_agent():
    """The creator of a team-private agent resolves it through both gates.

    Membership still has to be present: check_listing_visibility_async treats a
    team-private item as reachable through the teamspace only, so authorship alone
    does not survive removal from the team.
    """
    from api.routes.insights import _resolve_insights_agent
    from models.user import UserRole

    agent_id = uuid.uuid4()
    creator_id = uuid.uuid4()
    agent = SimpleNamespace(
        id=agent_id,
        name="team-only",
        created_by=creator_id,
        is_private=True,
        team_id=uuid.uuid4(),
        co_authors=[],
    )
    creator = SimpleNamespace(id=creator_id, role=UserRole.user)

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_result(agent))
    db.scalar = AsyncMock(return_value=uuid.uuid4())  # creator is a member of the teamspace

    resolved = await _resolve_insights_agent(str(agent_id), db, creator)

    assert resolved is agent


@pytest.mark.asyncio
async def test_resolve_insights_agent_raises_404_for_missing_name():
    from api.routes.insights import _resolve_insights_agent
    from models.user import UserRole

    user = SimpleNamespace(id=uuid.uuid4(), role=UserRole.user)
    db = AsyncMock()

    with (
        patch("api.routes.insights._load_agent", new=AsyncMock(return_value=None)),
        pytest.raises(HTTPException) as exc,
    ):
        await _resolve_insights_agent("ultra-pi", db, user)

    assert exc.value.status_code == 404
    assert exc.value.detail == "Agent not found"
