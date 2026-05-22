# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""SEC-028: Password lifecycle routes must be blocked when SSO_ONLY=True."""

from unittest.mock import AsyncMock, patch

import pytest


def _make_async_client():
    from httpx import ASGITransport, AsyncClient

    from api.ratelimit import limiter
    from main import app

    limiter.enabled = False

    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    )


def _cleanup():
    from main import app

    app.dependency_overrides.clear()


class TestSec028SsoGuards:
    """POST /init and PUT /profile/password must return 403 when SSO_ONLY=True."""

    @pytest.mark.asyncio
    async def test_init_blocked_when_sso_only(self):
        """POST /api/v1/auth/init returns 403 when SSO_ONLY=True."""

        with patch("services.dynamic_settings.get_bool", new_callable=AsyncMock, return_value=True):
            async with _make_async_client() as client:
                response = await client.post(
                    "/api/v1/auth/init",
                    json={
                        "email": "admin@example.com",
                        "password": "secret123",
                        "name": "Admin",
                    },
                )

        _cleanup()
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_change_password_blocked_when_sso_only(self):
        """PUT /api/v1/auth/profile/password returns 403 when SSO_ONLY=True."""

        with patch("services.dynamic_settings.get_bool", new_callable=AsyncMock, return_value=True):
            async with _make_async_client() as client:
                response = await client.put(
                    "/api/v1/auth/profile/password",
                    json={
                        "current_password": "old",
                        "new_password": "new",
                    },
                    headers={"Authorization": "Bearer dummy"},
                )

        _cleanup()
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_init_not_blocked_when_sso_only_false(self):
        """POST /api/v1/auth/init is not blocked when SSO_ONLY=False (returns 400 for already-initialized)."""
        from api.deps import get_db
        from main import app

        # Fake DB: pretend system already has a user so init returns 400, not 500
        mock_scalar = AsyncMock(return_value=1)
        mock_db = AsyncMock()
        mock_db.scalar = mock_scalar

        async def _mock_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = _mock_get_db

        with patch("services.dynamic_settings.get_bool", new_callable=AsyncMock, return_value=False):
            async with _make_async_client() as client:
                response = await client.post(
                    "/api/v1/auth/init",
                    json={
                        "email": "admin@example.com",
                        "password": "secret123",
                        "name": "Admin",
                    },
                )

        _cleanup()
        # Must NOT be 403 — the route is reachable; it returns 400 because system
        # is already initialized (our mock DB returns count=1).
        assert response.status_code != 403
        assert response.status_code == 400
