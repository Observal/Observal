# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Integration tests for SAML 2.0 + SCIM 2.0 enterprise features.

Covers:
- SCIM filter parsing (service layer)
- SCIM pagination validation (service layer)
- Admin SAML config API endpoints
- Admin SCIM token management endpoints
- Enterprise config validator (SAML-specific)
- SCIM discovery endpoints (no auth)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# 1. SCIM Filter Parsing Tests
# ---------------------------------------------------------------------------


class TestScimFilterParsing:
    """Test parse_scim_filter from ee.observal_server.services.scim_service."""

    def test_valid_eq_filter(self):
        from ee.observal_server.services.scim_service import parse_scim_filter

        result = parse_scim_filter('userName eq "user@example.com"')
        assert result is not None
        assert result.attr == "username"
        assert result.op == "eq"
        assert result.value == "user@example.com"

    def test_valid_sw_filter(self):
        from ee.observal_server.services.scim_service import parse_scim_filter

        result = parse_scim_filter('userName sw "user"')
        assert result is not None
        assert result.attr == "username"
        assert result.op == "sw"
        assert result.value == "user"

    def test_valid_co_filter(self):
        from ee.observal_server.services.scim_service import parse_scim_filter

        result = parse_scim_filter('userName co "example"')
        assert result is not None
        assert result.attr == "username"
        assert result.op == "co"
        assert result.value == "example"

    def test_valid_ne_filter(self):
        from ee.observal_server.services.scim_service import parse_scim_filter

        result = parse_scim_filter('userName ne "admin@test.com"')
        assert result is not None
        assert result.attr == "username"
        assert result.op == "ne"
        assert result.value == "admin@test.com"

    def test_invalid_filter_no_quotes(self):
        from ee.observal_server.services.scim_service import parse_scim_filter

        result = parse_scim_filter("userName eq user@example.com")
        assert result is None

    def test_invalid_filter_unsupported_op(self):
        from ee.observal_server.services.scim_service import parse_scim_filter

        result = parse_scim_filter('userName gt "admin@test.com"')
        assert result is None

    def test_empty_filter_returns_none(self):
        from ee.observal_server.services.scim_service import parse_scim_filter

        assert parse_scim_filter("") is None

    def test_whitespace_filter_returns_none(self):
        from ee.observal_server.services.scim_service import parse_scim_filter

        assert parse_scim_filter("   ") is None

    def test_none_filter_returns_none(self):
        from ee.observal_server.services.scim_service import parse_scim_filter

        assert parse_scim_filter(None) is None

    def test_filter_with_leading_trailing_whitespace(self):
        from ee.observal_server.services.scim_service import parse_scim_filter

        result = parse_scim_filter('  userName eq "user@example.com"  ')
        assert result is not None
        assert result.attr == "username"
        assert result.op == "eq"
        assert result.value == "user@example.com"

    def test_filter_case_insensitive_op(self):
        from ee.observal_server.services.scim_service import parse_scim_filter

        result = parse_scim_filter('userName EQ "user@example.com"')
        assert result is not None
        assert result.op == "eq"

    def test_filter_dotted_attribute(self):
        from ee.observal_server.services.scim_service import parse_scim_filter

        result = parse_scim_filter('name.givenName eq "Jane"')
        assert result is not None
        assert result.attr == "name.givenname"
        assert result.value == "Jane"


# ---------------------------------------------------------------------------
# 2. SCIM Pagination Validation Tests
# ---------------------------------------------------------------------------


class TestScimPaginationValidation:
    """Test validate_scim_pagination from ee.observal_server.services.scim_service."""

    def test_normal_values(self):
        from ee.observal_server.services.scim_service import validate_scim_pagination

        start, count = validate_scim_pagination(1, 100)
        assert start == 1
        assert count == 100

    def test_negative_start_index_clamped_to_one(self):
        from ee.observal_server.services.scim_service import validate_scim_pagination

        start, count = validate_scim_pagination(-5, 100)
        assert start == 1
        assert count == 100

    def test_zero_start_index_clamped_to_one(self):
        from ee.observal_server.services.scim_service import validate_scim_pagination

        start, count = validate_scim_pagination(0, 100)
        assert start == 1
        assert count == 100

    def test_huge_count_clamped_to_max(self):
        from ee.observal_server.services.scim_service import (
            MAX_SCIM_PAGE_SIZE,
            validate_scim_pagination,
        )

        start, count = validate_scim_pagination(1, 10000)
        assert start == 1
        assert count == MAX_SCIM_PAGE_SIZE
        assert count == 500

    def test_negative_count_clamped_to_zero(self):
        from ee.observal_server.services.scim_service import validate_scim_pagination

        start, count = validate_scim_pagination(1, -5)
        assert start == 1
        assert count == 0

    def test_both_boundary_values(self):
        from ee.observal_server.services.scim_service import validate_scim_pagination

        start, count = validate_scim_pagination(-100, 999999)
        assert start == 1
        assert count == 500

    def test_exact_max_page_size(self):
        from ee.observal_server.services.scim_service import (
            MAX_SCIM_PAGE_SIZE,
            validate_scim_pagination,
        )

        start, count = validate_scim_pagination(1, MAX_SCIM_PAGE_SIZE)
        assert count == MAX_SCIM_PAGE_SIZE


# ---------------------------------------------------------------------------
# 3. Admin SAML Config API Tests
# ---------------------------------------------------------------------------


class TestAdminSamlConfigAPI:
    """Test admin_sso.py SAML config endpoints with mocked dependencies."""

    ADMIN_USER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
    ORG_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")

    def _make_admin_app(self):
        """Create a FastAPI app with admin_sso router and overridden deps."""
        from fastapi import FastAPI

        from ee.observal_server.routes.admin_sso import router
        from models.user import UserRole

        app = FastAPI()
        app.include_router(router)

        mock_user = MagicMock()
        mock_user.id = self.ADMIN_USER_ID
        mock_user.email = "admin@test.com"
        mock_user.role = UserRole.admin
        mock_user.org_id = self.ORG_ID

        return app, mock_user

    def _override_deps(self, app, mock_user, mock_db):
        """Override get_db and require_role dependencies."""
        from api.deps import get_current_user, get_db

        async def override_get_db():
            yield mock_db

        async def override_get_current_user():
            return mock_user

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user

    @pytest.mark.asyncio
    async def test_get_saml_config_with_env_vars(self):
        app, mock_user = self._make_admin_app()
        mock_db = AsyncMock()

        # No DB config found
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        self._override_deps(app, mock_user, mock_db)

        with (
            patch(
                "ee.observal_server.routes.admin_sso.ds",
            ) as mock_settings,
        ):
            mock_settings.get_sync.side_effect = lambda key, *a, **kw: {
                "saml.idp_entity_id": "https://idp.example.com",
                "saml.idp_sso_url": "https://idp.example.com/sso",
                "saml.idp_slo_url": "https://idp.example.com/slo",
                "saml.sp_entity_id": "https://app.example.com/saml/metadata",
                "saml.sp_acs_url": "https://app.example.com/saml/acs",
                "saml.default_role": "user",
                "saml.idp_x509_cert": "MIICmzCCAYM...",
                "saml.sp_key_encryption_password": "test",
                "deployment.frontend_url": "https://app.example.com",
            }.get(key, a[0] if a else "")
            mock_settings.get_sync_bool.side_effect = lambda key, *a, **kw: {
                "saml.jit_provisioning": True,
            }.get(key, a[0] if a else False)

            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                r = await ac.get("/api/v1/admin/saml-config")

        assert r.status_code == 200
        data = r.json()
        assert data["configured"] is True
        assert data["source"] == "env"
        assert data["idp_entity_id"] == "https://idp.example.com"
        assert data["has_idp_cert"] is True
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_get_saml_config_unconfigured(self):
        app, mock_user = self._make_admin_app()
        mock_db = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        self._override_deps(app, mock_user, mock_db)

        with (
            patch(
                "ee.observal_server.routes.admin_sso.ds",
            ) as mock_settings,
        ):
            mock_settings.get_sync.side_effect = lambda key, *a, **kw: a[0] if a else ""
            mock_settings.get_sync_bool.side_effect = lambda key, *a, **kw: a[0] if a else False

            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                r = await ac.get("/api/v1/admin/saml-config")

        assert r.status_code == 200
        data = r.json()
        assert data["configured"] is False
        assert data["source"] == "none"
        assert data["idp_entity_id"] is None
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_put_saml_config_requires_all_fields(self):
        app, mock_user = self._make_admin_app()
        mock_db = AsyncMock()

        self._override_deps(app, mock_user, mock_db)

        try:
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                # Missing idp_x509_cert
                r = await ac.put(
                    "/api/v1/admin/saml-config",
                    json={
                        "idp_entity_id": "https://idp.example.com",
                        "idp_sso_url": "https://idp.example.com/sso",
                    },
                )

            assert r.status_code == 422
            assert "idp_x509_cert" in r.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_put_saml_config_missing_entity_id(self):
        app, mock_user = self._make_admin_app()
        mock_db = AsyncMock()

        self._override_deps(app, mock_user, mock_db)

        try:
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                r = await ac.put(
                    "/api/v1/admin/saml-config",
                    json={
                        "idp_sso_url": "https://idp.example.com/sso",
                        "idp_x509_cert": "MIICmzCCAYM...",
                    },
                )

            assert r.status_code == 422
            assert "idp_entity_id" in r.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_delete_saml_config_returns_404_when_missing(self):
        app, mock_user = self._make_admin_app()
        mock_db = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        self._override_deps(app, mock_user, mock_db)

        with patch(
            "ee.observal_server.routes.admin_sso.get_or_create_default_org",
            new_callable=AsyncMock,
        ) as mock_get_org:
            mock_org = MagicMock()
            mock_org.id = self.ORG_ID
            mock_get_org.return_value = mock_org

            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                r = await ac.delete("/api/v1/admin/saml-config")

        assert r.status_code == 404
        assert "No SAML configuration found" in r.json()["detail"]
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_get_saml_config_from_database(self):
        app, mock_user = self._make_admin_app()
        mock_db = AsyncMock()

        config_id = uuid.uuid4()
        mock_config = MagicMock()
        mock_config.id = config_id
        mock_config.org_id = self.ORG_ID
        mock_config.idp_entity_id = "https://idp.example.com"
        mock_config.idp_sso_url = "https://idp.example.com/sso"
        mock_config.idp_slo_url = ""
        mock_config.sp_entity_id = "https://app.example.com/saml/metadata"
        mock_config.sp_acs_url = "https://app.example.com/saml/acs"
        mock_config.jit_provisioning = True
        mock_config.default_role = "user"
        mock_config.idp_x509_cert = "MIICmzCCAYM..."
        mock_config.sp_private_key_enc = "enc:aesgcm:..."
        mock_config.active = True
        mock_config.created_at = datetime(2026, 1, 1, tzinfo=UTC)
        mock_config.updated_at = datetime(2026, 1, 2, tzinfo=UTC)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_config
        mock_db.execute = AsyncMock(return_value=mock_result)

        self._override_deps(app, mock_user, mock_db)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            r = await ac.get("/api/v1/admin/saml-config")

        assert r.status_code == 200
        data = r.json()
        assert data["configured"] is True
        assert data["source"] == "database"
        assert data["id"] == str(config_id)
        assert data["has_idp_cert"] is True
        assert data["has_sp_key"] is True
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 4. Admin SCIM Token API Tests
# ---------------------------------------------------------------------------


class TestAdminScimTokenAPI:
    """Test SCIM token management endpoints with mocked DB."""

    ADMIN_USER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
    ORG_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")

    def _make_admin_app(self):
        from fastapi import FastAPI

        from api.deps import get_current_user, get_db
        from ee.observal_server.routes.admin_sso import router
        from models.user import UserRole

        app = FastAPI()
        app.include_router(router)

        mock_user = MagicMock()
        mock_user.id = self.ADMIN_USER_ID
        mock_user.email = "admin@test.com"
        mock_user.role = UserRole.admin
        mock_user.org_id = self.ORG_ID

        mock_db = AsyncMock()

        async def override_get_db():
            yield mock_db

        async def override_get_current_user():
            return mock_user

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user

        return app, mock_user, mock_db

    @pytest.mark.asyncio
    async def test_create_scim_token_returns_plaintext(self):
        app, mock_user, mock_db = self._make_admin_app()

        token_id = uuid.uuid4()

        async def mock_refresh(obj):
            obj.id = token_id
            obj.created_at = datetime.now(UTC)

        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock(side_effect=mock_refresh)

        with (
            patch(
                "ee.observal_server.routes.admin_sso.emit_security_event",
                new_callable=AsyncMock,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                r = await ac.post(
                    "/api/v1/admin/scim-tokens",
                    json={"description": "Okta provisioning"},
                )

        assert r.status_code == 200
        data = r.json()
        assert "token" in data
        assert len(data["token"]) > 0
        assert data["description"] == "Okta provisioning"
        assert data["id"] == str(token_id)
        assert "Save this token now" in data["message"]
        mock_db.add.assert_called_once()
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_list_scim_tokens_excludes_plaintext(self):
        app, mock_user, mock_db = self._make_admin_app()

        token_id = uuid.uuid4()
        mock_token = MagicMock()
        mock_token.id = token_id
        mock_token.description = "Okta token"
        mock_token.active = True
        mock_token.created_at = datetime(2026, 1, 1, tzinfo=UTC)
        mock_token.token_hash = "abcdef1234567890abcdef1234567890"

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_token]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            r = await ac.get("/api/v1/admin/scim-tokens")

        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["id"] == str(token_id)
        assert data[0]["description"] == "Okta token"
        assert data[0]["active"] is True
        # Plaintext token should NOT be in the response
        assert "token" not in data[0]
        # token_prefix should be a truncated hash
        assert data[0]["token_prefix"] == "abcdef12..."
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_revoke_scim_token(self):
        app, mock_user, mock_db = self._make_admin_app()

        token_id = uuid.uuid4()
        mock_token = MagicMock()
        mock_token.id = token_id
        mock_token.active = True
        mock_token.org_id = self.ORG_ID

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_token
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        with (
            patch(
                "ee.observal_server.routes.admin_sso.emit_security_event",
                new_callable=AsyncMock,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                r = await ac.delete(f"/api/v1/admin/scim-tokens/{token_id}")

        assert r.status_code == 200
        data = r.json()
        assert data["revoked"] == str(token_id)
        # Verify active was set to False
        assert mock_token.active is False
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_revoke_scim_token_not_found(self):
        app, mock_user, mock_db = self._make_admin_app()

        token_id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch(
            "ee.observal_server.routes.admin_sso.get_or_create_default_org",
            new_callable=AsyncMock,
        ) as mock_get_org:
            mock_org = MagicMock()
            mock_org.id = self.ORG_ID
            mock_get_org.return_value = mock_org

            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                r = await ac.delete(f"/api/v1/admin/scim-tokens/{token_id}")

        assert r.status_code == 404
        assert "Token not found" in r.json()["detail"]
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_revoke_scim_token_invalid_uuid(self):
        app, mock_user, mock_db = self._make_admin_app()

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            r = await ac.delete("/api/v1/admin/scim-tokens/not-a-uuid")

        assert r.status_code == 404
        assert "Token not found" in r.json()["detail"]
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 5. Config Validator Tests (SAML-specific)
# ---------------------------------------------------------------------------


class TestConfigValidatorSaml:
    """Test enterprise config_validator for SAML-specific scenarios."""

    def _make_ds(self, **overrides):
        """Create a mock ds module for the config validator."""
        defaults = {
            "deployment.sso_only": "false",
            "deployment.frontend_url": "https://app.example.com",
            "saml.idp_entity_id": "",
            "saml.idp_sso_url": "",
            "saml.idp_x509_cert": "",
            "saml.sp_key_encryption_password": "strong-pass",
            "saml.sp_acs_url": "https://app.example.com/api/v1/sso/saml/acs",
        }
        defaults.update(overrides)
        mock = MagicMock()
        mock.get_sync.side_effect = lambda key, *a, **kw: defaults.get(key, a[0] if a else "")
        mock.get_sync_bool.side_effect = lambda key, *a, **kw: defaults.get(key, "false").lower() in ("true", "1")
        return mock

    def _make_settings(self, **overrides):
        """Create a mock Settings object with sensible defaults."""
        s = MagicMock()
        s.SECRET_KEY = "proper-random-secret-key"
        s.OAUTH_CLIENT_ID = "id"
        s.OAUTH_CLIENT_SECRET = "secret"
        s.OAUTH_SERVER_METADATA_URL = "https://idp.example.com"
        for k, v in overrides.items():
            setattr(s, k, v)
        return s

    def _make_settings(self, **overrides):
        """Create a mock Settings object with sensible defaults."""
        s = MagicMock()
        s.SECRET_KEY = "proper-random-secret-key"
        s.SSO_ONLY = False
        s.FRONTEND_URL = "https://app.example.com"
        s.SAML_IDP_ENTITY_ID = ""
        s.SAML_IDP_SSO_URL = ""
        s.SAML_IDP_X509_CERT = ""
        s.SAML_SP_KEY_ENCRYPTION_PASSWORD = ""
        s.SAML_SP_ACS_URL = ""
        for k, v in overrides.items():
            setattr(s, k, v)
        return s

    def test_saml_entity_id_without_sso_url(self):
        from ee.observal_server.services.config_validator import validate_enterprise_config

        settings = self._make_settings(
            SAML_IDP_ENTITY_ID="https://idp.example.com",
            SAML_IDP_SSO_URL="",
        )
        with patch(
            "ee.observal_server.services.config_validator.ds",
            self._make_ds(
                **{k.lower().replace("saml_", "saml."): v for k, v in vars(settings).items() if k.startswith("SAML_")}
            ),
        ):
            issues = validate_enterprise_config(settings)
        assert any("saml.idp_sso_url" in i for i in issues)

    def test_saml_sso_url_without_entity_id(self):
        from ee.observal_server.services.config_validator import validate_enterprise_config

        settings = self._make_settings(
            SAML_IDP_ENTITY_ID="",
            SAML_IDP_SSO_URL="https://idp.example.com/sso",
        )
        with patch(
            "ee.observal_server.services.config_validator.ds",
            self._make_ds(
                **{k.lower().replace("saml_", "saml."): v for k, v in vars(settings).items() if k.startswith("SAML_")}
            ),
        ):
            issues = validate_enterprise_config(settings)
        assert any("saml.idp_entity_id" in i for i in issues)

    def test_saml_configured_without_cert(self):
        from ee.observal_server.services.config_validator import validate_enterprise_config

        settings = self._make_settings(
            SAML_IDP_ENTITY_ID="https://idp.example.com",
            SAML_IDP_SSO_URL="https://idp.example.com/sso",
            SAML_IDP_X509_CERT="",
        )
        with patch(
            "ee.observal_server.services.config_validator.ds",
            self._make_ds(
                **{k.lower().replace("saml_", "saml."): v for k, v in vars(settings).items() if k.startswith("SAML_")}
            ),
        ):
            issues = validate_enterprise_config(settings)
        assert any("saml.idp_x509_cert" in i for i in issues)

    def test_saml_configured_without_encryption_password(self):
        from ee.observal_server.services.config_validator import validate_enterprise_config

        settings = self._make_settings(
            SAML_IDP_ENTITY_ID="https://idp.example.com",
            SAML_IDP_SSO_URL="https://idp.example.com/sso",
            SAML_IDP_X509_CERT="MIICmzCCAYM...",
            SAML_SP_KEY_ENCRYPTION_PASSWORD="",
        )
        with patch(
            "ee.observal_server.services.config_validator.ds",
            self._make_ds(
                **{k.lower().replace("saml_", "saml."): v for k, v in vars(settings).items() if k.startswith("SAML_")}
            ),
        ):
            issues = validate_enterprise_config(settings)
        assert any("sp_key_encryption_password" in i for i in issues)

    def test_saml_acs_url_not_https(self):
        from ee.observal_server.services.config_validator import validate_enterprise_config

        settings = self._make_settings(
            SAML_IDP_ENTITY_ID="https://idp.example.com",
            SAML_IDP_SSO_URL="https://idp.example.com/sso",
            SAML_IDP_X509_CERT="MIICmzCCAYM...",
            SAML_SP_KEY_ENCRYPTION_PASSWORD="supersecret",
            SAML_SP_ACS_URL="http://app.example.com/saml/acs",
        )
        with patch(
            "ee.observal_server.services.config_validator.ds",
            self._make_ds(
                **{k.lower().replace("saml_", "saml."): v for k, v in vars(settings).items() if k.startswith("SAML_")}
            ),
        ):
            issues = validate_enterprise_config(settings)
        assert any("saml.sp_acs_url" in i and "HTTPS" in i.upper() for i in issues)

    def test_complete_saml_config_no_saml_issues(self):
        from ee.observal_server.services.config_validator import validate_enterprise_config

        settings = self._make_settings(
            SAML_IDP_ENTITY_ID="https://idp.example.com",
            SAML_IDP_SSO_URL="https://idp.example.com/sso",
            SAML_IDP_X509_CERT="MIICmzCCAYM...",
            SAML_SP_KEY_ENCRYPTION_PASSWORD="supersecret",
            SAML_SP_ACS_URL="https://app.example.com/saml/acs",
        )
        with patch(
            "ee.observal_server.services.config_validator.ds",
            self._make_ds(
                **{k.lower().replace("saml_", "saml."): v for k, v in vars(settings).items() if k.startswith("SAML_")}
            ),
        ):
            issues = validate_enterprise_config(settings)
        # Should have no SAML-related issues
        saml_issues = [i for i in issues if "SAML" in i]
        assert len(saml_issues) == 0

    def test_saml_not_configured_no_saml_issues(self):
        from ee.observal_server.services.config_validator import validate_enterprise_config

        settings = self._make_settings(
            SAML_IDP_ENTITY_ID="",
            SAML_IDP_SSO_URL="",
        )
        with patch(
            "ee.observal_server.services.config_validator.ds",
            self._make_ds(
                **{k.lower().replace("saml_", "saml."): v for k, v in vars(settings).items() if k.startswith("SAML_")}
            ),
        ):
            issues = validate_enterprise_config(settings)
        saml_issues = [i for i in issues if "SAML" in i]
        assert len(saml_issues) == 0


# ---------------------------------------------------------------------------
# 6. SCIM Discovery Endpoints (no auth)
# ---------------------------------------------------------------------------


class TestScimDiscoveryEndpoints:
    """Test SCIM discovery endpoints that require no authentication."""

    @pytest.fixture
    def scim_app(self):
        from fastapi import FastAPI

        from ee.observal_server.routes.scim import router

        app = FastAPI()
        app.include_router(router)
        return app

    @pytest.mark.asyncio
    async def test_service_provider_config(self, scim_app):
        async with AsyncClient(
            transport=ASGITransport(app=scim_app),
            base_url="http://test",
        ) as ac:
            r = await ac.get("/api/v1/scim/ServiceProviderConfig")

        assert r.status_code == 200
        data = r.json()
        assert data["patch"]["supported"] is True
        assert data["filter"]["supported"] is True
        assert data["bulk"]["supported"] is False
        assert len(data["authenticationSchemes"]) > 0
        assert data["authenticationSchemes"][0]["type"] == "oauthbearertoken"

    @pytest.mark.asyncio
    async def test_schemas_has_user_schema(self, scim_app):
        async with AsyncClient(
            transport=ASGITransport(app=scim_app),
            base_url="http://test",
        ) as ac:
            r = await ac.get("/api/v1/scim/Schemas")

        assert r.status_code == 200
        data = r.json()
        assert data["totalResults"] == 1
        user_schema = data["Resources"][0]
        assert user_schema["name"] == "User"
        assert user_schema["id"] == "urn:ietf:params:scim:schemas:core:2.0:User"
        # Verify required attributes are present
        attr_names = [a["name"] for a in user_schema["attributes"]]
        assert "userName" in attr_names
        assert "emails" in attr_names
        assert "active" in attr_names
        assert "displayName" in attr_names
        assert "name" in attr_names

    @pytest.mark.asyncio
    async def test_resource_types_has_user(self, scim_app):
        async with AsyncClient(
            transport=ASGITransport(app=scim_app),
            base_url="http://test",
        ) as ac:
            r = await ac.get("/api/v1/scim/ResourceTypes")

        assert r.status_code == 200
        data = r.json()
        assert data["totalResults"] == 1
        user_rt = data["Resources"][0]
        assert user_rt["id"] == "User"
        assert user_rt["name"] == "User"
        assert user_rt["endpoint"] == "/Users"
        assert user_rt["schema"] == "urn:ietf:params:scim:schemas:core:2.0:User"

    @pytest.mark.asyncio
    async def test_service_provider_config_content_type(self, scim_app):
        """Discovery endpoints should return application/scim+json."""
        async with AsyncClient(
            transport=ASGITransport(app=scim_app),
            base_url="http://test",
        ) as ac:
            r = await ac.get("/api/v1/scim/ServiceProviderConfig")

        assert r.status_code == 200
        assert "application/scim+json" in r.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_discovery_endpoints_require_no_auth(self, scim_app):
        """All three discovery endpoints must return 200 without any bearer token."""
        endpoints = [
            "/api/v1/scim/ServiceProviderConfig",
            "/api/v1/scim/Schemas",
            "/api/v1/scim/ResourceTypes",
        ]
        async with AsyncClient(
            transport=ASGITransport(app=scim_app),
            base_url="http://test",
        ) as ac:
            for path in endpoints:
                r = await ac.get(path)
                assert r.status_code == 200, f"{path} returned {r.status_code}"
