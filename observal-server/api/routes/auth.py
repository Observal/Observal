import hashlib
import json
import logging
import secrets
import string
from datetime import UTC, datetime, timedelta

import jwt as pyjwt
from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user, get_db, require_local_mode, require_role
from api.ratelimit import limiter
from config import settings
from models.invite import InviteCode
from models.user import User, UserRole
from schemas.auth import (
    CodeExchangeRequest,
    InitRequest,
    InitResponse,
    InviteCreateRequest,
    InviteListResponse,
    InviteRedeemRequest,
    InviteResponse,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    RequestResetRequest,
    ResetPasswordRequest,
    RevokeRequest,
    TokenRequest,
    TokenResponse,
    UserResponse,
)
from services.jwt_service import create_access_token, create_refresh_token, decode_refresh_token
from services.redis import get_redis

logger = logging.getLogger(__name__)

# In-memory store for password reset tokens: email -> (token_hash, expires_at)
_reset_tokens: dict[str, tuple[str, datetime]] = {}

RESET_TOKEN_TTL_MINUTES = 15

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


def _generate_api_key() -> tuple[str, str]:
    """Return (raw_key, sha256_hash)."""
    raw = secrets.token_hex(settings.API_KEY_LENGTH)
    return raw, hashlib.sha256(raw.encode()).hexdigest()


@router.post("/init", response_model=InitResponse)
async def init_admin(req: InitRequest, db: AsyncSession = Depends(get_db)):
    count = await db.scalar(select(func.count()).select_from(User))
    if count and count > 0:
        raise HTTPException(status_code=400, detail="System already initialized")

    api_key, key_hash = _generate_api_key()

    user = User(
        email=req.email,
        name=req.name,
        role=UserRole.admin,
        api_key_hash=key_hash,
    )
    if req.password:
        user.set_password(req.password)
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="System already initialized or email already exists")
    await db.refresh(user)

    return InitResponse(user=UserResponse.model_validate(user), api_key=api_key)


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

    api_key, key_hash = _generate_api_key()

    user = User(
        email="admin@localhost",
        name="admin",
        role=UserRole.admin,
        api_key_hash=key_hash,
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="System already initialized")
    await db.refresh(user)

    return InitResponse(user=UserResponse.model_validate(user), api_key=api_key)


@router.post("/register", response_model=InitResponse, dependencies=[Depends(require_local_mode)])
@limiter.limit("3/minute")
async def register(request: Request, req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Create a new account with email + password."""
    existing = await db.execute(select(User).where(User.email == req.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    api_key, key_hash = _generate_api_key()

    user = User(
        email=req.email,
        name=req.name,
        role=UserRole.user,
        api_key_hash=key_hash,
    )
    user.set_password(req.password)
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Email already registered")
    await db.refresh(user)

    return InitResponse(user=UserResponse.model_validate(user), api_key=api_key)


@router.post("/login", response_model=InitResponse)
@limiter.limit("5/minute")
async def login(request: Request, req: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Login with API key or email+password. Returns user info and API key."""
    if req.api_key:
        key_hash = hashlib.sha256(req.api_key.encode()).hexdigest()
        result = await db.execute(select(User).where(User.api_key_hash == key_hash))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=401, detail="Invalid API key")
        return InitResponse(user=UserResponse.model_validate(user), api_key=req.api_key)

    # Email + password login
    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()
    if not user or not user.verify_password(req.password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # Return the user's current API key (regenerate so they always have a fresh one)
    api_key, key_hash = _generate_api_key()
    user.api_key_hash = key_hash
    await db.commit()
    await db.refresh(user)

    return InitResponse(user=UserResponse.model_validate(user), api_key=api_key)


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

    # Handle Okta / Entry specific formatting
    if not email:
        raise HTTPException(status_code=400, detail="Email claim is missing from ID token")

    # Check if user exists
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    api_key, key_hash = _generate_api_key()

    if user:
        # Existing user, just update their API key
        user.api_key_hash = key_hash
    else:
        # Auto-create new user via SSO
        user = User(
            email=email,
            name=name,
            role=UserRole.user,
            api_key_hash=key_hash,
        )
        db.add(user)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        # Race condition: user was created between our check and commit
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=500, detail="Failed to create or find user")
        user.api_key_hash = key_hash
        await db.commit()
    await db.refresh(user)

    # Generate a short-lived opaque code instead of exposing the API key in the URL.
    # The frontend will exchange this code for credentials via a POST request.
    code = secrets.token_urlsafe(32)
    redis = get_redis()
    await redis.setex(
        f"oauth_code:{code}",
        30,
        json.dumps({"api_key": api_key, "user_id": str(user.id), "role": user.role.value}),
    )

    frontend_redirect = f"{settings.FRONTEND_URL}/login?code={code}"
    return RedirectResponse(url=frontend_redirect)


@router.post("/exchange", response_model=InitResponse)
async def exchange_code(req: CodeExchangeRequest, db: AsyncSession = Depends(get_db)):
    """Exchange a one-time OAuth auth code for API credentials.

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

    api_key = payload.get("api_key")
    user_id = payload.get("user_id")

    if not api_key or not user_id:
        raise HTTPException(status_code=400, detail="Invalid or expired code")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired code")

    return InitResponse(user=UserResponse.model_validate(user), api_key=api_key)


@router.get("/whoami", response_model=UserResponse)
async def whoami(current_user: User = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)


# ── JWT Token Endpoints ────────────────────────────────────


@router.post("/token", response_model=TokenResponse)
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def issue_token(request: Request, req: TokenRequest, db: AsyncSession = Depends(get_db)):
    """Exchange API key or email+password for JWT access + refresh tokens."""
    user: User | None = None

    if req.api_key:
        key_hash = hashlib.sha256(req.api_key.encode()).hexdigest()
        result = await db.execute(select(User).where(User.api_key_hash == key_hash))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=401, detail="Invalid API key")
    else:
        result = await db.execute(select(User).where(User.email == req.email))
        user = result.scalar_one_or_none()
        if not user or not user.verify_password(req.password):
            raise HTTPException(status_code=401, detail="Invalid email or password")

    access_token, expires_in = create_access_token(user.id, user.role)
    refresh_token, jti = create_refresh_token(user.id, user.role)

    # Store refresh token JTI in Redis so it can be revoked later.
    # TTL matches the refresh token's lifetime.
    redis = get_redis()
    refresh_ttl = settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 86400
    await redis.setex(f"refresh_jti:{jti}", refresh_ttl, str(user.id))

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


# ── Password Reset ──────────────────────────────────────────


def _generate_reset_token() -> str:
    """Generate a 6-character uppercase alphanumeric reset code."""
    return "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))


def _purge_expired_tokens() -> None:
    """Remove expired tokens from the in-memory store."""
    now = datetime.now(UTC)
    expired = [email for email, (_, exp) in _reset_tokens.items() if exp < now]
    for email in expired:
        del _reset_tokens[email]


@router.post("/request-reset")
@limiter.limit("3/minute")
async def request_password_reset(request: Request, req: RequestResetRequest, db: AsyncSession = Depends(get_db)):
    """Request a password reset code. The code is logged to the server console.

    Since Observal is self-hosted, the admin has access to server logs.
    Always returns 200 to avoid leaking whether the email exists.
    """
    _purge_expired_tokens()

    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()

    if user:
        token = _generate_reset_token()
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        expires = datetime.now(UTC) + timedelta(minutes=RESET_TOKEN_TTL_MINUTES)
        _reset_tokens[req.email] = (token_hash, expires)

        logger.warning(
            "PASSWORD RESET CODE for %s: %s (expires in %d minutes)",
            req.email,
            token,
            RESET_TOKEN_TTL_MINUTES,
        )

    return {"message": "If the account exists, a reset code has been logged to the server console."}


@router.post("/reset-password", response_model=InitResponse)
@limiter.limit("5/minute")
async def reset_password(request: Request, req: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    """Reset password using a code from the server logs. Returns new API key."""
    _purge_expired_tokens()

    stored = _reset_tokens.get(req.email)
    if not stored:
        raise HTTPException(status_code=400, detail="Invalid or expired reset code")

    token_hash, expires = stored
    if datetime.now(UTC) > expires:
        del _reset_tokens[req.email]
        raise HTTPException(status_code=400, detail="Invalid or expired reset code")

    if hashlib.sha256(req.token.strip().upper().encode()).hexdigest() != token_hash:
        raise HTTPException(status_code=400, detail="Invalid or expired reset code")

    # Token is valid -- consume it
    del _reset_tokens[req.email]

    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired reset code")

    user.set_password(req.new_password)
    api_key, key_hash = _generate_api_key()
    user.api_key_hash = key_hash
    await db.commit()
    await db.refresh(user)

    return InitResponse(user=UserResponse.model_validate(user), api_key=api_key)


# -- Invite Codes --


@router.post("/invite", response_model=InviteResponse, dependencies=[Depends(require_local_mode)])
async def create_invite(
    req: InviteCreateRequest = InviteCreateRequest(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Admin creates an invite code for a new user."""
    from datetime import timedelta

    invite = InviteCode(
        role=req.role,
        created_by=current_user.id,
        expires_at=datetime.now(UTC) + timedelta(days=req.expires_days),
    )
    db.add(invite)
    await db.commit()
    await db.refresh(invite)

    return InviteResponse.model_validate(invite)


@router.post("/redeem", response_model=InitResponse, dependencies=[Depends(require_local_mode)])
@limiter.limit("5/minute")
async def redeem_invite(request: Request, req: InviteRedeemRequest, db: AsyncSession = Depends(get_db)):
    """Redeem an invite code to create an account and get an API key."""
    code = req.code.strip().upper()

    result = await db.execute(select(InviteCode).where(InviteCode.code == code))
    invite = result.scalar_one_or_none()

    if not invite:
        raise HTTPException(status_code=404, detail="Invalid invite code")
    if invite.used_by is not None:
        raise HTTPException(status_code=400, detail="Invite code already used")
    if invite.expires_at < datetime.now(UTC):
        raise HTTPException(status_code=400, detail="Invite code expired")

    # Generate user credentials
    api_key, key_hash = _generate_api_key()

    name = req.name or f"user-{code[-4:]}"
    email = req.email or f"{name.lower().replace(' ', '-')}@localhost"

    try:
        role = UserRole(invite.role)
    except ValueError:
        role = UserRole.reviewer

    user = User(
        email=email,
        name=name,
        role=role,
        api_key_hash=key_hash,
    )
    db.add(user)

    # Mark invite as used
    invite.used_by = user.id
    invite.used_at = datetime.now(UTC)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Invite already redeemed or email already exists")
    await db.refresh(user)

    return InitResponse(user=UserResponse.model_validate(user), api_key=api_key)


@router.get("/invites", response_model=list[InviteListResponse])
async def list_invites(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Admin lists all invite codes."""

    result = await db.execute(select(InviteCode).order_by(InviteCode.created_at.desc()))
    return [InviteListResponse.model_validate(i) for i in result.scalars().all()]
