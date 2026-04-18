import json
import logging
import secrets

import jwt as pyjwt
from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user, get_db, require_local_mode
from api.ratelimit import limiter
from config import settings
from models.user import User, UserRole
from schemas.auth import (
    CodeExchangeRequest,
    InitRequest,
    InitResponse,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    RevokeRequest,
    TokenRequest,
    TokenResponse,
    UsernameUpdateRequest,
    UserResponse,
)
from services.jwt_service import create_access_token, create_refresh_token, decode_refresh_token
from services.redis import get_redis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# Configure OAuth client
oauth = OAuth()
if settings.OAUTH_CLIENT_ID and settings.OAUTH_CLIENT_SECRET and settings.OAUTH_SERVER_METADATA_URL:
    oauth.register(
        name="oidc",
        client_id=settings.OAUTH_CLIENT_ID,
        client_secret=settings.OAUTH_CLIENT_SECRET,
        server_metadata_url=settings.OAUTH_SERVER_METADATA_URL,
        client_kwargs={
            "scope": "openid email profile",
        },
    )


async def _issue_tokens(user: User) -> tuple[str, str, int]:
    """Issue JWT access + refresh tokens for a user, storing refresh JTI in Redis.

    Returns (access_token, refresh_token, expires_in).
    """
    access_token, expires_in = create_access_token(user.id, user.role)
    refresh_token, jti = create_refresh_token(user.id, user.role)

    redis = get_redis()
    refresh_ttl = settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 86400
    await redis.setex(f"refresh_jti:{jti}", refresh_ttl, str(user.id))

    return access_token, refresh_token, expires_in


@router.post("/init", response_model=InitResponse)
async def init_admin(req: InitRequest, db: AsyncSession = Depends(get_db)):
    count = await db.scalar(select(func.count()).select_from(User))
    if count and count > 0:
        raise HTTPException(status_code=400, detail="System already initialized")

    user = User(
        email=req.email,
        username=req.username,
        name=req.name,
        role=UserRole.admin,
    )
    if req.password:
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
    client_host = request.client.host if request.client else None
    if client_host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(status_code=403, detail="Bootstrap is only available from localhost")

    count = await db.scalar(select(func.count()).select_from(User))
    if count and count > 0:
        raise HTTPException(status_code=400, detail="System already initialized")

    user = User(
        email="admin@localhost",
        name="admin",
        role=UserRole.admin,
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


@router.post("/register", response_model=InitResponse, dependencies=[Depends(require_local_mode)])
@limiter.limit("3/minute")
async def register(request: Request, req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Create a new account with email + password."""
    existing = await db.execute(select(User).where(User.email == req.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        email=req.email,
        username=req.username,
        name=req.name,
        role=UserRole.user,
    )
    user.set_password(req.password)
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Email or username already registered")
    await db.refresh(user)

    access_token, refresh_token, expires_in = await _issue_tokens(user)
    return InitResponse(
        user=UserResponse.model_validate(user),
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
    )


@router.post("/login", response_model=InitResponse)
@limiter.limit("5/minute")
async def login(request: Request, req: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Login with email + password. Returns user info and JWT tokens."""
    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()
    if not user or not user.verify_password(req.password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    access_token, refresh_token, expires_in = await _issue_tokens(user)
    return InitResponse(
        user=UserResponse.model_validate(user),
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
    )


@router.get("/oauth/login")
async def oauth_login(request: Request):
    """Initiates the OAuth SSO flow"""
    if not oauth.oidc:
        raise HTTPException(status_code=500, detail="OAuth is not configured on the server")

    # Use FRONTEND_URL as the base so the redirect works through the Next.js proxy.
    # This avoids Docker-internal hostnames (e.g. observal-api:8000) leaking into
    # the redirect URI, which would fail Azure AD's redirect URI validation.
    redirect_uri = settings.FRONTEND_URL.rstrip("/") + "/api/v1/auth/oauth/callback"
    return await oauth.oidc.authorize_redirect(request, redirect_uri)


@router.get("/oauth/callback")
async def oauth_callback(request: Request, db: AsyncSession = Depends(get_db)):
    """Handles the OAuth SSO callback, authenticates, and redirects to frontend with credentials"""
    if not oauth.oidc:
        raise HTTPException(status_code=500, detail="OAuth is not configured on the server")

    try:
        token = await oauth.oidc.authorize_access_token(request)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"OAuth authorization failed: {e}")

    userinfo = token.get("userinfo")
    if not userinfo:
        raise HTTPException(status_code=400, detail="Missing userinfo in token")

    email = userinfo.get("email")
    name = userinfo.get("name") or userinfo.get("preferred_username") or "SSO User"

    if not email:
        raise HTTPException(status_code=400, detail="Email claim is missing from ID token")

    email = email.strip().lower()

    # Check if user exists
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user:
        # Auto-create new user via SSO
        user = User(
            email=email,
            name=name,
            role=UserRole.user,
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

    # Issue JWT tokens for the OAuth login
    access_token, refresh_token, expires_in = await _issue_tokens(user)
    await db.commit()

    # Generate a short-lived opaque code instead of exposing tokens in the URL.
    # The frontend will exchange this code for credentials via a POST request.
    code = secrets.token_urlsafe(32)
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

    frontend_redirect = f"{settings.FRONTEND_URL}/login?code={code}"
    return RedirectResponse(url=frontend_redirect)


@router.post("/exchange", response_model=InitResponse)
async def exchange_code(req: CodeExchangeRequest, db: AsyncSession = Depends(get_db)):
    """Exchange a one-time OAuth auth code for JWT credentials.

    The code is stored in Redis with a 30-second TTL and is deleted after
    a single successful use, preventing replay attacks.
    """
    redis = get_redis()
    redis_key = f"oauth_code:{req.code}"
    data = await redis.get(redis_key)

    if not data:
        raise HTTPException(status_code=400, detail="Invalid or expired code")

    # Delete immediately to enforce single-use
    await redis.delete(redis_key)

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
    return UserResponse.model_validate(current_user)


# ── JWT Token Endpoints ────────────────────────────────────


@router.post("/token", response_model=TokenResponse)
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def issue_token(request: Request, req: TokenRequest, db: AsyncSession = Depends(get_db)):
    """Exchange email+password for JWT access + refresh tokens."""
    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()
    if not user or not user.verify_password(req.password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    access_token, refresh_token, expires_in = await _issue_tokens(user)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
    )


@router.post("/token/refresh", response_model=TokenResponse)
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def refresh_token(request: Request, req: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """Exchange a valid refresh token for a new access token (and rotated refresh token)."""
    try:
        payload = decode_refresh_token(req.refresh_token)
    except pyjwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid refresh token: {exc}")

    jti = payload.get("jti")
    user_id = payload.get("sub")
    if not jti or not user_id:
        raise HTTPException(status_code=401, detail="Invalid refresh token claims")

    # Check that the JTI has not been revoked
    redis = get_redis()
    stored = await redis.get(f"refresh_jti:{jti}")
    if stored is None:
        raise HTTPException(status_code=401, detail="Refresh token has been revoked or expired")

    # Revoke the old refresh token (one-time use / rotation)
    await redis.delete(f"refresh_jti:{jti}")

    # Look up the user to ensure they still exist
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User no longer exists")

    # Issue new token pair
    access_token, expires_in = create_access_token(user.id, user.role)
    new_refresh_token, new_jti = create_refresh_token(user.id, user.role)

    refresh_ttl = settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 86400
    await redis.setex(f"refresh_jti:{new_jti}", refresh_ttl, str(user.id))

    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        expires_in=expires_in,
    )


@router.post("/token/revoke")
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def revoke_token(request: Request, req: RevokeRequest):
    """Revoke a refresh token so it can no longer be used."""
    try:
        payload = decode_refresh_token(req.refresh_token)
    except pyjwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid refresh token: {exc}")

    jti = payload.get("jti")
    if not jti:
        raise HTTPException(status_code=401, detail="Invalid refresh token claims")

    redis = get_redis()
    await redis.delete(f"refresh_jti:{jti}")

    return {"detail": "Token revoked"}


@router.put("/profile/username", response_model=UserResponse)
async def set_username(
    req: UsernameUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Set or update the current user's username."""
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
    token, expires_in = create_access_token(
        current_user.id,
        current_user.role,
        expires_in_minutes=settings.JWT_HOOKS_TOKEN_EXPIRE_MINUTES,
    )
    return {"access_token": token, "expires_in": expires_in}
