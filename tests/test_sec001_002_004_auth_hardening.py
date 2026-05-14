# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for auth hardening: ES256 token signing, user-level revocation, and
Redis fail-closed behavior.

Covers:
- SEC-004: tokens are ES256-signed and verifiable via JWKS
- SEC-001: revoked_user Redis key blocks all tokens for that user
- SEC-002: Redis errors cause 401/503 rather than fail-open access
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True, scope="module")
def init_key_manager(tmp_path_factory):
    from services.crypto import init_key_manager

    key_dir = tmp_path_factory.mktemp("keys")
    init_key_manager(key_dir=str(key_dir), key_password=None)


# ── SEC-004: ES256 signing ────────────────────────────────────────────────────


def test_access_token_is_es256():
    """Access tokens are signed with ES256, not HS256."""
    import jwt as pyjwt

    from models.user import UserRole
    from services.jwt_service import create_access_token

    token, _ = create_access_token(uuid.uuid4(), UserRole.user)
    header = pyjwt.get_unverified_header(token)
    assert header["alg"] == "ES256"
    assert header["alg"] != "HS256"


def test_refresh_token_is_es256():
    """Refresh tokens are signed with ES256, not HS256."""
    import jwt as pyjwt

    from models.user import UserRole
    from services.jwt_service import create_refresh_token

    token, _ = create_refresh_token(uuid.uuid4(), UserRole.user)
    header = pyjwt.get_unverified_header(token)
    assert header["alg"] == "ES256"


def test_token_verifiable_with_public_key():
    """Tokens can be decoded using only the ES256 public key (no shared secret)."""
    import jwt as pyjwt

    from models.user import UserRole
    from services.crypto import get_key_manager
    from services.jwt_service import create_access_token, decode_access_token

    token, _ = create_access_token(uuid.uuid4(), UserRole.user)

    # decode_access_token uses the asymmetric key internally
    payload = decode_access_token(token)
    assert payload["type"] == "access"

    # Also verify directly with the raw public key
    pub_key = get_key_manager().get_public_key()
    decoded = pyjwt.decode(token, pub_key, algorithms=["ES256"])
    assert decoded["role"] == "user"


def test_hs256_token_rejected():
    """Tokens signed with HS256 (old format) are rejected."""
    import jwt as pyjwt

    from config import settings
    from services.jwt_service import decode_access_token

    old_token = pyjwt.encode(
        {"sub": str(uuid.uuid4()), "type": "access", "role": "user", "jti": "x", "groups": []},
        settings.SECRET_KEY,
        algorithm="HS256",
    )
    with pytest.raises(pyjwt.InvalidTokenError):
        decode_access_token(old_token)


def test_jwks_alg_matches_issued_tokens():
    """JWKS advertises ES256, matching what tokens are actually signed with."""
    from services.crypto import get_key_manager

    jwks = get_key_manager().get_jwks()
    assert len(jwks["keys"]) > 0
    for key in jwks["keys"]:
        assert key["alg"] == "ES256"
        assert key["kty"] == "EC"


# ── SEC-001: user-level revocation ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_revoked_user_key_blocks_authentication():
    """revoked_user:{user_id} in Redis causes authentication to return None."""
    from api.deps import _authenticate_via_jwt
    from models.user import UserRole
    from services.jwt_service import create_access_token

    user_id = uuid.uuid4()
    token, _ = create_access_token(user_id, UserRole.user)

    mock_redis = AsyncMock()
    # JTI check passes, but user-level revocation fires
    mock_redis.get = AsyncMock(side_effect=lambda key: "1" if "revoked_user" in key else None)

    mock_db = AsyncMock()

    with patch("api.deps.get_redis", return_value=mock_redis):
        result = await _authenticate_via_jwt(token, mock_db)

    assert result is None


@pytest.mark.asyncio
async def test_jti_revocation_still_blocks():
    """revoked_jti:{jti} still blocks authentication (existing behavior preserved)."""
    from api.deps import _authenticate_via_jwt
    from models.user import UserRole
    from services.jwt_service import create_access_token

    user_id = uuid.uuid4()
    token, _ = create_access_token(user_id, UserRole.user)

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(side_effect=lambda key: "1" if "revoked_jti" in key else None)

    mock_db = AsyncMock()

    with patch("api.deps.get_redis", return_value=mock_redis):
        result = await _authenticate_via_jwt(token, mock_db)

    assert result is None


# ── SEC-002: Redis fail-closed ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_redis_down_blocks_authentication():
    """When Redis is unreachable, authentication raises rather than failing open."""
    from redis.exceptions import ConnectionError as RedisConnectionError

    from api.deps import _authenticate_via_jwt
    from models.user import UserRole
    from services.jwt_service import create_access_token

    user_id = uuid.uuid4()
    token, _ = create_access_token(user_id, UserRole.user)

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(side_effect=RedisConnectionError("down"))

    mock_db = AsyncMock()

    from redis.exceptions import RedisError

    with patch("api.deps.get_redis", return_value=mock_redis), pytest.raises(RedisError):
        await _authenticate_via_jwt(token, mock_db)


def test_rate_limiter_swallow_errors_is_false():
    """Rate limiter is configured to fail closed (swallow_errors=False)."""
    from api.ratelimit import limiter

    assert limiter._swallow_errors is False
