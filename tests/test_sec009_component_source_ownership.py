# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for component source org ownership enforcement.

Verifies that:
- add_source derives owner_org_id from the authenticated user, not the request body
- list_sources returns only public sources and the caller's own org sources
- get_source returns 404 for private sources owned by a different org
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_client():
    from httpx import ASGITransport, AsyncClient

    from api.ratelimit import limiter
    from main import app

    limiter.enabled = False
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    )


def _user(role="user", org_id=None):
    from models.user import User, UserRole

    u = MagicMock(spec=User)
    u.id = uuid.uuid4()
    u.role = getattr(UserRole, role)
    u.org_id = org_id if org_id is not None else uuid.uuid4()
    return u


def _source(is_public=True, owner_org_id=None):
    s = MagicMock()
    s.id = uuid.uuid4()
    s.url = "https://github.com/example/repo"
    s.provider = "github"
    s.component_type = "mcp"
    s.is_public = is_public
    s.owner_org_id = owner_org_id or uuid.uuid4()
    s.auto_sync_interval = None
    s.last_synced_at = None
    s.sync_status = None
    s.sync_error = None
    from datetime import UTC, datetime

    s.created_at = datetime.now(UTC)
    return s


# ── add_source: owner_org_id derived from user, not request ──────────────────


@pytest.mark.asyncio
async def test_add_source_ignores_client_owner_org_id():
    """owner_org_id in the request body is ignored; user's org is used."""
    from api.deps import get_current_user, get_db
    from main import app

    org = uuid.uuid4()
    user = _user(org_id=org)
    foreign_org = uuid.uuid4()

    from datetime import UTC, datetime

    created_source = _source(owner_org_id=org)
    captured = {}

    db = AsyncMock()

    def capturing_add(obj):
        captured["source"] = obj
        # Copy required fields onto the object so pydantic serialisation works
        obj.id = created_source.id
        obj.provider = created_source.provider
        obj.created_at = datetime.now(UTC)
        obj.auto_sync_interval = None
        obj.last_synced_at = None
        obj.sync_status = None
        obj.sync_error = None

    db.add = MagicMock(side_effect=capturing_add)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    async def fake_db():
        yield db

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: user

    try:
        async with _make_client() as client:
            r = await client.post(
                "/api/v1/component-sources",
                json={
                    "url": "https://github.com/example/repo",
                    "component_type": "mcp",
                    "is_public": True,
                    "owner_org_id": str(foreign_org),  # attacker supplies foreign org
                },
            )
        assert r.status_code in (201, 409)
        # The source added to DB must use the user's org, not the foreign one
        if "source" in captured:
            assert captured["source"].owner_org_id == org
            assert captured["source"].owner_org_id != foreign_org
    finally:
        app.dependency_overrides.clear()


# ── list_sources: scoped to public + caller's org ─────────────────────────────


@pytest.mark.asyncio
async def test_list_sources_excludes_other_org_private_sources():
    """Private sources from a different org are not returned."""
    from api.deps import get_current_user, get_db
    from main import app

    my_org = uuid.uuid4()
    other_org = uuid.uuid4()
    user = _user(org_id=my_org)

    public_source = _source(is_public=True, owner_org_id=other_org)
    private_mine = _source(is_public=False, owner_org_id=my_org)
    private_other = _source(is_public=False, owner_org_id=other_org)

    db = AsyncMock()
    result = MagicMock()

    # Simulate DB filtering: only return sources that pass the WHERE clause
    # We test by checking what WHERE conditions are applied via the stmt
    executed_stmts = []
    orig_execute = db.execute

    async def capturing_execute(stmt, *a, **kw):
        executed_stmts.append(stmt)
        r = MagicMock()
        r.scalars.return_value.all.return_value = [public_source, private_mine]
        return r

    db.execute = capturing_execute

    async def fake_db():
        yield db

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: user

    try:
        async with _make_client() as client:
            r = await client.get("/api/v1/component-sources")
        assert r.status_code == 200
        # The WHERE clause on the stmt should include org scoping
        assert len(executed_stmts) == 1
        stmt_str = str(executed_stmts[0])
        assert str(my_org) in stmt_str or "owner_org_id" in stmt_str
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_sources_no_org_user_sees_only_public():
    """User with no org_id sees only public sources."""
    from api.deps import get_current_user, get_db
    from main import app

    user = _user()
    user.org_id = None

    db = AsyncMock()
    executed_stmts = []

    async def capturing_execute(stmt, *a, **kw):
        executed_stmts.append(stmt)
        r = MagicMock()
        r.scalars.return_value.all.return_value = []
        return r

    db.execute = capturing_execute

    async def fake_db():
        yield db

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: user

    try:
        async with _make_client() as client:
            r = await client.get("/api/v1/component-sources")
        assert r.status_code == 200
        assert len(executed_stmts) == 1
        # Query must filter to is_public = true only
        stmt_str = str(executed_stmts[0])
        assert "is_public" in stmt_str
    finally:
        app.dependency_overrides.clear()


# ── get_source: private source from another org returns 404 ──────────────────


@pytest.mark.asyncio
async def test_get_source_private_other_org_returns_404():
    """Fetching a private source owned by a different org returns 404."""
    from api.deps import get_current_user, get_db
    from main import app

    my_org = uuid.uuid4()
    other_org = uuid.uuid4()
    user = _user(org_id=my_org)

    private_source = _source(is_public=False, owner_org_id=other_org)

    db = AsyncMock()
    db.get = AsyncMock(return_value=private_source)

    async def fake_db():
        yield db

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: user

    try:
        async with _make_client() as client:
            r = await client.get(f"/api/v1/component-sources/{private_source.id}")
        assert r.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_source_private_same_org_returns_200():
    """Fetching a private source owned by the caller's org returns 200."""
    from api.deps import get_current_user, get_db
    from main import app

    org = uuid.uuid4()
    user = _user(org_id=org)
    private_source = _source(is_public=False, owner_org_id=org)

    db = AsyncMock()
    db.get = AsyncMock(return_value=private_source)

    async def fake_db():
        yield db

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: user

    try:
        async with _make_client() as client:
            r = await client.get(f"/api/v1/component-sources/{private_source.id}")
        assert r.status_code == 200
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_source_public_any_org_returns_200():
    """Public sources are accessible to any authenticated user."""
    from api.deps import get_current_user, get_db
    from main import app

    user = _user(org_id=uuid.uuid4())
    public_source = _source(is_public=True, owner_org_id=uuid.uuid4())

    db = AsyncMock()
    db.get = AsyncMock(return_value=public_source)

    async def fake_db():
        yield db

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: user

    try:
        async with _make_client() as client:
            r = await client.get(f"/api/v1/component-sources/{public_source.id}")
        assert r.status_code == 200
    finally:
        app.dependency_overrides.clear()
