import hashlib
from collections.abc import AsyncGenerator
from functools import wraps

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import async_session
from models.user import User, UserRole


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


async def get_current_user(
    x_api_key: str = Header(...),
    db: AsyncSession = Depends(get_db),
) -> User:
    key_hash = hashlib.sha256(x_api_key.encode()).hexdigest()
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
    import uuid as _uuid

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
