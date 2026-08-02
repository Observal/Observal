# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Tests for ownership transfer of teamspace listings.

Transfer rewrites ``namespace`` to the target user's handle and moves the owner
column. It never touched ``team_id`` or ``is_private``, so a team listing came
out sitting in a user namespace while still pointing at the teamspace it left,
and a team-private listing stayed private under an owner with no membership.
Neither silent repair is acceptable:

- clearing ``team_id`` and forcing ``visibility=public`` would publish a
  team-private listing as a side effect of a transfer nobody on the team
  approved, and the publish is irreversible once it is fetched;
- clearing ``team_id`` while keeping ``is_private=True`` would produce a private
  listing with no team, which is the legacy user-private shape Feature 3 removes.

So the transfer is refused for any listing that belongs to a teamspace. The
listing has to leave the teamspace first, which is an explicit, auditable act by
someone with authority over the team.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from api.routes.co_authors import TransferOwnershipRequest, transfer_ownership
from models.team import TeamRole

ENTITY_TYPES = ["agents", "mcps", "skills", "hooks", "prompts", "sandboxes"]


class _Listing(SimpleNamespace):
    @property
    def qualified_name(self):
        return f"{self.namespace}/{self.slug}"


def _listing(entity_type, owner_id, *, team_id=None, is_private=False):
    owner_field = "created_by" if entity_type == "agents" else "submitted_by"
    return _Listing(
        id=uuid.uuid4(),
        owner="platform",
        namespace="platform" if team_id else "alice",
        slug="tool",
        co_authors=[],
        team_id=team_id,
        is_private=is_private,
        owner_org_id=None,
        **{owner_field: owner_id},
    )


def _target_user():
    return SimpleNamespace(
        id=uuid.uuid4(),
        username="bob",
        email="bob@example.com",
        auth_provider="local",
    )


async def _transfer(entity_type, listing, current_user, target_user, db, *, team_role=None):
    """Run a transfer. ``team_role`` is the caller's role in the listing's teamspace."""
    membership = SimpleNamespace(role=team_role) if team_role is not None else None
    with (
        patch("api.routes.co_authors._get_entity_for_transfer", new=AsyncMock(return_value=listing)),
        patch("api.routes.co_authors._resolve_target_user", new=AsyncMock(return_value=target_user)),
        patch("api.routes.co_authors.identity_exists", new=AsyncMock(return_value=False)),
        patch("api.routes.co_authors.team_membership", new=AsyncMock(return_value=membership)),
        patch("api.routes.co_authors.is_admin", return_value=False),
        patch("api.routes.co_authors.review_publication_to_public", new=AsyncMock(return_value=True)),
    ):
        return await transfer_ownership(
            entity_type,
            listing.qualified_name,
            TransferOwnershipRequest(username="bob"),
            db,
            current_user,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("entity_type", ENTITY_TYPES)
@pytest.mark.parametrize("is_private", [False, True])
async def test_transfer_of_team_listing_needs_a_teamspace_owner(entity_type, is_private):
    """A plain member cannot walk a listing out of the teamspace."""
    current_user = SimpleNamespace(id=uuid.uuid4())
    team_id = uuid.uuid4()
    listing = _listing(entity_type, current_user.id, team_id=team_id, is_private=is_private)
    db = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())

    with pytest.raises(HTTPException) as exc:
        await _transfer(entity_type, listing, current_user, _target_user(), db, team_role=TeamRole.member)

    assert exc.value.status_code == 403
    # Nothing is rehomed, republished, or committed.
    assert listing.team_id == team_id
    assert listing.is_private is is_private
    assert listing.namespace == "platform"
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("entity_type", ENTITY_TYPES)
@pytest.mark.parametrize("is_private", [False, True])
async def test_teamspace_owner_transfer_detaches_the_listing(entity_type, is_private):
    """Transfer is the way OUT of a teamspace.

    Refusing outright used to be a dead end: deleting a teamspace requires
    emptying it, emptying it requires transferring, and transferring refused every
    team-owned listing. Leaving the teamspace also drops team visibility, because
    team-private requires a teamspace.
    """
    current_user = SimpleNamespace(id=uuid.uuid4())
    listing = _listing(entity_type, current_user.id, team_id=uuid.uuid4(), is_private=is_private)
    db = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())

    await _transfer(entity_type, listing, current_user, _target_user(), db, team_role=TeamRole.owner)

    assert listing.team_id is None
    assert listing.is_private is False
    db.commit.assert_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("entity_type", ENTITY_TYPES)
async def test_transfer_of_personal_listing_still_works(entity_type):
    current_user = SimpleNamespace(id=uuid.uuid4())
    listing = _listing(entity_type, current_user.id)
    target_user = _target_user()
    db = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())

    response = await _transfer(entity_type, listing, current_user, target_user, db)

    assert response.qualified_name == "bob/tool"
    assert listing.team_id is None
    assert listing.is_private is False
    owner_field = "created_by" if entity_type == "agents" else "submitted_by"
    assert getattr(listing, owner_field) == target_user.id
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_team_check_runs_before_the_target_user_is_resolved():
    """A refused transfer must not disclose whether the target account exists."""
    current_user = SimpleNamespace(id=uuid.uuid4())
    listing = _listing("mcps", current_user.id, team_id=uuid.uuid4())
    resolve_target = AsyncMock(side_effect=AssertionError("target user resolved before the teamspace check"))
    db = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())

    with (
        patch("api.routes.co_authors._get_entity_for_transfer", new=AsyncMock(return_value=listing)),
        patch("api.routes.co_authors._resolve_target_user", new=resolve_target),
        patch(
            "api.routes.co_authors.team_membership", new=AsyncMock(return_value=SimpleNamespace(role=TeamRole.member))
        ),
        patch("api.routes.co_authors.is_admin", return_value=False),
        pytest.raises(HTTPException) as exc,
    ):
        await transfer_ownership(
            "mcps",
            listing.qualified_name,
            TransferOwnershipRequest(username="bob"),
            db,
            current_user,
        )

    assert exc.value.status_code == 403
    resolve_target.assert_not_awaited()
