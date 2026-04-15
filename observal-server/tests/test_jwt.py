"""Tests for JWT token generation, validation, refresh, revocation, and auth dependency."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import jwt as pyjwt
import pytest

# Ensure settings are importable with defaults before anything else
from config import settings
from models.user import User, UserRole
from services.jwt_service import (
    ALGORITHM,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    decode_token,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(
    user_id: uuid.UUID | None = None,
    role: UserRole = UserRole.user,
) -> User:
    """Return a User for testing."""
    uid = user_id or uuid.uuid4()
    user = User(
        id=uid,
        email="test@example.com",
        name="Test User",
        role=role,
    )
    return user


# ---------------------------------------------------------------------------
# Token generation
# ---------------------------------------------------------------------------


class TestTokenGeneration:
    def test_create_access_token_returns_valid_jwt(self):
        uid = uuid.uuid4()
        token, expires_in = create_access_token(uid, UserRole.admin)

        payload = pyjwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        assert payload["sub"] == str(uid)
        assert payload["role"] == "admin"
        assert payload["type"] == "access"
        assert "jti" in payload
        assert "iat" in payload
        assert "exp" in payload
        assert expires_in == settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60

    def test_create_access_token_custom_expiry(self):
        uid = uuid.uuid4()
        token, expires_in = create_access_token(uid, UserRole.user, expires_in_minutes=1440)
        assert expires_in == 1440 * 60
        payload = pyjwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        assert payload["sub"] == str(uid)

    def test_create_refresh_token_returns_valid_jwt_with_jti(self):
        uid = uuid.uuid4()
        token, jti = create_refresh_token(uid, UserRole.reviewer)

        payload = pyjwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        assert payload["sub"] == str(uid)
        assert payload["role"] == "reviewer"
        assert payload["type"] == "refresh"
        assert payload["jti"] == jti

    def test_access_and_refresh_have_different_jtis(self):
        uid = uuid.uuid4()
        access_token, _ = create_access_token(uid, UserRole.user)
        refresh_token, _ = create_refresh_token(uid, UserRole.user)

        a_payload = pyjwt.decode(access_token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        r_payload = pyjwt.decode(refresh_token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        assert a_payload["jti"] != r_payload["jti"]


# ---------------------------------------------------------------------------
# Token validation
# ---------------------------------------------------------------------------


class TestTokenValidation:
    def test_decode_access_token_succeeds(self):
        uid = uuid.uuid4()
        token, _ = create_access_token(uid, UserRole.user)
        payload = decode_access_token(token)
        assert payload["sub"] == str(uid)

    def test_decode_access_token_rejects_refresh_token(self):
        uid = uuid.uuid4()
        token, _ = create_refresh_token(uid, UserRole.user)
        with pytest.raises(pyjwt.InvalidTokenError, match="not an access token"):
            decode_access_token(token)

    def test_decode_refresh_token_succeeds(self):
        uid = uuid.uuid4()
        token, jti = create_refresh_token(uid, UserRole.admin)
        payload = decode_refresh_token(token)
        assert payload["jti"] == jti

    def test_decode_refresh_token_rejects_access_token(self):
        uid = uuid.uuid4()
        token, _ = create_access_token(uid, UserRole.user)
        with pytest.raises(pyjwt.InvalidTokenError, match="not a refresh token"):
            decode_refresh_token(token)

    def test_expired_token_is_rejected(self):
        """A token whose exp is in the past should be rejected."""
        now = datetime.now(UTC)
        payload = {
            "sub": str(uuid.uuid4()),
            "role": "user",
            "type": "access",
            "jti": str(uuid.uuid4()),
            "iat": now - timedelta(hours=2),
            "exp": now - timedelta(hours=1),
        }
        token = pyjwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)
        with pytest.raises(pyjwt.ExpiredSignatureError):
            decode_token(token)

    def test_tampered_token_is_rejected(self):
        uid = uuid.uuid4()
        token, _ = create_access_token(uid, UserRole.user)
        # Flip a character in the signature portion
        parts = token.rsplit(".", 1)
        tampered = parts[0] + "." + parts[1][::-1]
        with pytest.raises(pyjwt.InvalidTokenError):
            decode_token(tampered)

    def test_wrong_secret_is_rejected(self):
        uid = uuid.uuid4()
        now = datetime.now(UTC)
        payload = {
            "sub": str(uid),
            "role": "user",
            "type": "access",
            "jti": str(uuid.uuid4()),
            "iat": now,
            "exp": now + timedelta(hours=1),
        }
        token = pyjwt.encode(payload, "wrong-secret-key", algorithm=ALGORITHM)
        with pytest.raises(pyjwt.InvalidSignatureError):
            decode_token(token)


# ---------------------------------------------------------------------------
# Auth dependency — JWT only
# ---------------------------------------------------------------------------


class TestAuthDependency:
    """Test the get_current_user dependency with JWT Bearer tokens."""

    @pytest.mark.asyncio
    async def test_jwt_bearer_authenticates(self):
        """A valid JWT in Authorization: Bearer should authenticate the user."""
        from api.deps import get_current_user

        user = _make_user()
        token, _ = create_access_token(user.id, user.role)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result

        result = await get_current_user(
            authorization=f"Bearer {token}",
            db=mock_db,
        )
        assert result.id == user.id

    @pytest.mark.asyncio
    async def test_missing_credentials_raises_401(self):
        """No credentials at all should raise 401."""
        from api.deps import get_current_user

        mock_db = AsyncMock()

        with pytest.raises(Exception) as exc_info:
            await get_current_user(authorization=None, db=mock_db)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_jwt_raises_401(self):
        """If the Bearer token is an invalid JWT, raise 401."""
        from api.deps import get_current_user

        mock_db = AsyncMock()

        with pytest.raises(Exception) as exc_info:
            await get_current_user(
                authorization="Bearer totally-bogus-token",
                db=mock_db,
            )
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_expired_jwt_raises_401(self):
        """An expired JWT should raise 401."""
        from api.deps import get_current_user

        user = _make_user()
        now = datetime.now(UTC)
        payload = {
            "sub": str(user.id),
            "role": "user",
            "type": "access",
            "jti": str(uuid.uuid4()),
            "iat": now - timedelta(hours=2),
            "exp": now - timedelta(hours=1),
        }
        expired_token = pyjwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)

        mock_db = AsyncMock()

        with pytest.raises(Exception) as exc_info:
            await get_current_user(
                authorization=f"Bearer {expired_token}",
                db=mock_db,
            )
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_missing_bearer_prefix_raises_401(self):
        """Authorization header without Bearer prefix should raise 401."""
        from api.deps import get_current_user

        user = _make_user()
        token, _ = create_access_token(user.id, user.role)
        mock_db = AsyncMock()

        with pytest.raises(Exception) as exc_info:
            await get_current_user(
                authorization=token,  # Missing "Bearer " prefix
                db=mock_db,
            )
        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


class TestSchemas:
    def test_token_request_requires_credentials(self):
        from schemas.auth import TokenRequest

        with pytest.raises(ValueError):
            TokenRequest()

    def test_token_request_accepts_email_password(self):
        from schemas.auth import TokenRequest

        req = TokenRequest(email="a@b.com", password="secret")
        assert req.email == "a@b.com"

    def test_token_response_has_defaults(self):
        from schemas.auth import TokenResponse

        resp = TokenResponse(
            access_token="a",
            refresh_token="r",
            expires_in=3600,
        )
        assert resp.token_type == "bearer"
