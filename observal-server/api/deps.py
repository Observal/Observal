import hashlib
import uuid as _uuid
from collections.abc import AsyncGenerator
from functools import wraps

from fastapi import Depends, Header, HTTPException
from sqlalchemy import String, cast, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import async_session
from models.user import User, UserRole


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


async def get_current_user(
    x_api_key: str | None = Header(None),
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
) -> User:
    # Try X-API-Key header first
    api_key = x_api_key
    # Fall back to Bearer token in Authorization header
    if not api_key and authorization and authorization.startswith("Bearer "):
        api_key = authorization.removeprefix("Bearer ").strip()
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing API key")

    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    result = await db.execute(select(User).where(User.api_key_hash == key_hash))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return user


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
    """Resolve a listing by UUID or name."""

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
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


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
