# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for the 3-tier health check endpoints."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


class TestLiveness:
    """GET /healthz — no I/O, always returns 200."""

    @pytest.mark.asyncio
    async def test_returns_alive(self):
        from main import app

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/healthz")
        assert r.status_code == 200
        assert r.json() == {"status": "alive"}


class TestReadiness:
    """GET /health — checks DB, returns degraded for misconfigured enterprise."""

    @pytest.mark.asyncio
    async def test_returns_ok_when_db_connected(self):
        from main import app

        # Patch get_db to return a mock session with scalar returning 1
        mock_db = AsyncMock()
        mock_db.scalar = AsyncMock(return_value=1)

        async def _mock_get_db():
            yield mock_db

        app.dependency_overrides = {}
        from api.deps import get_db

        app.dependency_overrides[get_db] = _mock_get_db
        try:
            with (
                patch("main.HAS_LICENSE", False),
                patch("services.clickhouse.clickhouse_health", new_callable=AsyncMock, return_value=True),
                patch("services.redis.ping", new_callable=AsyncMock, return_value=True),
            ):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    r = await ac.get("/health")
            assert r.status_code == 200
            data = r.json()
            assert data["status"] == "ok"
            assert data["clickhouse"] == "ok"
            assert data["initialized"] is True
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_returns_degraded_when_enterprise_misconfigured(self):
        from main import app

        mock_db = AsyncMock()
        mock_db.scalar = AsyncMock(return_value=1)

        async def _mock_get_db():
            yield mock_db

        from api.deps import get_db

        app.dependency_overrides[get_db] = _mock_get_db
        app.state.enterprise_issues = ["SECRET_KEY is default"]
        try:
            with (
                patch("main.HAS_LICENSE", True),
                patch("services.clickhouse.clickhouse_health", new_callable=AsyncMock, return_value=True),
                patch("services.redis.ping", new_callable=AsyncMock, return_value=True),
            ):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    r = await ac.get("/health")
            # degraded is still 200 — the app CAN serve requests
            assert r.status_code == 200
            assert r.json()["status"] == "degraded"
        finally:
            app.dependency_overrides.clear()
            if hasattr(app.state, "enterprise_issues"):
                del app.state.enterprise_issues


class TestDiagnostics:
    """GET /api/v1/admin/diagnostics — admin-only, full system status."""

    def _make_admin(self):
        from models.user import User, UserRole

        user = MagicMock(spec=User)
        user.id = uuid.uuid4()
        user.role = UserRole.admin
        user.org_id = None
        return user

    def _make_user(self):
        from models.user import User, UserRole

        user = MagicMock(spec=User)
        user.id = uuid.uuid4()
        user.role = UserRole.user
        user.org_id = None
        return user

    @pytest.mark.asyncio
    async def test_returns_diagnostics_for_admin(self):
        from api.deps import get_current_user, get_db
        from main import app

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock())
        mock_db.scalar = AsyncMock(return_value=5)

        async def _mock_get_db():
            yield mock_db

        admin = self._make_admin()

        async def _mock_admin():
            return admin

        app.dependency_overrides[get_db] = _mock_get_db
        app.dependency_overrides[get_current_user] = _mock_admin
        try:
            with (
                patch("api.routes.admin.enterprise_settings.HAS_LICENSE", False),
                patch("api.routes.admin.enterprise_settings.settings") as mock_settings,
                patch("api.routes.admin.enterprise_settings.ds") as mock_ds,
            ):
                mock_settings.JWT_SIGNING_ALGORITHM = "ES256"
                mock_ds.get_bool = AsyncMock(return_value=True)
                mock_ds.get = AsyncMock(return_value="http://localhost:3000")
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    r = await ac.get("/api/v1/admin/diagnostics")
            assert r.status_code == 200
            data = r.json()
            assert data["licensed"] is False
            assert data["status"] == "ok"
            assert "database" in data["checks"]
            assert "jwt_keys" in data["checks"]
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_requires_admin_role(self):
        from api.deps import get_current_user, get_db
        from main import app

        mock_db = AsyncMock()

        async def _mock_get_db():
            yield mock_db

        user = self._make_user()

        async def _mock_user():
            return user

        app.dependency_overrides[get_db] = _mock_get_db
        app.dependency_overrides[get_current_user] = _mock_user
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                r = await ac.get("/api/v1/admin/diagnostics")
            assert r.status_code == 403
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_enterprise_mode_shows_config_issues(self):
        from api.deps import get_current_user, get_db
        from main import app

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock())
        mock_db.scalar = AsyncMock(return_value=2)

        async def _mock_get_db():
            yield mock_db

        admin = self._make_admin()

        async def _mock_admin():
            return admin

        app.dependency_overrides[get_db] = _mock_get_db
        app.dependency_overrides[get_current_user] = _mock_admin
        try:
            with (
                patch("api.routes.admin.enterprise_settings.HAS_LICENSE", True),
                patch("api.routes.admin.enterprise_settings.settings") as mock_settings,
                patch("api.routes.admin.enterprise_settings.ds") as mock_ds,
            ):
                mock_settings.SECRET_KEY = "change-me-to-a-random-string"
                mock_settings.JWT_SIGNING_ALGORITHM = "ES256"
                mock_ds.get_bool = AsyncMock(return_value=True)
                mock_ds.get = AsyncMock(
                    side_effect=lambda key, *args: "" if key == "oauth.client_id" else "http://localhost:3000"
                )
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    r = await ac.get("/api/v1/admin/diagnostics")
            assert r.status_code == 200
            data = r.json()
            assert data["status"] == "degraded"
            assert "enterprise" in data["checks"]
            issues = data["checks"]["enterprise"]["issues"]
            assert any("SECRET_KEY" in i for i in issues)
            assert any("oauth.client_id" in i for i in issues)
            assert any("frontend" in i.lower() for i in issues)
        finally:
            app.dependency_overrides.clear()
