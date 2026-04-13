import hashlib
import uuid as _uuid
from collections.abc import AsyncGenerator
from functools import wraps

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy import String, cast, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import async_session
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


async def _authenticate_via_api_key(api_key: str, db: AsyncSession) -> User | None:
    """Try to authenticate using a raw API key. Returns User or None."""
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    result = await db.execute(select(User).where(User.api_key_hash == key_hash))
    return result.scalar_one_or_none()


async def get_current_user(
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
        user = await _authenticate_via_api_key(bearer_token, db)
        if user:
            return user

    # 2. Try X-API-Key header (backward compat with existing CLI installs)
    if x_api_key:
        user = await _authenticate_via_api_key(x_api_key, db)
        if user:
            return user

    raise HTTPException(status_code=401, detail="Invalid or missing credentials")


def require_role(*roles: UserRole):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, current_user: User = Depends(get_current_user), **kwargs):
            if current_user.role not in roles:
                raise HTTPException(status_code=403, detail="Insufficient permissions")
            return await func(*args, current_user=current_user, **kwargs)

        return wrapper

    return decorator


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
