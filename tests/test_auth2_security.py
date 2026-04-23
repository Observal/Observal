"""Tests for Auth 2.0 security features.

Covers:
- must_change_password enforcement in get_current_user
- Deactivated user blocking
- Code exchange atomicity (GETDEL)
- Username-based login
- Safe redirect path (_safe_redirect_path)
"""

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers shared across all test classes
# ---------------------------------------------------------------------------


def _make_mock_user(**overrides):
    from models.user import UserRole

    user = MagicMock()
    user.id = overrides.get("id", uuid.uuid4())
    user.email = overrides.get("email", "test@example.com")
    user.username = overrides.get("username", "testuser")
    user.name = overrides.get("name", "Test User")
    user.role = overrides.get("role", UserRole.user)
    user.auth_provider = overrides.get("auth_provider", "local")
    user.created_at = overrides.get("created_at", datetime.now(UTC))
    user.org_id = overrides.get("org_id", uuid.uuid4())
    user._trace_privacy = False
    return user


class FakeRedis:
    """In-memory fake Redis for testing auth flows."""

    def __init__(self):
        self._store: dict[str, str] = {}
        self._ttls: dict[str, int] = {}

    async def setex(self, key: str, ttl: int, value: str):
        self._store[key] = value
        self._ttls[key] = ttl

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def getdel(self, key: str) -> str | None:
        return self._store.pop(key, None)

    async def delete(self, *keys: str):
        for key in keys:
            self._store.pop(key, None)
            self._ttls.pop(key, None)


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


# ---------------------------------------------------------------------------
# 1. must_change_password enforcement
# ---------------------------------------------------------------------------


class TestMustChangePassword:
    """get_current_user blocks non-exempt paths when must_change_password is set."""

    @pytest.mark.asyncio
    async def test_must_change_password_blocks_api_access(self):
        """A user with the must_change_password Redis flag should receive 403 on normal endpoints.

        Uses POST /api/v1/auth/hooks-token which requires get_current_user directly and is
        not in the exempt paths list.
        """
        mock_user = _make_mock_user()
        fake_redis = FakeRedis()
        await fake_redis.setex(f"must_change_password:{mock_user.id}", 3600, "1")

        try:
            with (
                patch("api.deps._authenticate_via_jwt", new=AsyncMock(return_value=mock_user)),
                patch("api.deps.get_redis", return_value=fake_redis),
            ):
                async with _make_async_client() as client:
                    resp = await client.post(
                        "/api/v1/auth/hooks-token",
                        headers={"Authorization": "Bearer fake-token"},
                    )

            assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
            assert resp.json()["detail"] == "Password change required"
        finally:
            _cleanup()

    @pytest.mark.asyncio
    async def test_must_change_password_allows_password_change(self):
        """PUT /api/v1/auth/profile/password must remain accessible when flag is set."""
        mock_user = _make_mock_user()
        mock_user.verify_password = MagicMock(return_value=True)
        fake_redis = FakeRedis()
        await fake_redis.setex(f"must_change_password:{mock_user.id}", 3600, "1")

        _setup_db_override(mock_user)
        try:
            with (
                patch("api.deps._authenticate_via_jwt", new=AsyncMock(return_value=mock_user)),
                patch("api.deps.get_redis", return_value=fake_redis),
                patch("api.routes.auth.get_redis", return_value=fake_redis),
            ):
                async with _make_async_client() as client:
                    resp = await client.put(
                        "/api/v1/auth/profile/password",
                        json={"current_password": "old", "new_password": "Str0ng!Pass#1"},
                        headers={"Authorization": "Bearer fake-token"},
                    )

            # Must NOT be 403 "Password change required" -- any other response is acceptable
            # (400 for wrong password, 200 for success, etc.)
            if resp.status_code == 403:
                assert resp.json().get("detail") != "Password change required", (
                    "Exempt path /api/v1/auth/profile/password must not be blocked"
                )
        finally:
            _cleanup()

    @pytest.mark.asyncio
    async def test_must_change_password_allows_whoami(self):
        """GET /api/v1/auth/whoami must remain accessible when flag is set."""
        mock_user = _make_mock_user()
        fake_redis = FakeRedis()
        await fake_redis.setex(f"must_change_password:{mock_user.id}", 3600, "1")

        _setup_db_override(mock_user)
        try:
            with (
                patch("api.deps._authenticate_via_jwt", new=AsyncMock(return_value=mock_user)),
                patch("api.deps.get_redis", return_value=fake_redis),
            ):
                async with _make_async_client() as client:
                    resp = await client.get(
                        "/api/v1/auth/whoami",
                        headers={"Authorization": "Bearer fake-token"},
                    )

            assert resp.status_code != 403 or resp.json().get("detail") != "Password change required", (
                "Exempt path /api/v1/auth/whoami must not be blocked by must_change_password"
            )
        finally:
            _cleanup()

    @pytest.mark.asyncio
    async def test_must_change_password_redis_down_fails_open(self):
        """When Redis raises RedisError, get_current_user should not block the request."""
        from redis.exceptions import RedisError

        mock_user = _make_mock_user()

        broken_redis = MagicMock()
        broken_redis.get = AsyncMock(side_effect=RedisError("Connection refused"))

        try:
            with (
                patch("api.deps._authenticate_via_jwt", new=AsyncMock(return_value=mock_user)),
                patch("api.deps.get_redis", return_value=broken_redis),
            ):
                async with _make_async_client() as client:
                    # Use hooks-token which calls get_current_user directly
                    resp = await client.post(
                        "/api/v1/auth/hooks-token",
                        headers={"Authorization": "Bearer fake-token"},
                    )

            # Should NOT be a 403 from must_change_password -- Redis errors must fail open
            if resp.status_code == 403:
                assert resp.json().get("detail") != "Password change required", (
                    "Redis unavailability must not block access (fail-open)"
                )
        finally:
            _cleanup()

    @pytest.mark.asyncio
    async def test_no_flag_allows_normal_access(self):
        """Without the Redis flag, a normal user should pass get_current_user freely."""
        mock_user = _make_mock_user()
        fake_redis = FakeRedis()
        # No flag set in fake_redis

        try:
            with (
                patch("api.deps._authenticate_via_jwt", new=AsyncMock(return_value=mock_user)),
                patch("api.deps.get_redis", return_value=fake_redis),
            ):
                async with _make_async_client() as client:
                    # hooks-token calls get_current_user directly without exemptions
                    resp = await client.post(
                        "/api/v1/auth/hooks-token",
                        headers={"Authorization": "Bearer fake-token"},
                    )

            assert resp.status_code != 403 or resp.json().get("detail") != "Password change required"
        finally:
            _cleanup()


# ---------------------------------------------------------------------------
# 2. Deactivated user blocking
# ---------------------------------------------------------------------------


class TestDeactivatedUser:
    """get_current_user must reject users whose auth_provider is 'deactivated'."""

    @pytest.mark.asyncio
    async def test_deactivated_user_blocked(self):
        """A user with auth_provider='deactivated' should receive 403 Account deactivated."""
        mock_user = _make_mock_user(auth_provider="deactivated")
        fake_redis = FakeRedis()

        try:
            with (
                patch("api.deps._authenticate_via_jwt", new=AsyncMock(return_value=mock_user)),
                patch("api.deps.get_redis", return_value=fake_redis),
            ):
                async with _make_async_client() as client:
                    resp = await client.get(
                        "/api/v1/auth/whoami",
                        headers={"Authorization": "Bearer fake-token"},
                    )

            assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
            assert resp.json()["detail"] == "Account deactivated"
        finally:
            _cleanup()

    @pytest.mark.asyncio
    async def test_active_user_allowed(self):
        """A user with auth_provider='local' must NOT be blocked by the deactivation check."""
        mock_user = _make_mock_user(auth_provider="local")
        fake_redis = FakeRedis()

        _setup_db_override(mock_user)
        try:
            with (
                patch("api.deps._authenticate_via_jwt", new=AsyncMock(return_value=mock_user)),
                patch("api.deps.get_redis", return_value=fake_redis),
            ):
                async with _make_async_client() as client:
                    resp = await client.get(
                        "/api/v1/auth/whoami",
                        headers={"Authorization": "Bearer fake-token"},
                    )

            assert resp.status_code != 403 or resp.json().get("detail") != "Account deactivated", (
                "Active user must not be blocked as deactivated"
            )
        finally:
            _cleanup()

    @pytest.mark.asyncio
    async def test_saml_user_allowed(self):
        """A user with auth_provider='saml' should pass the deactivation check."""
        mock_user = _make_mock_user(auth_provider="saml")
        fake_redis = FakeRedis()

        _setup_db_override(mock_user)
        try:
            with (
                patch("api.deps._authenticate_via_jwt", new=AsyncMock(return_value=mock_user)),
                patch("api.deps.get_redis", return_value=fake_redis),
            ):
                async with _make_async_client() as client:
                    resp = await client.get(
                        "/api/v1/auth/whoami",
                        headers={"Authorization": "Bearer fake-token"},
                    )

            assert resp.status_code != 403 or resp.json().get("detail") != "Account deactivated"
        finally:
            _cleanup()


# ---------------------------------------------------------------------------
# 3. Code exchange atomicity (GETDEL)
# ---------------------------------------------------------------------------


class TestCodeExchange:
    """POST /api/v1/auth/exchange must use atomic GETDEL to prevent replay attacks."""

    def _make_code_payload(self, user_id: uuid.UUID) -> str:
        return json.dumps(
            {
                "access_token": "fake-access-token",
                "refresh_token": "fake-refresh-token",
                "expires_in": 3600,
                "user_id": str(user_id),
                "role": "user",
            }
        )

    @pytest.mark.asyncio
    async def test_code_exchange_single_use(self):
        """A code can be exchanged exactly once; a second attempt must return 400."""
        mock_user = _make_mock_user()
        fake_redis = FakeRedis()
        code = "test-one-time-code"
        await fake_redis.setex(f"oauth_code:{code}", 30, self._make_code_payload(mock_user.id))

        _setup_db_override(mock_user)
        try:
            with patch("api.routes.auth.get_redis", return_value=fake_redis):
                async with _make_async_client() as client:
                    # First exchange -- should succeed
                    first = await client.post("/api/v1/auth/exchange", json={"code": code})
                    assert first.status_code == 200, (
                        f"First exchange should succeed, got {first.status_code}: {first.text}"
                    )

                    # Second exchange of the same code -- must fail
                    second = await client.post("/api/v1/auth/exchange", json={"code": code})
                    assert second.status_code == 400, (
                        f"Second exchange must return 400, got {second.status_code}: {second.text}"
                    )
                    assert "Invalid or expired code" in second.json()["detail"]
        finally:
            _cleanup()

    @pytest.mark.asyncio
    async def test_code_exchange_expired(self):
        """Exchanging a code that was never stored (or already expired) must return 400."""
        fake_redis = FakeRedis()

        try:
            with patch("api.routes.auth.get_redis", return_value=fake_redis):
                async with _make_async_client() as client:
                    resp = await client.post(
                        "/api/v1/auth/exchange",
                        json={"code": "nonexistent-code"},
                    )

            assert resp.status_code == 400, f"Expected 400, got {resp.status_code}: {resp.text}"
            assert "Invalid or expired code" in resp.json()["detail"]
        finally:
            _cleanup()

    @pytest.mark.asyncio
    async def test_code_exchange_removed_after_use(self):
        """After a successful exchange the Redis key must no longer exist."""
        mock_user = _make_mock_user()
        fake_redis = FakeRedis()
        code = "cleanup-test-code"
        await fake_redis.setex(f"oauth_code:{code}", 30, self._make_code_payload(mock_user.id))

        _setup_db_override(mock_user)
        try:
            with patch("api.routes.auth.get_redis", return_value=fake_redis):
                async with _make_async_client() as client:
                    resp = await client.post("/api/v1/auth/exchange", json={"code": code})

            assert resp.status_code == 200
            # Key must be gone from Redis
            assert await fake_redis.get(f"oauth_code:{code}") is None
        finally:
            _cleanup()


# ---------------------------------------------------------------------------
# 4. Username login
# ---------------------------------------------------------------------------


class TestUsernameLogin:
    """POST /api/v1/auth/login must accept username (no @) as identifier."""

    @pytest.mark.asyncio
    async def test_login_with_username(self):
        """When the identifier has no @, the DB query should match on username."""
        mock_user = _make_mock_user(username="jdoe")
        mock_user.verify_password = MagicMock(return_value=True)

        # The login route uses db.execute() and scalar_one_or_none() to find user
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        from api.deps import get_db
        from main import app

        async def _mock_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = _mock_get_db

        fake_redis = FakeRedis()
        try:
            with patch("api.routes.auth.get_redis", return_value=fake_redis):
                async with _make_async_client() as client:
                    resp = await client.post(
                        "/api/v1/auth/login",
                        json={"email": "jdoe", "password": "secret"},
                    )

            assert resp.status_code == 200, f"Expected 200 for username login, got {resp.status_code}: {resp.text}"
            body = resp.json()
            assert "access_token" in body
            assert "refresh_token" in body
        finally:
            _cleanup()

    @pytest.mark.asyncio
    async def test_login_with_email_still_works(self):
        """Standard email login must continue to work after the username-login change."""
        mock_user = _make_mock_user(email="alice@example.com")
        mock_user.verify_password = MagicMock(return_value=True)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        from api.deps import get_db
        from main import app

        async def _mock_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = _mock_get_db

        fake_redis = FakeRedis()
        try:
            with patch("api.routes.auth.get_redis", return_value=fake_redis):
                async with _make_async_client() as client:
                    resp = await client.post(
                        "/api/v1/auth/login",
                        json={"email": "alice@example.com", "password": "secret"},
                    )

            assert resp.status_code == 200, f"Expected 200 for email login, got {resp.status_code}: {resp.text}"
        finally:
            _cleanup()

    @pytest.mark.asyncio
    async def test_login_bad_credentials_returns_401(self):
        """Wrong password must always return 401 regardless of identifier type."""
        mock_user = _make_mock_user()
        mock_user.verify_password = MagicMock(return_value=False)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        from api.deps import get_db
        from main import app

        async def _mock_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = _mock_get_db

        fake_redis = FakeRedis()
        try:
            with patch("api.routes.auth.get_redis", return_value=fake_redis):
                async with _make_async_client() as client:
                    resp = await client.post(
                        "/api/v1/auth/login",
                        json={"email": "testuser", "password": "wrong"},
                    )

            assert resp.status_code == 401
        finally:
            _cleanup()


# ---------------------------------------------------------------------------
# 5. Safe redirect path (_safe_redirect_path)
# ---------------------------------------------------------------------------


class TestSafeRedirectPath:
    """Unit tests for the _safe_redirect_path helper in ee/observal_server/routes/sso_saml.py."""

    def _fn(self):
        from ee.observal_server.routes.sso_saml import _safe_redirect_path

        return _safe_redirect_path

    def test_safe_redirect_rejects_protocol_relative(self):
        """Protocol-relative URLs like //evil.com must be rejected and return /."""
        fn = self._fn()
        assert fn("//evil.com") == "/"
        assert fn("//evil.com/path") == "/"

    def test_safe_redirect_rejects_absolute_url(self):
        """Absolute URLs (https:// or http://) must be rejected and return /."""
        fn = self._fn()
        assert fn("https://evil.com") == "/"
        assert fn("http://evil.com/steal") == "/"

    def test_safe_redirect_accepts_valid_path(self):
        """A simple relative path like /dashboard must be returned as-is."""
        fn = self._fn()
        assert fn("/dashboard") == "/dashboard"
        assert fn("/settings/profile") == "/settings/profile"

    def test_safe_redirect_handles_none(self):
        """None input must return /."""
        fn = self._fn()
        assert fn(None) == "/"

    def test_safe_redirect_handles_empty_string(self):
        """Empty string must return /."""
        fn = self._fn()
        assert fn("") == "/"

    def test_safe_redirect_handles_bare_slash(self):
        """A single / must be returned as /."""
        fn = self._fn()
        assert fn("/") == "/"

    def test_safe_redirect_rejects_non_slash_start(self):
        """Paths not starting with / must return /."""
        fn = self._fn()
        assert fn("evil.com") == "/"
        assert fn("javascript:alert(1)") == "/"
