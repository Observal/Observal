# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-FileCopyrightText: 2026 Subramania Raja <dhanpraja231@gmail.com>
# SPDX-FileCopyrightText: 2026 Harishankar <harishankar0301@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

import asyncio
import uuid as _uuid
from collections.abc import AsyncGenerator

import jwt
from fastapi import Depends, Header, HTTPException
from loguru import logger as optic
from redis.exceptions import RedisError
from sqlalchemy import String, cast, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from config import HAS_LICENSE
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
    except jwt.InvalidTokenError as e:
        optic.trace("JWT decode failed: {}", e)
        return None

    jti = payload.get("jti")
    user_id_str = payload.get("sub")
    try:
        redis = get_redis()
        # SEC-002: fail closed on revocation checks - Redis errors must not
        # re-enable revoked tokens or user-level revocations.
        # Gather both checks concurrently to reduce latency at scale
        # (2 sequential GETs → 1 concurrent round-trip).
        checks = []
        if jti:
            checks.append(redis.get(f"revoked_jti:{jti}"))
        if user_id_str:
            checks.append(redis.get(f"revoked_user:{user_id_str}"))
        results = await asyncio.gather(*checks) if checks else []
        idx = 0
        if jti:
            if results[idx]:
                return None
            idx += 1
        if user_id_str and results[idx]:
            return None  # SEC-001: account-wide revocation (e.g. logout all)
    except RedisError as e:
        # Redis is down: block all token-based auth to prevent revoked tokens
        # from regaining access. Requests will receive HTTP 503.
        optic.error("Redis unavailable during auth - blocking request to prevent revoked token use: {}", e)
        raise RedisError("Auth service temporarily unavailable - please retry")

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
        optic.trace("request has no Bearer token")
        raise HTTPException(status_code=401, detail="Missing credentials")
    token = authorization.removeprefix("Bearer ").strip()
    user = await _authenticate_via_jwt(token, db)
    if not user:
        optic.debug("authentication failed - token invalid or expired")
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    # Block deactivated users (SCIM sets auth_provider to "deactivated")
    if user.auth_provider == "deactivated":
        optic.warning("deactivated user {} attempted access", user.id)
        raise HTTPException(status_code=403, detail="Account deactivated")

    # Expose user to audit middleware
    request.state.audit_user = user

    # Enforce must_change_password - fail closed: if Redis is down we cannot
    # guarantee the gate is enforced, so block non-exempt requests.
    if request.url.path not in _PASSWORD_CHANGE_EXEMPT_PATHS:
        try:
            redis = get_redis()
            if await redis.get(f"must_change_password:{user.id}"):
                raise HTTPException(status_code=403, detail="Password change required")
        except RedisError:
            raise HTTPException(status_code=503, detail="Auth service temporarily unavailable")

    request.state.current_user = user
    request.state.org_id = user.org_id
    return user


async def optional_current_user(
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Return the authenticated user when a valid token is present, else None.

    Raises HTTP 401 if a Bearer token is present but invalid/expired -
    this distinguishes 'no credentials' from 'bad credentials'.
    """
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ").strip()
    user = await _authenticate_via_jwt(token, db)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if user.auth_provider == "deactivated":
        raise HTTPException(status_code=401, detail="Account deactivated")
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


def get_effective_agent_permission(agent: "Agent", user: User | None) -> str:  # noqa: F821
    """Evaluate effective permission for an agent: 'owner', 'edit', 'view', or 'none'."""
    if not user:
        return "view"

    if agent.created_by == user.id:
        return "owner"

    # Co-authors have full owner-level access
    if str(user.id) in [str(uid) for uid in (agent.co_authors or [])]:
        return "owner"

    user_role_level = ROLE_HIERARCHY.get(user.role, 999)
    if user_role_level <= ROLE_HIERARCHY[UserRole.admin]:
        return "owner"  # admins can edit anything

    return "view"


def get_effective_component_permission(listing, user: User | None) -> str:
    """Evaluate effective permission for a component listing: 'owner', 'view', or 'none'.

    Works with McpListing, HookListing, SandboxListing, PromptListing.
    Co-authors have full owner-level access (can edit, publish, manage co-authors).
    """
    if not user:
        return "view"

    if listing.submitted_by == user.id:
        return "owner"

    # Co-authors have full owner-level access
    if str(user.id) in [str(uid) for uid in (listing.co_authors or [])]:
        return "owner"

    user_role_level = ROLE_HIERARCHY.get(user.role, 999)
    if user_role_level <= ROLE_HIERARCHY[UserRole.admin]:
        return "owner"  # admins can edit anything

    return "view"


# Convenience shorthand for super_admin-only endpoints
require_super_admin = require_role(UserRole.super_admin)


async def commit_or_name_conflict(db: AsyncSession, item_type: str) -> None:
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        detail = str(exc.orig).lower()
        if "name" in detail and ("unique" in detail or "duplicate" in detail):
            raise HTTPException(status_code=409, detail=f"A {item_type} with this name already exists")
        raise


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

    Returns None when the user has no org (local mode - no filtering).
    Returns the org_id UUID when the user belongs to an org.
    """

    async def _dep(current_user: User = Depends(get_current_user)) -> _uuid.UUID | None:
        return current_user.org_id

    return _dep


async def require_local_mode() -> None:
    """FastAPI dependency that blocks the endpoint in enterprise mode.

    Usage: @router.post("/bootstrap", dependencies=[Depends(require_local_mode)])
    """
    if HAS_LICENSE:
        raise HTTPException(status_code=403, detail="Disabled in enterprise mode")


async def require_password_auth() -> None:
    """FastAPI dependency that blocks the endpoint when deployment.sso_only is enabled."""
    import services.dynamic_settings as ds

    sso_only = await ds.get_bool("deployment.sso_only")
    if sso_only:
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
        version_model = model.__mapper__.relationships["latest_version"].entity.class_
        stmt = stmt.join(version_model, model.latest_version_id == version_model.id).where(
            version_model.status == require_status
        )
    # Order by created_at desc so duplicates resolve to the most recent entry
    if hasattr(model, "created_at"):
        stmt = stmt.order_by(model.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().first()


MIN_ID_PREFIX_LENGTH = 4
MAX_AMBIGUOUS_MATCHES_SHOWN = 5


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

    if len(norm_id) < MIN_ID_PREFIX_LENGTH:
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
    for r in records[:MAX_AMBIGUOUS_MATCHES_SHOWN]:
        label = getattr(r, display_field, None) or "unnamed"
        matches.append(f"{label} ({str(r.id)[:13]}...)")
    detail = f"Ambiguous prefix '{norm_id}' matches {len(records)} records: {', '.join(matches)}"
    if len(records) > MAX_AMBIGUOUS_MATCHES_SHOWN:
        detail += " and more..."
    raise HTTPException(status_code=400, detail=detail)


def apply_visibility_filter(stmt, model, current_user):
    """Exclude private listings from orgs other than the requesting user's.

    Rules:
    - Public items (is_private=False) are always visible.
    - Private items are only visible to users in the same org, or to the
      submitter directly, or to admins/reviewers.
    """
    from sqlalchemy import or_

    from models.user import UserRole

    if not hasattr(model, "is_private"):
        return stmt

    is_admin = (
        current_user is not None and ROLE_HIERARCHY.get(current_user.role, 999) <= ROLE_HIERARCHY[UserRole.reviewer]
    )
    if is_admin:
        return stmt  # admins see everything

    public = model.is_private == False  # noqa: E712
    if current_user is None:
        return stmt.where(public)

    # Guard: only match same-org if user actually has an org (not NULL)
    if current_user.org_id is not None:
        same_org = (model.is_private == True) & (model.owner_org_id == current_user.org_id)  # noqa: E712
        own = (model.is_private == True) & (model.submitted_by == current_user.id)  # noqa: E712
        return stmt.where(or_(public, same_org, own))
    # User has no org - can only see their own private items
    own = (model.is_private == True) & (model.submitted_by == current_user.id)  # noqa: E712
    return stmt.where(or_(public, own))


def check_listing_visibility(listing, current_user) -> bool:
    """Return True if current_user may see this listing.

    Used on detail routes to gate access to private items.
    """
    from models.user import UserRole

    if not getattr(listing, "is_private", False):
        return True
    if current_user is None:
        return False
    is_admin = ROLE_HIERARCHY.get(current_user.role, 999) <= ROLE_HIERARCHY[UserRole.reviewer]
    if is_admin:
        return True
    if listing.submitted_by == current_user.id:
        return True
    return current_user.org_id is not None and listing.owner_org_id == current_user.org_id
