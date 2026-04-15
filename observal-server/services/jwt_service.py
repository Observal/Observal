"""JWT token generation and validation for unified browser/CLI auth."""

import uuid
from datetime import UTC, datetime, timedelta

import jwt

from config import settings
from models.user import UserRole

ALGORITHM = "HS256"


def create_access_token(user_id: uuid.UUID, role: UserRole, expires_in_minutes: int | None = None) -> tuple[str, int]:
    """Create a short-lived access token.

    Returns (encoded_token, expires_in_seconds).
    """
    now = datetime.now(UTC)
    expires_delta = timedelta(minutes=expires_in_minutes or settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    expires_in = int(expires_delta.total_seconds())
    payload = {
        "sub": str(user_id),
        "role": role.value,
        "type": "access",
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + expires_delta,
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)
    return token, expires_in


def create_refresh_token(user_id: uuid.UUID, role: UserRole) -> tuple[str, str]:
    """Create a long-lived refresh token.

    Returns (encoded_token, jti).
    The jti is returned separately so it can be stored for revocation.
    """
    now = datetime.now(UTC)
    jti = str(uuid.uuid4())
    payload = {
        "sub": str(user_id),
        "role": role.value,
        "type": "refresh",
        "jti": jti,
        "iat": now,
        "exp": now + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)
    return token, jti


def decode_token(token: str) -> dict:
    """Decode and validate a JWT token.

    Raises jwt.InvalidTokenError (or subclass) on failure.
    """
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])


def decode_access_token(token: str) -> dict:
    """Decode an access token and verify its type claim.

    Raises jwt.InvalidTokenError on failure or wrong token type.
    """
    payload = decode_token(token)
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("Token is not an access token")
    return payload


def decode_refresh_token(token: str) -> dict:
    """Decode a refresh token and verify its type claim.

    Raises jwt.InvalidTokenError on failure or wrong token type.
    """
    payload = decode_token(token)
    if payload.get("type") != "refresh":
        raise jwt.InvalidTokenError("Token is not a refresh token")
    return payload
