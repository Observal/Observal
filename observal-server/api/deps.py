import uuid as _uuid
from collections.abc import AsyncGenerator

import jwt
from fastapi import Depends, Header, HTTPException
from redis.exceptions import RedisError
from sqlalchemy import String, cast, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from config import settings
from database import async_session
from models.organization import Organization
from models.user import User, UserRole
from services.jwt_service import decode_access_token
from services.redis import get_redis
from services.security_events import (
    EventType,
    SecurityEvent,
    Severity,
    emit_security_event,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


async def _authenticate_via_jwt(token: str, db: AsyncSession) -> User | None:
    """Try to authenticate using a JWT access token. Returns User or None.

    Also resolves the org's trace_privacy flag in the same query (via JOIN)
    so downstream code never needs a separate DB call for it.
    """
    try:
        payload = decode_access_token(token)
    except jwt.InvalidTokenError:
        return None

    jti = payload.get("jti")
    if jti:
        try:
            redis = get_redis()
            if await redis.get(f"revoked_jti:{jti}"):
                return None
        except RedisError:
            pass  # Fail open if Redis is down

    user_id = payload.get("sub")

    if not user_id:
        return None

    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        return None

    result = await db.execute(
        select(User, Organization.trace_privacy)
        .outerjoin(Organization, User.org_id == Organization.id)
        .where(User.id == uid)
    )
    row = result.one_or_none()
    if not row:
        return None
    user, trace_privacy = row
    user._trace_privacy = bool(trace_privacy)
    user._groups = payload.get("groups", [])
    return user


# Paths that must remain accessible even when must_change_password is set
_PASSWORD_CHANGE_EXEMPT_PATHS = frozenset(
    {
        "/api/v1/auth/profile/password",
        "/api/v1/auth/whoami",
        "/api/v1/auth/token/refresh",
        "/api/v1/auth/token/revoke",
    }
)


async def get_current_user(
    request: Request,
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing credentials")
    token = authorization.removeprefix("Bearer ").strip()
    user = await _authenticate_via_jwt(token, db)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    # Block deactivated users (SCIM sets auth_provider to "deactivated")
    if user.auth_provider == "deactivated":
        raise HTTPException(status_code=403, detail="Account deactivated")

    # Enforce must_change_password (fail open if Redis is unavailable)
    if request.url.path not in _PASSWORD_CHANGE_EXEMPT_PATHS:
        try:
            redis = get_redis()
            if await redis.get(f"must_change_password:{user.id}"):
                raise HTTPException(status_code=403, detail="Password change required")
        except RedisError:
            pass

    return user


async def optional_current_user(
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Return the authenticated user when a valid token is present, else None."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ").strip()
    user = await _authenticate_via_jwt(token, db)
    if user and user.auth_provider == "deactivated":
        return None
    return user


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
            await emit_security_event(
                SecurityEvent(
                    event_type=EventType.PERMISSION_DENIED,
                    severity=Severity.WARNING,
                    outcome="failure",
                    actor_id=str(current_user.id),
                    actor_email=current_user.email,
                    actor_role=current_user.role.value,
                    detail=f"Required role: {min_role.value}, has: {current_user.role.value}",
                )
            )
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user

    return _check


def get_user_groups(user: User | None) -> list[str]:
    """Get user groups extracted from the JWT token during authentication."""
    if not user:
        return []
    return getattr(user, "_groups", [])


def get_effective_agent_permission(agent: "Agent", user: User | None) -> str:  # noqa: F821
    """Evaluate effective permission for an agent: 'owner', 'edit', 'view', or 'none'."""
    # Local import to avoid circular dependency
    from models.agent import AgentVisibility

    if not user:
        if agent.visibility == AgentVisibility.public:
            return "view"
        return "none"

    if agent.created_by == user.id:
        return "owner"

    user_role_level = ROLE_HIERARCHY.get(user.role, 999)
    if user_role_level <= ROLE_HIERARCHY[UserRole.admin]:
        return "owner"  # admins can edit anything

    user_groups = get_user_groups(user)
    best_perm = "none"
    perm_levels = {"none": 0, "view": 1, "edit": 2, "owner": 3}

    for access in getattr(agent, "team_accesses", []):
        if access.group_name in user_groups and perm_levels.get(access.permission, 0) > perm_levels[best_perm]:
            best_perm = access.permission

    if best_perm == "none" and agent.visibility == AgentVisibility.public:
        return "view"

    return best_perm


# Convenience shorthand for super_admin-only endpoints
require_super_admin = require_role(UserRole.super_admin)


async def get_current_org_id(
    current_user: User = Depends(get_current_user),
) -> _uuid.UUID | None:
    """Return the authenticated user's org_id (None for unaffiliated users)."""
    return current_user.org_id


def get_project_id(user: User) -> str:
    """Derive the ClickHouse project_id from a user's org membership.

    Returns "default" when the user has no org (backwards compat for local mode).
    """
    return str(user.org_id) if user.org_id else "default"


async def get_or_create_default_org(db: AsyncSession) -> Organization:
    """Return the default organization, creating it if it doesn't exist."""
    result = await db.execute(select(Organization).where(Organization.slug == "default"))
    org = result.scalar_one_or_none()
    if org:
        return org
    org = Organization(name="Default", slug="default")
    db.add(org)
    await db.flush()
    return org


def require_org_scope():
    """FastAPI dependency that applies org-scoped filtering.

    Returns None when the user has no org (local mode — no filtering).
    Returns the org_id UUID when the user belongs to an org.
    """

    async def _dep(current_user: User = Depends(get_current_user)) -> _uuid.UUID | None:
        return current_user.org_id

    return _dep


async def require_local_mode() -> None:
    """FastAPI dependency that blocks the endpoint in enterprise mode.

    Usage: @router.post("/bootstrap", dependencies=[Depends(require_local_mode)])
    """
    if settings.DEPLOYMENT_MODE != "local":
        raise HTTPException(status_code=403, detail="Disabled in enterprise mode")


async def require_password_auth() -> None:
    """FastAPI dependency that blocks the endpoint when SSO_ONLY is enabled."""
    if settings.SSO_ONLY:
        raise HTTPException(status_code=403, detail="Password authentication is disabled (SSO-only mode)")


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
