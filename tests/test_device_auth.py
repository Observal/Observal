# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for OAuth 2.0 Device Authorization Grant (RFC 8628) endpoints."""

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_mock_user(**overrides):
    from models.user import UserRole

    user = MagicMock()
    user.id = overrides.get("id", uuid.uuid4())
    user.email = overrides.get("email", "test@example.com")
    user.username = overrides.get("username", "testuser")
    user.name = overrides.get("name", "Test User")
    user.role = overrides.get("role", UserRole.user)
    user.created_at = overrides.get("created_at", datetime.now(UTC))
    user.org_id = overrides.get("org_id", uuid.uuid4())
    return user


class FakeRedis:
    """In-memory fake Redis for testing device auth flows."""

    def __init__(self):
        self._store: dict[str, str] = {}
        self._ttls: dict[str, int] = {}

    async def setex(self, key: str, ttl: int, value: str):
        self._store[key] = value
        self._ttls[key] = ttl

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def delete(self, *keys: str):
        for key in keys:
            self._store.pop(key, None)
            self._ttls.pop(key, None)

    async def ttl(self, key: str) -> int:
        return self._ttls.get(key, -1)

    def pipeline(self):
        return FakePipeline(self)


class FakePipeline:
    """Fake Redis pipeline that batches commands."""

    def __init__(self, redis: FakeRedis):
        self._redis = redis
        self._commands: list[tuple] = []

    def setex(self, key: str, ttl: int, value: str):
        self._commands.append(("setex", key, ttl, value))
        return self

    def delete(self, *keys: str):
        for key in keys:
            self._commands.append(("delete", key))
        return self

    async def execute(self):
        results = []
        for cmd in self._commands:
            if cmd[0] == "setex":
                await self._redis.setex(cmd[1], cmd[2], cmd[3])
                results.append(True)
            elif cmd[0] == "delete":
                await self._redis.delete(cmd[1])
                results.append(1)
        self._commands.clear()
        return results


def _make_async_client():
    from httpx import ASGITransport, AsyncClient

    from api.ratelimit import limiter
    from main import app

    limiter.enabled = False

    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    )


def _setup_auth_override(mock_user):
    """Override get_current_user to return the mock user."""
    from api.deps import get_current_user
    from main import app

    async def _override():
        return mock_user

    app.dependency_overrides[get_current_user] = _override


def _setup_db_override(mock_user):
    """Override get_db to return a mock session that finds the mock user."""
    from api.deps import get_db
    from main import app

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_user

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    async def _mock_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = _mock_get_db


def _cleanup():
    from main import app

    app.dependency_overrides.clear()


class TestDeviceAuthorize:
    """POST /api/v1/auth/device/authorize"""

    @pytest.mark.asyncio
    async def test_returns_device_and_user_codes(self):
        fake_redis = FakeRedis()
        try:
            with patch("api.routes.device_auth.get_redis", return_value=fake_redis):
                async with _make_async_client() as client:
                    resp = await client.post("/api/v1/auth/device/authorize", json={})

            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
            body = resp.json()
            assert "device_code" in body
            assert "user_code" in body
            assert len(body["device_code"]) > 0
            # User code should be formatted as XXXX-XXXX
            assert len(body["user_code"]) == 9
            assert body["user_code"][4] == "-"
            assert body["expires_in"] == 600
            assert body["interval"] == 5
            assert "/device" in body["verification_uri"]
            assert body["user_code"] in body["verification_uri_complete"]

            # Verify data was stored in Redis
            stored_keys = list(fake_redis._store.keys())
            device_keys = [k for k in stored_keys if k.startswith("device_auth:")]
            user_keys = [k for k in stored_keys if k.startswith("device_code_by_user:")]
            assert len(device_keys) == 1
            assert len(user_keys) == 1

            # Verify stored data structure
            stored_data = json.loads(fake_redis._store[device_keys[0]])
            assert stored_data["status"] == "pending"
            assert stored_data["user_code"] == body["user_code"]
        finally:
            _cleanup()

    def test_user_code_uses_unambiguous_chars(self):
        from api.routes.device_auth import _generate_user_code

        ambiguous = set("01OILAU")
        for _ in range(50):
            code = _generate_user_code().replace("-", "")
            assert len(code) == 8
            assert not ambiguous.intersection(set(code)), f"User code {code} contains ambiguous characters"


class TestDeviceToken:
    """POST /api/v1/auth/device/token"""

    @pytest.mark.asyncio
    async def test_invalid_grant_type_returns_400(self):
        fake_redis = FakeRedis()
        try:
            with patch("api.routes.device_auth.get_redis", return_value=fake_redis):
                async with _make_async_client() as client:
                    resp = await client.post(
                        "/api/v1/auth/device/token",
                        json={
                            "device_code": "abc",
                            "grant_type": "wrong_type",
                        },
                    )

            assert resp.status_code == 400
            assert resp.json()["error"] == "invalid_grant_type"
        finally:
            _cleanup()

    @pytest.mark.asyncio
    async def test_expired_device_code_returns_400(self):
        fake_redis = FakeRedis()
        try:
            with patch("api.routes.device_auth.get_redis", return_value=fake_redis):
                async with _make_async_client() as client:
                    resp = await client.post(
                        "/api/v1/auth/device/token",
                        json={
                            "device_code": "nonexistent",
                            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                        },
                    )

            assert resp.status_code == 400
            assert resp.json()["error"] == "expired_token"
        finally:
            _cleanup()

    @pytest.mark.asyncio
    async def test_pending_returns_428(self):
        fake_redis = FakeRedis()
        device_code = "test-device-code"
        await fake_redis.setex(
            f"device_auth:{device_code}",
            600,
            json.dumps({"user_code": "BCDF-GHJK", "status": "pending", "created_at": 1000}),
        )
        try:
            with patch("api.routes.device_auth.get_redis", return_value=fake_redis):
                async with _make_async_client() as client:
                    resp = await client.post(
                        "/api/v1/auth/device/token",
                        json={
                            "device_code": device_code,
                            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                        },
                    )

            assert resp.status_code == 428
            assert resp.json()["error"] == "authorization_pending"
        finally:
            _cleanup()

    @pytest.mark.asyncio
    async def test_denied_returns_400(self):
        fake_redis = FakeRedis()
        device_code = "test-device-code-denied"
        await fake_redis.setex(
            f"device_auth:{device_code}",
            600,
            json.dumps({"user_code": "BCDF-GHJK", "status": "denied", "created_at": 1000}),
        )
        try:
            with patch("api.routes.device_auth.get_redis", return_value=fake_redis):
                async with _make_async_client() as client:
                    resp = await client.post(
                        "/api/v1/auth/device/token",
                        json={
                            "device_code": device_code,
                            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                        },
                    )

            assert resp.status_code == 400
            assert resp.json()["error"] == "access_denied"
            # Key should be deleted after denial
            assert await fake_redis.get(f"device_auth:{device_code}") is None
        finally:
            _cleanup()

    @pytest.mark.asyncio
    async def test_approved_returns_tokens(self):
        mock_user = _make_mock_user()
        fake_redis = FakeRedis()
        device_code = "test-device-code-approved"
        await fake_redis.setex(
            f"device_auth:{device_code}",
            600,
            json.dumps(
                {
                    "user_code": "BCDF-GHJK",
                    "status": "approved",
                    "user_id": str(mock_user.id),
                    "created_at": 1000,
                }
            ),
        )
        await fake_redis.setex("device_code_by_user:BCDFGHJK", 600, device_code)

        _setup_db_override(mock_user)
        try:
            with (
                patch("api.routes.device_auth.get_redis", return_value=fake_redis),
                patch("api.routes.auth.get_redis", return_value=fake_redis),
            ):
                async with _make_async_client() as client:
                    resp = await client.post(
                        "/api/v1/auth/device/token",
                        json={
                            "device_code": device_code,
                            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                        },
                    )

            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
            body = resp.json()
            assert "access_token" in body
            assert "refresh_token" in body
            assert "expires_in" in body
            assert body["user"]["email"] == mock_user.email
            assert body["user"]["id"] == str(mock_user.id)
        finally:
            _cleanup()


class TestDeviceConfirm:
    """POST /api/v1/auth/device/confirm"""

    @pytest.mark.asyncio
    async def test_invalid_user_code_returns_404(self):
        mock_user = _make_mock_user()
        fake_redis = FakeRedis()

        _setup_auth_override(mock_user)
        try:
            with patch("api.routes.device_auth.get_redis", return_value=fake_redis):
                async with _make_async_client() as client:
                    resp = await client.post(
                        "/api/v1/auth/device/confirm",
                        json={"user_code": "ZZZZ-ZZZZ"},
                        headers={"Authorization": "Bearer fake-token"},
                    )

            assert resp.status_code == 404
            assert "Invalid or expired" in resp.json()["detail"]
        finally:
            _cleanup()

    @pytest.mark.asyncio
    async def test_confirm_approves_device(self):
        mock_user = _make_mock_user()
        fake_redis = FakeRedis()
        device_code = "test-device-code-confirm"
        user_code = "BCDF-GHJK"
        normalized = "BCDFGHJK"

        await fake_redis.setex(
            f"device_auth:{device_code}",
            600,
            json.dumps({"user_code": user_code, "status": "pending", "created_at": 1000}),
        )
        await fake_redis.setex(f"device_code_by_user:{normalized}", 600, device_code)

        _setup_auth_override(mock_user)
        try:
            with patch("api.routes.device_auth.get_redis", return_value=fake_redis):
                async with _make_async_client() as client:
                    resp = await client.post(
                        "/api/v1/auth/device/confirm",
                        json={"user_code": user_code},
                        headers={"Authorization": "Bearer fake-token"},
                    )

            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
            assert resp.json()["message"] == "Device authorized"

            # Verify the device_auth entry was updated to approved
            raw = await fake_redis.get(f"device_auth:{device_code}")
            data = json.loads(raw)
            assert data["status"] == "approved"
            assert data["user_id"] == str(mock_user.id)
        finally:
            _cleanup()

    @pytest.mark.asyncio
    async def test_confirm_case_insensitive(self):
        """User codes should match regardless of case."""
        mock_user = _make_mock_user()
        fake_redis = FakeRedis()
        device_code = "test-device-code-case"
        user_code = "BCDF-GHJK"
        normalized = "BCDFGHJK"

        await fake_redis.setex(
            f"device_auth:{device_code}",
            600,
            json.dumps({"user_code": user_code, "status": "pending", "created_at": 1000}),
        )
        await fake_redis.setex(f"device_code_by_user:{normalized}", 600, device_code)

        _setup_auth_override(mock_user)
        try:
            with patch("api.routes.device_auth.get_redis", return_value=fake_redis):
                async with _make_async_client() as client:
                    # Send lowercase user code
                    resp = await client.post(
                        "/api/v1/auth/device/confirm",
                        json={"user_code": "bcdf-ghjk"},
                        headers={"Authorization": "Bearer fake-token"},
                    )

            assert resp.status_code == 200
            assert resp.json()["message"] == "Device authorized"
        finally:
            _cleanup()

    @pytest.mark.asyncio
    async def test_confirm_already_approved_returns_400(self):
        mock_user = _make_mock_user()
        fake_redis = FakeRedis()
        device_code = "test-device-code-already"
        user_code = "BCDF-GHJK"
        normalized = "BCDFGHJK"

        await fake_redis.setex(
            f"device_auth:{device_code}",
            600,
            json.dumps(
                {
                    "user_code": user_code,
                    "status": "approved",
                    "user_id": str(uuid.uuid4()),
                    "created_at": 1000,
                }
            ),
        )
        await fake_redis.setex(f"device_code_by_user:{normalized}", 600, device_code)

        _setup_auth_override(mock_user)
        try:
            with patch("api.routes.device_auth.get_redis", return_value=fake_redis):
                async with _make_async_client() as client:
                    resp = await client.post(
                        "/api/v1/auth/device/confirm",
                        json={"user_code": user_code},
                        headers={"Authorization": "Bearer fake-token"},
                    )

            assert resp.status_code == 400
            assert "already used or expired" in resp.json()["detail"]
        finally:
            _cleanup()

    @pytest.mark.asyncio
    async def test_requires_authentication(self):
        """Confirm endpoint should require a valid JWT."""
        fake_redis = FakeRedis()
        try:
            with patch("api.routes.device_auth.get_redis", return_value=fake_redis):
                async with _make_async_client() as client:
                    resp = await client.post(
                        "/api/v1/auth/device/confirm",
                        json={"user_code": "BCDF-GHJK"},
                    )

            assert resp.status_code == 401
        finally:
            _cleanup()


class TestDeviceAuthFullFlow:
    """End-to-end device authorization flow."""

    @pytest.mark.asyncio
    async def test_full_flow_authorize_confirm_token(self):
        mock_user = _make_mock_user()
        fake_redis = FakeRedis()

        _setup_auth_override(mock_user)
        _setup_db_override(mock_user)
        try:
            with (
                patch("api.routes.device_auth.get_redis", return_value=fake_redis),
                patch("api.routes.auth.get_redis", return_value=fake_redis),
            ):
                async with _make_async_client() as client:
                    # Step 1: CLI requests device authorization
                    auth_resp = await client.post("/api/v1/auth/device/authorize", json={})
                    assert auth_resp.status_code == 200
                    auth_body = auth_resp.json()
                    device_code = auth_body["device_code"]
                    user_code = auth_body["user_code"]

                    # Step 2: CLI polls -- should get authorization_pending
                    poll_resp = await client.post(
                        "/api/v1/auth/device/token",
                        json={
                            "device_code": device_code,
                            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                        },
                    )
                    assert poll_resp.status_code == 428
                    assert poll_resp.json()["error"] == "authorization_pending"

                    # Step 3: User confirms in browser
                    confirm_resp = await client.post(
                        "/api/v1/auth/device/confirm",
                        json={"user_code": user_code},
                        headers={"Authorization": "Bearer fake-token"},
                    )
                    assert confirm_resp.status_code == 200

                    # Step 4: CLI polls again -- should get tokens
                    token_resp = await client.post(
                        "/api/v1/auth/device/token",
                        json={
                            "device_code": device_code,
                            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                        },
                    )
                    assert token_resp.status_code == 200, (
                        f"Expected 200, got {token_resp.status_code}: {token_resp.text}"
                    )
                    token_body = token_resp.json()
                    assert "access_token" in token_body
                    assert "refresh_token" in token_body
                    assert token_body["user"]["email"] == mock_user.email

                    # Step 5: Polling again should return expired_token (keys cleaned up)
                    expired_resp = await client.post(
                        "/api/v1/auth/device/token",
                        json={
                            "device_code": device_code,
                            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                        },
                    )
                    assert expired_resp.status_code == 400
                    assert expired_resp.json()["error"] == "expired_token"
        finally:
            _cleanup()
