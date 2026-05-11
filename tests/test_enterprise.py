# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for enterprise module (ee/) structure and integration."""

import pytest
from httpx import ASGITransport, AsyncClient


class TestConfigValidator:
    def test_detects_default_secret_key(self):
        from unittest.mock import MagicMock

        from ee.observal_server.services.config_validator import validate_enterprise_config

        settings = MagicMock()
        settings.SECRET_KEY = "change-me-to-a-random-string"
        settings.SSO_ONLY = False
        settings.FRONTEND_URL = "https://app.example.com"

        issues = validate_enterprise_config(settings)
        assert any("SECRET_KEY" in i for i in issues)
        assert len(issues) == 1

    def test_detects_missing_oauth_when_sso_only(self):
        from unittest.mock import MagicMock

        from ee.observal_server.services.config_validator import validate_enterprise_config

        settings = MagicMock()
        settings.SECRET_KEY = "proper-random-secret-key"
        settings.SSO_ONLY = True
        settings.OAUTH_CLIENT_ID = None
        settings.OAUTH_CLIENT_SECRET = None
        settings.OAUTH_SERVER_METADATA_URL = None
        settings.FRONTEND_URL = "https://app.example.com"

        issues = validate_enterprise_config(settings)
        assert len(issues) == 3
        assert any("OAUTH_CLIENT_ID" in i for i in issues)
        assert any("OAUTH_CLIENT_SECRET" in i for i in issues)
        assert any("OAUTH_SERVER_METADATA_URL" in i for i in issues)

    def test_no_oauth_issues_when_sso_not_required(self):
        from unittest.mock import MagicMock

        from ee.observal_server.services.config_validator import validate_enterprise_config

        settings = MagicMock()
        settings.SECRET_KEY = "proper-random-secret-key"
        settings.SSO_ONLY = False
        settings.OAUTH_CLIENT_ID = None
        settings.OAUTH_CLIENT_SECRET = None
        settings.OAUTH_SERVER_METADATA_URL = None
        settings.FRONTEND_URL = "https://app.example.com"

        issues = validate_enterprise_config(settings)
        assert len(issues) == 0

    def test_detects_localhost_frontend(self):
        from unittest.mock import MagicMock

        from ee.observal_server.services.config_validator import validate_enterprise_config

        settings = MagicMock()
        settings.SECRET_KEY = "proper-random-secret-key"
        settings.SSO_ONLY = False
        settings.FRONTEND_URL = "http://localhost:3000"

        issues = validate_enterprise_config(settings)
        assert any("FRONTEND_URL" in i for i in issues)

    def test_healthy_config_returns_empty(self):
        from unittest.mock import MagicMock

        from ee.observal_server.services.config_validator import validate_enterprise_config

        settings = MagicMock()
        settings.SECRET_KEY = "proper-random-secret-key"
        settings.SSO_ONLY = False
        settings.FRONTEND_URL = "https://app.example.com"

        issues = validate_enterprise_config(settings)
        assert issues == []

    def test_detects_missing_saml_idp_cert_when_saml_configured(self):
        from unittest.mock import MagicMock

        from ee.observal_server.services.config_validator import validate_enterprise_config

        settings = MagicMock()
        settings.SECRET_KEY = "proper-random-secret-key"
        settings.SSO_ONLY = True
        settings.OAUTH_CLIENT_ID = "client-id"
        settings.OAUTH_CLIENT_SECRET = "client-secret"
        settings.OAUTH_SERVER_METADATA_URL = "https://idp.example.com/.well-known"
        settings.SAML_IDP_ENTITY_ID = "https://idp.example.com"
        settings.SAML_IDP_SSO_URL = "https://idp.example.com/sso"
        settings.SAML_IDP_X509_CERT = ""
        settings.FRONTEND_URL = "https://app.example.com"

        issues = validate_enterprise_config(settings)
        assert any("SAML_IDP_X509_CERT" in i for i in issues)


class TestEERoutes:
    """SAML and SCIM endpoints require config/auth."""

    @pytest.mark.asyncio
    async def test_saml_login_returns_404_without_config(self):
        from unittest.mock import AsyncMock, patch

        from fastapi import FastAPI

        from ee.observal_server.routes.sso_saml import router

        app = FastAPI()
        app.include_router(router)
        with patch("ee.observal_server.routes.sso_saml._get_saml_config", new_callable=AsyncMock, return_value=None):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                r = await ac.get("/api/v1/sso/saml/login")
            assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_saml_metadata_returns_404_without_config(self):
        from unittest.mock import AsyncMock, patch

        from fastapi import FastAPI

        from ee.observal_server.routes.sso_saml import router

        app = FastAPI()
        app.include_router(router)
        with patch("ee.observal_server.routes.sso_saml._get_saml_config", new_callable=AsyncMock, return_value=None):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                r = await ac.get("/api/v1/sso/saml/metadata")
            assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_scim_list_requires_auth(self):
        from fastapi import FastAPI

        from ee.observal_server.routes.scim import router

        app = FastAPI()
        app.include_router(router)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/v1/scim/Users")
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_scim_create_requires_auth(self):
        from fastapi import FastAPI

        from ee.observal_server.routes.scim import router

        app = FastAPI()
        app.include_router(router)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/v1/scim/Users", json={})
        assert r.status_code == 401


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
        from unittest.mock import AsyncMock, patch

        from fastapi import FastAPI

        from ee.observal_server.middleware.enterprise_guard import EnterpriseGuardMiddleware
        from ee.observal_server.routes.sso_saml import router as saml_router

        app = FastAPI()
        app.include_router(saml_router)
        app.add_middleware(EnterpriseGuardMiddleware, issues=[])

        with patch("ee.observal_server.routes.sso_saml._get_saml_config", new_callable=AsyncMock, return_value=None):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                r = await ac.get("/api/v1/sso/saml/login")
            # No 503 from guard -- passes through to endpoint which returns 404 (not configured)
            assert r.status_code == 404


class TestRegisterEnterprise:
    def test_register_enterprise_returns_issues(self):
        from unittest.mock import MagicMock

        from ee import register_enterprise

        app = MagicMock()
        app.state = MagicMock()

        settings = MagicMock()
        settings.SECRET_KEY = "change-me-to-a-random-string"
        settings.SSO_ONLY = False
        settings.FRONTEND_URL = "http://localhost:3000"

        from services.events import bus

        bus.clear()
        issues = register_enterprise(app, settings)
        assert len(issues) > 0
        assert app.include_router.called
        assert app.add_middleware.called
        bus.clear()
