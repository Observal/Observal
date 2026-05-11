# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""OAuth 2.0 Device Authorization Grant (RFC 8628) endpoints.

Enables CLI authentication when SSO (SAML, OIDC) is the only login method.
The flow:
  1. CLI calls POST /device/authorize to get a device_code + user_code.
  2. User opens verification_uri in a browser, logs in, and enters the user_code.
  3. Browser calls POST /device/confirm to approve the device.
  4. CLI polls POST /device/token until it receives tokens.
"""

import json
import logging
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user, get_db
from api.ratelimit import limiter
from api.routes.auth import _issue_tokens
from config import settings
from models.user import User
from schemas.auth import (
    DeviceAuthRequest,
    DeviceAuthResponse,
    DeviceConfirmRequest,
    DeviceTokenRequest,
)
from services.audit_helpers import audit
from services.redis import get_redis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth/device", tags=["device-auth"])

# Characters excluding ambiguous ones: 0/O/1/I/L/A/E/U
_USER_CODE_ALPHABET = "BCDFGHJKMNPQRSTVWXZ23456789"

_DEVICE_AUTH_TTL = 600  # 10 minutes
_DEVICE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"


def _generate_user_code() -> str:
    """Generate an 8-character user code formatted as XXXX-XXXX."""
    chars = "".join(secrets.choice(_USER_CODE_ALPHABET) for _ in range(8))
    return f"{chars[:4]}-{chars[4:]}"


def _normalize_user_code(code: str) -> str:
    """Strip dashes and uppercase for case-insensitive matching."""
    return code.replace("-", "").upper()


def _resolve_frontend_url(request: Request) -> str:
    """Derive the frontend base URL from the request when FRONTEND_URL is not configured."""
    configured = settings.FRONTEND_URL
    if configured and configured != "http://localhost:3000":
        return configured.rstrip("/")
    # Only infer from headers when behind a TLS-terminating proxy (https)
    forwarded_proto = request.headers.get("x-forwarded-proto")
    if forwarded_proto == "https":
        host = request.headers.get("x-forwarded-host") or request.headers.get("host")
        if host:
            return f"https://{host}".rstrip("/")
    # Local dev: use the configured default (localhost:3000 = frontend dev server)
    return configured.rstrip("/")


@router.post("/authorize", response_model=DeviceAuthResponse)
@limiter.limit("5/minute")
async def device_authorize(request: Request, req: DeviceAuthRequest = None):
    """Create a device authorization request. Returns device_code + user_code."""
    device_code = secrets.token_urlsafe(48)
    user_code = _generate_user_code()
    normalized_code = _normalize_user_code(user_code)

    data = json.dumps(
        {
            "user_code": user_code,
            "status": "pending",
            "created_at": time.time(),
        }
    )

    try:
        redis = get_redis()
        pipe = redis.pipeline()
        pipe.setex(f"device_auth:{device_code}", _DEVICE_AUTH_TTL, data)
        pipe.setex(f"device_code_by_user:{normalized_code}", _DEVICE_AUTH_TTL, device_code)
        await pipe.execute()
    except RedisError as e:
        logger.error("Redis unavailable during device authorize: %s", e)
        raise HTTPException(status_code=503, detail="Service temporarily unavailable")

    frontend_url = _resolve_frontend_url(request)

    return DeviceAuthResponse(
        device_code=device_code,
        user_code=user_code,
        verification_uri=f"{frontend_url}/device",
        verification_uri_complete=f"{frontend_url}/device?code={user_code}",
        expires_in=_DEVICE_AUTH_TTL,
        interval=5,
    )


@router.post("/token")
@limiter.limit("10/minute")
async def device_token(request: Request, req: DeviceTokenRequest, db: AsyncSession = Depends(get_db)):
    """CLI polls this to check if the user approved the device code."""
    if req.grant_type != _DEVICE_GRANT_TYPE:
        return JSONResponse(status_code=400, content={"error": "invalid_grant_type"})

    try:
        redis = get_redis()
        raw = await redis.get(f"device_auth:{req.device_code}")
    except RedisError as e:
        logger.error("Redis unavailable during device token poll: %s", e)
        raise HTTPException(status_code=503, detail="Service temporarily unavailable")

    if not raw:
        return JSONResponse(status_code=400, content={"error": "expired_token"})

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return JSONResponse(status_code=400, content={"error": "expired_token"})

    status = data.get("status")

    if status == "pending":
        return JSONResponse(status_code=428, content={"error": "authorization_pending"})

    if status == "denied":
        try:
            await redis.delete(f"device_auth:{req.device_code}")
        except RedisError:
            pass
        return JSONResponse(status_code=400, content={"error": "access_denied"})

    if status == "approved":
        user_id = data.get("user_id")
        if not user_id:
            return JSONResponse(status_code=400, content={"error": "expired_token"})

        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            return JSONResponse(status_code=400, content={"error": "expired_token"})

        # Clean up Redis keys
        try:
            normalized_code = _normalize_user_code(data.get("user_code", ""))
            pipe = redis.pipeline()
            pipe.delete(f"device_auth:{req.device_code}")
            pipe.delete(f"device_code_by_user:{normalized_code}")
            await pipe.execute()
        except RedisError:
            pass

        access_token, refresh_token, expires_in = await _issue_tokens(user)

        return JSONResponse(
            status_code=200,
            content={
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_in": expires_in,
                "user": {
                    "id": str(user.id),
                    "email": user.email,
                    "name": user.name,
                    "role": user.role.value,
                },
            },
        )

    # Unknown status
    return JSONResponse(status_code=400, content={"error": "expired_token"})


@router.post("/confirm")
async def device_confirm(
    req: DeviceConfirmRequest,
    current_user: User = Depends(get_current_user),
):
    """Browser calls this after the user logs in and enters the code."""
    normalized_code = _normalize_user_code(req.user_code)

    try:
        redis = get_redis()
        device_code = await redis.get(f"device_code_by_user:{normalized_code}")
    except RedisError as e:
        logger.error("Redis unavailable during device confirm: %s", e)
        raise HTTPException(status_code=503, detail="Service temporarily unavailable")

    if not device_code:
        raise HTTPException(status_code=404, detail="Invalid or expired device code")

    try:
        raw = await redis.get(f"device_auth:{device_code}")
    except RedisError as e:
        logger.error("Redis unavailable during device confirm lookup: %s", e)
        raise HTTPException(status_code=503, detail="Service temporarily unavailable")

    if not raw:
        raise HTTPException(status_code=400, detail="Device code already used or expired")

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(status_code=400, detail="Device code already used or expired")

    if data.get("status") != "pending":
        raise HTTPException(status_code=400, detail="Device code already used or expired")

    # Update status to approved with the authenticated user's ID
    data["status"] = "approved"
    data["user_id"] = str(current_user.id)

    try:
        # Preserve existing TTL
        ttl = await redis.ttl(f"device_auth:{device_code}")
        if ttl and ttl > 0:
            await redis.setex(f"device_auth:{device_code}", ttl, json.dumps(data))
        else:
            await redis.setex(f"device_auth:{device_code}", _DEVICE_AUTH_TTL, json.dumps(data))
    except RedisError as e:
        logger.error("Redis unavailable during device confirm update: %s", e)
        raise HTTPException(status_code=503, detail="Service temporarily unavailable")

    await audit(
        current_user,
        "auth.device_confirm",
        resource_type="device_auth",
        resource_id=device_code,
        detail=f"Device code approved for user {current_user.email}",
    )

    return {"message": "Device authorized"}
