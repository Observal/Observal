import hashlib
import hmac
import uuid as _uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import String, cast, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import settings
from database import async_session
from models.api_key import ApiKey
from models.user import User, UserRole
from services.jwt_service import decode_access_token


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


async def _authenticate_via_jwt(token: str, db: AsyncSession) -> User | None:
    """Try to authenticate using a JWT access token. Returns User or None."""
    try:
        payload = decode_access_token(token)
    except jwt.InvalidTokenError:
        return None

    user_id = payload.get("sub")
    if not user_id:
        return None

    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        return None

    result = await db.execute(select(User).where(User.id == uid))
    return result.scalar_one_or_none()


async def _authenticate_via_api_key(api_key: str, db: AsyncSession, request: Request) -> User | None:
    """Try to authenticate using a raw API key. Returns User or None."""
    key_hash = hmac.new(settings.SECRET_KEY.encode(), api_key.encode(), "sha256").hexdigest()

    # Query ApiKey table with authorization check built into query
    result = await db.execute(
        select(ApiKey)
        .where(ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None))
        .options(selectinload(ApiKey.user))
    )
    api_key_record = result.scalar_one_or_none()

    if not api_key_record:
        # Fallback: Check legacy User.api_key_hash for backward compatibility
        # Legacy keys were stored with plain SHA256 (not HMAC)
        legacy_hash = hashlib.sha256(api_key.encode()).hexdigest()
        result = await db.execute(select(User).where(User.api_key_hash == legacy_hash))
        return result.scalar_one_or_none()

    # Check expiration
    if api_key_record.expires_at and api_key_record.expires_at <= datetime.now(UTC):
        return None

    # Update last_used_at (debounced - max once per minute)
    now = datetime.now(UTC)
    should_update = api_key_record.last_used_at is None or (now - api_key_record.last_used_at) > timedelta(minutes=1)

    if should_update:
        # Get IP from headers (support proxies)
        client_ip = request.headers.get("x-forwarded-for", request.client.host if request.client else None)
        if client_ip and "," in client_ip:
            client_ip = client_ip.split(",")[0].strip()

        api_key_record.last_used_at = now
        api_key_record.last_used_ip = client_ip
        await db.commit()

    return api_key_record.user


async def get_current_user(
    request: Request,
    x_api_key: str | None = Header(None),
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
) -> User:
    # Extract bearer token from Authorization header
    bearer_token: str | None = None
    if authorization and authorization.startswith("Bearer "):
        bearer_token = authorization.removeprefix("Bearer ").strip()

    # 1. If we have a Bearer token, try JWT first
    if bearer_token:
        user = await _authenticate_via_jwt(bearer_token, db)
        if user:
            return user
        # JWT decode failed -- fall back to treating it as a raw API key
        user = await _authenticate_via_api_key(bearer_token, db, request)
        if user:
            return user

    # 2. Try X-API-Key header (backward compat with existing CLI installs)
    if x_api_key:
        user = await _authenticate_via_api_key(x_api_key, db, request)
        if user:
            return user

    raise HTTPException(status_code=401, detail="Invalid or missing credentials")


# Role hierarchy: lower number = higher privilege
ROLE_HIERARCHY: dict[UserRole, int] = {
    UserRole.super_admin: 0,
    UserRole.admin: 1,
    UserRole.reviewer: 2,
    UserRole.user: 3,
}


def require_role(min_role: UserRole):
    """FastAPI dependency that requires the user to have at least the given role level.

    Usage: current_user: User = Depends(require_role(UserRole.admin))
    """

    async def _check(current_user: User = Depends(get_current_user)) -> User:
        user_level = ROLE_HIERARCHY.get(current_user.role, 999)
        required_level = ROLE_HIERARCHY[min_role]
        if user_level > required_level:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user

    return _check


# Convenience shorthand for super_admin-only endpoints
require_super_admin = require_role(UserRole.super_admin)


async def require_local_mode() -> None:
    """FastAPI dependency that blocks the endpoint in enterprise mode.

    Usage: @router.post("/bootstrap", dependencies=[Depends(require_local_mode)])
    """
    if settings.DEPLOYMENT_MODE != "local":
        raise HTTPException(status_code=403, detail="Disabled in enterprise mode")


async def resolve_listing(model, identifier: str, db: AsyncSession, *, require_status=None):
    """Resolve a listing by UUID or name. Returns most recent if duplicates exist."""

    if isinstance(identifier, _uuid.UUID):
        stmt = select(model).where(model.id == identifier)
    else:
        try:
            uid = _uuid.UUID(identifier)
            stmt = select(model).where(model.id == uid)
        except ValueError:
            stmt = select(model).where(model.name == identifier)
    if require_status is not None:
        stmt = stmt.where(model.status == require_status)
    # Order by created_at desc so duplicates resolve to the most recent entry
    if hasattr(model, "created_at"):
        stmt = stmt.order_by(model.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().first()


async def resolve_prefix_id(
    model,
    identifier: str,
    db: AsyncSession,
    *,
    extra_conditions=None,
    load_options=None,
    display_field: str = "name",
):
    """Find a record by UUID or unique prefix."""
    norm_id = identifier.strip().lower()

    try:
        uid = _uuid.UUID(norm_id)
        stmt = select(model).where(model.id == uid)
        if load_options:
            stmt = stmt.options(*load_options)
        if extra_conditions:
            stmt = stmt.where(*extra_conditions)
        result = await db.execute(stmt)
        record = result.scalar_one_or_none()
        if not record:
            raise HTTPException(status_code=404, detail=f"{model.__name__} not found")
        return record
    except ValueError:
        pass

    if len(norm_id) < 4:
        raise HTTPException(
            status_code=400,
            detail=f"Prefix '{norm_id}' is too short (minimum 4 characters required)",
        )

    stmt = select(model).where(cast(model.id, String).like(f"{norm_id}%"))
    if load_options:
        stmt = stmt.options(*load_options)
    if extra_conditions:
        stmt = stmt.where(*extra_conditions)
    result = await db.execute(stmt)
    records = result.scalars().all()

    if not records:
        raise HTTPException(
            status_code=404,
            detail=f"No {model.__name__} found matching prefix '{norm_id}'",
        )
    if len(records) == 1:
        return records[0]

    matches = []
    for r in records[:5]:
        label = getattr(r, display_field, None) or "unnamed"
        matches.append(f"{label} ({str(r.id)[:13]}...)")
    detail = f"Ambiguous prefix '{norm_id}' matches {len(records)} records: {', '.join(matches)}"
    if len(records) > 5:
        detail += " and more..."
    raise HTTPException(status_code=400, detail=detail)
