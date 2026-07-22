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
    """Reduce raw text to a namespace-valid handle (NAMESPACE_RE: 3-32, [a-z0-9-])."""
    base = _HANDLE_STRIP_RE.sub("-", (raw or "").strip().lower()).strip("-")
    if not base:
        base = fallback
    # NAMESPACE_RE requires 3-32 chars and alnum start/end; clip and pad.
    if len(base) > 32:
        base = base[:32].rstrip("-")
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


async def count_owners(db: AsyncSession, team_id: uuid.UUID) -> int:
    return (
        (
            await db.execute(
                select(TeamMembership.id).where(
                    TeamMembership.team_id == team_id, TeamMembership.role == TeamRole.owner
                )
            )
        )
        .scalars()
        .all()
        .__len__()
    )


if __name__ == "__main__":
    # ponytail: self-check uses fakes; reserve_handle hits two select() calls.
    import asyncio

    async def _ok():
        class _Scalar:
            def scalar_one_or_none(self):
                return None

        class _Res:
            def __init__(self):
                self.calls = 0

            async def execute(self, stmt):
                self.calls += 1
                return _Scalar()

        db = _Res()
        out = await reserve_handle(db, "Platform Tools!")
        assert out == "platform-tools", out
        assert db.calls == 2
        # slugify_handle targets NAMESPACE_RE (3-32, [a-z0-9-], alnum ends)
        assert slugify_handle("A B") == "a-b"
        assert slugify_handle("") == "team"
        print("reserve_handle ok:", out)

    asyncio.run(_ok())
