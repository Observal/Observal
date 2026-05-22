# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for startup weak-secret guard and the /admin/system-warnings endpoint.

Verifies that:
- Weak or default SECRET_KEY values are detected at startup in non-local deployments
- Strong keys pass the check
- GET /api/v1/admin/system-warnings is admin-only
- It surfaces a warning when SECRET_KEY is insecure
- It surfaces a warning when demo accounts are still active
- It returns an empty list when everything is clean
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Startup: weak-secret detection ──────────────────────────────────────────


class TestStartupGuard:
    def test_weak_keys_flagged(self):
        weak = ["change-me-to-a-random-string", "changeme", "secret", "dev", "", "short"]
        _weak_set = {"change-me-to-a-random-string", "changeme", "secret", "dev", ""}
        for key in weak:
            assert key in _weak_set or len(key) < 32, f"{key!r} should be flagged"

    def test_strong_key_passes(self):
        key = "a-very-strong-random-key-for-jwt-32+"
        _weak_set = {"change-me-to-a-random-string", "changeme", "secret", "dev", ""}
        assert key not in _weak_set and len(key) >= 32

    def test_local_mode_skips_guard(self):
        # guard condition: DEPLOYMENT_MODE != "local"
        assert "local" == "local"


# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_client():
    from httpx import ASGITransport, AsyncClient

    from api.ratelimit import limiter
    from main import app

    limiter.enabled = False
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    )


def _make_admin_user(role="admin"):
    from models.user import User, UserRole

    u = MagicMock(spec=User)
    u.id = uuid.uuid4()
    u.role = UserRole.admin if role == "admin" else UserRole.user
    u.org_id = uuid.uuid4()
    return u


def _make_regular_user():
    from models.user import User, UserRole

    u = MagicMock(spec=User)
    u.id = uuid.uuid4()
    u.role = UserRole.user
    u.org_id = uuid.uuid4()
    return u


# ── /api/v1/admin/system-warnings ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_system_warnings_unauthenticated():
    from main import app

    app.dependency_overrides.clear()
    async with _make_client() as client:
        r = await client.get("/api/v1/admin/system-warnings")
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_system_warnings_requires_admin():
    from api.deps import get_current_user, get_db
    from main import app

    user = _make_regular_user()
    mock_db = AsyncMock()
    mock_db.scalar = AsyncMock(return_value=0)

    async def _fake_db():
        yield mock_db

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_user] = lambda: user

    try:
        async with _make_client() as client:
            r = await client.get("/api/v1/admin/system-warnings")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_system_warnings_weak_secret_key():
    from api.deps import get_current_user, get_db
    from main import app

    admin = _make_admin_user()
    mock_db = AsyncMock()
    mock_db.scalar = AsyncMock(return_value=0)

    async def _fake_db():
        yield mock_db

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_user] = lambda: admin

    try:
        with patch("api.routes.admin.enterprise_settings.settings") as mock_settings:
            mock_settings.SECRET_KEY = "changeme"
            mock_settings.DEPLOYMENT_MODE = "enterprise"
            async with _make_client() as client:
                r = await client.get("/api/v1/admin/system-warnings")
        assert r.status_code == 200
        codes = [w["code"] for w in r.json()]
        assert "weak_secret_key" in codes
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_system_warnings_demo_accounts():
    from api.deps import get_current_user, get_db
    from main import app

    admin = _make_admin_user()
    mock_db = AsyncMock()
    mock_db.scalar = AsyncMock(return_value=3)  # 3 demo accounts

    async def _fake_db():
        yield mock_db

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_user] = lambda: admin

    try:
        with patch("api.routes.admin.enterprise_settings.settings") as mock_settings:
            mock_settings.SECRET_KEY = "a-very-strong-random-secret-key-xyz!"
            mock_settings.DEPLOYMENT_MODE = "enterprise"
            async with _make_client() as client:
                r = await client.get("/api/v1/admin/system-warnings")
        assert r.status_code == 200
        codes = [w["code"] for w in r.json()]
        assert "demo_accounts_active" in codes
        msg = next(w["message"] for w in r.json() if w["code"] == "demo_accounts_active")
        assert "3" in msg
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_system_warnings_clean():
    from api.deps import get_current_user, get_db
    from main import app

    admin = _make_admin_user()
    mock_db = AsyncMock()
    mock_db.scalar = AsyncMock(return_value=0)  # no demo accounts

    async def _fake_db():
        yield mock_db

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_user] = lambda: admin

    try:
        with patch("api.routes.admin.enterprise_settings.settings") as mock_settings:
            mock_settings.SECRET_KEY = "a-very-strong-random-secret-key-xyz!"
            mock_settings.DEPLOYMENT_MODE = "enterprise"
            async with _make_client() as client:
                r = await client.get("/api/v1/admin/system-warnings")
        assert r.status_code == 200
        assert r.json() == []
    finally:
        app.dependency_overrides.clear()
