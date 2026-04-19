"""Tests for bundle review endpoints (atomic approve/reject).

Covers approval and rejection of all listings in a bundle atomically,
and 404 handling for nonexistent bundles.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.deps import get_current_user, get_db
from api.routes.review import router
from models.mcp import ListingStatus
from models.user import User, UserRole

# ── Helpers ──────────────────────────────────────────────


def _user(**kw):
    u = MagicMock(spec=User)
    u.id = kw.get("id", uuid.uuid4())
    u.role = kw.get("role", UserRole.admin)
    return u


def _mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = MagicMock()
    return db


def _app_with(user=None, db=None):
    user = user or _user()
    db = db or _mock_db()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db
    return app, db, user


def _bundle_mock(**extra):
    """Return a MagicMock that looks like a ComponentBundle ORM instance."""
    m = MagicMock()
    m.id = extra.get("id", uuid.uuid4())
    m.name = extra.get("name", "test-bundle")
    m.description = extra.get("description", "A test bundle")
    m.submitted_by = extra.get("submitted_by", uuid.uuid4())
    m.created_at = datetime.now(UTC)
    return m


def _listing_mock(status=ListingStatus.pending, **extra):
    """Return a MagicMock that looks like a listing ORM instance."""
    m = MagicMock()
    m.id = extra.get("id", uuid.uuid4())
    m.name = extra.get("name", "test-listing")
    m.status = status
    m.rejection_reason = None
    m.bundle_id = extra.get("bundle_id", uuid.uuid4())
    m.submitted_by = uuid.uuid4()
    m.created_at = datetime.now(UTC)
    m.updated_at = datetime.now(UTC)
    return m


def _empty_result():
    r = MagicMock()
    r.scalars.return_value.all.return_value = []
    r.scalar_one_or_none.return_value = None
    return r


def _result_with_one(obj):
    """Result that returns obj via scalar_one_or_none."""
    r = MagicMock()
    r.scalar_one_or_none.return_value = obj
    r.scalars.return_value.all.return_value = [obj]
    return r


def _result_with_listings(*listings):
    """Result that returns listings via scalars().all()."""
    r = MagicMock()
    r.scalars.return_value.all.return_value = list(listings)
    r.scalar_one_or_none.return_value = listings[0] if listings else None
    return r


# ═══════════════════════════════════════════════════════════
# approve_bundle (POST /api/v1/review/bundles/{id}/approve)
# ═══════════════════════════════════════════════════════════


class TestBundleApprove:
    """Test bundle approval atomically approves all listings."""

    @pytest.mark.asyncio
    async def test_approves_all_listings(self):
        """Approving a bundle sets all associated listings to approved."""
        app, db, _ = _app_with()
        bundle = _bundle_mock()
        listing_a = _listing_mock(bundle_id=bundle.id, name="listing-a")
        listing_b = _listing_mock(bundle_id=bundle.id, name="listing-b")

        # First call: select bundle by id -> bundle found
        # Next 5 calls: one per listing model type -> only first returns listings
        db.execute = AsyncMock(
            side_effect=[
                _result_with_one(bundle),
                _result_with_listings(listing_a, listing_b),
                _empty_result(),
                _empty_result(),
                _empty_result(),
                _empty_result(),
            ]
        )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(f"/api/v1/review/bundles/{bundle.id}/approve")

        assert r.status_code == 200
        data = r.json()
        assert data["bundle_id"] == str(bundle.id)
        assert data["approved_count"] == 2
        assert listing_a.status == ListingStatus.approved
        assert listing_b.status == ListingStatus.approved
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_approve_empty_bundle_returns_zero_count(self):
        """Approving a bundle with no listings returns approved_count=0."""
        app, db, _ = _app_with()
        bundle = _bundle_mock()

        db.execute = AsyncMock(
            side_effect=[
                _result_with_one(bundle),
                _empty_result(),
                _empty_result(),
                _empty_result(),
                _empty_result(),
                _empty_result(),
            ]
        )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(f"/api/v1/review/bundles/{bundle.id}/approve")

        assert r.status_code == 200
        assert r.json()["approved_count"] == 0


# ═══════════════════════════════════════════════════════════
# reject_bundle (POST /api/v1/review/bundles/{id}/reject)
# ═══════════════════════════════════════════════════════════


class TestBundleReject:
    """Test bundle rejection atomically rejects all listings."""

    @pytest.mark.asyncio
    async def test_rejects_all_with_shared_reason(self):
        """Rejecting a bundle sets all listings to rejected with the given reason."""
        app, db, _ = _app_with()
        bundle = _bundle_mock()
        listing_a = _listing_mock(bundle_id=bundle.id, name="listing-a")
        listing_b = _listing_mock(bundle_id=bundle.id, name="listing-b")

        db.execute = AsyncMock(
            side_effect=[
                _result_with_one(bundle),
                _result_with_listings(listing_a, listing_b),
                _empty_result(),
                _empty_result(),
                _empty_result(),
                _empty_result(),
            ]
        )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(
                f"/api/v1/review/bundles/{bundle.id}/reject",
                json={"reason": "fails security review"},
            )

        assert r.status_code == 200
        data = r.json()
        assert data["rejected_count"] == 2
        assert listing_a.status == ListingStatus.rejected
        assert listing_a.rejection_reason == "fails security review"
        assert listing_b.status == ListingStatus.rejected
        assert listing_b.rejection_reason == "fails security review"
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reject_with_no_reason(self):
        """Rejecting with reason=None still transitions statuses."""
        app, db, _ = _app_with()
        bundle = _bundle_mock()
        listing = _listing_mock(bundle_id=bundle.id)

        db.execute = AsyncMock(
            side_effect=[
                _result_with_one(bundle),
                _result_with_listings(listing),
                _empty_result(),
                _empty_result(),
                _empty_result(),
                _empty_result(),
            ]
        )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(
                f"/api/v1/review/bundles/{bundle.id}/reject",
                json={"reason": None},
            )

        assert r.status_code == 200
        assert listing.status == ListingStatus.rejected


# ═══════════════════════════════════════════════════════════
# Not found (404)
# ═══════════════════════════════════════════════════════════


class TestBundleNotFound:
    """Test 404 for nonexistent bundle in review endpoints."""

    @pytest.mark.asyncio
    async def test_approve_not_found(self):
        """Approving a nonexistent bundle returns 404."""
        app, db, _ = _app_with()
        db.execute = AsyncMock(return_value=_empty_result())

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(f"/api/v1/review/bundles/{uuid.uuid4()}/approve")

        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_reject_not_found(self):
        """Rejecting a nonexistent bundle returns 404."""
        app, db, _ = _app_with()
        db.execute = AsyncMock(return_value=_empty_result())

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(
                f"/api/v1/review/bundles/{uuid.uuid4()}/reject",
                json={"reason": "bad"},
            )

        assert r.status_code == 404
