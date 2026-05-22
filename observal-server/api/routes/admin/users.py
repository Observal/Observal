# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Admin user management routes."""

import json
import logging
import uuid

from fastapi import Depends, HTTPException
from pydantic import BaseModel
from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import ROLE_HIERARCHY, get_db, get_or_create_default_org, require_password_auth, require_role
from models.user import User, UserRole
from schemas.admin import (
    AdminResetPasswordRequest,
    UserAdminResponse,
    UserCreateRequest,
    UserCreateResponse,
    UserDepartmentUpdate,
    UserRoleUpdate,
)
from services.audit_helpers import audit
from services.security_events import EventType, SecurityEvent, Severity, emit_security_event
from services.username_generator import generate_unique_username

from ._router import router
from .helpers import _generate_unique_password

logger = logging.getLogger(__name__)

# ── User Management ──────────────────────────────────────


@router.get("/users", response_model=list[UserAdminResponse])
async def list_users(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    stmt = select(User).order_by(User.created_at.desc())
    if current_user.org_id is not None:
        stmt = stmt.where(User.org_id == current_user.org_id)
    result = await db.execute(stmt)
    users = [UserAdminResponse.model_validate(u) for u in result.scalars().all()]
    await audit(current_user, "admin.users.list", "user")
    return users


@router.post("/users", response_model=UserCreateResponse, dependencies=[Depends(require_password_auth)])
async def create_user(
    req: UserCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Admin creates a new user and gets back their generated password."""
    existing = await db.execute(select(User).where(User.email == req.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    try:
        role = UserRole(req.role)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid role. Must be one of: {[r.value for r in UserRole]}")

    if ROLE_HIERARCHY.get(role, 999) < ROLE_HIERARCHY[current_user.role]:
        raise HTTPException(status_code=403, detail="Cannot assign a role higher than your own")

    password = req.password or await _generate_unique_password(db)

    org_id = current_user.org_id
    if not org_id:
        default_org = await get_or_create_default_org(db)
        org_id = default_org.id

    username = req.username or await generate_unique_username(req.email, db)
    user = User(email=req.email, username=username, name=req.name, role=role, org_id=org_id)
    user.set_password(password)
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Email already registered")
    await db.refresh(user)

    await emit_security_event(
        SecurityEvent(
            event_type=EventType.USER_CREATED,
            severity=Severity.INFO,
            outcome="success",
            actor_id=str(current_user.id),
            actor_email=current_user.email,
            actor_role=current_user.role.value,
            target_id=str(user.id),
            target_type="user",
            detail=f"Created user {user.email} with role {role.value}",
        )
    )
    await audit(
        current_user,
        "admin.users.create",
        "user",
        resource_id=str(user.id),
        resource_name=user.email,
        detail=json.dumps({"role": role.value}),
    )
    return UserCreateResponse(
        id=user.id,
        email=user.email,
        username=user.username,
        name=user.name,
        role=user.role.value,
        password=password,
    )


@router.put("/users/{user_id}/role", response_model=UserAdminResponse)
async def update_user_role(
    user_id: uuid.UUID,
    req: UserRoleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    try:
        new_role = UserRole(req.role)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid role. Must be one of: {[r.value for r in UserRole]}")

    from api.deps import ROLE_HIERARCHY

    if ROLE_HIERARCHY.get(new_role, 999) < ROLE_HIERARCHY[current_user.role]:
        raise HTTPException(status_code=403, detail="Cannot assign a role higher than your own")

    if user_id == current_user.id and new_role != current_user.role:
        raise HTTPException(status_code=400, detail="Cannot change your own role")

    stmt = select(User).where(User.id == user_id)
    if current_user.org_id is not None:
        stmt = stmt.where(User.org_id == current_user.org_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    old_role = user.role.value
    user.role = new_role
    await db.commit()
    await db.refresh(user)
    await emit_security_event(
        SecurityEvent(
            event_type=EventType.ROLE_CHANGED,
            severity=Severity.WARNING,
            outcome="success",
            actor_id=str(current_user.id),
            actor_email=current_user.email,
            actor_role=current_user.role.value,
            target_id=str(user.id),
            target_type="user",
            detail=f"Role changed from {old_role} to {new_role.value}",
        )
    )
    await audit(
        current_user,
        "admin.users.role_update",
        "user",
        resource_id=str(user.id),
        resource_name=user.email,
        detail=json.dumps({"old_role": old_role, "new_role": new_role.value}),
    )
    return UserAdminResponse.model_validate(user)


@router.put("/users/{user_id}/department", response_model=UserAdminResponse)
async def update_user_department(
    user_id: uuid.UUID,
    req: UserDepartmentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    stmt = select(User).where(User.id == user_id)
    if current_user.org_id is not None:
        stmt = stmt.where(User.org_id == current_user.org_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.department = req.department
    await db.commit()
    await db.refresh(user)
    return UserAdminResponse.model_validate(user)


class BulkDepartmentEntry(BaseModel):
    email: str
    department: str


class BulkDepartmentRequest(BaseModel):
    entries: list[BulkDepartmentEntry]


class BulkDepartmentResult(BaseModel):
    updated: int
    not_found: list[str]


@router.post("/users/bulk-department", response_model=BulkDepartmentResult)
async def bulk_update_departments(
    req: BulkDepartmentRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Bulk-assign departments to users by email."""
    updated = 0
    not_found = []

    for entry in req.entries:
        stmt = select(User).where(User.email == entry.email.strip().lower())
        if current_user.org_id is not None:
            stmt = stmt.where(User.org_id == current_user.org_id)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        if user:
            user.department = entry.department.strip()
            updated += 1
        else:
            not_found.append(entry.email)

    await db.commit()
    return BulkDepartmentResult(updated=updated, not_found=not_found)


@router.put("/users/{user_id}/password", dependencies=[Depends(require_password_auth)])
async def reset_user_password(
    user_id: uuid.UUID,
    req: AdminResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Admin resets a user's password.

    Either provide new_password directly, or set generate=true to create
    a secure random password that doesn't collide with existing hashes.
    """
    stmt = select(User).where(User.id == user_id)
    if current_user.org_id is not None:
        stmt = stmt.where(User.org_id == current_user.org_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if req.generate:
        new_password = await _generate_unique_password(db)
    elif req.new_password:
        new_password = req.new_password
    else:
        raise HTTPException(status_code=422, detail="Provide new_password or set generate=true")

    user.set_password(new_password)
    await db.commit()

    try:
        from services.redis import get_redis

        redis = get_redis()
        await redis.setex(f"must_change_password:{user.id}", 86400, "1")
    except (RedisError, Exception):
        pass

    await emit_security_event(
        SecurityEvent(
            event_type=EventType.ADMIN_PASSWORD_RESET,
            severity=Severity.WARNING,
            outcome="success",
            actor_id=str(current_user.id),
            actor_email=current_user.email,
            actor_role=current_user.role.value,
            target_id=str(user.id),
            target_type="user",
            detail=f"Password reset for {user.email}",
        )
    )
    logger.warning("Admin %s reset password for user %s", current_user.email, user.email)
    await audit(
        current_user,
        "admin.users.password_reset",
        "user",
        resource_id=str(user.id),
        resource_name=user.email,
    )

    resp: dict[str, str] = {"message": f"Password reset for {user.email}"}
    if req.generate:
        resp["generated_password"] = new_password
        resp["must_change_password"] = "true"
    return resp


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Admin deletes a user account and all associated data."""
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    stmt = select(User).where(User.id == user_id)
    if current_user.org_id is not None:
        stmt = stmt.where(User.org_id == current_user.org_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Prevent deleting the last admin/super_admin
    if user.role in (UserRole.admin, UserRole.super_admin):
        admin_count = await db.scalar(
            select(func.count()).select_from(User).where(User.role.in_([UserRole.admin, UserRole.super_admin]))
        )
        if admin_count is not None and admin_count <= 1:
            raise HTTPException(status_code=400, detail="Cannot delete the last admin")

    logger.warning("Admin %s deleted user %s (%s)", current_user.email, user.email, user.id)
    deleted_user_email = user.email
    deleted_user_id = str(user.id)
    await emit_security_event(
        SecurityEvent(
            event_type=EventType.USER_DELETED,
            severity=Severity.WARNING,
            outcome="success",
            actor_id=str(current_user.id),
            actor_email=current_user.email,
            actor_role=current_user.role.value,
            target_id=deleted_user_id,
            target_type="user",
            detail=f"Deleted user {deleted_user_email}",
        )
    )
    await db.delete(user)
    await db.commit()
    await audit(
        current_user,
        "admin.users.delete",
        "user",
        resource_id=deleted_user_id,
        resource_name=deleted_user_email,
    )


# ── Penalty & Weight Customization ──────────────────────
