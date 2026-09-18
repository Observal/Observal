# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Who may see which discovery entries.

Reproduces the registry's rules (ADR 0001, Decision 6) as a SQL predicate:

1. Privacy — same as ``api.deps.apply_visibility_filter``: public entries to
   everyone, owner-private entries to their submitter, team-private entries to
   team members, everything to admins and super-admins.
2. Lifecycle — approved entries to everyone who passes (1); pending, rejected
   and draft entries only to the owner or a co-author (the owner fallback that
   install already honours); reviewers additionally see pending entries, which
   is their queue, but not other people's drafts or rejections; archived
   entries only when asked for explicitly.

Anonymous callers see public approved entries, and only when the deployment
has switched public search on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, or_, select, true

from models.discovery_entry import DiscoveryEntry, DiscoveryLifecycle, DiscoveryVisibility
from models.team import TeamMembership
from models.user import UserRole

if TYPE_CHECKING:
    import uuid

_ADMIN_ROLES = {UserRole.admin, UserRole.super_admin}

# Lifecycle states returned when the caller does not filter on obs:lifecycle.
DEFAULT_LIFECYCLES: tuple[DiscoveryLifecycle, ...] = (
    DiscoveryLifecycle.approved,
    DiscoveryLifecycle.pending,
    DiscoveryLifecycle.rejected,
    DiscoveryLifecycle.draft,
)


def _is_admin(user: Any | None) -> bool:
    return user is not None and getattr(user, "role", None) in _ADMIN_ROLES


def _is_reviewer(user: Any | None) -> bool:
    return user is not None and getattr(user, "role", None) == UserRole.reviewer


def privacy_predicate(user: Any | None):
    """Which entries the caller is allowed to know exist."""
    public = DiscoveryEntry.visibility == DiscoveryVisibility.public
    if user is None:
        return public
    if _is_admin(user):
        return true()
    user_id: uuid.UUID = user.id
    own = and_(DiscoveryEntry.visibility == DiscoveryVisibility.owner, DiscoveryEntry.owner_user_id == user_id)
    member = (
        select(TeamMembership.id)
        .where(TeamMembership.team_id == DiscoveryEntry.team_id, TeamMembership.user_id == user_id)
        .correlate(DiscoveryEntry)
        .exists()
    )
    team = and_(DiscoveryEntry.visibility == DiscoveryVisibility.team, member)
    return or_(public, own, team)


def lifecycle_predicate(user: Any | None, lifecycles: tuple[DiscoveryLifecycle, ...] = DEFAULT_LIFECYCLES):
    """Which lifecycle states the caller may see among the requested ones."""
    wanted = set(lifecycles)
    approved_wanted = DiscoveryLifecycle.approved in wanted
    unapproved_wanted = wanted - {DiscoveryLifecycle.approved}

    clauses = []
    if approved_wanted:
        clauses.append(DiscoveryEntry.lifecycle_status == DiscoveryLifecycle.approved)
    if unapproved_wanted and user is not None:
        in_unapproved = DiscoveryEntry.lifecycle_status.in_(list(unapproved_wanted))
        owner = DiscoveryEntry.owner_user_id == user.id
        co_author = DiscoveryEntry.co_author_ids.like(f"%{user.id}%")
        if _is_admin(user):
            clauses.append(in_unapproved)
        elif _is_reviewer(user):
            # A reviewer's mandate is the queue: pending items, plus their own work.
            own = and_(in_unapproved, or_(owner, co_author))
            queue = DiscoveryEntry.lifecycle_status == DiscoveryLifecycle.pending
            clauses.append(or_(own, queue) if DiscoveryLifecycle.pending in wanted else own)
        else:
            clauses.append(and_(in_unapproved, or_(owner, co_author)))
    if not clauses:
        # Nothing the caller is allowed to see in the requested states.
        return DiscoveryEntry.id.is_(None)
    return or_(*clauses)


def visible_entries_predicate(
    user: Any | None,
    *,
    lifecycles: tuple[DiscoveryLifecycle, ...] = DEFAULT_LIFECYCLES,
):
    """Complete predicate: live, allowed to see, and in a permitted lifecycle."""
    return and_(
        DiscoveryEntry.tombstoned_at.is_(None),
        privacy_predicate(user),
        lifecycle_predicate(user, lifecycles),
    )
