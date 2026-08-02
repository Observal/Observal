# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Teamspace membership and handle reservation helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import HTTPException
from sqlalchemy import select

from models.team import Team, TeamMembership, TeamRole
from models.user import User, UserRole
from services.registry_namespace import namespace_for_user, slugify, validate_namespace

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


def is_global_reviewer(user: User) -> bool:
    return user.role in (UserRole.reviewer, UserRole.admin, UserRole.super_admin)


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


def team_role_self_publishes(membership: TeamMembership | None, visibility: str) -> bool:
    """Whether a team role alone clears review, for a listing of this visibility.

    Team roles are self-service: a team owner can promote any member to owner, so
    letting a team role auto-approve a PUBLIC listing would be a privilege escalation
    path straight into the global catalog. Public listings published from a team
    namespace therefore still go through the global review queue. Team-visibility
    publishing stays self-service because the result is only visible to that team.
    """
    if visibility != "team":
        return False
    return membership is not None and membership.role in (TeamRole.owner, TeamRole.reviewer)


@dataclass(frozen=True)
class PublishTarget:
    namespace: str
    slug: str
    team_id: uuid.UUID | None
    visibility: str
    owner: str
    auto_approve: bool


async def resolve_publish_target(
    db: AsyncSession,
    user: User,
    name: str,
    *,
    team_id: uuid.UUID | None = None,
    visibility: str | None = None,
) -> PublishTarget:
    """Resolve and authorize the namespace and visibility for a new listing."""
    target_visibility = (visibility or "public").strip().lower()
    if target_visibility not in {"public", "team"}:
        raise HTTPException(status_code=422, detail="visibility must be 'public' or 'team'")

    if team_id is None:
        if target_visibility == "team":
            raise HTTPException(status_code=422, detail="Team visibility requires a teamspace")
        return PublishTarget(
            namespace=namespace_for_user(user),
            slug=slugify(name),
            team_id=None,
            visibility="public",
            owner=user.username or user.email,
            auto_approve=False,
        )

    team = await db.get(Team, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Teamspace not found")
    membership = await team_membership(db, team.id, user.id)
    if not membership and not is_global_reviewer(user):
        raise HTTPException(status_code=403, detail="You are not a member of this teamspace")

    auto_approve = is_global_reviewer(user) or team_role_self_publishes(membership, target_visibility)
    return PublishTarget(
        namespace=team.handle,
        slug=slugify(name),
        team_id=team.id,
        visibility=target_visibility,
        owner=team.handle,
        auto_approve=auto_approve,
    )


async def publish_auto_approves_for_entity(entity, user: User, db: AsyncSession) -> bool:
    """Return whether this actor can publish an already saved team item without review.

    The entity carries its own visibility, so a public listing sitting in a team
    namespace is held for global review even when the submitter is a team owner or
    team reviewer. See team_role_self_publishes for why.
    """
    if getattr(entity, "team_id", None) is None:
        return False
    membership = await team_membership(db, entity.team_id, user.id)
    visibility = "team" if entity.is_private else "public"
    return is_global_reviewer(user) or team_role_self_publishes(membership, visibility)


def review_publication_to_public(entity, user: User, *, was_private: bool) -> bool:
    """Send a listing back to the review queue when it becomes publicly visible.

    Turning a team-private listing public publishes it into the global registry, so
    it has to clear global review. Without this, the auto-approval rule in
    team_role_self_publishes is trivially bypassed in two steps: publish as team
    visibility, which a team owner or team reviewer approves for themselves because
    only their own teamspace can see it, then flip the same approved row to public
    and reach every user without a reviewer ever seeing it.

    Only a global reviewer, admin, or super_admin keeps an approved status through
    the transition, because they already hold the authority the queue represents.

    Restricting a public listing back to team visibility is not a publication and
    needs no review, so this returns False for that direction.

    Returns True when the entity was moved back to pending.
    """
    if not was_private or entity.is_private or is_global_reviewer(user):
        return False

    version = getattr(entity, "latest_version", None)
    if version is None:
        raise RuntimeError(f"{type(entity).__name__} has no latest_version; cannot re-enter review")
    if version.status != _approved_status(entity):
        # A draft, pending, or rejected listing has not been approved for anything
        # yet, so becoming public changes nothing about its review state.
        return False

    entity.status = _pending_status(entity)
    version.reviewed_by = None
    version.reviewed_at = None
    return True


def _approved_status(entity):
    from models.agent import Agent, AgentStatus
    from models.mcp import ListingStatus

    return AgentStatus.approved if isinstance(entity, Agent) else ListingStatus.approved


def _pending_status(entity):
    from models.agent import Agent, AgentStatus
    from models.mcp import ListingStatus

    return AgentStatus.pending if isinstance(entity, Agent) else ListingStatus.pending


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
