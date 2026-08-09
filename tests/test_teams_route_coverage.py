# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Focused branch coverage for the teamspace route module.

The broader teamspace suites exercise the public HTTP contract against SQLite.
These tests call route functions with deterministic session doubles so database
errors, row locks, SQL predicates, and security event payloads are observable.
"""

from __future__ import annotations

import hashlib
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from api.routes import teams
from models.team import Team, TeamJoinRequestStatus, TeamMembership, TeamMembershipRequest, TeamRole
from models.team_invite import TeamInvite
from models.user import User, UserRole

_NOW = datetime(2026, 4, 2, 12, 0, tzinfo=UTC)
_MISSING = object()


class _FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return _NOW if tz is not None else _NOW.replace(tzinfo=None)


@pytest.fixture(autouse=True)
def _fixed_route_clock(monkeypatch):
    monkeypatch.setattr(teams, "datetime", _FixedDateTime)


class _ScalarRows:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


class _Result:
    def __init__(self, *, one=_MISSING, rows=(), scalars=_MISSING):
        self._one = one
        self._rows = list(rows)
        self._scalars = list(scalars) if scalars is not _MISSING else None

    def scalar_one_or_none(self):
        return None if self._one is _MISSING else self._one

    def all(self):
        return list(self._rows)

    def scalars(self):
        if self._scalars is not None:
            return _ScalarRows(self._scalars)
        if self._one is not _MISSING:
            return _ScalarRows([] if self._one is None else [self._one])
        return _ScalarRows(self._rows)


def _db(*results):
    database = SimpleNamespace(
        execute=AsyncMock(side_effect=list(results)),
        get=AsyncMock(return_value=None),
        scalar=AsyncMock(return_value=0),
        add=MagicMock(),
        delete=AsyncMock(),
        flush=AsyncMock(),
        commit=AsyncMock(),
        rollback=AsyncMock(),
        refresh=AsyncMock(),
    )

    @asynccontextmanager
    async def nested():
        yield

    database.begin_nested = MagicMock(side_effect=nested)
    return database


def _integrity_error(message="duplicate key"):
    return IntegrityError("statement", {}, RuntimeError(message))


def _user(*, role=UserRole.user, username="alice", name="Alice", user_id=None):
    return User(
        id=user_id or uuid.uuid4(),
        email=f"{username}@example.test",
        username=username,
        name=name,
        password_hash="x",
        role=role,
        created_at=_NOW,
    )


def _team(*, owner=None, private=False, personal=False, handle="platform", team_id=None):
    owner = owner or _user()
    return Team(
        id=team_id or uuid.uuid4(),
        name="Platform Tools",
        handle=handle,
        description="Team description",
        is_private=private,
        is_personal=personal,
        created_by=owner.id,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _membership(team, user, role=TeamRole.member):
    return TeamMembership(
        id=uuid.uuid4(),
        team_id=team.id,
        user_id=user.id,
        role=role,
        created_at=_NOW,
    )


def _invite(team, owner, *, token="invite-token", uses=0, max_uses=3, revoked_at=None):
    return TeamInvite(
        id=uuid.uuid4(),
        token_hash="a" * 64,
        token_encrypted=f"encrypted:{token}",
        name="Release partners",
        team_id=team.id,
        invited_by=owner.id,
        max_uses=max_uses,
        use_count=uses,
        expires_at=_NOW + timedelta(days=7),
        revoked_at=revoked_at,
        created_at=_NOW,
    )


def _join_request(team, requester, *, invite=None, status=TeamJoinRequestStatus.pending):
    return TeamMembershipRequest(
        id=uuid.uuid4(),
        team_id=team.id,
        user_id=requester.id,
        invite_id=invite.id if invite else None,
        status=status,
        message="Please add me",
        decided_by=None,
        decided_at=None,
        decision_reason=None,
        created_at=_NOW,
    )


def _sql(statement):
    return " ".join(str(statement.compile(compile_kwargs={"literal_binds": True})).split())


def _assert_http(exc, status, detail):
    assert exc.value.status_code == status
    assert exc.value.detail == detail


@pytest.mark.asyncio
async def test_load_helpers_lock_rows_and_hide_private_teams(monkeypatch):
    owner = _user()
    outsider = _user(username="outsider")
    team = _team(owner=owner, private=True)

    normal_db = _db()
    normal_db.get.return_value = team
    assert await teams._load_team(normal_db, team.id) is team
    normal_db.get.assert_awaited_once_with(Team, team.id)

    locked_db = _db(_Result(one=team))
    assert await teams._load_team(locked_db, team.id, for_update=True) is team
    assert locked_db.execute.await_args.args[0]._for_update_arg is not None

    missing_db = _db()
    missing_db.get.return_value = None
    with pytest.raises(HTTPException) as exc:
        await teams._load_team(missing_db, team.id)
    _assert_http(exc, 404, "Team not found")

    monkeypatch.setattr(teams, "_load_team", AsyncMock(return_value=team))
    monkeypatch.setattr(teams, "team_membership", AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as exc:
        await teams._load_visible_team(_db(), team.id, outsider)
    _assert_http(exc, 404, "Team not found")

    member = _membership(team, outsider)
    teams.team_membership.return_value = member
    assert await teams._load_visible_team(_db(), team.id, outsider) is team


@pytest.mark.asyncio
async def test_owner_guard_enforces_role_hierarchy_without_private_team_leaks(monkeypatch):
    owner = _user(username="owner")
    member = _user(username="member")
    admin = _user(role=UserRole.admin, username="admin")
    public = _team(owner=owner)
    private = _team(owner=owner, private=True)
    database = _db()

    monkeypatch.setattr(teams, "_load_team", AsyncMock(return_value=public))
    membership = AsyncMock(return_value=_membership(public, owner, TeamRole.owner))
    monkeypatch.setattr(teams, "team_membership", membership)
    assert await teams._require_owner_or_admin(database, public.id, owner) is public

    teams._load_team.return_value = private
    membership.reset_mock()
    assert await teams._require_owner_or_admin(database, private.id, admin) is private
    membership.assert_not_awaited()

    teams._load_team.return_value = public
    membership.return_value = _membership(public, member, TeamRole.reviewer)
    with pytest.raises(HTTPException) as exc:
        await teams._require_owner_or_admin(database, public.id, member)
    _assert_http(exc, 403, "Only team owners can manage this team")

    teams._load_team.return_value = private
    membership.return_value = None
    with pytest.raises(HTTPException) as exc:
        await teams._require_owner_or_admin(database, private.id, member)
    _assert_http(exc, 404, "Team not found")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("lookup", "expected"),
    [
        (SimpleNamespace(user_id=uuid.UUID(int=1), email=None, username=None), "users.id"),
        (SimpleNamespace(user_id=None, email=" USER@Example.Test ", username=None), "user@example.test"),
        (SimpleNamespace(user_id=None, email=None, username=" @alice "), "alice"),
    ],
)
async def test_resolve_member_normalizes_each_identifier_and_preserves_sql_intent(lookup, expected):
    target = _user()
    database = _db(_Result(one=target))

    assert await teams._resolve_member(database, lookup) is target
    sql = _sql(database.execute.await_args.args[0]).lower()
    assert expected in sql


@pytest.mark.asyncio
async def test_resolve_member_rejects_absent_identifier_and_unknown_user():
    with pytest.raises(HTTPException) as exc:
        await teams._resolve_member(_db(), SimpleNamespace(user_id=None, email=None, username=None))
    _assert_http(exc, 422, "Provide email, username, or user_id")

    request = SimpleNamespace(user_id=None, email="missing@example.test", username=None)
    with pytest.raises(HTTPException) as exc:
        await teams._resolve_member(_db(_Result(one=None)), request)
    _assert_http(exc, 404, "User not found")


def test_role_value_serializes_enums_strings_and_null():
    assert teams._role_value(None) is None
    assert teams._role_value(TeamRole.owner) == "owner"
    assert teams._role_value("reviewer") == "reviewer"


@pytest.mark.asyncio
async def test_team_lists_serialize_roles_counts_and_visibility():
    actor = _user()
    mine = _team(owner=actor, private=True, personal=True, handle="alice-team")
    public = _team(owner=actor, handle="public-team")

    mine_db = _db(_Result(rows=[(mine, TeamRole.owner), (public, "member")]))
    response = await teams.my_teams(mine_db, actor)
    assert [item.model_dump(mode="json") for item in response] == [
        {
            "id": str(mine.id),
            "name": mine.name,
            "handle": "alice-team",
            "description": mine.description,
            "visibility": "private",
            "is_personal": True,
            "role": "owner",
            "member_count": None,
            "created_at": _NOW.isoformat().replace("+00:00", "Z"),
        },
        {
            "id": str(public.id),
            "name": public.name,
            "handle": "public-team",
            "description": public.description,
            "visibility": "public",
            "is_personal": False,
            "role": "member",
            "member_count": None,
            "created_at": _NOW.isoformat().replace("+00:00", "Z"),
        },
    ]
    mine_sql = _sql(mine_db.execute.await_args.args[0])
    assert "JOIN team_memberships" in mine_sql
    assert "ORDER BY teams.name" in mine_sql

    all_db = _db(_Result(rows=[(public, None, None), (mine, 2, TeamRole.owner)]))
    all_response = await teams.all_teams(all_db, actor)
    assert [(item.handle, item.member_count, item.role) for item in all_response] == [
        ("public-team", 0, None),
        ("alice-team", 2, "owner"),
    ]
    regular_sql = _sql(all_db.execute.await_args.args[0])
    assert "teams.is_private = false" in regular_sql

    admin = _user(role=UserRole.super_admin, username="root")
    admin_db = _db(_Result(rows=[]))
    assert await teams.all_teams(admin_db, admin) == []
    assert "teams.is_private = false" not in _sql(admin_db.execute.await_args.args[0])


@pytest.mark.asyncio
async def test_team_by_handle_normalizes_input_and_admin_gets_owner_view(monkeypatch):
    admin = _user(role=UserRole.admin, username="admin")
    team = _team(private=True, handle="platform")
    database = _db(_Result(one=team))
    database.scalar.return_value = 4
    membership = AsyncMock(return_value=None)
    monkeypatch.setattr(teams, "team_membership", membership)

    response = await teams.team_by_handle("  @PLATFORM ", database, admin)

    assert response.role == "owner"
    assert response.member_count == 4
    assert "teams.handle = 'platform'" in _sql(database.execute.await_args.args[0])

    member = _user(username="member")
    member_db = _db(_Result(one=team))
    member_db.scalar.return_value = 1
    membership.return_value = _membership(team, member, TeamRole.reviewer)
    member_response = await teams.team_by_handle("platform", member_db, member)
    assert member_response.role == "reviewer"


@pytest.mark.asyncio
async def test_team_by_handle_hides_missing_and_private_team_from_outsider(monkeypatch):
    outsider = _user(username="outsider")
    missing_db = _db(_Result(one=None))
    with pytest.raises(HTTPException) as exc:
        await teams.team_by_handle("missing", missing_db, outsider)
    _assert_http(exc, 404, "Teamspace not found")

    private = _team(private=True)
    hidden_db = _db(_Result(one=private))
    monkeypatch.setattr(teams, "team_membership", AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as exc:
        await teams.team_by_handle(private.handle, hidden_db, outsider)
    _assert_http(exc, 404, "Teamspace not found")


@pytest.mark.asyncio
async def test_invite_preview_covers_invalid_expired_personal_and_durable_states(monkeypatch):
    actor = _user(username="recipient")
    owner = _user(username="owner", name="Owner Name")
    team = _team(owner=owner, private=True)
    invite = _invite(team, owner)

    lookup = AsyncMock(return_value=None)
    monkeypatch.setattr(teams, "team_invite_by_token", lookup)
    invalid = await teams.preview_team_invite(teams.TeamInvitePreviewRequest(token="missing"), _db(), actor)
    assert invalid.model_dump() == {
        "valid": False,
        "invite_state": None,
        "team_id": None,
        "team_name": None,
        "team_handle": None,
        "team_description": None,
        "invited_by": None,
        "request": None,
    }

    lookup.return_value = invite
    monkeypatch.setattr(teams, "invite_state", MagicMock(return_value="expired"))
    expired = await teams.preview_team_invite(
        teams.TeamInvitePreviewRequest(token="expired"),
        _db(_Result(one=None)),
        actor,
    )
    assert expired.valid is False
    assert expired.invite_state == "expired"
    assert expired.team_id is None

    monkeypatch.setattr(teams, "invite_state", MagicMock(return_value="active"))
    personal = _team(owner=owner, private=True, personal=True)
    personal_db = _db(_Result(one=None))
    personal_db.get.side_effect = [personal]
    personal_response = await teams.preview_team_invite(
        teams.TeamInvitePreviewRequest(token="personal"), personal_db, actor
    )
    assert personal_response.valid is False

    request = _join_request(team, actor, invite=invite, status=TeamJoinRequestStatus.rejected)
    request.decision_reason = "Not yet"
    request.decided_at = _NOW
    durable_db = _db(_Result(one=request))
    durable_db.get.side_effect = [team, owner]
    durable = await teams.preview_team_invite(teams.TeamInvitePreviewRequest(token="active"), durable_db, actor)
    assert durable.valid is True
    assert durable.invited_by == "Owner Name"
    assert durable.request.status == "rejected"
    assert durable.request.decision_reason == "Not yet"


@pytest.mark.asyncio
async def test_team_detail_serializes_member_and_admin_roles(monkeypatch):
    member = _user(username="member")
    team = _team()
    membership = _membership(team, member, TeamRole.reviewer)
    monkeypatch.setattr(teams, "_load_visible_team", AsyncMock(return_value=team))
    monkeypatch.setattr(teams, "team_membership", AsyncMock(return_value=membership))

    response = await teams.team_detail(team.id, _db(), member)
    assert response.role == "reviewer"
    assert response.model_dump(mode="json")["visibility"] == "public"

    admin = _user(role=UserRole.admin, username="admin")
    response = await teams.team_detail(team.id, _db(), admin)
    assert response.role == "owner"


@pytest.mark.asyncio
async def test_create_team_persists_owner_and_serializes_response(monkeypatch):
    actor = _user()
    database = _db()
    created_id = uuid.uuid4()
    monkeypatch.setattr(teams, "reserve_handle", AsyncMock(return_value="platform-tools"))

    async def flush():
        team = database.add.call_args_list[0].args[0]
        team.id = created_id
        team.is_personal = False
        team.created_at = _NOW

    database.flush.side_effect = flush
    request = teams.TeamCreateRequest(
        name="  Platform Tools  ",
        description="description",
        visibility="private",
    )

    response = await teams.create_team(request, database, actor)

    created_team = database.add.call_args_list[0].args[0]
    created_membership = database.add.call_args_list[1].args[0]
    assert (created_team.name, created_team.handle, created_team.is_private) == (
        "Platform Tools",
        "platform-tools",
        True,
    )
    assert (created_membership.team_id, created_membership.user_id, created_membership.role) == (
        created_id,
        actor.id,
        TeamRole.owner,
    )
    assert response.model_dump(mode="json")["member_count"] == 1
    database.commit.assert_awaited_once()
    database.refresh.assert_awaited_once_with(created_team)


@pytest.mark.asyncio
async def test_create_team_maps_namespace_and_database_conflicts_to_409(monkeypatch):
    actor = _user()
    monkeypatch.setattr(teams, "reserve_handle", AsyncMock(side_effect=ValueError("Handle is already taken")))
    with pytest.raises(HTTPException) as exc:
        await teams.create_team(teams.TeamCreateRequest(name="Taken"), _db(), actor)
    _assert_http(exc, 409, "Handle is already taken")

    monkeypatch.setattr(teams, "reserve_handle", AsyncMock(return_value="taken"))
    database = _db()

    async def flush_failure():
        raise _integrity_error()

    database.flush.side_effect = flush_failure
    with pytest.raises(HTTPException) as exc:
        await teams.create_team(teams.TeamCreateRequest(name="Taken"), database, actor)
    _assert_http(exc, 409, "Team handle already exists")
    database.rollback.assert_awaited_once()
    database.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_personal_invariants_repair_owner_and_remove_everyone_else():
    creator = _user()
    stranger = _user(username="stranger")
    team = _team(owner=creator, private=False, personal=True)
    creator_membership = _membership(team, creator, TeamRole.member)
    stranger_membership = _membership(team, stranger, TeamRole.owner)
    database = _db(_Result(scalars=[creator_membership, stranger_membership]))

    await teams._ensure_personal_team_invariants(database, team, creator)

    assert team.is_private is True
    assert creator_membership.role == TeamRole.owner
    database.delete.assert_awaited_once_with(stranger_membership)
    database.commit.assert_awaited_once()
    assert database.execute.await_args.args[0]._for_update_arg is not None

    missing_owner_db = _db(_Result(scalars=[stranger_membership]))
    await teams._ensure_personal_team_invariants(missing_owner_db, team, creator)
    added = missing_owner_db.add.call_args.args[0]
    assert (added.team_id, added.user_id, added.role) == (team.id, creator.id, TeamRole.owner)

    wrong_creator = _user(username="wrong")
    with pytest.raises(HTTPException) as exc:
        await teams._ensure_personal_team_invariants(_db(), team, wrong_creator)
    _assert_http(exc, 403, "Only the personal teamspace creator may claim it")


@pytest.mark.asyncio
async def test_personal_response_counts_members_and_handles_missing_membership(monkeypatch):
    creator = _user()
    team = _team(owner=creator, private=True, personal=True)
    monkeypatch.setattr(teams, "team_membership", AsyncMock(return_value=None))
    database = _db()
    database.scalar.return_value = None

    response = await teams._personal_team_response(database, team, creator)

    assert response.is_personal is True
    assert response.role is None
    assert response.member_count == 0


@pytest.mark.asyncio
async def test_claim_personal_returns_and_repairs_existing_space(monkeypatch):
    creator = _user()
    personal = _team(owner=creator, private=True, personal=True)
    database = _db(_Result(one=personal))
    ensure = AsyncMock()
    response = teams.TeamResponse(
        id=personal.id,
        name=personal.name,
        handle=personal.handle,
        visibility="private",
        is_personal=True,
        role="owner",
    )
    monkeypatch.setattr(teams, "_ensure_personal_team_invariants", ensure)
    monkeypatch.setattr(teams, "_personal_team_response", AsyncMock(return_value=response))

    assert await teams.claim_personal_teamspace(database, creator) is response
    ensure.assert_awaited_once_with(database, personal, creator)


@pytest.mark.asyncio
async def test_claim_personal_adopts_legacy_space(monkeypatch):
    creator = _user(username="legacy")
    legacy = _team(owner=creator, private=True, handle="legacy-team")
    legacy.description = teams._PERSONAL_TEAM_DESCRIPTION
    membership = _membership(legacy, creator, TeamRole.owner)
    database = _db(_Result(one=None), _Result(one=legacy))
    monkeypatch.setattr(teams, "team_membership", AsyncMock(return_value=membership))
    monkeypatch.setattr(teams, "_ensure_personal_team_invariants", AsyncMock())
    expected = teams.TeamResponse(
        id=legacy.id,
        name=legacy.name,
        handle=legacy.handle,
        visibility="private",
        is_personal=True,
        role="owner",
    )
    monkeypatch.setattr(teams, "_personal_team_response", AsyncMock(return_value=expected))

    response = await teams.claim_personal_teamspace(database, creator)

    assert response is expected
    assert legacy.is_personal is True
    database.commit.assert_awaited_once()
    teams._ensure_personal_team_invariants.assert_awaited_once_with(database, legacy, creator)


@pytest.mark.asyncio
async def test_claim_personal_recovers_legacy_adoption_race(monkeypatch):
    creator = _user(username="legacy")
    legacy = _team(owner=creator, private=True, handle="legacy-team")
    legacy.description = teams._PERSONAL_TEAM_DESCRIPTION
    winner = _team(owner=creator, private=True, personal=True, handle="winner")
    database = _db(_Result(one=None), _Result(one=legacy), _Result(one=winner))
    database.commit.side_effect = _integrity_error()
    monkeypatch.setattr(
        teams,
        "team_membership",
        AsyncMock(return_value=_membership(legacy, creator, TeamRole.owner)),
    )
    monkeypatch.setattr(teams, "_ensure_personal_team_invariants", AsyncMock())
    expected = teams.TeamResponse(
        id=winner.id,
        name=winner.name,
        handle=winner.handle,
        visibility="private",
        is_personal=True,
        role="owner",
    )
    monkeypatch.setattr(teams, "_personal_team_response", AsyncMock(return_value=expected))

    assert await teams.claim_personal_teamspace(database, creator) is expected
    database.rollback.assert_awaited_once()
    teams._ensure_personal_team_invariants.assert_awaited_once_with(database, winner, creator)

    failed_db = _db(_Result(one=None), _Result(one=legacy), _Result(one=None))
    failed_db.commit.side_effect = _integrity_error()
    with pytest.raises(IntegrityError):
        await teams.claim_personal_teamspace(failed_db, creator)
    failed_db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_claim_personal_creates_space_and_recovers_insert_race(monkeypatch):
    creator = _user(username="new-user", name="New User")
    regular = _team(owner=creator, handle="new-user-team")
    database = _db(_Result(one=None), _Result(one=regular), _Result(one=None))
    monkeypatch.setattr(teams, "team_membership", AsyncMock(return_value=None))
    monkeypatch.setattr(teams, "reserve_handle", AsyncMock(return_value="new-user-team"))
    expected_id = uuid.uuid4()

    async def flush():
        created = database.add.call_args_list[0].args[0]
        created.id = expected_id
        created.is_personal = True
        created.created_at = _NOW

    database.flush.side_effect = flush
    monkeypatch.setattr(teams, "_personal_team_response", AsyncMock())
    teams._personal_team_response.return_value = teams.TeamResponse(
        id=expected_id,
        name="New User's Teamspace",
        handle="new-user-team",
        visibility="private",
        is_personal=True,
        role="owner",
    )

    response = await teams.claim_personal_teamspace(database, creator)

    assert response.handle == "new-user-team"
    created = database.add.call_args_list[0].args[0]
    membership = database.add.call_args_list[1].args[0]
    assert created.description == teams._PERSONAL_TEAM_DESCRIPTION
    assert created.is_private is True
    assert membership.role == TeamRole.owner
    database.refresh.assert_awaited_once_with(created)

    winner = _team(owner=creator, private=True, personal=True, handle="winner")
    race_db = _db(_Result(one=None), _Result(one=None), _Result(one=winner))
    race_db.flush.side_effect = _integrity_error()
    monkeypatch.setattr(teams, "_ensure_personal_team_invariants", AsyncMock())
    teams._personal_team_response.return_value = teams.TeamResponse(
        id=winner.id,
        name=winner.name,
        handle=winner.handle,
        visibility="private",
        is_personal=True,
        role="owner",
    )

    recovered = await teams.claim_personal_teamspace(race_db, creator)
    assert recovered.id == winner.id
    race_db.rollback.assert_awaited_once()
    teams._ensure_personal_team_invariants.assert_awaited_once_with(race_db, winner, creator)


@pytest.mark.asyncio
async def test_claim_personal_retries_insert_conflict_without_a_race_winner(monkeypatch):
    creator = _user(username="retry", name="Retry User")
    database = _db(
        _Result(one=None),
        _Result(one=None),
        _Result(one=None),
        _Result(one=None),
    )
    reserve = AsyncMock(side_effect=["retry-team", "retry-team-1"])
    monkeypatch.setattr(teams, "reserve_handle", reserve)
    created_id = uuid.uuid4()
    flush_count = 0

    async def flush():
        nonlocal flush_count
        flush_count += 1
        if flush_count == 1:
            raise _integrity_error()
        created = database.add.call_args_list[-1].args[0]
        created.id = created_id
        created.is_personal = True
        created.created_at = _NOW

    database.flush.side_effect = flush
    expected = teams.TeamResponse(
        id=created_id,
        name="Retry User's Teamspace",
        handle="retry-team-1",
        visibility="private",
        is_personal=True,
        role="owner",
    )
    monkeypatch.setattr(teams, "_personal_team_response", AsyncMock(return_value=expected))

    response = await teams.claim_personal_teamspace(database, creator)

    assert response is expected
    assert reserve.await_count == 2
    database.rollback.assert_awaited_once()
    database.refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_claim_personal_exhausts_conflicting_candidates(monkeypatch):
    creator = _user(username="blocked")
    database = _db(_Result(one=None), *[_Result(one=None) for _ in range(6)])
    reserve = AsyncMock(side_effect=ValueError("taken"))
    monkeypatch.setattr(teams, "reserve_handle", reserve)

    with pytest.raises(HTTPException) as exc:
        await teams.claim_personal_teamspace(database, creator)

    _assert_http(exc, 409, "Could not find a free handle for your personal teamspace")
    assert reserve.await_count == 6


@pytest.mark.asyncio
async def test_update_team_persists_trimmed_fields(monkeypatch):
    actor = _user()
    team = _team(owner=actor)
    database = _db()
    monkeypatch.setattr(teams, "_require_owner_or_admin", AsyncMock(return_value=team))

    response = await teams.update_team(
        team.id,
        teams.TeamUpdateRequest(name="  Renamed  ", description="Updated"),
        database,
        actor,
    )

    assert (team.name, team.description) == ("Renamed", "Updated")
    assert response.name == "Renamed"
    assert response.role == "owner"
    database.commit.assert_awaited_once()
    database.refresh.assert_awaited_once_with(team)

    database.commit.reset_mock()
    unchanged = await teams.update_team(team.id, teams.TeamUpdateRequest(), database, actor)
    assert (unchanged.name, unchanged.description) == ("Renamed", "Updated")
    database.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_visibility_rejects_unauthorized_personal_and_owned_public_items(monkeypatch):
    actor = _user(username="member")
    private = _team(private=True)
    database = _db()
    monkeypatch.setattr(teams, "_load_team", AsyncMock(return_value=private))
    monkeypatch.setattr(teams, "team_membership", AsyncMock(return_value=None))

    with pytest.raises(HTTPException) as exc:
        await teams.update_team_visibility(
            private.id, teams.TeamVisibilityUpdateRequest(visibility="public"), database, actor
        )
    _assert_http(exc, 404, "Team not found")

    teams.team_membership.return_value = _membership(private, actor, TeamRole.member)
    with pytest.raises(HTTPException) as exc:
        await teams.update_team_visibility(
            private.id, teams.TeamVisibilityUpdateRequest(visibility="public"), database, actor
        )
    _assert_http(exc, 403, "Only team owners can change visibility")

    personal = _team(owner=actor, private=True, personal=True)
    teams._load_team.return_value = personal
    teams.team_membership.return_value = _membership(personal, actor, TeamRole.owner)
    with pytest.raises(HTTPException) as exc:
        await teams.update_team_visibility(
            personal.id, teams.TeamVisibilityUpdateRequest(visibility="public"), database, actor
        )
    _assert_http(exc, 409, "Personal teamspaces are always private")

    public = _team(owner=actor)
    teams._load_team.return_value = public
    teams.team_membership.return_value = _membership(public, actor, TeamRole.owner)
    monkeypatch.setattr(teams, "_team_owned_listing_counts", AsyncMock(return_value={"skills": 2, "agent": 1}))
    with pytest.raises(HTTPException) as exc:
        await teams.update_team_visibility(
            public.id, teams.TeamVisibilityUpdateRequest(visibility="private"), database, actor
        )
    _assert_http(exc, 409, "Make these public registry items team-private first: 1 agent, 2 skills")


@pytest.mark.asyncio
async def test_visibility_change_revokes_invites_and_emits_audit_event(monkeypatch):
    admin = _user(role=UserRole.admin, username="admin")
    team = _team(private=True)
    database = _db(_Result(rows=[]))
    monkeypatch.setattr(teams, "_load_team", AsyncMock(return_value=team))
    monkeypatch.setattr(teams, "team_membership", AsyncMock(return_value=None))
    emitted = AsyncMock()
    monkeypatch.setattr(teams, "emit_security_event", emitted)

    response = await teams.update_team_visibility(
        team.id,
        teams.TeamVisibilityUpdateRequest(visibility="public"),
        database,
        admin,
    )

    assert response.visibility == "public"
    assert response.role == "owner"
    statement = database.execute.await_args.args[0]
    sql = _sql(statement)
    assert "UPDATE team_invites" in sql
    assert "team_invites.revoked_at IS NULL" in sql
    event = emitted.await_args.args[0]
    assert event.event_type == teams.EventType.TEAM_VISIBILITY_CHANGED
    assert event.actor_id == str(admin.id)
    assert event.target_id == str(team.id)
    assert "is now public" in event.detail

    emitted.reset_mock()
    database.execute.reset_mock()
    no_change = await teams.update_team_visibility(
        team.id,
        teams.TeamVisibilityUpdateRequest(visibility="public"),
        database,
        admin,
    )
    assert no_change.visibility == "public"
    database.execute.assert_not_awaited()
    emitted.assert_not_awaited()

    monkeypatch.setattr(teams, "_team_owned_listing_counts", AsyncMock(return_value={}))
    private_response = await teams.update_team_visibility(
        team.id,
        teams.TeamVisibilityUpdateRequest(visibility="private"),
        database,
        admin,
    )
    assert private_response.visibility == "private"
    database.execute.assert_not_awaited()
    emitted.assert_awaited_once()


@pytest.mark.asyncio
async def test_owned_listing_counts_names_singular_plural_and_public_predicates():
    team_id = uuid.uuid4()
    database = _db()
    database.scalar.side_effect = [1, 2, 0, 0, 0, 3, 1]

    counts = await teams._team_owned_listing_counts(database, team_id)

    assert counts == {
        "agent": 1,
        "MCP servers": 2,
        "sandboxes": 3,
        "component source": 1,
    }
    assert database.scalar.await_count == 7
    assert all("team_id" in _sql(call.args[0]) for call in database.scalar.await_args_list)

    public_db = _db()
    public_db.scalar.side_effect = [0, 1, 0, 0, 0, 0]
    public_counts = await teams._team_owned_listing_counts(public_db, team_id, public_only=True)
    assert public_counts == {"MCP server": 1}
    assert public_db.scalar.await_count == 6
    assert all("is_private IS false" in _sql(call.args[0]) for call in public_db.scalar.await_args_list)


@pytest.mark.asyncio
async def test_delete_team_guards_personal_owned_and_constraint_races(monkeypatch):
    actor = _user()
    team = _team(owner=actor)
    personal = _team(owner=actor, private=True, personal=True)
    database = _db()
    require = AsyncMock(return_value=personal)
    monkeypatch.setattr(teams, "_require_owner_or_admin", require)
    counts = AsyncMock(return_value={})
    monkeypatch.setattr(teams, "_team_owned_listing_counts", counts)

    with pytest.raises(HTTPException) as exc:
        await teams.delete_team(personal.id, database, actor)
    _assert_http(exc, 409, "Personal teamspaces cannot be deleted")

    require.return_value = team
    counts.return_value = {"skills": 2, "agent": 1}
    with pytest.raises(HTTPException) as exc:
        await teams.delete_team(team.id, database, actor)
    assert exc.value.status_code == 409
    assert "1 agent, 2 skills" in exc.value.detail
    assert "Transfer each listing" in exc.value.detail
    database.delete.assert_not_awaited()

    counts.return_value = {}
    await teams.delete_team(team.id, database, actor)
    database.delete.assert_awaited_once_with(team)
    database.commit.assert_awaited_once()

    failed_db = _db()
    failed_db.commit.side_effect = _integrity_error("foreign key")
    with pytest.raises(HTTPException) as exc:
        await teams.delete_team(team.id, failed_db, actor)
    _assert_http(exc, 409, "Teamspace still owns registry items")
    failed_db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_member_roster_enforces_visibility_and_serializes_rows(monkeypatch):
    actor = _user(username="member")
    team = _team()
    row = SimpleNamespace(
        id=actor.id,
        email=actor.email,
        username=actor.username,
        name=actor.name,
        role=TeamRole.reviewer,
    )
    database = _db(_Result(rows=[row]))
    monkeypatch.setattr(teams, "_load_team", AsyncMock(return_value=team))
    monkeypatch.setattr(teams, "team_membership", AsyncMock(return_value=_membership(team, actor)))

    response = await teams.list_team_members(team.id, database, actor)
    assert response[0].model_dump(mode="json") == {
        "id": str(actor.id),
        "email": actor.email,
        "username": actor.username,
        "name": actor.name,
        "role": "reviewer",
    }
    assert "ORDER BY users.email" in _sql(database.execute.await_args.args[0])

    public_outsider = _user(username="outsider")
    teams.team_membership.return_value = None
    with pytest.raises(HTTPException) as exc:
        await teams.list_team_members(team.id, _db(), public_outsider)
    _assert_http(exc, 403, "Only team members can view the roster")

    team.is_private = True
    with pytest.raises(HTTPException) as exc:
        await teams.list_team_members(team.id, _db(), public_outsider)
    _assert_http(exc, 404, "Team not found")

    admin = _user(role=UserRole.admin, username="admin")
    admin_db = _db(_Result(rows=[]))
    assert await teams.list_team_members(team.id, admin_db, admin) == []


@pytest.mark.asyncio
async def test_member_upsert_adds_changes_and_protects_last_owner(monkeypatch):
    owner = _user(username="owner")
    target = _user(username="target")
    team = _team(owner=owner)
    database = _db()
    monkeypatch.setattr(teams, "_require_owner_or_admin", AsyncMock(return_value=team))
    monkeypatch.setattr(teams, "_resolve_member", AsyncMock(return_value=target))
    membership_lookup = AsyncMock(return_value=None)
    monkeypatch.setattr(teams, "team_membership", membership_lookup)
    count = AsyncMock(return_value=1)
    monkeypatch.setattr(teams, "count_owners", count)

    request = teams.TeamMemberUpsertRequest(user_id=target.id, role=TeamRole.reviewer)
    response = await teams.upsert_team_member(team.id, request, database, owner)
    added = database.add.call_args.args[0]
    assert (added.team_id, added.user_id, added.role) == (team.id, target.id, TeamRole.reviewer)
    assert response.role == "reviewer"

    existing = _membership(team, target, TeamRole.member)
    membership_lookup.return_value = existing
    request = teams.TeamMemberUpsertRequest(email=target.email.upper(), role=TeamRole.owner)
    response = await teams.upsert_team_member(team.id, request, database, owner)
    assert existing.role == TeamRole.owner
    assert response.role == "owner"

    existing.role = TeamRole.owner
    request = teams.TeamMemberUpsertRequest(username="@target", role=TeamRole.member)
    with pytest.raises(HTTPException) as exc:
        await teams.upsert_team_member(team.id, request, database, owner)
    _assert_http(exc, 409, "A team must have at least one owner")
    count.assert_awaited_with(database, team.id, for_update=True)

    team.is_personal = True
    with pytest.raises(HTTPException) as exc:
        await teams.upsert_team_member(team.id, request, database, owner)
    _assert_http(exc, 409, "Personal teamspaces cannot add members or change roles")


@pytest.mark.asyncio
async def test_remove_member_handles_personal_missing_last_owner_and_success(monkeypatch):
    owner = _user(username="owner")
    target = _user(username="target")
    team = _team(owner=owner)
    database = _db()
    monkeypatch.setattr(teams, "_require_owner_or_admin", AsyncMock(return_value=team))
    membership_lookup = AsyncMock(return_value=None)
    monkeypatch.setattr(teams, "team_membership", membership_lookup)
    monkeypatch.setattr(teams, "count_owners", AsyncMock(return_value=1))

    with pytest.raises(HTTPException) as exc:
        await teams.remove_team_member(team.id, target.id, database, owner)
    _assert_http(exc, 404, "Membership not found")

    membership = _membership(team, target, TeamRole.owner)
    membership_lookup.return_value = membership
    with pytest.raises(HTTPException) as exc:
        await teams.remove_team_member(team.id, target.id, database, owner)
    _assert_http(exc, 409, "A team must have at least one owner")

    membership.role = TeamRole.member
    await teams.remove_team_member(team.id, target.id, database, owner)
    database.delete.assert_awaited_once_with(membership)
    database.commit.assert_awaited_once()

    team.is_personal = True
    with pytest.raises(HTTPException) as exc:
        await teams.remove_team_member(team.id, target.id, database, owner)
    _assert_http(exc, 409, "The personal teamspace creator cannot be removed")


@pytest.mark.asyncio
async def test_leave_team_handles_membership_and_owner_safeguards(monkeypatch):
    actor = _user()
    team = _team(owner=actor)
    database = _db()
    monkeypatch.setattr(teams, "_load_team", AsyncMock(return_value=team))
    membership_lookup = AsyncMock(return_value=None)
    monkeypatch.setattr(teams, "team_membership", membership_lookup)
    monkeypatch.setattr(teams, "count_owners", AsyncMock(return_value=1))

    with pytest.raises(HTTPException) as exc:
        await teams.leave_team(team.id, database, actor)
    _assert_http(exc, 404, "You are not a member of this team")

    membership = _membership(team, actor, TeamRole.owner)
    membership_lookup.return_value = membership
    with pytest.raises(HTTPException) as exc:
        await teams.leave_team(team.id, database, actor)
    _assert_http(exc, 409, "A team must have at least one owner; transfer ownership first")

    membership.role = TeamRole.member
    await teams.leave_team(team.id, database, actor)
    database.delete.assert_awaited_once_with(membership)
    database.commit.assert_awaited_once()

    team.is_personal = True
    with pytest.raises(HTTPException) as exc:
        await teams.leave_team(team.id, database, actor)
    _assert_http(exc, 409, "The personal teamspace creator cannot leave")


@pytest.mark.asyncio
async def test_invite_response_and_event_use_mocked_crypto_and_audit(monkeypatch):
    owner = _user(username="owner")
    team = _team(owner=owner, private=True)
    invite = _invite(team, owner)
    decrypt = MagicMock(return_value="clear-token")
    monkeypatch.setattr(teams.ds, "decrypt_value", decrypt)
    monkeypatch.setattr(teams.ds, "get_sync", MagicMock(return_value="https://ui.example.test/"))
    monkeypatch.setattr(teams, "invite_state", MagicMock(return_value="active"))

    response = teams._team_invite_response(invite, owner.username)

    assert response.url == "https://ui.example.test/team-invites/clear-token"
    assert response.state == "active"
    decrypt.assert_called_once_with(invite.token_encrypted)

    decrypt.return_value = ""
    assert teams._team_invite_response(invite).url is None

    emitted = AsyncMock()
    monkeypatch.setattr(teams, "emit_security_event", emitted)
    await teams._emit_team_invite_event(teams.EventType.TEAM_INVITE_REVOKED, invite, owner, "revoked")
    event = emitted.await_args.args[0]
    assert event.target_type == "team_invite"
    assert event.target_id == str(invite.id)
    assert event.detail == "revoked"


@pytest.mark.asyncio
async def test_create_invite_is_deterministic_hashes_token_and_emits_event(monkeypatch):
    owner = _user(username="owner")
    team = _team(owner=owner, private=True)
    database = _db()
    monkeypatch.setattr(teams, "_require_owner_or_admin", AsyncMock(return_value=team))
    monkeypatch.setattr(teams.secrets, "token_urlsafe", MagicMock(return_value="fixed-token"))
    encrypt = MagicMock(return_value="encrypted-fixed-token")
    monkeypatch.setattr(teams.ds, "encrypt_value", encrypt)
    monkeypatch.setattr(teams, "_team_invite_response", MagicMock())
    emitted = AsyncMock()
    monkeypatch.setattr(teams, "_emit_team_invite_event", emitted)

    async def commit():
        invite = database.add.call_args.args[0]
        invite.id = uuid.UUID(int=50)
        invite.use_count = 0
        invite.created_at = _NOW

    database.commit.side_effect = commit
    base = teams.TeamInviteResponse(
        id=uuid.UUID(int=50),
        team_id=team.id,
        name="Partners",
        url="https://ui/team-invites/fixed-token",
        invited_by_username=owner.username,
        max_uses=2,
        use_count=0,
        expires_at=_NOW + timedelta(days=3),
        created_at=_NOW,
        state="active",
    )
    teams._team_invite_response.return_value = base

    response = await teams.create_team_invite(
        team.id,
        teams.TeamInviteCreateRequest(name="  Partners  ", expires_in_days=3, max_uses=2),
        database,
        owner,
    )

    invite = database.add.call_args.args[0]
    assert invite.token_hash == hashlib.sha256(b"fixed-token").hexdigest()
    assert invite.token_encrypted == "encrypted-fixed-token"
    assert invite.name == "Partners"
    assert invite.expires_at == _NOW + timedelta(days=3)
    assert response.token == "fixed-token"
    encrypt.assert_called_once_with("fixed-token")
    emitted.assert_awaited_once_with(
        teams.EventType.TEAM_INVITE_CREATED,
        invite,
        owner,
        "Invite created for platform",
    )


@pytest.mark.asyncio
async def test_create_and_list_invites_reject_ineligible_teamspaces(monkeypatch):
    owner = _user()
    public = _team(owner=owner)
    personal = _team(owner=owner, private=True, personal=True)
    require = AsyncMock(return_value=public)
    monkeypatch.setattr(teams, "_require_owner_or_admin", require)

    with pytest.raises(HTTPException) as exc:
        await teams.create_team_invite(public.id, teams.TeamInviteCreateRequest(), _db(), owner)
    _assert_http(exc, 409, "Public teamspaces use Share links")
    assert await teams.list_team_invites(public.id, _db(), owner) == []

    require.return_value = personal
    with pytest.raises(HTTPException) as exc:
        await teams.create_team_invite(personal.id, teams.TeamInviteCreateRequest(), _db(), owner)
    _assert_http(exc, 409, "Personal teamspaces do not support invitation links")

    private = _team(owner=owner, private=True)
    invite = _invite(private, owner)
    require.return_value = private
    database = _db(_Result(rows=[(invite, owner.username)]))
    monkeypatch.setattr(teams, "_team_invite_response", MagicMock(return_value="serialized"))
    assert await teams.list_team_invites(private.id, database, owner) == ["serialized"]
    assert "ORDER BY team_invites.created_at DESC" in _sql(database.execute.await_args.args[0])


@pytest.mark.asyncio
async def test_revoke_invite_checks_scope_is_idempotent_and_serializes_inviter(monkeypatch):
    owner = _user(username="owner")
    team = _team(owner=owner, private=True)
    other = _team(owner=owner, private=True)
    invite = _invite(team, owner)
    database = _db()
    monkeypatch.setattr(teams, "_require_owner_or_admin", AsyncMock(return_value=team))
    emitted = AsyncMock()
    monkeypatch.setattr(teams, "_emit_team_invite_event", emitted)
    monkeypatch.setattr(teams, "_team_invite_response", MagicMock(return_value="response"))

    database.get.return_value = None
    with pytest.raises(HTTPException) as exc:
        await teams.revoke_team_invite(team.id, invite.id, database, owner)
    _assert_http(exc, 404, "Invite not found")

    invite.team_id = other.id
    database.get.return_value = invite
    with pytest.raises(HTTPException) as exc:
        await teams.revoke_team_invite(team.id, invite.id, database, owner)
    _assert_http(exc, 404, "Invite not found")

    invite.team_id = team.id
    database.get.side_effect = [invite, owner]
    assert await teams.revoke_team_invite(team.id, invite.id, database, owner) == "response"
    assert invite.revoked_at is not None
    database.commit.assert_awaited_once()
    emitted.assert_awaited_once()
    teams._team_invite_response.assert_called_with(invite, owner.username)

    database.commit.reset_mock()
    emitted.reset_mock()
    database.get.side_effect = [invite, owner]
    await teams.revoke_team_invite(team.id, invite.id, database, owner)
    database.commit.assert_not_awaited()
    emitted.assert_not_awaited()


@pytest.mark.asyncio
async def test_invite_request_audit_listing_scopes_invite_and_serializes_rows(monkeypatch):
    owner = _user(username="owner")
    requester = _user(username="requester")
    team = _team(owner=owner, private=True)
    other = _team(owner=owner, private=True)
    invite = _invite(team, owner)
    request = _join_request(team, requester, invite=invite)
    database = _db(_Result(rows=[(request, requester, owner.username)]))
    monkeypatch.setattr(teams, "_require_owner_or_admin", AsyncMock(return_value=team))
    database.get.return_value = None

    with pytest.raises(HTTPException) as exc:
        await teams.team_invite_requests(team.id, invite.id, database, owner)
    _assert_http(exc, 404, "Invite not found")

    invite.team_id = other.id
    database.get.return_value = invite
    with pytest.raises(HTTPException) as exc:
        await teams.team_invite_requests(team.id, invite.id, database, owner)
    _assert_http(exc, 404, "Invite not found")

    invite.team_id = team.id
    database.get.return_value = invite
    rows = await teams.team_invite_requests(team.id, invite.id, database, owner)
    assert rows[0].username == requester.username
    assert rows[0].decided_by_username == owner.username
    assert "team_membership_requests.invite_id" in _sql(database.execute.await_args.args[0])


@pytest.mark.asyncio
async def test_delete_invite_locks_row_retains_used_and_audits_unused(monkeypatch):
    owner = _user()
    team = _team(owner=owner, private=True)
    invite = _invite(team, owner)
    monkeypatch.setattr(teams, "_require_owner_or_admin", AsyncMock(return_value=team))
    emitted = AsyncMock()
    monkeypatch.setattr(teams, "_emit_team_invite_event", emitted)

    missing_db = _db(_Result(one=None))
    with pytest.raises(HTTPException) as exc:
        await teams.delete_unused_team_invite(team.id, invite.id, missing_db, owner)
    _assert_http(exc, 404, "Invite not found")
    assert missing_db.execute.await_args.args[0]._for_update_arg is not None

    invite.use_count = 1
    used_db = _db(_Result(one=invite))
    with pytest.raises(HTTPException) as exc:
        await teams.delete_unused_team_invite(team.id, invite.id, used_db, owner)
    _assert_http(exc, 409, "Used invites are retained for audit")

    invite.use_count = 0
    database = _db(_Result(one=invite))
    await teams.delete_unused_team_invite(team.id, invite.id, database, owner)
    database.delete.assert_awaited_once_with(invite)
    database.commit.assert_awaited_once()
    emitted.assert_awaited_once_with(teams.EventType.TEAM_INVITE_DELETED, invite, owner, "Unused invite deleted")


@pytest.mark.asyncio
async def test_join_request_helpers_lock_scope_serialize_and_emit(monkeypatch):
    owner = _user(username="owner")
    requester = _user(username="requester")
    team = _team(owner=owner)
    row = _join_request(team, requester)
    row.decided_by = owner.id
    row.decided_at = _NOW
    row.decision_reason = "Approved"

    response = teams._join_request_response(row, requester, owner.username)
    assert response.model_dump(mode="json") == {
        "id": str(row.id),
        "team_id": str(team.id),
        "user_id": str(requester.id),
        "invite_id": None,
        "email": requester.email,
        "username": requester.username,
        "name": requester.name,
        "status": "pending",
        "message": "Please add me",
        "decided_by": str(owner.id),
        "decided_by_username": "owner",
        "decided_at": _NOW.isoformat().replace("+00:00", "Z"),
        "decision_reason": "Approved",
        "created_at": _NOW.isoformat().replace("+00:00", "Z"),
    }
    assert teams._join_request_response(row).email is None

    database = _db(_Result(one=row))
    assert await teams._load_join_request(database, team.id, row.id, for_update=True) is row
    statement = database.execute.await_args.args[0]
    assert statement._for_update_arg is not None
    sql = _sql(statement)
    assert team.id.hex in sql and row.id.hex in sql

    with pytest.raises(HTTPException) as exc:
        await teams._load_join_request(_db(_Result(one=None)), team.id, row.id)
    _assert_http(exc, 404, "Join request not found")

    emitted = AsyncMock()
    monkeypatch.setattr(teams, "emit_security_event", emitted)
    await teams._emit_join_event(teams.EventType.TEAM_JOIN_DECIDED, team, owner, "approved")
    event = emitted.await_args.args[0]
    assert event.target_type == "team"
    assert event.target_id == str(team.id)
    assert event.detail == "approved"


@pytest.mark.asyncio
async def test_create_join_request_rejects_personal_members_and_hidden_teams(monkeypatch):
    actor = _user(username="requester")
    personal = _team(private=True, personal=True)
    public = _team()
    private = _team(private=True)
    database = _db()
    load = AsyncMock(return_value=personal)
    monkeypatch.setattr(teams, "_load_team", load)
    membership = AsyncMock(return_value=None)
    monkeypatch.setattr(teams, "team_membership", membership)

    with pytest.raises(HTTPException) as exc:
        await teams.create_join_request(personal.id, teams.TeamJoinRequestCreate(), database, actor)
    _assert_http(exc, 404, "Team not found")

    load.return_value = public
    membership.return_value = _membership(public, actor)
    with pytest.raises(HTTPException) as exc:
        await teams.create_join_request(public.id, teams.TeamJoinRequestCreate(), database, actor)
    _assert_http(exc, 409, "You are already a member of this teamspace")

    load.return_value = private
    membership.return_value = None
    redeem = AsyncMock(return_value=None)
    monkeypatch.setattr(teams, "redeemable_team_invite", redeem)
    with pytest.raises(HTTPException) as exc:
        await teams.create_join_request(
            private.id,
            teams.TeamJoinRequestCreate(invite_token="invalid"),
            database,
            actor,
        )
    _assert_http(exc, 404, "Team not found")
    redeem.assert_awaited_once_with(database, "invalid", team_id=private.id, for_update=True)


@pytest.mark.asyncio
async def test_create_join_request_persists_invite_usage_inbox_and_audit(monkeypatch):
    actor = _user(username="requester")
    owner = _user(username="owner")
    team = _team(owner=owner, private=True)
    invite = _invite(team, owner, uses=0, max_uses=1)
    database = _db()
    monkeypatch.setattr(teams, "_load_team", AsyncMock(return_value=team))
    monkeypatch.setattr(teams, "team_membership", AsyncMock(return_value=None))
    monkeypatch.setattr(teams, "team_visible_to", MagicMock(return_value=False))
    monkeypatch.setattr(teams, "redeemable_team_invite", AsyncMock(return_value=invite))
    requested = AsyncMock()
    monkeypatch.setattr(teams.inbox_sources, "on_team_join_requested", requested)
    join_event = AsyncMock()
    invite_event = AsyncMock()
    monkeypatch.setattr(teams, "_emit_join_event", join_event)
    monkeypatch.setattr(teams, "_emit_team_invite_event", invite_event)

    async def flush():
        row = database.add.call_args.args[0]
        row.id = uuid.UUID(int=60)
        row.status = TeamJoinRequestStatus.pending
        row.created_at = _NOW

    database.flush.side_effect = flush
    response = await teams.create_join_request(
        team.id,
        teams.TeamJoinRequestCreate(message="  Please add me  ", invite_token="fixed"),
        database,
        actor,
    )

    row = database.add.call_args.args[0]
    assert row.message == "Please add me"
    assert row.invite_id == invite.id
    assert invite.use_count == 1
    assert response.status == "pending"
    requested.assert_awaited_once_with(database, team, requester_id=actor.id, message="Please add me")
    database.commit.assert_awaited_once()
    join_event.assert_awaited_once_with(
        teams.EventType.TEAM_JOIN_REQUESTED,
        team,
        actor,
        "Requested to join 'platform'",
    )
    invite_event.assert_awaited_once_with(
        teams.EventType.TEAM_INVITE_REDEEMED,
        invite,
        actor,
        "Invite used to request access",
    )


@pytest.mark.asyncio
async def test_create_public_join_request_does_not_consume_an_invite(monkeypatch):
    actor = _user(username="requester")
    team = _team()
    database = _db()
    monkeypatch.setattr(teams, "_load_team", AsyncMock(return_value=team))
    monkeypatch.setattr(teams, "team_membership", AsyncMock(return_value=None))
    redeem = AsyncMock()
    monkeypatch.setattr(teams, "redeemable_team_invite", redeem)
    requested = AsyncMock()
    monkeypatch.setattr(teams.inbox_sources, "on_team_join_requested", requested)
    monkeypatch.setattr(teams, "_emit_join_event", AsyncMock())
    invite_event = AsyncMock()
    monkeypatch.setattr(teams, "_emit_team_invite_event", invite_event)

    async def flush():
        row = database.add.call_args.args[0]
        row.id = uuid.UUID(int=61)
        row.status = TeamJoinRequestStatus.pending
        row.created_at = _NOW

    database.flush.side_effect = flush
    response = await teams.create_join_request(
        team.id,
        teams.TeamJoinRequestCreate(message="   "),
        database,
        actor,
    )

    assert response.invite_id is None
    assert response.message is None
    redeem.assert_not_awaited()
    invite_event.assert_not_awaited()
    requested.assert_awaited_once_with(database, team, requester_id=actor.id, message=None)


@pytest.mark.asyncio
async def test_create_join_request_duplicate_uses_savepoint_without_external_side_effects(monkeypatch):
    actor = _user(username="requester")
    team = _team()
    database = _db()
    database.flush.side_effect = _integrity_error()
    monkeypatch.setattr(teams, "_load_team", AsyncMock(return_value=team))
    monkeypatch.setattr(teams, "team_membership", AsyncMock(return_value=None))
    requested = AsyncMock()
    monkeypatch.setattr(teams.inbox_sources, "on_team_join_requested", requested)

    with pytest.raises(HTTPException) as exc:
        await teams.create_join_request(team.id, teams.TeamJoinRequestCreate(), database, actor)

    _assert_http(exc, 409, "You already have a pending request for this teamspace")
    database.begin_nested.assert_called_once_with()
    database.commit.assert_not_awaited()
    requested.assert_not_awaited()


@pytest.mark.asyncio
async def test_join_request_lists_apply_visibility_status_and_response_fields(monkeypatch):
    owner = _user(username="owner")
    requester = _user(username="requester")
    team = _team(owner=owner)
    row = _join_request(team, requester)
    monkeypatch.setattr(teams, "_load_visible_team", AsyncMock(return_value=team))
    mine_db = _db(_Result(scalars=[row]))

    mine = await teams.my_join_requests(team.id, mine_db, requester)
    assert [item.id for item in mine] == [row.id]
    assert mine[0].username == requester.username
    mine_sql = _sql(mine_db.execute.await_args.args[0])
    assert requester.id.hex in mine_sql
    assert "created_at DESC" in mine_sql

    monkeypatch.setattr(teams, "_require_owner_or_admin", AsyncMock(return_value=team))
    listing_db = _db(_Result(rows=[(row, requester, owner.username)]))
    listing = await teams.list_join_requests(team.id, "pending", listing_db, owner)
    assert listing[0].decided_by_username == owner.username
    sql = _sql(listing_db.execute.await_args.args[0])
    assert "team_membership_requests.status = 'pending'" in sql
    assert "created_at DESC" in sql

    unfiltered_db = _db(_Result(rows=[]))
    assert await teams.list_join_requests(team.id, None, unfiltered_db, owner) == []
    assert "team_membership_requests.status =" not in _sql(unfiltered_db.execute.await_args.args[0])


@pytest.mark.asyncio
async def test_approve_join_request_grants_member_notifies_and_audits(monkeypatch):
    owner = _user(username="owner")
    requester = _user(username="requester")
    team = _team(owner=owner)
    row = _join_request(team, requester)
    database = _db()
    monkeypatch.setattr(teams, "_require_owner_or_admin", AsyncMock(return_value=team))
    monkeypatch.setattr(teams, "_load_join_request", AsyncMock(return_value=row))
    membership = AsyncMock(return_value=None)
    monkeypatch.setattr(teams, "team_membership", membership)
    decided = AsyncMock()
    monkeypatch.setattr(teams.inbox_sources, "on_team_join_decided", decided)
    event = AsyncMock()
    monkeypatch.setattr(teams, "_emit_join_event", event)
    database.get.return_value = requester

    response = await teams.approve_join_request(team.id, row.id, database, owner)

    added = database.add.call_args.args[0]
    assert (added.team_id, added.user_id, added.role) == (team.id, requester.id, TeamRole.member)
    assert row.status == TeamJoinRequestStatus.approved
    assert row.decided_by == owner.id
    assert row.decided_at is not None
    assert response.username == requester.username
    decided.assert_awaited_once_with(
        database,
        team,
        request_id=row.id,
        requester_id=requester.id,
        approved=True,
        actor_id=owner.id,
    )
    event.assert_awaited_once()
    database.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_approve_join_request_handles_existing_decision_membership_and_constraint_race(monkeypatch):
    owner = _user(username="owner")
    requester = _user(username="requester")
    team = _team(owner=owner)
    row = _join_request(team, requester, status=TeamJoinRequestStatus.rejected)
    database = _db()
    monkeypatch.setattr(teams, "_require_owner_or_admin", AsyncMock(return_value=team))
    monkeypatch.setattr(teams, "_load_join_request", AsyncMock(return_value=row))

    with pytest.raises(HTTPException) as exc:
        await teams.approve_join_request(team.id, row.id, database, owner)
    _assert_http(exc, 409, "Request already rejected")

    row.status = TeamJoinRequestStatus.pending
    existing = _membership(team, requester, TeamRole.reviewer)
    membership = AsyncMock(return_value=existing)
    monkeypatch.setattr(teams, "team_membership", membership)
    monkeypatch.setattr(teams.inbox_sources, "on_team_join_decided", AsyncMock())
    monkeypatch.setattr(teams, "_emit_join_event", AsyncMock())
    database.get.return_value = requester
    await teams.approve_join_request(team.id, row.id, database, owner)
    database.add.assert_not_called()
    assert existing.role == TeamRole.reviewer

    row.status = TeamJoinRequestStatus.pending
    race_db = _db()
    race_db.flush.side_effect = _integrity_error()
    race_db.get.return_value = requester
    membership.side_effect = [None, existing]
    await teams.approve_join_request(team.id, row.id, race_db, owner)
    assert row.status == TeamJoinRequestStatus.approved

    row.status = TeamJoinRequestStatus.pending
    failed_db = _db()
    failed_db.flush.side_effect = _integrity_error()
    membership.side_effect = [None, None]
    with pytest.raises(IntegrityError):
        await teams.approve_join_request(team.id, row.id, failed_db, owner)
    failed_db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_reject_join_request_records_trimmed_reason_and_event(monkeypatch):
    owner = _user(username="owner")
    requester = _user(username="requester")
    team = _team(owner=owner)
    row = _join_request(team, requester)
    database = _db()
    database.get.return_value = requester
    monkeypatch.setattr(teams, "_require_owner_or_admin", AsyncMock(return_value=team))
    monkeypatch.setattr(teams, "_load_join_request", AsyncMock(return_value=row))
    decided = AsyncMock()
    monkeypatch.setattr(teams.inbox_sources, "on_team_join_decided", decided)
    event = AsyncMock()
    monkeypatch.setattr(teams, "_emit_join_event", event)

    response = await teams.reject_join_request(
        team.id,
        row.id,
        teams.TeamJoinDecisionRequest(reason="  Capacity reached  "),
        database,
        owner,
    )

    assert row.status == TeamJoinRequestStatus.rejected
    assert row.decision_reason == "Capacity reached"
    assert response.decision_reason == "Capacity reached"
    decided.assert_awaited_once_with(
        database,
        team,
        request_id=row.id,
        requester_id=requester.id,
        approved=False,
        actor_id=owner.id,
        reason="Capacity reached",
    )
    event.assert_awaited_once()

    row.status = TeamJoinRequestStatus.approved
    with pytest.raises(HTTPException) as exc:
        await teams.reject_join_request(team.id, row.id, None, database, owner)
    _assert_http(exc, 409, "Request already approved")


@pytest.mark.asyncio
async def test_cancel_join_request_enforces_requester_pending_state_and_persists(monkeypatch):
    requester = _user(username="requester")
    other = _user(username="other")
    team = _team()
    row = _join_request(team, requester)
    database = _db()
    monkeypatch.setattr(teams, "_load_team", AsyncMock(return_value=team))
    monkeypatch.setattr(teams, "_load_join_request", AsyncMock(return_value=row))
    cancelled = AsyncMock()
    monkeypatch.setattr(teams.inbox_sources, "on_team_join_cancelled", cancelled)

    with pytest.raises(HTTPException) as exc:
        await teams.cancel_join_request(team.id, row.id, database, other)
    _assert_http(exc, 403, "Only the requester can withdraw a request")

    row.status = TeamJoinRequestStatus.approved
    with pytest.raises(HTTPException) as exc:
        await teams.cancel_join_request(team.id, row.id, database, requester)
    _assert_http(exc, 409, "Request already approved")

    row.status = TeamJoinRequestStatus.pending
    await teams.cancel_join_request(team.id, row.id, database, requester)
    assert row.status == TeamJoinRequestStatus.cancelled
    assert row.decided_by == requester.id
    assert row.decided_at is not None
    cancelled.assert_awaited_once_with(database, team, requester_id=requester.id)
    database.commit.assert_awaited_once()
