# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Teamspace membership and handle reservation helpers."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from sqlalchemy import select

from models.team import Team, TeamMembership, TeamRole
from models.user import User, UserRole
from services.registry_namespace import validate_namespace

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

_HANDLE_STRIP_RE = re.compile(r"[^a-z0-9-]+")


def slugify_handle(raw: str, *, fallback: str = "team") -> str:
    """Reduce raw text to a namespace-valid handle (3-32 lowercase chars)."""
    base = _HANDLE_STRIP_RE.sub("-", (raw or "").strip().lower()).strip("-")
    if not base:
        base = fallback
    # Namespaces require 3-32 chars. Keep short names recognizable instead of
    # appending an opaque character.
    if len(base) > 32:
        base = base[:32].rstrip("-")
    if len(base) < 3:
        base = f"{base}-team"
    return validate_namespace(base, allow_reserved=True)


def is_admin(user: User) -> bool:
    return user.role in (UserRole.admin, UserRole.super_admin)


def is_team_role(role: TeamRole | str, expected: TeamRole) -> bool:
    value = role.value if isinstance(role, TeamRole) else str(role)
    return value == expected.value


async def team_membership(db: AsyncSession, team_id: uuid.UUID, user_id: uuid.UUID) -> TeamMembership | None:
    return (
        await db.execute(
            select(TeamMembership).where(TeamMembership.team_id == team_id, TeamMembership.user_id == user_id)
        )
    ).scalar_one_or_none()


async def user_team_ids(db: AsyncSession, user_id: uuid.UUID) -> list[uuid.UUID]:
    rows = await db.execute(select(TeamMembership.team_id).where(TeamMembership.user_id == user_id))
    return list(rows.scalars().all())


async def reserve_handle(
    db: AsyncSession,
    handle: str,
    *,
    exclude_team_id: uuid.UUID | None = None,
    exclude_user_id: uuid.UUID | None = None,
) -> str:
    """Slugify, validate, and ensure handle is free across users and teams.

    A handle is the namespace identity for both a user and a team, so it must
    resolve unambiguously. Raises ValueError on validation failure or collision.
    """
    value = validate_namespace(slugify_handle(handle))

    user_stmt = select(User.id).where(User.username == value)
    if exclude_user_id is not None:
        user_stmt = user_stmt.where(User.id != exclude_user_id)
    if (await db.execute(user_stmt.limit(1))).scalar_one_or_none() is not None:
        raise ValueError(f"Handle '{value}' is already taken")

    team_stmt = select(Team.id).where(Team.handle == value)
    if exclude_team_id is not None:
        team_stmt = team_stmt.where(Team.id != exclude_team_id)
    if (await db.execute(team_stmt.limit(1))).scalar_one_or_none() is not None:
        raise ValueError(f"Handle '{value}' is already taken")

    return value


async def count_owners(db: AsyncSession, team_id: uuid.UUID, *, for_update: bool = False) -> int:
    stmt = select(TeamMembership.id).where(TeamMembership.team_id == team_id, TeamMembership.role == TeamRole.owner)
    if for_update:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalars().all().__len__()
