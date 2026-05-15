# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for auth endpoint resilience when Redis is unavailable.

Validates fail-closed behavior:
- Login returns 503 when Redis is down (cannot durably store refresh JTI)
- Token refresh returns 503 when Redis is down
- Token revoke returns 503 when Redis is down
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError


@pytest.fixture(autouse=True, scope="module")
def init_key_manager_for_module(tmp_path_factory):
    """Ensure the asymmetric key manager is initialised for all tests in this module."""
    from services.crypto import init_key_manager

    key_dir = tmp_path_factory.mktemp("keys")
    init_key_manager(key_dir=str(key_dir), key_password=None)


def _make_mock_user():
    from models.user import UserRole

    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = "test@example.com"
    user.username = "testuser"
    user.name = "Test User"
    user.role = UserRole.user
    user.avatar_url = None
    user.verify_password = MagicMock(return_value=True)
    return user


def _make_broken_redis():
    r = MagicMock()
    r.setex = AsyncMock(side_effect=RedisConnectionError("Connection refused"))
    r.get = AsyncMock(side_effect=RedisConnectionError("Connection refused"))
    r.delete = AsyncMock(side_effect=RedisConnectionError("Connection refused"))
    return r


class TestLoginRedisDown:
    """POST /api/v1/auth/login should return 503 when Redis is unreachable.

    Fail closed: if the refresh JTI cannot be stored we cannot revoke it
    later, so the token must not be issued.
    """

    @pytest.mark.asyncio
    async def test_login_succeeds_when_redis_down(self):
        from api.deps import get_db
        from main import app

        mock_user = _make_mock_user()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def _mock_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = _mock_get_db
        try:
            with patch("api.routes.auth.get_redis", return_value=_make_broken_redis()):
                from httpx import ASGITransport, AsyncClient

                async with AsyncClient(
                    transport=ASGITransport(app=app, raise_app_exceptions=False),
                    base_url="http://test",
                ) as client:
                    resp = await client.post(
                        "/api/v1/auth/login",
                        json={"email": "test@example.com", "password": "password"},
                    )

            assert resp.status_code == 503, f"Expected 503 (fail closed), got {resp.status_code}: {resp.text}"
        finally:
            app.dependency_overrides.clear()


class TestRefreshRedisDown:
    """POST /api/v1/auth/token/refresh should return 503 when Redis is unreachable."""

    @pytest.mark.asyncio
    async def test_refresh_returns_503_when_redis_down(self):
        from services.jwt_service import create_refresh_token

        mock_user = _make_mock_user()
        refresh_tok, _ = create_refresh_token(mock_user.id, mock_user.role)

        from httpx import ASGITransport, AsyncClient

        from main import app

        with patch("api.routes.auth.get_redis", return_value=_make_broken_redis()):
            async with AsyncClient(
                transport=ASGITransport(app=app, raise_app_exceptions=False),
                base_url="http://test",
            ) as client:
                resp = await client.post(
                    "/api/v1/auth/token/refresh",
                    json={"refresh_token": refresh_tok},
                )

        assert resp.status_code == 503, f"Expected 503, got {resp.status_code}: {resp.text}"
        assert resp.json()["detail"] == "Service temporarily unavailable"


class TestRevokeRedisDown:
    """POST /api/v1/auth/token/revoke should return 503 when Redis is unreachable."""

    @pytest.mark.asyncio
    async def test_revoke_returns_503_when_redis_down(self):
        from services.jwt_service import create_refresh_token

        mock_user = _make_mock_user()
        refresh_tok, _ = create_refresh_token(mock_user.id, mock_user.role)

        from httpx import ASGITransport, AsyncClient

        from main import app

        with patch("api.routes.auth.get_redis", return_value=_make_broken_redis()):
            async with AsyncClient(
                transport=ASGITransport(app=app, raise_app_exceptions=False),
                base_url="http://test",
            ) as client:
                resp = await client.post(
                    "/api/v1/auth/token/revoke",
                    json={"refresh_token": refresh_tok},
                )

        assert resp.status_code == 503, f"Expected 503, got {resp.status_code}: {resp.text}"
        assert resp.json()["detail"] == "Service temporarily unavailable"


class TestGlobalRedisErrorHandler:
    """Any unhandled RedisError should be caught by the global handler and return 503."""

    @pytest.mark.asyncio
    async def test_unhandled_redis_error_returns_503(self):
        from main import app

        @app.get("/_test_redis_error")
        async def _trigger():
            raise RedisConnectionError("simulated")

        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            resp = await client.get("/_test_redis_error")

        assert resp.status_code == 503
        assert resp.json()["detail"] == "Service temporarily unavailable"
