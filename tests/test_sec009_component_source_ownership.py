# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Tests for teamspace visibility enforcement on component sources.

Component sources have exactly two visibilities: public (everyone) and team
(members of the owning teamspace, plus global reviewers and admins). There is no
organization axis.

Verifies that:
- add_source derives the teamspace and visibility from the authenticated user's
  membership, never from unvalidated request-body input
- list_sources returns public sources plus team-private sources of teams the
  caller belongs to, and nothing else
- get_source answers 404 (not 403) for a team-private source the caller cannot
  see, so existence is never leaked

The routes run against a real in-memory SQLite session so the visibility SQL is
actually executed rather than merely inspected.
"""

import uuid
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models.base import Base
from models.component_source import ComponentSource
from models.team import Team, TeamMembership, TeamRole
from models.user import User, UserRole

_TABLES = [ComponentSource.__table__, Team.__table__, TeamMembership.__table__]


def _make_client():
    from httpx import ASGITransport, AsyncClient

    from api.ratelimit import limiter
    from main import app

    limiter.enabled = False
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    )


@asynccontextmanager
async def _api(user: User | None):
    """Bind the app to a fresh database and authenticate as ``user`` (None = anonymous)."""
    from api.deps import get_current_user, get_db
    from main import app

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=_TABLES)
        sessions = async_sessionmaker(engine, expire_on_commit=False)

        async def _db():
            async with sessions() as session:
                yield session

        app.dependency_overrides[get_db] = _db
        if user is not None:
            app.dependency_overrides[get_current_user] = lambda: user
        try:
            async with _make_client() as client:
                yield client, sessions
        finally:
            app.dependency_overrides.clear()
    finally:
        await engine.dispose()


async def _seed(sessions, *rows):
    async with sessions() as session:
        session.add_all(rows)
        await session.commit()


async def _sources(sessions) -> list[ComponentSource]:
    async with sessions() as session:
        return list((await session.execute(select(ComponentSource))).scalars().all())


def _user(username: str = "alice", role: UserRole = UserRole.user) -> User:
    return User(
        id=uuid.uuid4(),
        email=f"{username}@example.com",
        username=username,
        name=username.title(),
        role=role,
    )


def _team(handle: str) -> Team:
    return Team(id=uuid.uuid4(), name=handle.title(), handle=handle, created_by=uuid.uuid4())


def _member(team: Team, user: User, role: TeamRole = TeamRole.member) -> TeamMembership:
    return TeamMembership(id=uuid.uuid4(), team_id=team.id, user_id=user.id, role=role)


def _source(url: str, *, is_public: bool = True, team_id: uuid.UUID | None = None) -> ComponentSource:
    return ComponentSource(
        id=uuid.uuid4(),
        url=url,
        provider="github",
        component_type="mcp",
        is_public=is_public,
        team_id=team_id,
    )


# ── add_source: teamspace derived from membership, not from the request body ──


@pytest.mark.asyncio
async def test_add_source_rejects_team_id_the_caller_is_not_a_member_of():
    """A client-supplied team_id cannot attach a source to a foreign teamspace."""
    user = _user()
    foreign_team = _team("platform")

    async with _api(user) as (client, sessions):
        await _seed(sessions, foreign_team)
        r = await client.post(
            "/api/v1/component-sources",
            json={
                "url": "https://github.com/example/repo",
                "component_type": "mcp",
                "team_id": str(foreign_team.id),
                "visibility": "team",
            },
        )
        assert r.status_code == 403
        assert await _sources(sessions) == []


@pytest.mark.asyncio
async def test_add_source_rejects_foreign_team_even_for_public_visibility():
    """Membership is checked on team_id itself, not only when visibility is 'team'."""
    user = _user()
    foreign_team = _team("platform")

    async with _api(user) as (client, sessions):
        await _seed(sessions, foreign_team)
        r = await client.post(
            "/api/v1/component-sources",
            json={
                "url": "https://github.com/example/repo",
                "component_type": "mcp",
                "team_id": str(foreign_team.id),
                "visibility": "public",
            },
        )
        assert r.status_code == 403
        assert await _sources(sessions) == []


@pytest.mark.asyncio
async def test_add_source_rejects_team_visibility_without_a_teamspace():
    """Team visibility with no teamspace has no membership to authorize against."""
    async with _api(_user()) as (client, sessions):
        r = await client.post(
            "/api/v1/component-sources",
            json={
                "url": "https://github.com/example/repo",
                "component_type": "mcp",
                "visibility": "team",
            },
        )
        assert r.status_code == 422
        assert await _sources(sessions) == []


@pytest.mark.asyncio
async def test_add_source_stores_team_visibility_for_a_member():
    """A member publishing to their own teamspace gets a team-private source."""
    user = _user()
    team = _team("platform")

    async with _api(user) as (client, sessions):
        await _seed(sessions, team, _member(team, user))
        r = await client.post(
            "/api/v1/component-sources",
            json={
                "url": "https://github.com/example/repo",
                "component_type": "mcp",
                "team_id": str(team.id),
                "visibility": "team",
            },
        )
        assert r.status_code == 201
        assert r.json()["visibility"] == "team"
        assert r.json()["team_id"] == str(team.id)

        stored = await _sources(sessions)
        assert len(stored) == 1
        assert stored[0].is_public is False
        assert stored[0].team_id == team.id


@pytest.mark.asyncio
async def test_add_source_without_a_team_is_public():
    """No teamspace means no private scope to hide the source in."""
    async with _api(_user()) as (client, sessions):
        r = await client.post(
            "/api/v1/component-sources",
            json={"url": "https://github.com/example/repo", "component_type": "mcp"},
        )
        assert r.status_code == 201
        assert r.json()["visibility"] == "public"
        assert r.json()["team_id"] is None

        stored = await _sources(sessions)
        assert len(stored) == 1
        assert stored[0].is_public is True
        assert stored[0].team_id is None


# ── list_sources: public plus the caller's own teamspaces ────────────────────


@pytest.mark.asyncio
async def test_list_sources_excludes_team_private_sources_of_other_teams():
    """Team-private sources of a teamspace the caller is not in are never listed."""
    user = _user()
    mine, theirs = _team("mine"), _team("theirs")

    async with _api(user) as (client, sessions):
        await _seed(
            sessions,
            mine,
            theirs,
            _member(mine, user),
            _source("https://github.com/example/public", is_public=True),
            _source("https://github.com/example/mine", is_public=False, team_id=mine.id),
            _source("https://github.com/example/theirs", is_public=False, team_id=theirs.id),
        )
        r = await client.get("/api/v1/component-sources")
        assert r.status_code == 200
        assert {s["url"] for s in r.json()} == {
            "https://github.com/example/public",
            "https://github.com/example/mine",
        }


@pytest.mark.asyncio
async def test_list_sources_includes_team_private_sources_for_a_member():
    """Membership is what admits a team-private source into the listing."""
    user = _user()
    team = _team("platform")

    async with _api(user) as (client, sessions):
        await _seed(
            sessions,
            team,
            _member(team, user),
            _source("https://github.com/example/private", is_public=False, team_id=team.id),
        )
        r = await client.get("/api/v1/component-sources")
        assert r.status_code == 200
        assert [s["url"] for s in r.json()] == ["https://github.com/example/private"]
        assert r.json()[0]["visibility"] == "team"


@pytest.mark.asyncio
async def test_list_sources_hides_private_sources_with_no_teamspace():
    """A private source with no teamspace has no membership that can admit it."""
    async with _api(_user()) as (client, sessions):
        await _seed(
            sessions,
            _source("https://github.com/example/orphan", is_public=False, team_id=None),
            _source("https://github.com/example/public", is_public=True),
        )
        r = await client.get("/api/v1/component-sources")
        assert r.status_code == 200
        assert [s["url"] for s in r.json()] == ["https://github.com/example/public"]


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRole.reviewer, UserRole.admin, UserRole.super_admin])
async def test_list_sources_returns_every_team_private_source_to_global_reviewers(role):
    """Global reviewers and admins moderate the whole registry, so they see all of it."""
    team = _team("platform")

    async with _api(_user(role=role)) as (client, sessions):
        await _seed(
            sessions,
            team,
            _source("https://github.com/example/private", is_public=False, team_id=team.id),
            _source("https://github.com/example/public", is_public=True),
        )
        r = await client.get("/api/v1/component-sources")
        assert r.status_code == 200
        assert {s["url"] for s in r.json()} == {
            "https://github.com/example/private",
            "https://github.com/example/public",
        }


# ── get_source: non-members get 404 so existence is not leaked ───────────────


@pytest.mark.asyncio
async def test_get_team_private_source_as_non_member_returns_404():
    """A non-member gets the same answer as for an id that does not exist."""
    team = _team("platform")
    private = _source("https://github.com/example/private", is_public=False, team_id=team.id)

    async with _api(_user()) as (client, sessions):
        await _seed(sessions, team, private)
        hidden = await client.get(f"/api/v1/component-sources/{private.id}")
        missing = await client.get(f"/api/v1/component-sources/{uuid.uuid4()}")
        assert hidden.status_code == 404
        assert hidden.json() == missing.json()


@pytest.mark.asyncio
async def test_get_private_source_with_no_teamspace_returns_404():
    """No teamspace means no membership can grant access, so it stays hidden."""
    orphan = _source("https://github.com/example/orphan", is_public=False, team_id=None)

    async with _api(_user()) as (client, sessions):
        await _seed(sessions, orphan)
        r = await client.get(f"/api/v1/component-sources/{orphan.id}")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_team_private_source_as_member_returns_200():
    """Members of the owning teamspace can read the source."""
    user = _user()
    team = _team("platform")
    private = _source("https://github.com/example/private", is_public=False, team_id=team.id)

    async with _api(user) as (client, sessions):
        await _seed(sessions, team, _member(team, user), private)
        r = await client.get(f"/api/v1/component-sources/{private.id}")
        assert r.status_code == 200
        assert r.json()["visibility"] == "team"
        assert r.json()["team_id"] == str(team.id)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRole.reviewer, UserRole.admin, UserRole.super_admin])
async def test_get_team_private_source_as_global_reviewer_returns_200(role):
    """Global reviewers and admins can read team-private sources."""
    team = _team("platform")
    private = _source("https://github.com/example/private", is_public=False, team_id=team.id)

    async with _api(_user(role=role)) as (client, sessions):
        await _seed(sessions, team, private)
        r = await client.get(f"/api/v1/component-sources/{private.id}")
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_get_public_source_returns_200_for_any_authenticated_caller():
    """Public sources carry no teamspace restriction."""
    public = _source("https://github.com/example/public", is_public=True)

    async with _api(_user(username="nobody")) as (client, sessions):
        await _seed(sessions, public)
        r = await client.get(f"/api/v1/component-sources/{public.id}")
        assert r.status_code == 200
        assert r.json()["visibility"] == "public"
        assert r.json()["team_id"] is None


@pytest.mark.asyncio
async def test_component_sources_require_authentication():
    """The whole surface is authenticated, so anonymous callers never reach visibility."""
    public = _source("https://github.com/example/public", is_public=True)

    async with _api(None) as (client, sessions):
        await _seed(sessions, public)
        assert (await client.get("/api/v1/component-sources")).status_code == 401
        assert (await client.get(f"/api/v1/component-sources/{public.id}")).status_code == 401
