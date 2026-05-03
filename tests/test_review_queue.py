"""Tests for the review queue endpoints (PR #174 changes).

Covers the list_pending response including description/version/owner fields,
type filtering, get_review detail, and admin enforcement on all endpoints.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.deps import get_current_user, get_db
from api.routes.review import LISTING_MODELS, router
from models.mcp import ListingStatus
from models.user import User, UserRole

# ── Helpers ──────────────────────────────────────────────


def _user(**kw):
    u = MagicMock(spec=User)
    u.id = kw.get("id", uuid.uuid4())
    u.role = kw.get("role", UserRole.admin)
    u.org_id = kw.get("org_id")
    return u


def _mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    return db


def _app_with(user=None, db=None):
    user = user or _user()
    db = db or _mock_db()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db
    return app, db, user


def _listing_mock(status=ListingStatus.pending, **extra):
    m = MagicMock()
    m.id = uuid.uuid4()
    m.name = extra.get("name", "test-listing")
    m.version = extra.get("version", "1.0.0")
    m.description = extra.get("description", "A test description")
    m.owner = extra.get("owner", "testowner")
    m.status = status
    m.rejection_reason = None
    m.submitted_by = uuid.uuid4()
    m.created_at = datetime.now(UTC)
    m.updated_at = datetime.now(UTC)
    m.bundle_id = extra.get("bundle_id")
    m.versions = extra.get("versions", [])
    m.latest_version_id = extra.get("latest_version_id")
    m.latest_version = extra.get("latest_version")
    for k, v in extra.items():
        setattr(m, k, v)
    return m


def _version_mock(listing_id, **extra):
    m = MagicMock()
    m.id = uuid.uuid4()
    m.listing_id = listing_id
    m.status = extra.get("status", ListingStatus.pending)
    m.description = extra.get("description", "A test description")
    m.version = extra.get("version", "1.0.0")
    m.created_at = extra.get("created_at", datetime.now(UTC))
    m.is_editing = False
    m.editing_since = None
    m.editing_by = None
    return m


def _empty_result():
    r = MagicMock()
    r.scalars.return_value.all.return_value = []
    r.scalar_one_or_none.return_value = None
    return r


def _result_with(*listings):
    r = MagicMock()
    r.scalars.return_value.all.return_value = list(listings)
    if listings:
        r.scalar_one_or_none.return_value = listings[0]
    else:
        r.scalar_one_or_none.return_value = None
    return r


# ═══════════════════════════════════════════════════════════
# list_pending (GET /api/v1/review)
# ═══════════════════════════════════════════════════════════


class TestListPending:
    @pytest.mark.asyncio
    async def test_response_includes_description_version_owner(self):
        """PR #174: list_pending must return description, version, owner fields."""
        app, db, _ = _app_with()
        listing = _listing_mock(owner="acme-corp")
        version = _version_mock(listing.id, description="My cool MCP server", version="2.1.0")
        results = [
            _empty_result(),  # agents: pending versions (empty → return early)
            _result_with(version),  # mcp: pending versions
            _result_with(listing),  # mcp: listings load
            _empty_result(),  # skill: pending versions (empty → continue)
            _empty_result(),  # hook: pending versions (empty → continue)
            _empty_result(),  # prompt: pending versions (empty → continue)
            _empty_result(),  # sandbox: pending versions (empty → continue)
            _empty_result(),  # user lookup
        ]
        db.execute = AsyncMock(side_effect=results)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/v1/review")

        assert r.status_code == 200
        items = r.json()
        assert len(items) >= 1
        item = items[0]
        assert item["description"] == "My cool MCP server"
        assert item["version"] == "2.1.0"
        assert item["owner"] == "acme-corp"

    @pytest.mark.asyncio
    async def test_response_includes_all_expected_fields(self):
        """Verify the full shape of each item in the list_pending response."""
        app, db, _ = _app_with()
        listing = _listing_mock()
        version = _version_mock(listing.id)
        results = [
            _empty_result(),  # agents: pending versions (empty → return early)
            _result_with(version),  # mcp: pending versions
            _result_with(listing),  # mcp: listings load
            _empty_result(),  # skill: pending versions (empty → continue)
            _empty_result(),  # hook: pending versions (empty → continue)
            _empty_result(),  # prompt: pending versions (empty → continue)
            _empty_result(),  # sandbox: pending versions (empty → continue)
            _empty_result(),  # user lookup
        ]
        db.execute = AsyncMock(side_effect=results)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/v1/review")

        assert r.status_code == 200
        item = r.json()[0]
        expected_keys = {
            "type",
            "id",
            "name",
            "description",
            "version",
            "owner",
            "status",
            "submitted_by",
            "created_at",
        }
        assert expected_keys.issubset(set(item.keys()))

    @pytest.mark.asyncio
    async def test_missing_description_defaults_to_empty(self):
        """When a listing has no description attr, response should default to empty string."""
        app, db, _ = _app_with()
        listing = _listing_mock()
        version = _version_mock(listing.id)
        version.description = None
        listing.description = None
        results = [
            _empty_result(),  # agents: pending versions (empty → return early)
            _result_with(version),  # mcp: pending versions
            _result_with(listing),  # mcp: listings load
            _empty_result(),  # skill: pending versions (empty → continue)
            _empty_result(),  # hook: pending versions (empty → continue)
            _empty_result(),  # prompt: pending versions (empty → continue)
            _empty_result(),  # sandbox: pending versions (empty → continue)
            _empty_result(),  # user lookup
        ]
        db.execute = AsyncMock(side_effect=results)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/v1/review")

        assert r.json()[0]["description"] == ""

    @pytest.mark.asyncio
    async def test_missing_version_defaults_to_empty(self):
        """When a listing has no version attr, response should default to empty string."""
        app, db, _ = _app_with()
        listing = _listing_mock()
        version = _version_mock(listing.id)
        version.version = None
        results = [
            _empty_result(),  # agents: pending versions (empty → return early)
            _result_with(version),  # mcp: pending versions
            _result_with(listing),  # mcp: listings load
            _empty_result(),  # skill: pending versions (empty → continue)
            _empty_result(),  # hook: pending versions (empty → continue)
            _empty_result(),  # prompt: pending versions (empty → continue)
            _empty_result(),  # sandbox: pending versions (empty → continue)
            _empty_result(),  # user lookup
        ]
        db.execute = AsyncMock(side_effect=results)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/v1/review")

        assert r.json()[0]["version"] == ""

    @pytest.mark.asyncio
    async def test_missing_owner_defaults_to_empty(self):
        """When a listing has no owner attr, response should default to empty string."""
        app, db, _ = _app_with()
        listing = _listing_mock()
        version = _version_mock(listing.id)
        listing.owner = None
        results = [
            _empty_result(),  # agents: pending versions (empty → return early)
            _result_with(version),  # mcp: pending versions
            _result_with(listing),  # mcp: listings load
            _empty_result(),  # skill: pending versions (empty → continue)
            _empty_result(),  # hook: pending versions (empty → continue)
            _empty_result(),  # prompt: pending versions (empty → continue)
            _empty_result(),  # sandbox: pending versions (empty → continue)
            _empty_result(),  # user lookup
        ]
        db.execute = AsyncMock(side_effect=results)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/v1/review")

        assert r.json()[0]["owner"] == ""

    @pytest.mark.asyncio
    async def test_type_filter_queries_single_model(self):
        """The ?type= query param should only query that one listing type."""
        app, db, _ = _app_with()
        listing = _listing_mock()
        version = _version_mock(listing.id)
        results = [
            _empty_result(),  # agents: pending versions (empty → return early)
            _result_with(version),  # mcp: pending versions
            _result_with(listing),  # mcp: listings load
            _empty_result(),  # user lookup
        ]
        db.execute = AsyncMock(side_effect=results)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/v1/review?type=mcp")

        assert r.status_code == 200
        # 1 agents query + 2 mcp queries (versions + listings) + 1 user lookup
        assert db.execute.call_count == 4
        assert r.json()[0]["type"] == "mcp"

    @pytest.mark.asyncio
    async def test_invalid_type_filter_returns_all(self):
        """An unrecognized ?type= value should query all listing types."""
        app, db, _ = _app_with()
        db.execute = AsyncMock(return_value=_empty_result())

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/v1/review?type=nonexistent")

        assert r.status_code == 200
        # 1 agents query + 5 listing types (invalid type falls back to all)
        assert db.execute.call_count == 1 + len(LISTING_MODELS)

    @pytest.mark.asyncio
    async def test_multiple_listings_across_types(self):
        """Listings from different model types all appear in a single response."""
        app, db, _ = _app_with()
        mcp_listing = _listing_mock(name="mcp-one")
        mcp_version = _version_mock(mcp_listing.id)
        skill_listing = _listing_mock(name="skill-one")
        skill_version = _version_mock(skill_listing.id)
        results = [
            _empty_result(),  # agents: pending versions (empty → return early)
            _result_with(mcp_version),  # mcp: pending versions
            _result_with(mcp_listing),  # mcp: listings load
            _result_with(skill_version),  # skill: pending versions
            _result_with(skill_listing),  # skill: listings load
            _empty_result(),  # hook: pending versions (empty → continue)
            _empty_result(),  # prompt: pending versions (empty → continue)
            _empty_result(),  # sandbox: pending versions (empty → continue)
            _empty_result(),  # user lookup
        ]
        db.execute = AsyncMock(side_effect=results)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/v1/review")

        assert r.status_code == 200
        names = {item["name"] for item in r.json()}
        assert "mcp-one" in names
        assert "skill-one" in names

    @pytest.mark.asyncio
    async def test_requires_admin(self):
        user = _user(role=UserRole.user)
        app, _, _ = _app_with(user=user)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/v1/review")

        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_user_role_forbidden(self):
        user = _user(role=UserRole.user)
        app, _, _ = _app_with(user=user)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/v1/review")

        assert r.status_code == 403


# ═══════════════════════════════════════════════════════════
# get_review (GET /api/v1/review/{listing_id})
# ═══════════════════════════════════════════════════════════


class TestGetReview:
    @pytest.mark.asyncio
    async def test_returns_listing_detail(self):
        app, db, _ = _app_with()
        listing = _listing_mock(name="my-mcp")
        listing.validation_results = []
        db.execute = AsyncMock(side_effect=[_result_with(listing)] + [_empty_result() for _ in range(5)])

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get(f"/api/v1/review/{listing.id}")

        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "my-mcp"
        assert data["id"] == str(listing.id)
        assert "type" in data
        assert "status" in data

    @pytest.mark.asyncio
    async def test_not_found(self):
        app, db, _ = _app_with()
        db.execute = AsyncMock(return_value=_empty_result())

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get(f"/api/v1/review/{uuid.uuid4()}")

        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_requires_admin(self):
        user = _user(role=UserRole.user)
        app, _, _ = _app_with(user=user)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get(f"/api/v1/review/{uuid.uuid4()}")

        assert r.status_code == 403


# ═══════════════════════════════════════════════════════════
# approve (POST /api/v1/review/{listing_id}/approve)
# ═══════════════════════════════════════════════════════════


class TestApprove:
    @pytest.mark.asyncio
    async def test_sets_status_to_approved(self):
        app, db, _ = _app_with()
        listing = _listing_mock(status=ListingStatus.pending)
        db.execute = AsyncMock(side_effect=[_result_with(listing)] + [_empty_result() for _ in range(4)])
        db.refresh = AsyncMock(side_effect=lambda obj: None)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(f"/api/v1/review/{listing.id}/approve")

        assert r.status_code == 200
        assert listing.status == ListingStatus.approved
        assert r.json()["status"] == "approved"
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_response_includes_type_and_name(self):
        app, db, _ = _app_with()
        listing = _listing_mock(name="cool-server")
        db.execute = AsyncMock(side_effect=[_result_with(listing)] + [_empty_result() for _ in range(4)])
        db.refresh = AsyncMock(side_effect=lambda obj: None)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(f"/api/v1/review/{listing.id}/approve")

        data = r.json()
        assert data["name"] == "cool-server"
        assert "type" in data
        assert "id" in data

    @pytest.mark.asyncio
    async def test_approves_pending_version_and_updates_latest(self):
        """When a listing has a pending version, approve targets the version
        and updates latest_version_id (with flush before to avoid CircularDependencyError)."""
        app, db, user = _app_with()
        listing = _listing_mock(status=ListingStatus.approved)
        pending_ver = _version_mock(listing.id, status=ListingStatus.pending, version="2.0.0")
        listing.versions = [pending_ver]
        listing.latest_version_id = uuid.uuid4()  # points to old approved version
        db.execute = AsyncMock(side_effect=[_result_with(listing)] + [_empty_result() for _ in range(4)])
        db.refresh = AsyncMock(side_effect=lambda obj: None)
        db.flush = AsyncMock()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(f"/api/v1/review/{listing.id}/approve")

        assert r.status_code == 200
        assert pending_ver.status == ListingStatus.approved
        assert pending_ver.rejection_reason is None
        assert pending_ver.reviewed_by == user.id
        assert listing.latest_version_id == pending_ver.id
        # flush must be called before commit to avoid CircularDependencyError
        db.flush.assert_awaited_once()
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_not_found(self):
        app, db, _ = _app_with()
        db.execute = AsyncMock(return_value=_empty_result())

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(f"/api/v1/review/{uuid.uuid4()}/approve")

        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_requires_admin(self):
        user = _user(role=UserRole.user)
        app, _, _ = _app_with(user=user)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(f"/api/v1/review/{uuid.uuid4()}/approve")

        assert r.status_code == 403


# ═══════════════════════════════════════════════════════════
# reject (POST /api/v1/review/{listing_id}/reject)
# ═══════════════════════════════════════════════════════════


class TestReject:
    @pytest.mark.asyncio
    async def test_sets_status_and_reason(self):
        app, db, _ = _app_with()
        listing = _listing_mock(status=ListingStatus.pending)
        db.execute = AsyncMock(side_effect=[_result_with(listing)] + [_empty_result() for _ in range(4)])
        db.refresh = AsyncMock(side_effect=lambda obj: None)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(
                f"/api/v1/review/{listing.id}/reject",
                json={"reason": "missing docs"},
            )

        assert r.status_code == 200
        assert listing.status == ListingStatus.rejected
        assert listing.rejection_reason == "missing docs"
        assert r.json()["status"] == "rejected"
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reject_with_no_reason(self):
        app, db, _ = _app_with()
        listing = _listing_mock(status=ListingStatus.pending)
        db.execute = AsyncMock(side_effect=[_result_with(listing)] + [_empty_result() for _ in range(4)])
        db.refresh = AsyncMock(side_effect=lambda obj: None)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(
                f"/api/v1/review/{listing.id}/reject",
                json={"reason": None},
            )

        assert r.status_code == 200
        assert listing.status == ListingStatus.rejected

    @pytest.mark.asyncio
    async def test_not_found(self):
        app, db, _ = _app_with()
        db.execute = AsyncMock(return_value=_empty_result())

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(
                f"/api/v1/review/{uuid.uuid4()}/reject",
                json={"reason": "bad"},
            )

        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_requires_admin(self):
        user = _user(role=UserRole.user)
        app, _, _ = _app_with(user=user)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(
                f"/api/v1/review/{uuid.uuid4()}/reject",
                json={"reason": "no"},
            )

        assert r.status_code == 403
