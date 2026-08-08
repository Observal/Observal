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


# The team roles that clear review for their own teamspace. A plain member
# publishes into the queue; it is these two that empty it.
REVIEWING_TEAM_ROLES = (TeamRole.owner, TeamRole.reviewer)


@dataclass(frozen=True)
class ReviewScope:
    """What one caller is allowed to review.

    ``is_admin`` reviews everything, team-private items included, because an admin
    already administers the whole deployment. ``is_global_reviewer`` without
    ``is_admin`` is the plain global reviewer role: public items only. ``team_ids``
    are the teamspaces where the caller is an owner or a reviewer, and they carry
    the right to review that teamspace's own private items and nothing else.
    """

    is_admin: bool
    is_global_reviewer: bool
    team_ids: frozenset[uuid.UUID]

    @property
    def is_empty(self) -> bool:
        """True when the caller may not review anything at all."""
        return not self.is_global_reviewer and not self.team_ids


async def review_scope(db: AsyncSession, user: User) -> ReviewScope:
    """Resolve the caller's review capability once, for both listing and acting.

    The review queue and the approve and reject actions must agree on what a
    caller may touch, so both read this single answer instead of re-deriving it.
    """
    if is_admin(user):
        # An admin reviews every item regardless of teamspace, so their own
        # memberships would not widen anything and the query is skipped.
        return ReviewScope(is_admin=True, is_global_reviewer=True, team_ids=frozenset())

    rows = await db.execute(
        select(TeamMembership.team_id).where(
            TeamMembership.user_id == user.id,
            TeamMembership.role.in_(REVIEWING_TEAM_ROLES),
        )
    )
    return ReviewScope(
        is_admin=False,
        is_global_reviewer=is_global_reviewer(user),
        team_ids=frozenset(row[0] for row in rows),
    )


def can_review(entity, scope: ReviewScope) -> bool:
    """Whether this caller may review one listing, agent version, or agent.

    Decided from the item's own visibility, never from what the caller asked for.
    A team-private item belongs to its teamspace: only that teamspace's owners and
    reviewers, plus admins, may act on it, which is what keeps private titles away
    from a global reviewer who is not in the team. A public item is the global
    catalog: only a global reviewer and above may act on it, so a team owner cannot
    walk a listing out of their own namespace into everyone's registry. Reviewing
    their OWN submission is allowed — team publishes never auto-approve, so
    self-approval is the recorded decision that replaces the old silent skip.

    A private item with no teamspace is a personal listing. Nobody holds a team
    role over it, so it stays admin-only.
    """
    if scope.is_admin:
        return True
    if getattr(entity, "is_private", False):
        team_id = getattr(entity, "team_id", None)
        return team_id is not None and team_id in scope.team_ids
    return scope.is_global_reviewer


async def user_team_ids(db: AsyncSession, user_id: uuid.UUID) -> list[uuid.UUID]:
    rows = await db.execute(select(TeamMembership.team_id).where(TeamMembership.user_id == user_id))
    return list(rows.scalars().all())


def team_visible_to(team: Team, membership: TeamMembership | None, user: User) -> bool:
    """Whether this caller may see this teamspace at all.

    Public teamspaces are visible to every signed-in user. A private one is
    visible only to its members and to global reviewers, admins, and
    super_admins — hidden precisely from other plain users, like a private
    GitHub org. Callers that fail this get 404, never 403, so a private
    handle's existence is not confirmed.
    """
    if not team.is_private:
        return True
    return membership is not None or is_global_reviewer(user)


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
    # Publishing into a teamspace you do not belong to is an admin capability, not a
    # reviewer one. A global reviewer cannot read another team's private listings, so
    # letting one publish a team-private item here would create a listing its author
    # can no longer see. Admins keep it because they can still read the result.
    if not membership and not is_admin(user):
        raise HTTPException(status_code=403, detail="You are not a member of this teamspace")

    # NOTHING published into a teamspace auto-approves. Every submission enters
    # the review queue; team owners and team reviewers may then explicitly
    # approve — including their own submissions — so every release carries a
    # recorded reviewed_by decision instead of a silent skip.
    return PublishTarget(
        namespace=team.handle,
        slug=slugify(name),
        team_id=team.id,
        visibility=target_visibility,
        owner=team.handle,
        auto_approve=False,
    )


async def publish_auto_approves_for_entity(entity, user: User, db: AsyncSession) -> bool:
    """Return whether this actor can publish an already saved team item without review.

    Always False: teamspace publishing never auto-approves. Team owners and
    team reviewers clear their own queue explicitly (self-approval is allowed),
    so approval is a recorded decision rather than a side effect of publishing.
    The helper survives so every publish path keeps one policy chokepoint.
    """
    del entity, user, db
    return False


async def review_publication_to_public(entity, user: User, db: AsyncSession, *, was_private: bool) -> bool:
    """Send a listing back to the review queue when it becomes publicly visible.

    Turning a team-private listing public publishes it into the global registry, so
    it has to clear global review. Without this, team review is trivially
    bypassed in two steps: publish as team visibility, which a team owner or
    team reviewer approves for themselves because only their own teamspace can
    see it, then flip the same approved row to public and reach every user
    without a global reviewer ever seeing it.

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

    # EVERY approved version returns to the queue, not just the latest. Older
    # versions were approved by a team role for a team-only audience, and installs
    # can pin any approved version, so leaving them approved would publish content
    # no global reviewer ever saw.
    version_model, listing_column = _version_model_for(entity)
    approved = _approved_status(entity)
    pending = _pending_status(entity)
    rows = (
        await db.execute(select(version_model).where(listing_column == entity.id, version_model.status == approved))
    ).scalars()
    for row in rows:
        row.status = pending
        row.reviewed_by = None
        row.reviewed_at = None

    # The listing's own status mirrors its latest version, so set it explicitly in
    # case the latest version was not among the rows above.
    entity.status = pending
    version.reviewed_by = None
    version.reviewed_at = None
    return True


def _version_model_for(entity):
    """Return (version model, the column linking a version back to its listing)."""
    from models.agent import Agent, AgentVersion

    if isinstance(entity, Agent):
        return AgentVersion, AgentVersion.agent_id
    version_model = type(entity).__mapper__.relationships["latest_version"].entity.class_
    return version_model, version_model.listing_id


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
