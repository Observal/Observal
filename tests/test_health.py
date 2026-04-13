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
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                r = await ac.get("/health")
            assert r.status_code == 200
            data = r.json()
            assert data["status"] == "ok"
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
            with patch("main.settings") as mock_settings:
                mock_settings.DEPLOYMENT_MODE = "enterprise"
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
        return user

    def _make_user(self):
        from models.user import User, UserRole

        user = MagicMock(spec=User)
        user.id = uuid.uuid4()
        user.role = UserRole.user
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
            with patch("api.routes.admin.settings") as mock_settings:
                mock_settings.DEPLOYMENT_MODE = "local"
                mock_settings.JWT_SIGNING_ALGORITHM = "ES256"
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    r = await ac.get("/api/v1/admin/diagnostics")
            assert r.status_code == 200
            data = r.json()
            assert data["deployment_mode"] == "local"
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
            with patch("api.routes.admin.settings") as mock_settings:
                mock_settings.DEPLOYMENT_MODE = "enterprise"
                mock_settings.SECRET_KEY = "change-me-to-a-random-string"
                mock_settings.OAUTH_CLIENT_ID = None
                mock_settings.FRONTEND_URL = "http://localhost:3000"
                mock_settings.JWT_SIGNING_ALGORITHM = "ES256"
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    r = await ac.get("/api/v1/admin/diagnostics")
            assert r.status_code == 200
            data = r.json()
            assert data["status"] == "degraded"
            assert "enterprise" in data["checks"]
            issues = data["checks"]["enterprise"]["issues"]
            assert any("SECRET_KEY" in i for i in issues)
            assert any("OAUTH_CLIENT_ID" in i for i in issues)
            assert any("FRONTEND_URL" in i for i in issues)
        finally:
            app.dependency_overrides.clear()
