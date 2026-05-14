# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""JWT token generation and validation for unified browser/CLI auth.

Tokens are signed with ES256 (ECDSA P-256) via the asymmetric key manager
in services.crypto.  The corresponding public keys are published at
/.well-known/jwks.json so external consumers can verify tokens without
sharing a secret.
"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt

from config import settings
from models.user import UserRole

ALGORITHM = "ES256"


def create_access_token(
    user_id: uuid.UUID, role: UserRole, expires_in_minutes: int | None = None, groups: list[str] | None = None
) -> tuple[str, int]:
    """Create a short-lived ES256-signed access token.

    Returns (encoded_token, expires_in_seconds).
    """
    from services.crypto import sign_token

    now = datetime.now(UTC)
    expires_delta = timedelta(minutes=expires_in_minutes or settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    expires_in = int(expires_delta.total_seconds())
    payload = {
        "sub": str(user_id),
        "role": role.value,
        "type": "access",
        "groups": groups or [],
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + expires_delta,
    }
    token = sign_token(payload)
    return token, expires_in


def create_refresh_token(user_id: uuid.UUID, role: UserRole, groups: list[str] | None = None) -> tuple[str, str]:
    """Create a long-lived ES256-signed refresh token.

    Returns (encoded_token, jti).
    The jti is returned separately so it can be stored for revocation.
    """
    from services.crypto import sign_token

    now = datetime.now(UTC)
    jti = str(uuid.uuid4())
    payload = {
        "sub": str(user_id),
        "role": role.value,
        "type": "refresh",
        "groups": groups or [],
        "jti": jti,
        "iat": now,
        "exp": now + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
    }
    token = sign_token(payload)
    return token, jti


def decode_token(token: str) -> dict:
    """Decode and validate a JWT token using the published ES256 key set.

    Raises jwt.InvalidTokenError (or subclass) on failure.
    """
    from services.crypto import verify_token

    return verify_token(token)


def decode_access_token(token: str) -> dict:
    """Decode an access token and verify its type claim."""
    payload = decode_token(token)
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("Token is not an access token")
    return payload


def decode_refresh_token(token: str) -> dict:
    """Decode a refresh token and verify its type claim."""
    payload = decode_token(token)
    if payload.get("type") != "refresh":
        raise jwt.InvalidTokenError("Token is not a refresh token")
    return payload
