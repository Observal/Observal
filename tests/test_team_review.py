# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Tests for the team-scoped review queue at /api/v1/review.

Every route in api/routes/review.py used to sit behind require_role(UserRole.reviewer),
the GLOBAL role, which produced two defects at once:

1. A team-private item published by a plain team member landed in the global queue,
   where only a reviewer outside the team could approve it. Team-private titles were
   routed to outsiders and the team stayed blocked until one of them acted.
2. The "reviewer" team role granted no review capability whatsoever. A team owner and
   a team reviewer both got 403 on the queue and on approve.

Review is now capability scoped. The queue, the detail view, and the approve and
reject actions all read one ReviewScope, so the list and the actions cannot drift
apart: whatever a caller cannot see in the queue, they also cannot approve.

The escalation this must not open is the mirror of the one team_role_self_publishes
closes at publish time. Team roles are self-service, so a team owner who could approve
a PUBLIC listing standing in their own team namespace would have a one-step route into
the global catalog. Public items therefore stay with global reviewers, team roles or not.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.deps import get_current_user, get_db
from api.routes.review import router as review_router
from models.agent import Agent, AgentStatus, AgentVersion
from models.agent_component import AgentComponent
from models.base import Base
from models.hook import HookListing, HookVersion
from models.mcp import ListingStatus, McpListing, McpValidationResult, McpVersion
from models.prompt import PromptListing, PromptVersion
from models.sandbox import SandboxListing, SandboxVersion
from models.skill import SkillListing, SkillVersion
from models.team import Team, TeamMembership, TeamRole
from models.user import User, UserRole

# The default queue walks agents plus all five component types, so every one of
# those tables has to exist even when a case only seeds MCPs.
_TABLES = [
    User.__table__,
    Team.__table__,
    TeamMembership.__table__,
    McpListing.__table__,
    McpVersion.__table__,
    McpValidationResult.__table__,
    SkillListing.__table__,
    SkillVersion.__table__,
    HookListing.__table__,
    HookVersion.__table__,
    PromptListing.__table__,
    PromptVersion.__table__,
    SandboxListing.__table__,
    SandboxVersion.__table__,
    Agent.__table__,
    AgentVersion.__table__,
    AgentComponent.__table__,
]

_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)


@asynccontextmanager
async def _sessions():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=_TABLES)
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


def _actor(user: User) -> SimpleNamespace:
    """The request-scoped view of a seeded user, as get_current_user hands it over."""
    return SimpleNamespace(id=user.id, role=user.role, email=user.email, username=user.username)


def _user(handle: str, role: UserRole = UserRole.user) -> User:
    return User(
        id=uuid.uuid4(),
        email=f"{handle}@example.com",
        username=handle,
        name=handle,
        role=role,
    )


def _mcp(name: str, *, team_id, is_private: bool, submitted_by) -> McpListing:
    return McpListing(
        id=uuid.uuid4(),
        name=name,
        namespace="acme",
        slug=name,
        category="general",
        owner="acme",
        submitted_by=submitted_by,
        team_id=team_id,
        is_private=is_private,
        co_authors=[],
    )


def _mcp_version(listing: McpListing, released_by) -> McpVersion:
    return McpVersion(
        id=uuid.uuid4(),
        listing_id=listing.id,
        version="1.0.0",
        description=f"{listing.name} description",
        released_by=released_by,
        released_at=_EPOCH,
        status=ListingStatus.pending,
    )


@asynccontextmanager
async def _client(sessions, actor):
    async with sessions() as session:
        app = FastAPI()
        app.include_router(review_router)
        app.dependency_overrides[get_db] = lambda: session
        app.dependency_overrides[get_current_user] = lambda: actor
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client


async def _seed(sessions):
    """One teamspace holding a pending team-private MCP, a pending public MCP, and a pending team-private agent.

    Every item is submitted by a plain team member, which is the case the whole
    feature exists for: a member publishes, and someone has to clear the queue.
    """
    owner = _user("teamowner")
    reviewer = _user("teamreviewer")
    member = _user("teammember")
    outsider = _user("outsider")
    other_owner = _user("otherowner")
    global_reviewer = _user("globalreviewer", role=UserRole.reviewer)
    admin = _user("admin", role=UserRole.admin)

    team = Team(id=uuid.uuid4(), name="Acme", handle="acme", created_by=owner.id)
    other_team = Team(id=uuid.uuid4(), name="Other", handle="other", created_by=other_owner.id)
    memberships = [
        TeamMembership(team_id=team.id, user_id=owner.id, role=TeamRole.owner),
        TeamMembership(team_id=team.id, user_id=reviewer.id, role=TeamRole.reviewer),
        TeamMembership(team_id=team.id, user_id=member.id, role=TeamRole.member),
        TeamMembership(team_id=other_team.id, user_id=other_owner.id, role=TeamRole.owner),
    ]

    private = _mcp("internal", team_id=team.id, is_private=True, submitted_by=member.id)
    public = _mcp("shared", team_id=team.id, is_private=False, submitted_by=member.id)

    agent = Agent(
        id=uuid.uuid4(),
        name="Triage",
        namespace="acme",
        slug="triage",
        owner="acme",
        created_by=member.id,
        team_id=team.id,
        is_private=True,
        co_authors=[],
    )
    agent_version = AgentVersion(
        id=uuid.uuid4(),
        agent_id=agent.id,
        version="1.0.0",
        model_name="claude-sonnet-4-5",
        released_by=member.id,
        status=AgentStatus.pending,
        created_at=_EPOCH,
    )

    async with sessions() as session:
        session.add_all([owner, reviewer, member, outsider, other_owner, global_reviewer, admin])
        session.add_all([team, other_team, *memberships])
        # Listings go in before their versions: listing.versions and
        # listing.latest_version point at each other, so flushing both in one unit
        # of work makes SQLAlchemy see a circular dependency.
        session.add_all([private, public, agent])
        await session.flush()
        for listing in (private, public):
            version = _mcp_version(listing, member.id)
            session.add(version)
            await session.flush()
            listing.latest_version_id = version.id
        session.add(agent_version)
        await session.flush()
        agent.latest_version_id = agent_version.id
        await session.commit()

    return SimpleNamespace(
        team_owner=_actor(owner),
        team_reviewer=_actor(reviewer),
        team_member=_actor(member),
        outsider=_actor(outsider),
        other_owner=_actor(other_owner),
        global_reviewer=_actor(global_reviewer),
        admin=_actor(admin),
        team_id=team.id,
        other_team_id=other_team.id,
        private_id=private.id,
        public_id=public.id,
        agent_id=agent.id,
    )


async def _queue(sessions, actor, **params):
    async with _client(sessions, actor) as client:
        return await client.get("/api/v1/review", params=params)


def _names(response) -> set[str]:
    return {item["name"] for item in response.json()}


# ── The queue: who may open it at all ──────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("who", ["team_owner", "team_reviewer", "global_reviewer", "admin"])
async def test_review_capability_opens_the_queue(who):
    async with _sessions() as sessions:
        seed = await _seed(sessions)
        response = await _queue(sessions, getattr(seed, who))
    assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("who", ["team_member", "outsider"])
async def test_no_review_capability_is_403_not_an_empty_queue(who):
    """A plain member and a non-member keep the 'you have no business here' signal.

    Answering 200 with [] would read as "nothing to review" and hide the fact that
    the caller holds no review capability at all.
    """
    async with _sessions() as sessions:
        seed = await _seed(sessions)
        response = await _queue(sessions, getattr(seed, who))
    assert response.status_code == 403
    assert response.json()["detail"] == "Insufficient permissions"


# ── The queue: what each capability contains ───────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("who", ["team_owner", "team_reviewer"])
async def test_team_review_roles_see_their_teams_private_items(who):
    async with _sessions() as sessions:
        seed = await _seed(sessions)
        response = await _queue(sessions, getattr(seed, who))
    assert response.status_code == 200
    assert "internal" in _names(response)


@pytest.mark.asyncio
@pytest.mark.parametrize("who", ["team_owner", "team_reviewer"])
async def test_team_review_roles_do_not_see_their_teams_public_items(who):
    """They cannot approve a public item, so listing it would only mislead them."""
    async with _sessions() as sessions:
        seed = await _seed(sessions)
        response = await _queue(sessions, getattr(seed, who))
    assert "shared" not in _names(response)


@pytest.mark.asyncio
async def test_team_review_roles_see_their_teams_private_agents():
    """Agents carry team_id and is_private too, so they scope the same way."""
    async with _sessions() as sessions:
        seed = await _seed(sessions)
        response = await _queue(sessions, seed.team_owner)
    assert "Triage" in _names(response)


@pytest.mark.asyncio
async def test_global_reviewer_sees_public_pending_items():
    async with _sessions() as sessions:
        seed = await _seed(sessions)
        response = await _queue(sessions, seed.global_reviewer)
    assert response.status_code == 200
    assert "shared" in _names(response)


@pytest.mark.asyncio
async def test_global_reviewer_never_sees_team_private_items():
    """The privacy fix: private titles must not reach a reviewer outside the team."""
    async with _sessions() as sessions:
        seed = await _seed(sessions)
        response = await _queue(sessions, seed.global_reviewer)
    assert "internal" not in _names(response)
    assert "Triage" not in _names(response)
    assert "internal" not in response.text


@pytest.mark.asyncio
async def test_admin_sees_public_and_private_items():
    async with _sessions() as sessions:
        seed = await _seed(sessions)
        response = await _queue(sessions, seed.admin)
    assert {"internal", "shared", "Triage"} <= _names(response)


@pytest.mark.asyncio
async def test_a_team_owner_does_not_see_another_teams_private_items():
    """The teamspace grants the item, not merely holding a team role somewhere."""
    async with _sessions() as sessions:
        seed = await _seed(sessions)
        response = await _queue(sessions, seed.other_owner)
    assert response.status_code == 200
    assert _names(response) == set()


@pytest.mark.asyncio
async def test_another_teams_owner_cannot_approve_this_teams_private_item():
    async with _sessions() as sessions:
        seed = await _seed(sessions)
        response = await _approve(sessions, seed.other_owner, seed.private_id)
    assert response.status_code == 404


# ── The queue: ?team_id= narrowing ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_team_id_filter_narrows_to_that_teamspace():
    async with _sessions() as sessions:
        seed = await _seed(sessions)
        response = await _queue(sessions, seed.team_owner, team_id=str(seed.team_id))
    assert response.status_code == 200
    assert "internal" in _names(response)


@pytest.mark.asyncio
async def test_team_id_filter_for_a_teamspace_the_caller_does_not_review_for_is_403():
    async with _sessions() as sessions:
        seed = await _seed(sessions)
        response = await _queue(sessions, seed.team_owner, team_id=str(seed.other_team_id))
    assert response.status_code == 403
    assert response.json()["detail"] == "You do not review for this teamspace"


@pytest.mark.asyncio
async def test_team_id_filter_drops_items_from_other_teamspaces():
    async with _sessions() as sessions:
        seed = await _seed(sessions)
        response = await _queue(sessions, seed.admin, team_id=str(seed.other_team_id))
    assert response.status_code == 200
    assert _names(response) == set()


@pytest.mark.asyncio
async def test_team_id_filter_does_not_widen_a_global_reviewer():
    """Narrowing to a teamspace still cannot surface that teamspace's private items."""
    async with _sessions() as sessions:
        seed = await _seed(sessions)
        response = await _queue(sessions, seed.global_reviewer, team_id=str(seed.team_id))
    assert response.status_code == 200
    assert _names(response) == {"shared"}


# ── Approving a team-private item ──────────────────────────────────────────


async def _approve(sessions, actor, listing_id):
    async with _client(sessions, actor) as client:
        return await client.post(f"/api/v1/review/{listing_id}/approve")


async def _reject(sessions, actor, listing_id, reason="not yet"):
    async with _client(sessions, actor) as client:
        return await client.post(f"/api/v1/review/{listing_id}/reject", json={"reason": reason})


@pytest.mark.asyncio
@pytest.mark.parametrize("who", ["team_owner", "team_reviewer", "admin"])
async def test_team_private_item_is_approved_inside_its_team(who):
    async with _sessions() as sessions:
        seed = await _seed(sessions)
        response = await _approve(sessions, getattr(seed, who), seed.private_id)
        assert response.status_code == 200
        assert response.json()["status"] == ListingStatus.approved.value

        async with sessions() as session:
            listing = await session.get(McpListing, seed.private_id)
            version = await session.get(McpVersion, listing.latest_version_id)
            assert version.status == ListingStatus.approved
            assert version.reviewed_by == getattr(seed, who).id
            assert version.reviewed_at is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("who", ["team_member", "outsider"])
async def test_team_private_item_is_not_approved_without_a_review_role(who):
    async with _sessions() as sessions:
        seed = await _seed(sessions)
        response = await _approve(sessions, getattr(seed, who), seed.private_id)
        assert response.status_code == 403

        async with sessions() as session:
            listing = await session.get(McpListing, seed.private_id)
            version = await session.get(McpVersion, listing.latest_version_id)
            assert version.status == ListingStatus.pending


@pytest.mark.asyncio
async def test_global_reviewer_cannot_approve_a_team_private_item():
    async with _sessions() as sessions:
        seed = await _seed(sessions)
        response = await _approve(sessions, seed.global_reviewer, seed.private_id)
        assert response.status_code == 404

        async with sessions() as session:
            listing = await session.get(McpListing, seed.private_id)
            version = await session.get(McpVersion, listing.latest_version_id)
            assert version.status == ListingStatus.pending


@pytest.mark.asyncio
async def test_team_reviewer_rejects_a_team_private_item():
    async with _sessions() as sessions:
        seed = await _seed(sessions)
        response = await _reject(sessions, seed.team_reviewer, seed.private_id, reason="needs docs")
        assert response.status_code == 200

        async with sessions() as session:
            listing = await session.get(McpListing, seed.private_id)
            version = await session.get(McpVersion, listing.latest_version_id)
            assert version.status == ListingStatus.rejected
            assert version.rejection_reason == "needs docs"


@pytest.mark.asyncio
async def test_global_reviewer_cannot_reject_a_team_private_item():
    async with _sessions() as sessions:
        seed = await _seed(sessions)
        response = await _reject(sessions, seed.global_reviewer, seed.private_id)
        assert response.status_code == 404


# ── Approving a public item ────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("who", ["global_reviewer", "admin"])
async def test_public_item_is_approved_by_a_global_role(who):
    async with _sessions() as sessions:
        seed = await _seed(sessions)
        response = await _approve(sessions, getattr(seed, who), seed.public_id)
        assert response.status_code == 200

        async with sessions() as session:
            listing = await session.get(McpListing, seed.public_id)
            version = await session.get(McpVersion, listing.latest_version_id)
            assert version.status == ListingStatus.approved


@pytest.mark.asyncio
@pytest.mark.parametrize("who", ["team_owner", "team_reviewer"])
async def test_team_role_cannot_approve_a_public_item_in_its_own_namespace(who):
    """The escalation this closes: team roles are self-service, so a team owner who
    could approve a public listing standing in their own namespace would promote
    anything into the global catalog by first promoting themselves."""
    async with _sessions() as sessions:
        seed = await _seed(sessions)
        response = await _approve(sessions, getattr(seed, who), seed.public_id)
        assert response.status_code == 403
        assert response.json()["detail"] == "Public items are reviewed by global reviewers, not by teamspace roles"

        async with sessions() as session:
            listing = await session.get(McpListing, seed.public_id)
            version = await session.get(McpVersion, listing.latest_version_id)
            assert version.status == ListingStatus.pending


@pytest.mark.asyncio
async def test_team_role_cannot_reject_a_public_item_in_its_own_namespace():
    async with _sessions() as sessions:
        seed = await _seed(sessions)
        response = await _reject(sessions, seed.team_owner, seed.public_id)
        assert response.status_code == 403


# ── Agents ─────────────────────────────────────────────────────────────────


async def _approve_agent(sessions, actor, agent_id):
    async with _client(sessions, actor) as client:
        return await client.post(f"/api/v1/review/agents/{agent_id}/approve")


@pytest.mark.asyncio
@pytest.mark.parametrize("who", ["team_owner", "team_reviewer", "admin"])
async def test_team_private_agent_is_approved_inside_its_team(who):
    async with _sessions() as sessions:
        seed = await _seed(sessions)
        response = await _approve_agent(sessions, getattr(seed, who), seed.agent_id)
        assert response.status_code == 200
        assert response.json()["status"] == "approved"

        async with sessions() as session:
            agent = await session.get(Agent, seed.agent_id)
            version = await session.get(AgentVersion, agent.latest_version_id)
            assert version.status == AgentStatus.approved


@pytest.mark.asyncio
async def test_global_reviewer_cannot_approve_a_team_private_agent():
    async with _sessions() as sessions:
        seed = await _seed(sessions)
        response = await _approve_agent(sessions, seed.global_reviewer, seed.agent_id)
        assert response.status_code == 404

        async with sessions() as session:
            agent = await session.get(Agent, seed.agent_id)
            version = await session.get(AgentVersion, agent.latest_version_id)
            assert version.status == AgentStatus.pending


@pytest.mark.asyncio
async def test_team_member_cannot_reject_a_team_private_agent():
    async with _sessions() as sessions:
        seed = await _seed(sessions)
        async with _client(sessions, seed.team_member) as client:
            response = await client.post(
                f"/api/v1/review/agents/{seed.agent_id}/reject",
                json={"reason": "no"},
            )
    assert response.status_code == 403


# ── The detail view follows the queue ──────────────────────────────────────


async def _detail(sessions, actor, listing_id):
    async with _client(sessions, actor) as client:
        return await client.get(f"/api/v1/review/{listing_id}")


@pytest.mark.asyncio
@pytest.mark.parametrize("who", ["team_owner", "team_reviewer", "admin"])
async def test_team_private_detail_opens_for_its_team(who):
    async with _sessions() as sessions:
        seed = await _seed(sessions)
        response = await _detail(sessions, getattr(seed, who), seed.private_id)
    assert response.status_code == 200
    assert response.json()["name"] == "internal"


@pytest.mark.asyncio
async def test_team_private_detail_is_404_for_a_global_reviewer():
    """404, not 403: a 403 would confirm the item exists to the reviewer the
    scoping keeps away from it, and the queue already hides it."""
    async with _sessions() as sessions:
        seed = await _seed(sessions)
        response = await _detail(sessions, seed.global_reviewer, seed.private_id)
    assert response.status_code == 404
    assert "internal" not in response.text


@pytest.mark.asyncio
async def test_team_private_agent_detail_is_404_for_a_global_reviewer():
    async with _sessions() as sessions:
        seed = await _seed(sessions)
        response = await _detail(sessions, seed.global_reviewer, seed.agent_id)
    assert response.status_code == 404
    assert "Triage" not in response.text


@pytest.mark.asyncio
async def test_public_detail_is_404_for_a_team_role_that_cannot_act_on_it():
    """The detail view and the queue read one scope, so they cannot drift apart."""
    async with _sessions() as sessions:
        seed = await _seed(sessions)
        response = await _detail(sessions, seed.team_owner, seed.public_id)
    assert response.status_code == 404


# ── Deleting a teamspace must not strip access from its listings ─────────────


class TestTeamDeletionGuard:
    """ON DELETE SET NULL turns a team-private listing into an orphan.

    Reproduced against a live stack before the guard existed: deleting a team
    returned 204, and the listing kept is_private=True with team_id=NULL. Its
    submitter still reached it through the personal-private clause, but every
    other member went from 200 to 404 with no warning, and the listing still
    reported visibility "team" while belonging to no team. Freeing the handle
    also lets the next registrant claim that namespace.
    """

    @staticmethod
    def _team():
        team = MagicMock()
        team.id = uuid.uuid4()
        team.handle = "platform-tools"
        return team

    @pytest.mark.asyncio
    async def test_delete_is_refused_while_the_team_owns_listings(self):
        from api.routes.teams import delete_team

        team = self._team()
        db = AsyncMock()
        # One skill left in the teamspace is enough to block the delete.
        # agents, mcp, skill, hook, prompt, sandbox, component_source
        db.scalar = AsyncMock(side_effect=[0, 0, 1, 0, 0, 0, 0])

        with (
            patch("api.routes.teams._require_owner_or_admin", new=AsyncMock(return_value=team)),
            pytest.raises(HTTPException) as exc,
        ):
            await delete_team(team_id=team.id, db=db, current_user=MagicMock())

        assert exc.value.status_code == 409
        assert "1 skill" in exc.value.detail
        assert "platform-tools" in exc.value.detail
        db.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_proceeds_for_an_empty_teamspace(self):
        from api.routes.teams import delete_team

        team = self._team()
        db = AsyncMock()
        db.scalar = AsyncMock(return_value=0)

        with patch("api.routes.teams._require_owner_or_admin", new=AsyncMock(return_value=team)):
            await delete_team(team_id=team.id, db=db, current_user=MagicMock())

        db.delete.assert_awaited_once_with(team)
        db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_every_listing_kind_is_counted(self):
        """A teamspace holding only sandboxes must block too, not just skills."""
        from api.routes.teams import delete_team

        team = self._team()
        db = AsyncMock()
        db.scalar = AsyncMock(side_effect=[0, 0, 0, 0, 0, 2, 0])

        with (
            patch("api.routes.teams._require_owner_or_admin", new=AsyncMock(return_value=team)),
            pytest.raises(HTTPException) as exc,
        ):
            await delete_team(team_id=team.id, db=db, current_user=MagicMock())

        assert exc.value.status_code == 409
        assert "2 sandboxes" in exc.value.detail
