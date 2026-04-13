"""Tests for enterprise module (ee/) structure and integration."""

import pytest
from httpx import ASGITransport, AsyncClient


class TestConfigValidator:
    def test_detects_default_secret_key(self):
        from unittest.mock import MagicMock

        from ee.observal_server.services.config_validator import validate_enterprise_config

        settings = MagicMock()
        settings.SECRET_KEY = "change-me-to-a-random-string"
        settings.OAUTH_CLIENT_ID = "some-id"
        settings.OAUTH_CLIENT_SECRET = "some-secret"
        settings.OAUTH_SERVER_METADATA_URL = "https://example.com/.well-known"
        settings.FRONTEND_URL = "https://app.example.com"

        issues = validate_enterprise_config(settings)
        assert any("SECRET_KEY" in i for i in issues)
        assert len(issues) == 1

    def test_detects_missing_oauth(self):
        from unittest.mock import MagicMock

        from ee.observal_server.services.config_validator import validate_enterprise_config

        settings = MagicMock()
        settings.SECRET_KEY = "proper-random-secret-key"
        settings.OAUTH_CLIENT_ID = None
        settings.OAUTH_CLIENT_SECRET = None
        settings.OAUTH_SERVER_METADATA_URL = None
        settings.FRONTEND_URL = "https://app.example.com"

        issues = validate_enterprise_config(settings)
        assert len(issues) == 3
        assert any("OAUTH_CLIENT_ID" in i for i in issues)
        assert any("OAUTH_CLIENT_SECRET" in i for i in issues)
        assert any("OAUTH_SERVER_METADATA_URL" in i for i in issues)

    def test_detects_localhost_frontend(self):
        from unittest.mock import MagicMock

        from ee.observal_server.services.config_validator import validate_enterprise_config

        settings = MagicMock()
        settings.SECRET_KEY = "proper-random-secret-key"
        settings.OAUTH_CLIENT_ID = "id"
        settings.OAUTH_CLIENT_SECRET = "secret"
        settings.OAUTH_SERVER_METADATA_URL = "https://example.com/.well-known"
        settings.FRONTEND_URL = "http://localhost:3000"

        issues = validate_enterprise_config(settings)
        assert any("FRONTEND_URL" in i for i in issues)

    def test_healthy_config_returns_empty(self):
        from unittest.mock import MagicMock

        from ee.observal_server.services.config_validator import validate_enterprise_config

        settings = MagicMock()
        settings.SECRET_KEY = "proper-random-secret-key"
        settings.OAUTH_CLIENT_ID = "id"
        settings.OAUTH_CLIENT_SECRET = "secret"
        settings.OAUTH_SERVER_METADATA_URL = "https://login.microsoftonline.com/..."
        settings.FRONTEND_URL = "https://app.example.com"

        issues = validate_enterprise_config(settings)
        assert issues == []


class TestEEPlaceholderRoutes:
    """SAML and SCIM endpoints should return 501 placeholder responses."""

    @pytest.mark.asyncio
    async def test_saml_login_returns_501(self):
        from fastapi import FastAPI

        from ee.observal_server.routes.sso_saml import router

        app = FastAPI()
        app.include_router(router)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/v1/sso/saml/login")
        assert r.status_code == 200  # route exists, returns 501 in body
        assert r.json()["status"] == 501

    @pytest.mark.asyncio
    async def test_saml_metadata_returns_501(self):
        from fastapi import FastAPI

        from ee.observal_server.routes.sso_saml import router

        app = FastAPI()
        app.include_router(router)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/v1/sso/saml/metadata")
        assert r.json()["status"] == 501

    @pytest.mark.asyncio
    async def test_scim_list_users_returns_501(self):
        from fastapi import FastAPI

        from ee.observal_server.routes.scim import router

        app = FastAPI()
        app.include_router(router)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/v1/scim/Users")
        assert r.json()["status"] == 501

    @pytest.mark.asyncio
    async def test_scim_create_user_returns_501(self):
        from fastapi import FastAPI

        from ee.observal_server.routes.scim import router

        app = FastAPI()
        app.include_router(router)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/v1/scim/Users")
        assert r.json()["status"] == 501


class TestEnterpriseGuardMiddleware:
    @pytest.mark.asyncio
    async def test_blocks_ee_routes_when_misconfigured(self):
        from fastapi import FastAPI

        from ee.observal_server.middleware.enterprise_guard import EnterpriseGuardMiddleware
        from ee.observal_server.routes.sso_saml import router as saml_router

        app = FastAPI()
        app.include_router(saml_router)
        app.add_middleware(EnterpriseGuardMiddleware, issues=["SECRET_KEY is default"])

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/v1/sso/saml/login")
        assert r.status_code == 503
        assert "issues" in r.json()

    @pytest.mark.asyncio
    async def test_allows_non_ee_routes_when_misconfigured(self):
        from fastapi import FastAPI

        from ee.observal_server.middleware.enterprise_guard import EnterpriseGuardMiddleware

        app = FastAPI()

        @app.get("/health")
        async def health():
            return {"status": "ok"}

        app.add_middleware(EnterpriseGuardMiddleware, issues=["SECRET_KEY is default"])

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/health")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_allows_ee_routes_when_healthy(self):
        from fastapi import FastAPI

        from ee.observal_server.middleware.enterprise_guard import EnterpriseGuardMiddleware
        from ee.observal_server.routes.sso_saml import router as saml_router

        app = FastAPI()
        app.include_router(saml_router)
        app.add_middleware(EnterpriseGuardMiddleware, issues=[])

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/v1/sso/saml/login")
        # No 503 — passes through to the placeholder 501 response
        assert r.status_code == 200
        assert r.json()["status"] == 501


class TestRegisterEnterprise:
    def test_register_enterprise_returns_issues(self):
        from unittest.mock import MagicMock

        from ee import register_enterprise

        app = MagicMock()
        app.state = MagicMock()

        settings = MagicMock()
        settings.SECRET_KEY = "change-me-to-a-random-string"
        settings.OAUTH_CLIENT_ID = None
        settings.OAUTH_CLIENT_SECRET = None
        settings.OAUTH_SERVER_METADATA_URL = None
        settings.FRONTEND_URL = "http://localhost:3000"

        issues = register_enterprise(app, settings)
        assert len(issues) > 0
        assert app.include_router.called
        assert app.add_middleware.called
