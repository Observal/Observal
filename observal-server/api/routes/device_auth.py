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
import secrets
import time
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from loguru import logger as optic
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user, get_db
from api.ratelimit import limiter
from api.routes.auth import _issue_tokens
from models.user import User
from schemas.auth import (
    DeviceAuthRequest,
    DeviceAuthResponse,
    DeviceConfirmRequest,
    DeviceTokenRequest,
)
from services.redis import get_redis

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


def _is_localhost_url(url: str) -> bool:
    """Return True if url points to a localhost address (i.e. not explicitly configured)."""
    parsed = urlparse(url)
    return parsed.hostname in ("localhost", "127.0.0.1", "::1") if parsed.hostname else True


def _resolve_frontend_url(request: Request) -> str:
    """Derive the frontend base URL for verification links.

    Resolution order:
      1. deployment.frontend_url (if explicitly set to a non-localhost value)
      2. deployment.public_url hostname (scheme + host, no port/path)
      3. Request headers (x-forwarded-proto/host, or Host)
      4. Fallback to http://localhost (local dev only)
    """
    import services.dynamic_settings as ds

    # 1. Explicitly configured frontend URL
    configured = ds.get_sync("deployment.frontend_url")
    if configured and not _is_localhost_url(configured):
        return configured.rstrip("/")

    # 2. Derive from public_url if set
    public_url = ds.get_sync("deployment.public_url")
    if public_url and not _is_localhost_url(public_url):
        parsed = urlparse(public_url)
        scheme = parsed.scheme or "https"
        host = parsed.hostname or "localhost"
        # Include non-standard ports
        port_suffix = ""
        if parsed.port and parsed.port not in (80, 443):
            port_suffix = f":{parsed.port}"
        return f"{scheme}://{host}{port_suffix}"

    # 3. Infer from request headers (works behind any reverse proxy)
    forwarded_proto = request.headers.get("x-forwarded-proto")
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if host:
        # Strip port from host header if present (will re-add if needed)
        clean_host = host.split(",")[0].strip()  # first value if comma-separated
        # Infer scheme from port suffix only when no forwarded-proto is available
        if ":" in clean_host:
            host_part, port_str = clean_host.rsplit(":", 1)
            inferred_scheme = {"443": "https", "80": "http"}.get(port_str, "http")
            # Remove standard ports for clean URLs
            if port_str in ("80", "443"):
                clean_host = host_part
        else:
            inferred_scheme = "http"
        scheme = forwarded_proto or inferred_scheme
        if not _is_localhost_url(f"{scheme}://{clean_host}"):
            return f"{scheme}://{clean_host}"

    # 4. Local dev fallback
    return "http://localhost"


@router.post("/authorize", response_model=DeviceAuthResponse)
@limiter.limit("5/minute")
async def device_authorize(request: Request, req: DeviceAuthRequest = None):
    """Create a device authorization request. Returns device_code + user_code."""
    optic.debug("initiating device auth flow")
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
        optic.error("Redis unavailable during device authorize: {}", e)
        raise HTTPException(status_code=503, detail="Service temporarily unavailable")

    frontend_url = _resolve_frontend_url(request)

    optic.info("device_authorize: code issued, user_code={}", user_code)
    sso_param = "&sso=1" if req and req.sso else ""
    return DeviceAuthResponse(
        device_code=device_code,
        user_code=user_code,
        verification_uri=f"{frontend_url}/device",
        verification_uri_complete=f"{frontend_url}/device?code={user_code}{sso_param}",
        expires_in=_DEVICE_AUTH_TTL,
        interval=5,
    )


@router.post("/token")
@limiter.limit("30/minute")
async def device_token(request: Request, req: DeviceTokenRequest, db: AsyncSession = Depends(get_db)):
    """CLI polls this to check if the user approved the device code."""
    optic.debug("polling for device_code approval")
    if req.grant_type != _DEVICE_GRANT_TYPE:
        return JSONResponse(status_code=400, content={"error": "invalid_grant_type"})

    try:
        redis = get_redis()
        raw = await redis.get(f"device_auth:{req.device_code}")
    except RedisError as e:
        optic.error("Redis unavailable during device token poll: {}", e)
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

        optic.info("device_token: tokens issued for user={}", user.email)
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
    optic.trace("user={} confirming code", current_user.email)
    normalized_code = _normalize_user_code(req.user_code)

    try:
        redis = get_redis()
        device_code = await redis.get(f"device_code_by_user:{normalized_code}")
    except RedisError as e:
        optic.error("Redis unavailable during device confirm: {}", e)
        raise HTTPException(status_code=503, detail="Service temporarily unavailable")

    if not device_code:
        raise HTTPException(status_code=404, detail="Invalid or expired device code")

    try:
        raw = await redis.get(f"device_auth:{device_code}")
    except RedisError as e:
        optic.error("Redis unavailable during device confirm lookup: {}", e)
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
        optic.error("Redis unavailable during device confirm update: {}", e)
        raise HTTPException(status_code=503, detail="Service temporarily unavailable")

    optic.info("device_confirm: device authorized for user={}", current_user.email)
    return {"message": "Device authorized"}
