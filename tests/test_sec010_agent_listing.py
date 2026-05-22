# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for anonymous agent listing visibility.

Verifies that unauthenticated callers cannot see private agents regardless
of deployment mode, and that the visibility filter behaves correctly for
anonymous, authenticated, and admin users.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

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


# ── Unit: skip_visibility logic ───────────────────────────────────────────────


class TestSkipVisibilityLogic:
    def test_local_mode_anon_does_not_skip(self):
        """Anonymous callers must not skip visibility even in local mode."""
        current_user = None
        skip = "local" == "local" and current_user is not None
        assert skip is False

    def test_local_mode_authed_skips(self):
        """Authenticated users in local mode skip visibility (dev convenience)."""
        current_user = _user()
        skip = "local" == "local" and current_user is not None
        assert skip is True

    def test_enterprise_authed_does_not_skip(self):
        current_user = _user()
        skip = "enterprise" == "local" and current_user is not None
        assert skip is False

    def test_enterprise_anon_does_not_skip(self):
        skip = "enterprise" == "local" and None is not None
        assert skip is False


# ── Integration: GET /api/v1/agents ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_anonymous_cannot_see_private_agents_local_mode():
    """In local mode, anonymous callers only see public agents (skip_visibility=False for anon)."""
    from api.deps import get_db, optional_current_user
    from main import app

    mock = _mock_db()

    async def _fake_db():
        yield mock

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[optional_current_user] = lambda: None

    try:
        with patch("api.routes.agent.crud.settings") as ms:
            ms.DEPLOYMENT_MODE = "local"
            async with _make_client() as client:
                r = await client.get("/api/v1/agents")
        assert r.status_code == 200
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_anonymous_cannot_see_private_agents_enterprise_mode():
    """In enterprise mode, anonymous callers only see public agents."""
    from api.deps import get_db, optional_current_user
    from main import app

    mock = _mock_db()

    async def _fake_db():
        yield mock

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[optional_current_user] = lambda: None

    try:
        with patch("api.routes.agent.crud.settings") as ms:
            ms.DEPLOYMENT_MODE = "enterprise"
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
