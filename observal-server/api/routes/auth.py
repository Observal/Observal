# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-FileCopyrightText: 2026 Subramania Raja <dhanpraja231@gmail.com>
# SPDX-FileCopyrightText: 2026 Harishankar <harishankar0301@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

import base64
import json
import re
import secrets
from datetime import UTC, datetime
from urllib.parse import quote

import jwt as pyjwt
from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from loguru import logger as optic
from redis.exceptions import RedisError
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import services.dynamic_settings as ds
from api.deps import get_current_user, get_db, get_or_create_default_org, require_local_mode, require_password_auth
from api.ratelimit import limiter
from config import settings
from models.user import User, UserRole
from schemas.auth import (
    ChangePasswordRequest,
    CodeExchangeRequest,
    InitRequest,
    InitResponse,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RevokeRequest,
    TokenRequest,
    TokenResponse,
    UsernameUpdateRequest,
    UserResponse,
)
from services.jwt_service import create_access_token, create_refresh_token, decode_access_token, decode_refresh_token
from services.redis import get_redis
from services.security_events import (
    EventType,
    SecurityEvent,
    Severity,
    _extract_request_info,
    emit_security_event,
)
from services.username_generator import generate_unique_username

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_COMMON_WEAK_PASSWORDS = frozenset(
    {
        # Passwords that fail the complexity rules anyway (kept for clarity)
        "password",
        "password1",
        "password123",
        "12345678",
        "123456789",
        "qwerty123",
        "iloveyou",
        "letmein123",
        "welcome1",
        "monkey123",
        # Passwords that pass all four complexity rules but are still common
        "P@ssw0rd!123",
        "Admin@1234!!",
        "Welcome@123!",
        "Password@1!2",
        "Qwerty@123!!",
        "Letmein@123!",
        "Passw0rd@123",
        "P@$$w0rd1234",
    }
)


def _validate_password_strength(password: str) -> None:
    optic.debug("_validate_password_strength called")
    if len(password) < 12:
        raise HTTPException(status_code=422, detail="Password must be at least 12 characters")
    if not re.search(r"[A-Z]", password):
        raise HTTPException(status_code=422, detail="Password must contain at least one uppercase letter")
    if not re.search(r"[0-9]", password):
        raise HTTPException(status_code=422, detail="Password must contain at least one digit")
    if not re.search(r"[^A-Za-z0-9]", password):
        raise HTTPException(status_code=422, detail="Password must contain at least one special character")
    if password.lower() in _COMMON_WEAK_PASSWORDS:
        raise HTTPException(status_code=422, detail="Password is too common")


# Configure OAuth client
oauth = OAuth()
if settings.OAUTH_CLIENT_ID and settings.OAUTH_CLIENT_SECRET and settings.OAUTH_SERVER_METADATA_URL:
    oauth.register(
        name="oidc",
        client_id=settings.OAUTH_CLIENT_ID,
        client_secret=settings.OAUTH_CLIENT_SECRET,
        server_metadata_url=settings.OAUTH_SERVER_METADATA_URL,
        client_kwargs={
            "scope": "openid email profile groups",
        },
    )


async def _issue_tokens(user: User, groups: list[str] | None = None) -> tuple[str, str, int]:
    """Issue JWT access + refresh tokens for a user, storing refresh JTI in Redis.

    Returns (access_token, refresh_token, expires_in).
    Fails open: tokens are still returned if Redis is temporarily unreachable.
    """
    optic.trace("user_id={}, groups={}", user.id, groups)
    access_token, expires_in = create_access_token(user.id, user.role, groups=groups)
    refresh_token, jti = create_refresh_token(user.id, user.role, groups=groups)

    try:
        redis = get_redis()
        refresh_ttl = ds.get_sync_int("jwt.refresh_token_expire_days", 30) * 86400
        await redis.setex(f"refresh_jti:{jti}", refresh_ttl, str(user.id))
        # Clear any logout revocation so hooks resume after re-login
        await redis.delete(f"revoked_user:{user.id}")
    except RedisError as e:
        optic.warning("Redis unavailable when storing refresh JTI: {}", e)
        raise HTTPException(status_code=503, detail="Auth service temporarily unavailable")

    return access_token, refresh_token, expires_in


@router.post("/init", response_model=InitResponse, dependencies=[Depends(require_password_auth)])
async def init_admin(req: InitRequest, db: AsyncSession = Depends(get_db)):
    optic.trace("email={}", req.email)
    count = await db.scalar(select(func.count()).select_from(User))
    if count and count > 0:
        raise HTTPException(status_code=400, detail="System already initialized")

    default_org = await get_or_create_default_org(db)
    username = req.username or await generate_unique_username(req.email, db)
    user = User(
        email=req.email,
        username=username,
        name=req.name,
        role=UserRole.admin,
        org_id=default_org.id,
    )
    if req.password:
        _validate_password_strength(req.password)
        user.set_password(req.password)
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="System already initialized or email/username already exists")
    await db.refresh(user)

    access_token, refresh_token, expires_in = await _issue_tokens(user)
    return InitResponse(
        user=UserResponse.model_validate(user),
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
    )


@router.post("/bootstrap", response_model=InitResponse, dependencies=[Depends(require_local_mode)])
@limiter.limit("1/minute")
async def bootstrap(request: Request, db: AsyncSession = Depends(get_db)):
    """Auto-create admin account on a fresh server. No input needed."""
    optic.debug("bootstrap called")
    client_host = request.client.host if request.client else None
    if client_host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(status_code=403, detail="Bootstrap is only available from localhost")

    count = await db.scalar(select(func.count()).select_from(User))
    if count and count > 0:
        raise HTTPException(status_code=400, detail="System already initialized")

    default_org = await get_or_create_default_org(db)
    user = User(
        email="admin@localhost",
        username=await generate_unique_username("admin@localhost", db),
        name="admin",
        role=UserRole.admin,
        org_id=default_org.id,
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="System already initialized")
    await db.refresh(user)

    access_token, refresh_token, expires_in = await _issue_tokens(user)
    return InitResponse(
        user=UserResponse.model_validate(user),
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
    )


@router.post("/login", response_model=InitResponse, dependencies=[Depends(require_password_auth)])
@limiter.limit("5/minute")
async def login(request: Request, req: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Login with email/username + password. Returns user info and JWT tokens."""
    optic.debug("auth login attempt")
    source_ip, user_agent = _extract_request_info(request)
    identifier = req.email
    if "@" in identifier:
        stmt = select(User).where(User.email == identifier)
    else:
        stmt = select(User).where(or_(User.username == identifier, User.email == identifier))
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user or not user.verify_password(req.password):
        await emit_security_event(
            SecurityEvent(
                event_type=EventType.LOGIN_FAILURE,
                severity=Severity.WARNING,
                outcome="failure",
                actor_email=identifier,
                source_ip=source_ip,
                user_agent=user_agent,
                detail="Invalid credentials",
            )
        )
        raise HTTPException(status_code=401, detail="Invalid email or password")

    access_token, refresh_token, expires_in = await _issue_tokens(user)
    await emit_security_event(
        SecurityEvent(
            event_type=EventType.LOGIN_SUCCESS,
            severity=Severity.INFO,
            outcome="success",
            actor_id=str(user.id),
            actor_email=user.email,
            actor_role=user.role.value,
            source_ip=source_ip,
            user_agent=user_agent,
        )
    )

    must_change = False
    try:
        redis = get_redis()
        must_change = bool(await redis.get(f"must_change_password:{user.id}"))
    except RedisError:
        pass

    return {
        **InitResponse(
            user=UserResponse.model_validate(user),
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
        ).model_dump(),
        "must_change_password": must_change,
    }


@router.get("/oauth/login")
async def oauth_login(request: Request, next: str | None = None):
    """Initiates the OAuth SSO flow"""
    optic.debug("oauth_login called")
    if not oauth.oidc:
        raise HTTPException(status_code=500, detail="OAuth is not configured on the server")

    # Preserve the post-login redirect target (e.g. /device?code=XXXX) across the
    # OAuth round-trip so the user lands on the correct page after SSO completes.
    if next and next.startswith("/") and not next.startswith("//") and "\\" not in next:
        request.session["oauth_next"] = next

    # Use FRONTEND_URL as the base so the redirect works through the Next.js proxy.
    # This avoids Docker-internal hostnames (e.g. observal-api:8000) leaking into
    # the redirect URI, which would fail Azure AD's redirect URI validation.
    redirect_uri = (
        ds.get_sync("deployment.frontend_url", "http://localhost:3000").rstrip("/") + "/api/v1/auth/oauth/callback"
    )
    return await oauth.oidc.authorize_redirect(request, redirect_uri)


@router.get("/oauth/callback")
async def oauth_callback(request: Request, db: AsyncSession = Depends(get_db)):
    """Handles the OAuth SSO callback, authenticates, and redirects to frontend with credentials"""
    optic.debug("oauth_callback called")
    if not oauth.oidc:
        raise HTTPException(status_code=500, detail="OAuth is not configured on the server")

    source_ip, user_agent = _extract_request_info(request)
    try:
        token = await oauth.oidc.authorize_access_token(request)
    except Exception as e:
        await emit_security_event(
            SecurityEvent(
                event_type=EventType.SSO_FAILURE,
                severity=Severity.WARNING,
                outcome="failure",
                source_ip=source_ip,
                user_agent=user_agent,
                detail=f"OAuth authorization failed: {e}",
            )
        )
        raise HTTPException(status_code=400, detail=f"OAuth authorization failed: {e}")

    userinfo = token.get("userinfo")
    if not userinfo:
        raise HTTPException(status_code=400, detail="Missing userinfo in token")

    email = userinfo.get("email")
    name = userinfo.get("name") or userinfo.get("preferred_username") or "SSO User"
    groups = userinfo.get("groups", [])

    if not email:
        raise HTTPException(status_code=400, detail="Email claim is missing from ID token")

    email = email.strip().lower()

    # Check if user exists
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user:
        # Auto-create new user via SSO
        default_org = await get_or_create_default_org(db)
        user = User(
            email=email,
            username=await generate_unique_username(email, db),
            name=name,
            role=UserRole.user,
            org_id=default_org.id,
        )
        db.add(user)

        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            # Race condition: user was created between our check and commit
            result = await db.execute(select(User).where(User.email == email))
            user = result.scalar_one_or_none()
            if not user:
                raise HTTPException(status_code=500, detail="Failed to create or find user")

    # Persist SSO groups for exec dashboard department mapping
    if groups:
        try:
            from sqlalchemy import delete as sa_delete

            from models.user_group import UserGroup

            await db.execute(sa_delete(UserGroup).where(UserGroup.user_id == user.id))
            db.add_all([UserGroup(user_id=user.id, group_name=g) for g in groups])
        except Exception as e:
            optic.warning("Failed to persist SSO groups: {}", e)

    # Issue JWT tokens for the OAuth login
    access_token, refresh_token, expires_in = await _issue_tokens(user, groups=groups)
    await db.commit()

    # Generate a short-lived opaque code instead of exposing tokens in the URL.
    # The frontend will exchange this code for credentials via a POST request.
    code = secrets.token_urlsafe(32)
    try:
        redis = get_redis()
        await redis.setex(
            f"oauth_code:{code}",
            30,
            json.dumps(
                {
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "expires_in": expires_in,
                    "user_id": str(user.id),
                    "role": user.role.value,
                }
            ),
        )
    except RedisError as e:
        optic.warning("Redis unavailable during OAuth callback: {}", e)
        raise HTTPException(status_code=503, detail="Service temporarily unavailable")

    await emit_security_event(
        SecurityEvent(
            event_type=EventType.SSO_SUCCESS,
            severity=Severity.INFO,
            outcome="success",
            actor_id=str(user.id),
            actor_email=email,
            actor_role=user.role.value,
            source_ip=source_ip,
            user_agent=user_agent,
        )
    )
    # Restore the post-login redirect target that was saved before the OAuth round-trip.
    oauth_next = request.session.pop("oauth_next", None)
    frontend_base = ds.get_sync("deployment.frontend_url", "http://localhost:3000")
    frontend_redirect = f"{frontend_base}/login?code={code}"
    if oauth_next and oauth_next.startswith("/") and not oauth_next.startswith("//") and "\\" not in oauth_next:
        frontend_redirect += f"&next={quote(oauth_next, safe='')}"
    return RedirectResponse(url=frontend_redirect)


@router.post("/exchange", response_model=InitResponse)
async def exchange_code(req: CodeExchangeRequest, db: AsyncSession = Depends(get_db)):
    """Exchange a one-time OAuth auth code for JWT credentials.

    The code is stored in Redis with a 30-second TTL and is deleted after
    a single successful use, preventing replay attacks.
    """
    optic.debug("exchange_code called")
    try:
        redis = get_redis()
        redis_key = f"oauth_code:{req.code}"
        data = await redis.getdel(redis_key)
    except RedisError as e:
        optic.warning("Redis unavailable during code exchange: {}", e)
        raise HTTPException(status_code=503, detail="Service temporarily unavailable")

    if not data:
        raise HTTPException(status_code=400, detail="Invalid or expired code")

    try:
        payload = json.loads(data)
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid or expired code")

    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    expires_in = payload.get("expires_in")
    user_id = payload.get("user_id")

    if not access_token or not user_id:
        raise HTTPException(status_code=400, detail="Invalid or expired code")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired code")
    return InitResponse(
        user=UserResponse.model_validate(user),
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
    )


@router.get("/whoami", response_model=UserResponse)
async def whoami(current_user: User = Depends(get_current_user)):
    optic.debug("auth whoami")
    return UserResponse.model_validate(current_user)


@router.post("/logout")
async def logout(
    request: Request,
    req: LogoutRequest,
    current_user: User = Depends(get_current_user),
):
    """Revoke the current access token and optionally a refresh token.

    Blacklists the access token JTI in Redis so it can no longer be used,
    and marks the user_id as revoked so hook scripts stop sending telemetry.
    """
    # Extract the raw token from the Authorization header so we can get jti/exp
    optic.debug("auth logout")
    auth_header = request.headers.get("authorization", "")
    token = auth_header.removeprefix("Bearer ").strip() if auth_header.startswith("Bearer ") else ""

    try:
        payload = decode_access_token(token)
        jti = payload.get("jti")
        exp = payload.get("exp")
    except Exception:
        jti = None
        exp = None

    try:
        redis = get_redis()
        if jti and exp:
            now_ts = int(datetime.now(UTC).timestamp())
            ttl = max(exp - now_ts, 1)
            await redis.setex(f"revoked_jti:{jti}", ttl, "1")

        # Mark the user as revoked for 30 days (max hooks token lifetime)
        hooks_ttl = 30 * 86400
        await redis.setex(f"revoked_user:{current_user.id}", hooks_ttl, "1")
    except RedisError as e:
        optic.warning("Redis unavailable during logout: {}", e)
        raise HTTPException(status_code=503, detail="Service temporarily unavailable")

    # Optionally revoke the refresh token
    if req.refresh_token:
        try:
            refresh_payload = decode_refresh_token(req.refresh_token)
            refresh_jti = refresh_payload.get("jti")
            if refresh_jti:
                try:
                    await redis.delete(f"refresh_jti:{refresh_jti}")
                except RedisError:
                    pass
        except Exception:
            pass  # Best-effort

    source_ip, user_agent = _extract_request_info(request)
    await emit_security_event(
        SecurityEvent(
            event_type=EventType.LOGOUT,
            severity=Severity.INFO,
            outcome="success",
            actor_id=str(current_user.id),
            actor_email=current_user.email,
            actor_role=current_user.role.value,
            source_ip=source_ip,
            user_agent=user_agent,
        )
    )
    return {"detail": "Logged out"}


# ── JWT Token Endpoints ────────────────────────────────────


@router.post("/token", response_model=TokenResponse, dependencies=[Depends(require_password_auth)])
@limiter.limit(ds.get_sync("security.rate_limit_auth", "10/minute"))
async def issue_token(request: Request, req: TokenRequest, db: AsyncSession = Depends(get_db)):
    """Exchange email/username + password for JWT access + refresh tokens."""
    optic.trace("email={}", req.email)
    source_ip, user_agent = _extract_request_info(request)
    identifier = req.email
    if "@" in identifier:
        stmt = select(User).where(User.email == identifier)
    else:
        stmt = select(User).where(or_(User.username == identifier, User.email == identifier))
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user or not user.verify_password(req.password):
        await emit_security_event(
            SecurityEvent(
                event_type=EventType.LOGIN_FAILURE,
                severity=Severity.WARNING,
                outcome="failure",
                actor_email=identifier,
                source_ip=source_ip,
                user_agent=user_agent,
                detail="Invalid credentials (token endpoint)",
            )
        )
        raise HTTPException(status_code=401, detail="Invalid email or password")

    await emit_security_event(
        SecurityEvent(
            event_type=EventType.LOGIN_SUCCESS,
            severity=Severity.INFO,
            outcome="success",
            actor_id=str(user.id),
            actor_email=user.email,
            actor_role=user.role.value,
            source_ip=source_ip,
            user_agent=user_agent,
        )
    )
    access_token, refresh_token, expires_in = await _issue_tokens(user)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
    )


@router.post("/token/refresh", response_model=TokenResponse)
@limiter.limit(ds.get_sync("security.rate_limit_auth", "10/minute"))
async def refresh_token(request: Request, req: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """Exchange a valid refresh token for a new access token (and rotated refresh token)."""
    optic.debug("auth token refresh")
    try:
        payload = decode_refresh_token(req.refresh_token)
    except pyjwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid refresh token: {exc}")

    jti = payload.get("jti")
    user_id = payload.get("sub")
    if not jti or not user_id:
        raise HTTPException(status_code=401, detail="Invalid refresh token claims")

    # Check that the JTI has not been revoked
    try:
        redis = get_redis()
        stored = await redis.get(f"refresh_jti:{jti}")
    except RedisError as e:
        optic.warning("Redis unavailable during token refresh: {}", e)
        raise HTTPException(status_code=503, detail="Service temporarily unavailable")

    if stored is None:
        raise HTTPException(status_code=401, detail="Refresh token has been revoked or expired")

    # Revoke the old refresh token (one-time use / rotation)
    try:
        await redis.delete(f"refresh_jti:{jti}")
    except RedisError:
        pass

    # Look up the user to ensure they still exist
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User no longer exists")

    # Issue new token pair
    groups = payload.get("groups", [])
    access_token, expires_in = create_access_token(user.id, user.role, groups=groups)
    new_refresh_token, new_jti = create_refresh_token(user.id, user.role, groups=groups)

    try:
        refresh_ttl = ds.get_sync_int("jwt.refresh_token_expire_days", 30) * 86400
        await redis.setex(f"refresh_jti:{new_jti}", refresh_ttl, str(user.id))
    except RedisError as e:
        optic.warning("Redis unavailable when storing new refresh JTI: {}", e)
        raise HTTPException(status_code=503, detail="Auth service temporarily unavailable")
    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        expires_in=expires_in,
    )


@router.post("/token/revoke")
@limiter.limit(ds.get_sync("security.rate_limit_auth", "10/minute"))
async def revoke_token(request: Request, req: RevokeRequest):
    """Revoke a refresh token so it can no longer be used."""
    optic.debug("revoke_token called")
    try:
        payload = decode_refresh_token(req.refresh_token)
    except pyjwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid refresh token: {exc}")

    jti = payload.get("jti")
    if not jti:
        raise HTTPException(status_code=401, detail="Invalid refresh token claims")

    try:
        redis = get_redis()
        await redis.delete(f"refresh_jti:{jti}")
    except RedisError as e:
        optic.warning("Redis unavailable during token revocation: {}", e)
        raise HTTPException(status_code=503, detail="Service temporarily unavailable")

    return {"detail": "Token revoked"}


@router.put("/profile/password", dependencies=[Depends(require_password_auth)])
@limiter.limit("5/minute")
async def change_password(
    request: Request,
    req: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Change the current user's password. Clears forced-change flag if set."""
    optic.debug("user initiated password change")
    if not current_user.verify_password(req.current_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    _validate_password_strength(req.new_password)
    current_user.set_password(req.new_password)
    await db.commit()

    try:
        redis = get_redis()
        await redis.delete(f"must_change_password:{current_user.id}")
    except RedisError:
        pass
    return {"message": "Password changed"}


@router.put("/profile/username", response_model=UserResponse)
async def set_username(
    req: UsernameUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Set or update the current user's username."""
    optic.trace("req={}", req)
    existing = await db.execute(select(User).where(User.username == req.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Username already taken")

    current_user.username = req.username
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Username already taken")
    await db.refresh(current_user)
    return UserResponse.model_validate(current_user)


@router.post("/hooks-token")
async def create_hooks_token(current_user: User = Depends(get_current_user)):
    """Return a long-lived access token for OTEL telemetry hooks.

    Hooks need a static token in the environment that can't do refresh
    mid-session, so this endpoint issues a 30-day access token by default.
    """
    optic.trace("user_id={}", current_user.id)
    token, expires_in = create_access_token(
        current_user.id,
        current_user.role,
        expires_in_minutes=ds.get_sync_int("jwt.hooks_token_expire_minutes", 43200),
        groups=getattr(current_user, "_groups", []),
    )
    await emit_security_event(
        SecurityEvent(
            event_type=EventType.API_KEY_CREATED,
            severity=Severity.INFO,
            outcome="success",
            actor_id=str(current_user.id),
            actor_email=current_user.email,
            actor_role=current_user.role.value,
            detail="Hooks token created (30-day)",
        )
    )
    return {"access_token": token, "expires_in": expires_in}


# ── Avatar Upload ─────────────────────────────────────────────────

_MAX_AVATAR_BYTES = 2 * 1024 * 1024
# Data URL encoding adds ~33% overhead; 2MB binary → ~2.7MB encoded.
# Frontend also caps at 2MB before upload so these stay in sync.
_MAX_AVATAR_DATA_URL_LEN = int(2 * 1024 * 1024 * 1.4)
_AVATAR_ALLOWED_MIMES = {"image/png", "image/jpeg", "image/webp"}
_AVATAR_MAGIC_BYTES: dict[str, list[bytes]] = {
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/webp": [b"RIFF"],
}


def _validate_avatar_data_url(value: str) -> None:
    optic.trace("value={}", value)
    if len(value) > _MAX_AVATAR_DATA_URL_LEN:
        raise HTTPException(status_code=422, detail="Image data too large")

    match = re.match(r"^data:(image/[a-zA-Z0-9.+-]+);base64,(.+)$", value, re.DOTALL)
    if not match:
        raise HTTPException(status_code=422, detail="Avatar must be a base64 data URL")

    mime_type = match.group(1)
    b64_data = match.group(2)

    if mime_type not in _AVATAR_ALLOWED_MIMES:
        raise HTTPException(status_code=422, detail="Only PNG, JPEG, and WebP images are allowed")

    try:
        raw = base64.b64decode(b64_data)
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid base64 data")

    if len(raw) > _MAX_AVATAR_BYTES:
        raise HTTPException(status_code=422, detail="Image too large (max 2MB)")

    signatures = _AVATAR_MAGIC_BYTES.get(mime_type, [])
    if not any(raw.startswith(sig) for sig in signatures):
        raise HTTPException(status_code=422, detail="File content does not match declared type")
    if mime_type == "image/webp" and raw[8:12] != b"WEBP":
        raise HTTPException(status_code=422, detail="File content does not match declared type")


@router.put("/profile/avatar", response_model=UserResponse)
@limiter.limit("1/minute")
async def upload_avatar(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    optic.debug("upload_avatar called")
    body = await request.json()
    avatar_url = body.get("avatar_url")
    if not avatar_url or not isinstance(avatar_url, str):
        raise HTTPException(status_code=422, detail="avatar_url is required")

    _validate_avatar_data_url(avatar_url)

    current_user.avatar_url = avatar_url
    await db.commit()
    await db.refresh(current_user)
    return UserResponse.model_validate(current_user)


@router.delete("/profile/avatar", response_model=UserResponse)
async def delete_avatar(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    optic.debug("delete_avatar called")
    current_user.avatar_url = None
    await db.commit()
    await db.refresh(current_user)
    return UserResponse.model_validate(current_user)
