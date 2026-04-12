import hashlib
import logging
import secrets
import string
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user, get_db
from config import settings
from models.invite import InviteCode
from models.user import User, UserRole
from schemas.auth import (
    InitRequest,
    InitResponse,
    InviteCreateRequest,
    InviteListResponse,
    InviteRedeemRequest,
    InviteResponse,
    LoginRequest,
    RegisterRequest,
    RequestResetRequest,
    ResetPasswordRequest,
    UserResponse,
)

logger = logging.getLogger(__name__)

# In-memory store for password reset tokens: email -> (token_hash, expires_at)
_reset_tokens: dict[str, tuple[str, datetime]] = {}

RESET_TOKEN_TTL_MINUTES = 15

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


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
    await db.commit()
    await db.refresh(user)

    return InitResponse(user=UserResponse.model_validate(user), api_key=api_key)


@router.post("/bootstrap", response_model=InitResponse)
async def bootstrap(db: AsyncSession = Depends(get_db)):
    """Auto-create admin account on a fresh server. No input needed."""
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
    await db.commit()
    await db.refresh(user)

    return InitResponse(user=UserResponse.model_validate(user), api_key=api_key)


@router.post("/register", response_model=InitResponse)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
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
    await db.commit()
    await db.refresh(user)

    return InitResponse(user=UserResponse.model_validate(user), api_key=api_key)


@router.post("/login", response_model=InitResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
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


@router.get("/whoami", response_model=UserResponse)
async def whoami(current_user: User = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)


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
async def request_password_reset(req: RequestResetRequest, db: AsyncSession = Depends(get_db)):
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
async def reset_password(req: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
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

    # Token is valid — consume it
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


# ── Invite Codes ────────────────────────────────────────────


@router.post("/invite", response_model=InviteResponse)
async def create_invite(
    req: InviteCreateRequest = InviteCreateRequest(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Admin creates an invite code for a new user."""
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Admin access required")

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


@router.post("/redeem", response_model=InitResponse)
async def redeem_invite(req: InviteRedeemRequest, db: AsyncSession = Depends(get_db)):
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
        role = UserRole.developer

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

    await db.commit()
    await db.refresh(user)

    return InitResponse(user=UserResponse.model_validate(user), api_key=api_key)


@router.get("/invites", response_model=list[InviteListResponse])
async def list_invites(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Admin lists all invite codes."""
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    result = await db.execute(select(InviteCode).order_by(InviteCode.created_at.desc()))
    return [InviteListResponse.model_validate(i) for i in result.scalars().all()]
