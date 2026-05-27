# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for agent listing endpoint access.

Verifies that both anonymous and authenticated callers can list agents
(no visibility gating).
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_client():
    from httpx import ASGITransport, AsyncClient

    from api.ratelimit import limiter
    from main import app

    limiter.enabled = False
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    )


def _user(role="user"):
    from models.user import User, UserRole

    u = MagicMock(spec=User)
    u.id = uuid.uuid4()
    u.role = getattr(UserRole, role)
    u.org_id = uuid.uuid4()
    u.username = "testuser"
    u.email = "test@example.com"
    return u


def _mock_db():
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_result.scalar_one.return_value = 0
    mock_result.all.return_value = []
    db.execute = AsyncMock(return_value=mock_result)
    db.scalar = AsyncMock(return_value=0)
    return db


# ── Integration: GET /api/v1/agents ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_anonymous_can_list_agents():
    """Anonymous callers can list agents (all agents are public)."""
    from api.deps import get_db, optional_current_user
    from main import app

    mock = _mock_db()

    async def _fake_db():
        yield mock

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[optional_current_user] = lambda: None

    try:
        async with _make_client() as client:
            r = await client.get("/api/v1/agents")
        assert r.status_code == 200
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_authenticated_user_can_list_agents():
    """Authenticated users get a 200 from the agent list endpoint."""
    from api.deps import get_db, optional_current_user
    from main import app

    user = _user()
    mock = _mock_db()

    async def _fake_db():
        yield mock

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[optional_current_user] = lambda: user

    try:
        async with _make_client() as client:
            r = await client.get("/api/v1/agents")
        assert r.status_code == 200
    finally:
        app.dependency_overrides.clear()
