# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Teamspace join requests: request, approve, reject, cancel, and inbox wiring.

A shared /teamspaces/{handle} link must never grant access on its own. These
tests pin the whole contract: the request is explicit, only an owner or admin
decision changes the roster, duplicates are answered cleanly by the partial
unique index, and the inbox items appear and clear exactly with the request's
lifecycle — all against a real SQLite database, because the behaviour under
test includes the unique constraint and the SAVEPOINT that absorbs it.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.deps import get_current_user, get_db
from api.routes.teams import router as teams_router
from models.base import Base
from models.inbox import InboxItem, InboxItemEvent, InboxKind, InboxState
from models.team import (
    Team,
    TeamJoinRequestStatus,
    TeamMembership,
    TeamMembershipRequest,
    TeamRole,
)
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


async def _team(db, owner: User, handle: str | None = None) -> Team:
    team = Team(
        id=uuid.uuid4(),
        name="Platform Tools",
        handle=handle or f"team-{uuid.uuid4().hex[:8]}",
        created_by=owner.id,
    )
    db.add(team)
    await db.flush()
    db.add(TeamMembership(team_id=team.id, user_id=owner.id, role=TeamRole.owner))
    await db.flush()
    return team


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
    async with sessions() as db:
        owner = await _user(db)
        second_owner = await _user(db)
        member = await _user(db)
        outsider = await _user(db)
        team = await _team(db, owner)
        db.add(TeamMembership(team_id=team.id, user_id=second_owner.id, role=TeamRole.owner))
        db.add(TeamMembership(team_id=team.id, user_id=member.id, role=TeamRole.member))
        await db.commit()
        return owner, second_owner, member, outsider, team


async def _request_rows(sessions, team_id):
    async with sessions() as db:
        return (
            (await db.execute(select(TeamMembershipRequest).where(TeamMembershipRequest.team_id == team_id)))
            .scalars()
            .all()
        )


async def _inbox_rows(sessions, kind: InboxKind):
    async with sessions() as db:
        return ((await db.execute(select(InboxItem).where(InboxItem.kind == kind))).scalars().all())


# ── Requesting ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_request_creates_pending_row_and_notifies_owners_only(sessions):
    owner, second_owner, member, outsider, team = await _seed(sessions)

    async with _client(sessions, outsider) as (client, _):
        response = await client.post(f"/api/v1/teams/{team.id}/join-requests", json={"message": "hi there"})
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"
    assert body["message"] == "hi there"

    rows = await _request_rows(sessions, team.id)
    assert len(rows) == 1
    assert rows[0].status == TeamJoinRequestStatus.pending

    items = await _inbox_rows(sessions, InboxKind.team_join_requested)
    assert {item.user_id for item in items} == {owner.id, second_owner.id}
    assert all(item.action_required for item in items)
    assert all(item.action_url == f"/teamspaces/{team.handle}?tab=review-queue" for item in items)
    # The member is not an owner and the requester never notifies themselves.
    assert member.id not in {item.user_id for item in items}
    assert outsider.id not in {item.user_id for item in items}


@pytest.mark.asyncio
async def test_duplicate_pending_request_is_409(sessions):
    _owner, _second, _member, outsider, team = await _seed(sessions)

    async with _client(sessions, outsider) as (client, _):
        first = await client.post(f"/api/v1/teams/{team.id}/join-requests", json={})
        second = await client.post(f"/api/v1/teams/{team.id}/join-requests", json={})
    assert first.status_code == 201
    assert second.status_code == 409
    assert "pending request" in second.json()["detail"]
    assert len(await _request_rows(sessions, team.id)) == 1


@pytest.mark.asyncio
async def test_member_request_is_409(sessions):
    _owner, _second, member, _outsider, team = await _seed(sessions)
    async with _client(sessions, member) as (client, _):
        response = await client.post(f"/api/v1/teams/{team.id}/join-requests", json={})
    assert response.status_code == 409
    assert "already a member" in response.json()["detail"]


# ── Deciding ─────────────────────────────────────────────────────────


async def _pending_request(sessions, team, requester) -> str:
    async with _client(sessions, requester) as (client, _):
        response = await client.post(f"/api/v1/teams/{team.id}/join-requests", json={})
    assert response.status_code == 201
    return response.json()["id"]


@pytest.mark.asyncio
async def test_owner_approval_grants_member_and_clears_owner_items(sessions):
    owner, second_owner, _member, outsider, team = await _seed(sessions)
    request_id = await _pending_request(sessions, team, outsider)

    async with _client(sessions, owner) as (client, _):
        response = await client.post(f"/api/v1/teams/{team.id}/join-requests/{request_id}/approve")
    assert response.status_code == 200
    assert response.json()["status"] == "approved"

    async with sessions() as db:
        membership = (
            await db.execute(
                select(TeamMembership).where(
                    TeamMembership.team_id == team.id, TeamMembership.user_id == outsider.id
                )
            )
        ).scalar_one()
        assert membership.role == TeamRole.member
        row = (await db.execute(select(TeamMembershipRequest))).scalar_one()
        assert row.status == TeamJoinRequestStatus.approved
        assert row.decided_by == owner.id
        assert row.decided_at is not None

    decided = await _inbox_rows(sessions, InboxKind.team_join_decided)
    assert [item.user_id for item in decided] == [outsider.id]
    assert "approved" in decided[0].title

    # The decision empties the queue for EVERY owner, not only the decider.
    requested = await _inbox_rows(sessions, InboxKind.team_join_requested)
    assert requested and all(item.state == InboxState.done for item in requested)
    assert {item.user_id for item in requested} == {owner.id, second_owner.id}


@pytest.mark.asyncio
async def test_plain_member_cannot_decide(sessions):
    _owner, _second, member, outsider, team = await _seed(sessions)
    request_id = await _pending_request(sessions, team, outsider)
    async with _client(sessions, member) as (client, _):
        approve = await client.post(f"/api/v1/teams/{team.id}/join-requests/{request_id}/approve")
        listing = await client.get(f"/api/v1/teams/{team.id}/join-requests")
    assert approve.status_code == 403
    assert listing.status_code == 403
    async with sessions() as db:
        membership = (
            await db.execute(
                select(TeamMembership).where(
                    TeamMembership.team_id == team.id, TeamMembership.user_id == outsider.id
                )
            )
        ).scalar_one_or_none()
        assert membership is None


@pytest.mark.asyncio
async def test_reject_records_reason_and_allows_rerequest(sessions):
    owner, _second, _member, outsider, team = await _seed(sessions)
    request_id = await _pending_request(sessions, team, outsider)

    async with _client(sessions, owner) as (client, _):
        response = await client.post(
            f"/api/v1/teams/{team.id}/join-requests/{request_id}/reject",
            json={"reason": "Ask the SRE teamspace instead"},
        )
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert response.json()["decision_reason"] == "Ask the SRE teamspace instead"

    decided = await _inbox_rows(sessions, InboxKind.team_join_decided)
    assert decided[0].user_id == outsider.id
    assert decided[0].body == "Ask the SRE teamspace instead"
    assert "rejected" in decided[0].title

    # No membership was created, and the requester may ask again: the partial
    # unique index only blocks a second PENDING row.
    async with sessions() as db:
        membership = (
            await db.execute(
                select(TeamMembership).where(
                    TeamMembership.team_id == team.id, TeamMembership.user_id == outsider.id
                )
            )
        ).scalar_one_or_none()
        assert membership is None
    second_id = await _pending_request(sessions, team, outsider)
    assert second_id != request_id


@pytest.mark.asyncio
async def test_deciding_a_decided_request_is_409(sessions):
    owner, _second, _member, outsider, team = await _seed(sessions)
    request_id = await _pending_request(sessions, team, outsider)
    async with _client(sessions, owner) as (client, _):
        first = await client.post(f"/api/v1/teams/{team.id}/join-requests/{request_id}/approve")
        again = await client.post(f"/api/v1/teams/{team.id}/join-requests/{request_id}/reject", json={})
    assert first.status_code == 200
    assert again.status_code == 409
    assert "approved" in again.json()["detail"]


@pytest.mark.asyncio
async def test_approving_someone_already_added_directly_does_not_duplicate(sessions):
    owner, _second, _member, outsider, team = await _seed(sessions)
    request_id = await _pending_request(sessions, team, outsider)
    async with sessions() as db:
        db.add(TeamMembership(team_id=team.id, user_id=outsider.id, role=TeamRole.reviewer))
        await db.commit()

    async with _client(sessions, owner) as (client, _):
        response = await client.post(f"/api/v1/teams/{team.id}/join-requests/{request_id}/approve")
    assert response.status_code == 200

    async with sessions() as db:
        memberships = (
            (
                await db.execute(
                    select(TeamMembership).where(
                        TeamMembership.team_id == team.id, TeamMembership.user_id == outsider.id
                    )
                )
            )
            .scalars()
            .all()
        )
        # Still exactly one row, and the directly-granted role was not downgraded.
        assert len(memberships) == 1
        assert memberships[0].role == TeamRole.reviewer


# ── Withdrawing ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_requester_can_cancel_and_owner_items_clear(sessions):
    _owner, _second, _member, outsider, team = await _seed(sessions)
    request_id = await _pending_request(sessions, team, outsider)

    async with _client(sessions, outsider) as (client, _):
        response = await client.delete(f"/api/v1/teams/{team.id}/join-requests/{request_id}")
    assert response.status_code == 204

    rows = await _request_rows(sessions, team.id)
    assert rows[0].status == TeamJoinRequestStatus.cancelled
    requested = await _inbox_rows(sessions, InboxKind.team_join_requested)
    assert requested and all(item.state == InboxState.done for item in requested)
    # Withdrawal is not a decision: nobody is told it was "rejected".
    assert await _inbox_rows(sessions, InboxKind.team_join_decided) == []


@pytest.mark.asyncio
async def test_only_the_requester_can_cancel(sessions):
    owner, _second, _member, outsider, team = await _seed(sessions)
    request_id = await _pending_request(sessions, team, outsider)
    async with _client(sessions, owner) as (client, _):
        response = await client.delete(f"/api/v1/teams/{team.id}/join-requests/{request_id}")
    assert response.status_code == 403


# ── Listing and resolution ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_owner_sees_queue_and_requester_sees_mine(sessions):
    owner, _second, _member, outsider, team = await _seed(sessions)
    await _pending_request(sessions, team, outsider)

    async with _client(sessions, owner) as (client, _):
        listing = await client.get(f"/api/v1/teams/{team.id}/join-requests", params={"status": "pending"})
    assert listing.status_code == 200
    rows = listing.json()
    assert len(rows) == 1
    assert rows[0]["username"] == outsider.username
    assert rows[0]["status"] == "pending"

    async with _client(sessions, outsider) as (client, _):
        mine = await client.get(f"/api/v1/teams/{team.id}/join-requests/mine")
    assert mine.status_code == 200
    assert [row["status"] for row in mine.json()] == ["pending"]


@pytest.mark.asyncio
async def test_by_handle_resolves_role_and_member_count(sessions):
    owner, _second, _member, outsider, team = await _seed(sessions)

    async with _client(sessions, owner) as (client, _):
        as_owner = await client.get(f"/api/v1/teams/by-handle/{team.handle}")
    async with _client(sessions, outsider) as (client, _):
        as_outsider = await client.get(f"/api/v1/teams/by-handle/@{team.handle.upper()}")
        missing = await client.get("/api/v1/teams/by-handle/no-such-team")

    assert as_owner.status_code == 200
    assert as_owner.json()["role"] == "owner"
    assert as_owner.json()["member_count"] == 3
    # Non-members resolve the handle too (case- and @-insensitively) but carry
    # no role; the page offers Request to join instead.
    assert as_outsider.status_code == 200
    assert as_outsider.json()["role"] is None
    assert missing.status_code == 404
