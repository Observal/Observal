# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for retention admin API endpoints (GET/PUT config, preview, stats, warnings)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.deps import get_current_user, get_db
from api.routes.admin import router
from models.user import User, UserRole

# ── Helpers ──────────────────────────────────────────────


def _user(role=UserRole.super_admin, org_id=None):
    u = MagicMock(spec=User)
    u.id = uuid.uuid4()
    u.role = role
    u.email = "admin@test.example"
    u.username = "admin"
    u.org_id = org_id or uuid.uuid4()
    return u


def _org(retention_enabled=False, data_retention_days=None, score_retention_days=None, max_trace_count=None):
    org = MagicMock()
    org.id = uuid.uuid4()
    org.slug = "test-org"
    org.retention_enabled = retention_enabled
    org.data_retention_days = data_retention_days
    org.score_retention_days = score_retention_days
    org.max_trace_count = max_trace_count
    return org


def _mock_db(org=None):
    db = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    if org:
        result = MagicMock()
        result.scalar_one_or_none.return_value = org
        db.execute = AsyncMock(return_value=result)

    return db


def _app_with(user=None, db=None):
    user = user or _user()
    db = db or _mock_db()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db
    return app, db, user


def _clickhouse_response(status_code=200, data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = ""
    if data is not None:
        resp.json.return_value = {"data": data}
    else:
        resp.json.return_value = {"data": []}
    return resp


# ── GET /api/v1/admin/org/retention ─────────────────────────────


class TestGetRetentionConfig:
    @pytest.mark.asyncio
    async def test_returns_config_for_admin(self):
        org = _org(retention_enabled=True, data_retention_days=14, score_retention_days=30)
        user = _user(role=UserRole.admin, org_id=org.id)
        db = _mock_db(org)
        app, _, _ = _app_with(user=user, db=db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.get("/api/v1/admin/org/retention")

        assert resp.status_code == 200
        data = resp.json()
        assert data["retention_enabled"] is True
        assert data["data_retention_days"] == 14
        assert data["score_retention_days"] == 30

    @pytest.mark.asyncio
    async def test_returns_global_ceiling(self):
        org = _org()
        user = _user(role=UserRole.admin, org_id=org.id)
        db = _mock_db(org)
        app, _, _ = _app_with(user=user, db=db)

        with patch("api.routes.admin.retention.ds") as mock_ds:
            mock_ds.get_int = AsyncMock(return_value=45)
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
                resp = await c.get("/api/v1/admin/org/retention")

        assert resp.status_code == 200
        assert resp.json()["global_retention_days"] == 45


# ── PUT /api/v1/admin/org/retention ─────────────────────────────


class TestUpdateRetentionConfig:
    @pytest.mark.asyncio
    async def test_update_succeeds_with_valid_config(self):
        org = _org()
        user = _user(role=UserRole.super_admin, org_id=org.id)
        db = _mock_db(org)
        app, _, _ = _app_with(user=user, db=db)

        with (
            patch("api.routes.admin.retention.ds") as mock_ds,
            patch("api.routes.admin.retention.emit_security_event", new_callable=AsyncMock),
        ):
            mock_ds.get_int = AsyncMock(return_value=90)
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
                resp = await c.put(
                    "/api/v1/admin/org/retention",
                    json={
                        "retention_enabled": True,
                        "data_retention_days": 14,
                        "score_retention_days": 30,
                        "max_trace_count": 5000,
                    },
                )

        assert resp.status_code == 200
        assert org.retention_enabled is True
        assert org.data_retention_days == 14

    @pytest.mark.asyncio
    async def test_rejects_days_exceeding_global_ceiling(self):
        org = _org()
        user = _user(role=UserRole.super_admin, org_id=org.id)
        db = _mock_db(org)
        app, _, _ = _app_with(user=user, db=db)

        with patch("api.routes.admin.retention.ds") as mock_ds:
            mock_ds.get_int = AsyncMock(return_value=10)
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
                resp = await c.put(
                    "/api/v1/admin/org/retention",
                    json={
                        "retention_enabled": True,
                        "data_retention_days": 15,
                    },
                )

        assert resp.status_code == 422
        assert "global ceiling" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_allows_any_days_when_ceiling_is_zero(self):
        org = _org()
        user = _user(role=UserRole.super_admin, org_id=org.id)
        db = _mock_db(org)
        app, _, _ = _app_with(user=user, db=db)

        with (
            patch("api.routes.admin.retention.ds") as mock_ds,
            patch("api.routes.admin.retention.emit_security_event", new_callable=AsyncMock),
        ):
            mock_ds.get_int = AsyncMock(return_value=0)
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
                resp = await c.put(
                    "/api/v1/admin/org/retention",
                    json={
                        "retention_enabled": True,
                        "data_retention_days": 365,
                    },
                )

        assert resp.status_code == 200


# ── GET /api/v1/admin/org/retention/preview ─────────────────────


class TestPreviewRetention:
    @pytest.mark.asyncio
    async def test_preview_returns_counts(self):
        org = _org()
        user = _user(role=UserRole.super_admin, org_id=org.id)
        db = _mock_db(org)
        app, _, _ = _app_with(user=user, db=db)

        ch_resp = _clickhouse_response(data=[{"cnt": "42"}])

        with (
            patch("api.routes.admin.retention._get_user_org", new_callable=AsyncMock, return_value=org),
            patch("services.clickhouse._query", new_callable=AsyncMock, return_value=ch_resp),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
                resp = await c.get("/api/v1/admin/org/retention/preview?days=14")

        assert resp.status_code == 200
        data = resp.json()
        assert data["session_events"] == 42
        assert "traces" not in data
        assert "spans" not in data

    @pytest.mark.asyncio
    async def test_preview_rejects_days_below_7(self):
        org = _org()
        user = _user(role=UserRole.super_admin, org_id=org.id)
        db = _mock_db(org)
        app, _, _ = _app_with(user=user, db=db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.get("/api/v1/admin/org/retention/preview?days=3")

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_preview_handles_clickhouse_failure(self):
        org = _org()
        user = _user(role=UserRole.super_admin, org_id=org.id)
        db = _mock_db(org)
        app, _, _ = _app_with(user=user, db=db)

        ch_resp = _clickhouse_response(status_code=500)

        with (
            patch("api.routes.admin.retention._get_user_org", new_callable=AsyncMock, return_value=org),
            patch("services.clickhouse._query", new_callable=AsyncMock, return_value=ch_resp),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
                resp = await c.get("/api/v1/admin/org/retention/preview?days=14")

        assert resp.status_code == 200
        data = resp.json()
        assert data["session_events"] == -1


# ── GET /api/v1/admin/org/retention/stats ───────────────────────


class TestRetentionStats:
    @pytest.mark.asyncio
    async def test_stats_disabled_returns_zeroes(self):
        org = _org(retention_enabled=False)
        user = _user(role=UserRole.admin, org_id=org.id)
        db = _mock_db(org)
        app, _, _ = _app_with(user=user, db=db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.get("/api/v1/admin/org/retention/stats")

        assert resp.status_code == 200
        data = resp.json()
        assert data["retention_enabled"] is False
        assert data["total_traces"] == 0
        assert data["oldest_trace_age_days"] == 0

    @pytest.mark.asyncio
    async def test_stats_enabled_with_traces(self):
        org = _org(retention_enabled=True, data_retention_days=14)
        user = _user(role=UserRole.admin, org_id=org.id)
        db = _mock_db(org)
        app, _, _ = _app_with(user=user, db=db)

        ch_resp = _clickhouse_response(data=[{"cnt": "100", "age": "5"}])

        with (
            patch("api.routes.admin.retention._get_user_org", new_callable=AsyncMock, return_value=org),
            patch("services.clickhouse._query", new_callable=AsyncMock, return_value=ch_resp),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
                resp = await c.get("/api/v1/admin/org/retention/stats")

        assert resp.status_code == 200
        data = resp.json()
        assert data["retention_enabled"] is True
        assert data["total_traces"] == 100
        assert data["oldest_trace_age_days"] == 5

    @pytest.mark.asyncio
    async def test_stats_zero_traces_shows_zero_age(self):
        org = _org(retention_enabled=True, data_retention_days=14)
        user = _user(role=UserRole.admin, org_id=org.id)
        db = _mock_db(org)
        app, _, _ = _app_with(user=user, db=db)

        ch_resp = _clickhouse_response(data=[{"cnt": "0", "age": "20591"}])

        with (
            patch("api.routes.admin.retention._get_user_org", new_callable=AsyncMock, return_value=org),
            patch("services.clickhouse._query", new_callable=AsyncMock, return_value=ch_resp),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
                resp = await c.get("/api/v1/admin/org/retention/stats")

        assert resp.status_code == 200
        data = resp.json()
        assert data["oldest_trace_age_days"] == 0


# ── GET /api/v1/admin/org/retention/warnings ────────────────────


class TestRetentionWarnings:
    @pytest.mark.asyncio
    async def test_warnings_disabled_returns_empty(self):
        org = _org(retention_enabled=False)
        user = _user(role=UserRole.admin, org_id=org.id)
        db = _mock_db(org)
        app, _, _ = _app_with(user=user, db=db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.get("/api/v1/admin/org/retention/warnings")

        assert resp.status_code == 200
        data = resp.json()
        assert data["warnings"] == []
        assert data["retention_enabled"] is False

    @pytest.mark.asyncio
    async def test_warnings_no_agents_returns_empty(self):
        org = _org(retention_enabled=True, data_retention_days=14)
        user = _user(role=UserRole.admin, org_id=org.id)
        db = _mock_db(org)
        app, _, _ = _app_with(user=user, db=db)

        # Mock the agent query to return empty
        agents_result = MagicMock()
        agents_result.all.return_value = []
        agents_result.scalar_one_or_none.return_value = org
        db.execute = AsyncMock(return_value=agents_result)

        with patch("api.routes.admin.retention._get_user_org", new_callable=AsyncMock, return_value=org):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
                resp = await c.get("/api/v1/admin/org/retention/warnings")

        assert resp.status_code == 200
        assert resp.json()["warnings"] == []
