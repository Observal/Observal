# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Teamspace visibility and open creation.

Private teamspaces work like private GitHub orgs: hidden from plain users who
are not members — discovery, by-handle resolution, detail, and join requests
all answer as if the teamspace does not exist — while members, global
reviewers, admins, and super_admins keep seeing them. Visibility is changed by
team owners and team reviewers (and deployment admins). Creation is open to
every signed-in user, who becomes the new teamspace's owner.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.deps import get_current_user, get_db
from api.routes.teams import router as teams_router
from models.base import Base
from models.inbox import InboxItem, InboxItemEvent
from models.team import Team, TeamMembership, TeamMembershipRequest, TeamRole
from models.user import User, UserRole

_TABLES = [
    User.__table__,
    Team.__table__,
    TeamMembership.__table__,
    TeamMembershipRequest.__table__,
    InboxItem.__table__,
    InboxItemEvent.__table__,
]


@pytest_asyncio.fixture()
async def sessions():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=_TABLES)
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def _user(db, role=UserRole.user) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex[:8]}@example.test",
        username=uuid.uuid4().hex[:12],
        name="Test User",
        password_hash="x",
        role=role,
    )
    db.add(user)
    await db.flush()
    return user


@asynccontextmanager
async def _client(sessions, actor: User):
    async with sessions() as session:
        app = FastAPI()
        app.include_router(teams_router)
        app.dependency_overrides[get_db] = lambda: session
        app.dependency_overrides[get_current_user] = lambda: actor
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, session


async def _seed(sessions):
    """A private team with an owner, reviewer, and member, plus bystanders."""
    async with sessions() as db:
        owner = await _user(db)
        team_reviewer = await _user(db)
        member = await _user(db)
        outsider = await _user(db)
        global_reviewer = await _user(db, role=UserRole.reviewer)
        admin = await _user(db, role=UserRole.admin)
        team = Team(
            id=uuid.uuid4(),
            name="Secret Ops",
            handle=f"secret-{uuid.uuid4().hex[:8]}",
            is_private=True,
            created_by=owner.id,
        )
        db.add(team)
        await db.flush()
        db.add(TeamMembership(team_id=team.id, user_id=owner.id, role=TeamRole.owner))
        db.add(TeamMembership(team_id=team.id, user_id=team_reviewer.id, role=TeamRole.reviewer))
        db.add(TeamMembership(team_id=team.id, user_id=member.id, role=TeamRole.member))
        await db.commit()
        return owner, team_reviewer, member, outsider, global_reviewer, admin, team


# ── Creation is open to everyone ─────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRole.user, UserRole.reviewer, UserRole.admin, UserRole.super_admin])
async def test_any_signed_in_user_creates_a_teamspace_and_owns_it(sessions, role):
    async with sessions() as db:
        creator = await _user(db, role=role)
        await db.commit()
    async with _client(sessions, creator) as (client, _):
        response = await client.post("/api/v1/teams", json={"name": "My Team", "handle": f"my-{uuid.uuid4().hex[:8]}"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["role"] == "owner"
    assert body["visibility"] == "public"


@pytest.mark.asyncio
async def test_creation_honors_requested_visibility(sessions):
    async with sessions() as db:
        creator = await _user(db)
        await db.commit()
    async with _client(sessions, creator) as (client, _):
        response = await client.post(
            "/api/v1/teams",
            json={"name": "Quiet Team", "handle": f"quiet-{uuid.uuid4().hex[:8]}", "visibility": "private"},
        )
    assert response.status_code == 200
    assert response.json()["visibility"] == "private"


# ── Private teamspaces are hidden from plain non-members ─────────────


@pytest.mark.asyncio
async def test_private_team_is_hidden_from_plain_non_members_everywhere(sessions):
    _owner, _rev, _member, outsider, _gr, _admin, team = await _seed(sessions)
    async with _client(sessions, outsider) as (client, _):
        listing = await client.get("/api/v1/teams/all")
        by_handle = await client.get(f"/api/v1/teams/by-handle/{team.handle}")
        detail = await client.get(f"/api/v1/teams/{team.id}")
        join = await client.post(f"/api/v1/teams/{team.id}/join-requests", json={})
    assert team.handle not in {row["handle"] for row in listing.json()}
    # Hidden and nonexistent are indistinguishable: 404 everywhere, never 403.
    assert by_handle.status_code == 404
    assert detail.status_code == 404
    assert join.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("who", ["member", "global_reviewer", "admin"])
async def test_private_team_stays_visible_to_members_and_global_roles(sessions, who):
    owner, team_reviewer, member, _outsider, global_reviewer, admin, team = await _seed(sessions)
    actor = {"member": member, "global_reviewer": global_reviewer, "admin": admin}[who]
    async with _client(sessions, actor) as (client, _):
        listing = await client.get("/api/v1/teams/all")
        by_handle = await client.get(f"/api/v1/teams/by-handle/{team.handle}")
    assert team.handle in {row["handle"] for row in listing.json()}
    assert by_handle.status_code == 200
    assert by_handle.json()["visibility"] == "private"


# ── Changing visibility ──────────────────────────────────────────────


async def _set_visibility(sessions, actor, team_id, visibility):
    async with _client(sessions, actor) as (client, _):
        return await client.patch(f"/api/v1/teams/{team_id}/visibility", json={"visibility": visibility})


@pytest.mark.asyncio
@pytest.mark.parametrize("who", ["owner", "team_reviewer", "admin"])
async def test_owners_reviewers_and_admins_change_visibility(sessions, who):
    owner, team_reviewer, _member, _outsider, _gr, admin, team = await _seed(sessions)
    actor = {"owner": owner, "team_reviewer": team_reviewer, "admin": admin}[who]
    response = await _set_visibility(sessions, actor, team.id, "public")
    assert response.status_code == 200
    assert response.json()["visibility"] == "public"


@pytest.mark.asyncio
async def test_plain_member_cannot_change_visibility(sessions):
    _owner, _rev, member, _outsider, _gr, _admin, team = await _seed(sessions)
    response = await _set_visibility(sessions, member, team.id, "public")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_global_reviewer_sees_but_cannot_change_visibility(sessions):
    """Global reviewers see private teamspaces; changing them stays a team control."""
    _owner, _rev, _member, _outsider, global_reviewer, _admin, team = await _seed(sessions)
    response = await _set_visibility(sessions, global_reviewer, team.id, "public")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_outsider_gets_404_not_403_on_a_private_team(sessions):
    _owner, _rev, _member, outsider, _gr, _admin, team = await _seed(sessions)
    response = await _set_visibility(sessions, outsider, team.id, "public")
    assert response.status_code == 404


# ── Personal private teamspace claim ─────────────────────────────────


@pytest.mark.asyncio
async def test_claim_creates_a_private_owned_teamspace_and_is_idempotent(sessions):
    async with sessions() as db:
        user = await _user(db)
        stranger = await _user(db)
        await db.commit()

    async with _client(sessions, user) as (client, _):
        first = await client.post("/api/v1/teams/claim-personal")
        again = await client.post("/api/v1/teams/claim-personal")
        mine = await client.get("/api/v1/teams")
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["visibility"] == "private"
    assert body["is_personal"] is True
    assert body["role"] == "owner"
    assert body["handle"].startswith(user.username)
    # Claiming twice hands back the same teamspace, no duplicate.
    assert again.status_code == 200
    assert again.json()["id"] == body["id"]
    assert [team["id"] for team in mine.json() if team["is_personal"]] == [body["id"]]

    async with sessions() as db:
        count = await db.scalar(
            select(func.count(Team.id)).where(Team.created_by == user.id, Team.is_personal.is_(True))
        )
    assert count == 1

    # Private by default means hidden from other plain users.
    async with _client(sessions, stranger) as (client, _):
        listing = await client.get("/api/v1/teams/all")
    assert body["handle"] not in {t["handle"] for t in listing.json()}


@pytest.mark.asyncio
async def test_claim_does_not_reuse_a_regular_team_owned_by_the_user(sessions):
    async with sessions() as db:
        user = await _user(db)
        regular = Team(
            id=uuid.uuid4(),
            name="Regular Team",
            handle=f"{user.username}-team",
            created_by=user.id,
        )
        db.add(regular)
        await db.flush()
        db.add(TeamMembership(team_id=regular.id, user_id=user.id, role=TeamRole.owner))
        await db.commit()

    async with _client(sessions, user) as (client, _):
        response = await client.post("/api/v1/teams/claim-personal")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] != str(regular.id)
    assert body["is_personal"] is True


@pytest.mark.asyncio
async def test_claim_falls_back_when_the_derived_handle_is_taken(sessions):
    async with sessions() as db:
        user = await _user(db)
        squatter = await _user(db)
        taken = Team(
            id=uuid.uuid4(),
            name="Squatted",
            handle=f"{user.username}-team",
            created_by=squatter.id,
        )
        db.add(taken)
        await db.flush()
        db.add(TeamMembership(team_id=taken.id, user_id=squatter.id, role=TeamRole.owner))
        await db.commit()

    async with _client(sessions, user) as (client, _):
        response = await client.post("/api/v1/teams/claim-personal")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["handle"] != f"{user.username}-team"
    assert body["handle"].startswith(user.username[:20])
    assert body["role"] == "owner"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path_suffix",
    [
        ("get", "/join-requests"),
        ("get", "/members"),
        ("post", "/join-requests"),
    ],
)
async def test_private_team_owner_gated_routes_answer_404_not_403(sessions, method, path_suffix):
    """A non-member holding a private team's UUID must not tell hidden from
    absent: owner/member-gated routes answer 404, exactly like a missing team,
    never a 403 that confirms the team exists."""
    _owner, _rev, _member, outsider, _gr, _admin, team = await _seed(sessions)
    async with _client(sessions, outsider) as (client, _):
        caller = getattr(client, method)
        resp = await (
            caller(f"/api/v1/teams/{team.id}{path_suffix}", json={})
            if method == "post"
            else caller(f"/api/v1/teams/{team.id}{path_suffix}")
        )
    assert resp.status_code == 404, f"{method} {path_suffix} leaked existence with {resp.status_code}"


@pytest.mark.asyncio
async def test_public_team_owner_routes_still_403_for_non_members(sessions):
    """A public team is openly listed, so 403 there is correct and leaks nothing
    — only private teams switch to 404."""
    async with sessions() as db:
        owner = await _user(db)
        outsider = await _user(db)
        team = Team(id=uuid.uuid4(), name="Open", handle=f"open-{uuid.uuid4().hex[:8]}", created_by=owner.id)
        db.add(team)
        await db.flush()
        db.add(TeamMembership(team_id=team.id, user_id=owner.id, role=TeamRole.owner))
        await db.commit()
    async with _client(sessions, outsider) as (client, _):
        members = await client.get(f"/api/v1/teams/{team.id}/members")
        queue = await client.get(f"/api/v1/teams/{team.id}/join-requests")
    assert members.status_code == 403
    assert queue.status_code == 403


@pytest.mark.asyncio
async def test_going_private_then_public_round_trips_discovery(sessions):
    async with sessions() as db:
        owner = await _user(db)
        outsider = await _user(db)
        team = Team(id=uuid.uuid4(), name="Flip", handle=f"flip-{uuid.uuid4().hex[:8]}", created_by=owner.id)
        db.add(team)
        await db.flush()
        db.add(TeamMembership(team_id=team.id, user_id=owner.id, role=TeamRole.owner))
        await db.commit()

    assert (await _set_visibility(sessions, owner, team.id, "private")).status_code == 200
    async with _client(sessions, outsider) as (client, _):
        hidden = await client.get(f"/api/v1/teams/by-handle/{team.handle}")
    assert hidden.status_code == 404

    assert (await _set_visibility(sessions, owner, team.id, "public")).status_code == 200
    async with _client(sessions, outsider) as (client, _):
        visible = await client.get(f"/api/v1/teams/by-handle/{team.handle}")
    assert visible.status_code == 200
