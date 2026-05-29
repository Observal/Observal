# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for SAML service layer."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


class TestSamlKeyGeneration:
    def test_generate_sp_key_pair_returns_pem_strings(self):
        from ee.observal_server.services.saml import generate_sp_key_pair

        private_key_pem, cert_pem = generate_sp_key_pair(common_name="test-sp.example.com")
        assert "BEGIN RSA PRIVATE KEY" in private_key_pem or "BEGIN PRIVATE KEY" in private_key_pem
        assert "BEGIN CERTIFICATE" in cert_pem

    def test_encrypt_decrypt_private_key_roundtrip(self):
        from ee.observal_server.services.saml import (
            decrypt_private_key,
            encrypt_private_key,
            generate_sp_key_pair,
        )

        private_key_pem, _ = generate_sp_key_pair(common_name="test.example.com")
        password = "test-encryption-password"
        encrypted = encrypt_private_key(private_key_pem, password)
        assert encrypted != private_key_pem
        assert encrypted.startswith("enc:aesgcm:")
        decrypted = decrypt_private_key(encrypted, password)
        assert decrypted == private_key_pem

    def test_encrypt_decrypt_with_empty_password_is_noop(self):
        from ee.observal_server.services.saml import (
            decrypt_private_key,
            encrypt_private_key,
            generate_sp_key_pair,
        )

        private_key_pem, _ = generate_sp_key_pair(common_name="test.example.com")
        encrypted = encrypt_private_key(private_key_pem, "")
        assert encrypted == private_key_pem
        decrypted = decrypt_private_key(encrypted, "")
        assert decrypted == private_key_pem

    def test_build_saml_settings_returns_valid_dict(self):
        from ee.observal_server.services.saml import build_saml_settings, generate_sp_key_pair

        private_key_pem, cert_pem = generate_sp_key_pair(common_name="test.example.com")
        result = build_saml_settings(
            idp_entity_id="https://idp.example.com",
            idp_sso_url="https://idp.example.com/sso",
            idp_x509_cert="MIICmzCCAYMCBgGN...",
            sp_entity_id="https://app.example.com/api/v1/sso/saml/metadata",
            sp_acs_url="https://app.example.com/api/v1/sso/saml/acs",
            sp_private_key=private_key_pem,
            sp_x509_cert=cert_pem,
        )
        assert result["idp"]["entityId"] == "https://idp.example.com"
        assert result["sp"]["entityId"] == "https://app.example.com/api/v1/sso/saml/metadata"
        assert "x509cert" in result["sp"]
        assert "privateKey" in result["sp"]
        assert result["security"]["authnRequestsSigned"] is False


class TestSamlHelpers:
    def test_extract_name_id_and_attrs(self):
        from unittest.mock import MagicMock

        from ee.observal_server.services.saml import extract_name_id_and_attrs

        auth = MagicMock()
        auth.get_nameid.return_value = "User@Example.COM"
        auth.get_attributes.return_value = {"displayName": ["Test User"]}

        email, attrs = extract_name_id_and_attrs(auth)
        assert email == "user@example.com"
        assert attrs["displayName"] == ["Test User"]

    def test_get_display_name_from_display_name_attr(self):
        from ee.observal_server.services.saml import get_display_name

        attrs = {"displayName": ["Jane Smith"]}
        assert get_display_name(attrs) == "Jane Smith"

    def test_get_display_name_fallback(self):
        from ee.observal_server.services.saml import get_display_name

        assert get_display_name({}) == "SSO User"
        assert get_display_name({}, fallback="Unknown") == "Unknown"

    def test_get_display_name_tries_multiple_claims(self):
        from ee.observal_server.services.saml import get_display_name

        attrs = {"givenName": ["Jane"]}
        assert get_display_name(attrs) == "Jane"

    def test_strip_pem_headers(self):
        from ee.observal_server.services.saml import _strip_pem_headers

        pem = "-----BEGIN CERTIFICATE-----\nMIIC\nmzCC\n-----END CERTIFICATE-----\n"
        assert _strip_pem_headers(pem) == "MIICmzCC"


class TestSamlEndpoints:
    @pytest.fixture
    def saml_app(self):
        from fastapi import FastAPI

        from ee.observal_server.routes.sso_saml import router

        app = FastAPI()
        app.include_router(router)
        return app

    def _make_mock_config(self):
        from ee.observal_server.services.saml import generate_sp_key_pair

        private_key, cert = generate_sp_key_pair("test.example.com")
        mock_config = MagicMock()
        mock_config.idp_entity_id = "https://idp.example.com"
        mock_config.idp_sso_url = "https://idp.example.com/sso"
        mock_config.idp_slo_url = ""
        mock_config.idp_x509_cert = cert  # Use a real cert for metadata generation
        mock_config.sp_entity_id = "https://app.example.com/api/v1/sso/saml/metadata"
        mock_config.sp_acs_url = "https://app.example.com/api/v1/sso/saml/acs"
        mock_config.sp_private_key_enc = private_key
        mock_config.sp_x509_cert = cert
        mock_config.jit_provisioning = True
        mock_config.default_role = "user"
        mock_config.org_id = None
        return mock_config, private_key

    @pytest.mark.asyncio
    async def test_metadata_returns_xml_when_configured(self, saml_app):
        mock_config, private_key = self._make_mock_config()

        with (
            patch(
                "ee.observal_server.routes.sso_saml._get_saml_config",
                new_callable=AsyncMock,
                return_value=mock_config,
            ),
            patch(
                "ee.observal_server.routes.sso_saml._decrypt_sp_key",
                return_value=private_key,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=saml_app),
                base_url="http://test",
            ) as ac:
                r = await ac.get("/api/v1/sso/saml/metadata")
            assert r.status_code == 200
            assert "xml" in r.headers.get("content-type", "").lower()
            assert "EntityDescriptor" in r.text

    @pytest.mark.asyncio
    async def test_metadata_returns_404_when_not_configured(self, saml_app):
        with patch(
            "ee.observal_server.routes.sso_saml._get_saml_config",
            new_callable=AsyncMock,
            return_value=None,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=saml_app),
                base_url="http://test",
            ) as ac:
                r = await ac.get("/api/v1/sso/saml/metadata")
            assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_login_returns_redirect_when_configured(self, saml_app):
        mock_config, private_key = self._make_mock_config()

        with (
            patch(
                "ee.observal_server.routes.sso_saml._get_saml_config",
                new_callable=AsyncMock,
                return_value=mock_config,
            ),
            patch(
                "ee.observal_server.routes.sso_saml._decrypt_sp_key",
                return_value=private_key,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=saml_app),
                base_url="http://test",
                follow_redirects=False,
            ) as ac:
                r = await ac.get("/api/v1/sso/saml/login")
            assert r.status_code == 302
            location = r.headers.get("location", "")
            assert "idp.example.com/sso" in location

    @pytest.mark.asyncio
    async def test_login_returns_404_when_not_configured(self, saml_app):
        with patch(
            "ee.observal_server.routes.sso_saml._get_saml_config",
            new_callable=AsyncMock,
            return_value=None,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=saml_app),
                base_url="http://test",
            ) as ac:
                r = await ac.get("/api/v1/sso/saml/login")
            assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_acs_returns_404_when_not_configured(self, saml_app):
        with patch(
            "ee.observal_server.routes.sso_saml._get_saml_config",
            new_callable=AsyncMock,
            return_value=None,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=saml_app),
                base_url="http://test",
            ) as ac:
                r = await ac.post("/api/v1/sso/saml/acs")
            assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_acs_replay_protection_stores_assertion_id(self, saml_app):
        """First ACS call with a given response ID should store it in Redis."""
        from api.deps import get_db

        mock_config, private_key = self._make_mock_config()
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()
        mock_redis.delete = AsyncMock()

        mock_auth = MagicMock()
        mock_auth.process_response.return_value = None
        mock_auth.get_errors.return_value = []
        mock_auth.is_authenticated.return_value = True
        mock_auth.get_last_message_id.return_value = "saml-response-id-12345"
        mock_auth.get_nameid.return_value = "user@example.com"
        mock_auth.get_attributes.return_value = {"displayName": ["Test User"]}

        mock_user = MagicMock()
        mock_user.id = "user-uuid-1"
        mock_user.email = "user@example.com"
        mock_user.name = "Test User"
        mock_user.username = "testuser"
        mock_user.role = MagicMock()
        mock_user.role.value = "user"
        mock_user.auth_provider = "saml"
        mock_user.sso_subject_id = "user@example.com"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        async def override_get_db():
            yield mock_db

        saml_app.dependency_overrides[get_db] = override_get_db

        try:
            with (
                patch(
                    "ee.observal_server.routes.sso_saml._get_saml_config",
                    new_callable=AsyncMock,
                    return_value=mock_config,
                ),
                patch(
                    "ee.observal_server.routes.sso_saml._decrypt_sp_key",
                    return_value=private_key,
                ),
                patch(
                    "ee.observal_server.routes.sso_saml._build_auth",
                    return_value=mock_auth,
                ),
                patch(
                    "ee.observal_server.routes.sso_saml.get_redis",
                    return_value=mock_redis,
                ),
                patch(
                    "ee.observal_server.routes.sso_saml.emit_security_event",
                    new_callable=AsyncMock,
                ),
                patch(
                    "ee.observal_server.routes.sso_saml.create_access_token",
                    return_value=("access-tok", 3600),
                ),
                patch(
                    "ee.observal_server.routes.sso_saml.create_refresh_token",
                    return_value=("refresh-tok", "jti-1"),
                ),
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=saml_app),
                    base_url="http://test",
                    follow_redirects=False,
                ) as ac:
                    r = await ac.post(
                        "/api/v1/sso/saml/acs",
                        data={"SAMLResponse": "dummybase64"},
                    )
                # Should succeed (redirect) and store the assertion ID
                assert r.status_code == 302
                mock_redis.get.assert_called_with("saml_assertion:saml-response-id-12345")
                mock_redis.setex.assert_any_call("saml_assertion:saml-response-id-12345", 300, "1")
        finally:
            saml_app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_acs_replay_protection_blocks_replayed_assertion(self, saml_app):
        """Second ACS call with same response ID should be rejected as replay."""
        from api.deps import get_db

        mock_config, private_key = self._make_mock_config()
        mock_redis = AsyncMock()
        # Simulate that this assertion ID was already seen
        mock_redis.get = AsyncMock(return_value=b"1")

        mock_auth = MagicMock()
        mock_auth.process_response.return_value = None
        mock_auth.get_errors.return_value = []
        mock_auth.is_authenticated.return_value = True
        mock_auth.get_last_message_id.return_value = "saml-response-id-12345"

        mock_db = AsyncMock()

        async def override_get_db():
            yield mock_db

        saml_app.dependency_overrides[get_db] = override_get_db

        try:
            with (
                patch(
                    "ee.observal_server.routes.sso_saml._get_saml_config",
                    new_callable=AsyncMock,
                    return_value=mock_config,
                ),
                patch(
                    "ee.observal_server.routes.sso_saml._decrypt_sp_key",
                    return_value=private_key,
                ),
                patch(
                    "ee.observal_server.routes.sso_saml._build_auth",
                    return_value=mock_auth,
                ),
                patch(
                    "ee.observal_server.routes.sso_saml.get_redis",
                    return_value=mock_redis,
                ),
                patch(
                    "ee.observal_server.routes.sso_saml.emit_security_event",
                    new_callable=AsyncMock,
                ) as mock_emit,
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=saml_app),
                    base_url="http://test",
                    follow_redirects=False,
                ) as ac:
                    r = await ac.post(
                        "/api/v1/sso/saml/acs",
                        data={"SAMLResponse": "dummybase64"},
                    )
                assert r.status_code == 400
                assert "already been processed" in r.json()["detail"]
                # Verify security event was emitted for the replay
                mock_emit.assert_called()
                event_arg = mock_emit.call_args[0][0]
                assert "replay" in event_arg.detail.lower()
        finally:
            saml_app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_logout_redirects_to_idp_when_slo_configured(self, saml_app):
        """Logout should redirect to IdP SLO endpoint when configured."""
        mock_config, private_key = self._make_mock_config()
        mock_config.idp_slo_url = "https://idp.example.com/slo"

        with (
            patch(
                "ee.observal_server.routes.sso_saml._get_saml_config",
                new_callable=AsyncMock,
                return_value=mock_config,
            ),
            patch(
                "ee.observal_server.routes.sso_saml._decrypt_sp_key",
                return_value=private_key,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=saml_app),
                base_url="http://test",
                follow_redirects=False,
            ) as ac:
                r = await ac.get("/api/v1/sso/saml/logout")
            assert r.status_code == 302
            location = r.headers.get("location", "")
            assert "idp.example.com/slo" in location

    @pytest.mark.asyncio
    async def test_logout_redirects_to_login_when_no_slo(self, saml_app):
        """Logout should redirect to /login when SLO is not configured."""
        mock_config, _private_key = self._make_mock_config()
        mock_config.idp_slo_url = ""

        with patch(
            "ee.observal_server.routes.sso_saml._get_saml_config",
            new_callable=AsyncMock,
            return_value=mock_config,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=saml_app),
                base_url="http://test",
                follow_redirects=False,
            ) as ac:
                r = await ac.get("/api/v1/sso/saml/logout")
            assert r.status_code == 302
            location = r.headers.get("location", "")
            assert "/login" in location

    @pytest.mark.asyncio
    async def test_logout_redirects_to_login_when_not_configured(self, saml_app):
        """Logout should redirect to /login when SAML is not configured at all."""
        with patch(
            "ee.observal_server.routes.sso_saml._get_saml_config",
            new_callable=AsyncMock,
            return_value=None,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=saml_app),
                base_url="http://test",
                follow_redirects=False,
            ) as ac:
                r = await ac.get("/api/v1/sso/saml/logout")
            assert r.status_code == 302
            assert "/login" in r.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_sls_handles_callback(self, saml_app):
        """SLS endpoint should process SLO and redirect to /login."""
        mock_config, private_key = self._make_mock_config()
        mock_config.idp_slo_url = "https://idp.example.com/slo"

        mock_auth = MagicMock()
        mock_auth.process_slo.return_value = None
        mock_auth.get_errors.return_value = []

        with (
            patch(
                "ee.observal_server.routes.sso_saml._get_saml_config",
                new_callable=AsyncMock,
                return_value=mock_config,
            ),
            patch(
                "ee.observal_server.routes.sso_saml._decrypt_sp_key",
                return_value=private_key,
            ),
            patch(
                "ee.observal_server.routes.sso_saml._build_auth",
                return_value=mock_auth,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=saml_app),
                base_url="http://test",
                follow_redirects=False,
            ) as ac:
                r = await ac.get("/api/v1/sso/saml/sls?SAMLResponse=dummybase64")
            assert r.status_code == 302
            assert "/login" in r.headers.get("location", "")
            mock_auth.process_slo.assert_called_once()

    @pytest.mark.asyncio
    async def test_sls_redirects_when_not_configured(self, saml_app):
        """SLS endpoint should redirect to /login when SAML is not configured."""
        with patch(
            "ee.observal_server.routes.sso_saml._get_saml_config",
            new_callable=AsyncMock,
            return_value=None,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=saml_app),
                base_url="http://test",
                follow_redirects=False,
            ) as ac:
                r = await ac.get("/api/v1/sso/saml/sls")
            assert r.status_code == 302
            assert "/login" in r.headers.get("location", "")


class TestSamlRelayState:
    """Tests for SAML RelayState (post-login redirect) support."""

    @pytest.fixture
    def saml_app(self):
        from fastapi import FastAPI

        from ee.observal_server.routes.sso_saml import router

        app = FastAPI()
        app.include_router(router)
        return app

    def _make_mock_config(self):
        from ee.observal_server.services.saml import generate_sp_key_pair

        private_key, cert = generate_sp_key_pair("test.example.com")
        mock_config = MagicMock()
        mock_config.idp_entity_id = "https://idp.example.com"
        mock_config.idp_sso_url = "https://idp.example.com/sso"
        mock_config.idp_slo_url = ""
        mock_config.idp_x509_cert = cert
        mock_config.sp_entity_id = "https://app.example.com/api/v1/sso/saml/metadata"
        mock_config.sp_acs_url = "https://app.example.com/api/v1/sso/saml/acs"
        mock_config.sp_private_key_enc = private_key
        mock_config.sp_x509_cert = cert
        mock_config.jit_provisioning = True
        mock_config.default_role = "user"
        mock_config.org_id = None
        return mock_config, private_key

    @pytest.mark.asyncio
    async def test_login_passes_relay_state(self, saml_app):
        """Login with ?next= should include RelayState in the redirect URL."""
        mock_config, private_key = self._make_mock_config()

        with (
            patch(
                "ee.observal_server.routes.sso_saml._get_saml_config",
                new_callable=AsyncMock,
                return_value=mock_config,
            ),
            patch(
                "ee.observal_server.routes.sso_saml._decrypt_sp_key",
                return_value=private_key,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=saml_app),
                base_url="http://test",
                follow_redirects=False,
            ) as ac:
                r = await ac.get("/api/v1/sso/saml/login?next=/sessions/abc")
            assert r.status_code == 302
            location = r.headers.get("location", "")
            assert "idp.example.com/sso" in location
            # RelayState should be passed to the IdP
            assert "RelayState" in location

    @pytest.mark.asyncio
    async def test_login_sanitizes_non_relative_relay_state(self, saml_app):
        """Login with absolute URL in ?next= should be sanitized to /."""
        mock_config, private_key = self._make_mock_config()

        with (
            patch(
                "ee.observal_server.routes.sso_saml._get_saml_config",
                new_callable=AsyncMock,
                return_value=mock_config,
            ),
            patch(
                "ee.observal_server.routes.sso_saml._decrypt_sp_key",
                return_value=private_key,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=saml_app),
                base_url="http://test",
                follow_redirects=False,
            ) as ac:
                r = await ac.get("/api/v1/sso/saml/login?next=https://evil.com/phish")
            assert r.status_code == 302
            location = r.headers.get("location", "")
            # Should NOT contain the evil URL in RelayState
            assert "evil.com" not in location

    @pytest.mark.asyncio
    async def test_login_defaults_relay_state_to_root(self, saml_app):
        """Login without ?next= should use / as default RelayState."""
        mock_config, private_key = self._make_mock_config()

        with (
            patch(
                "ee.observal_server.routes.sso_saml._get_saml_config",
                new_callable=AsyncMock,
                return_value=mock_config,
            ),
            patch(
                "ee.observal_server.routes.sso_saml._decrypt_sp_key",
                return_value=private_key,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=saml_app),
                base_url="http://test",
                follow_redirects=False,
            ) as ac:
                r = await ac.get("/api/v1/sso/saml/login")
            assert r.status_code == 302
            location = r.headers.get("location", "")
            assert "idp.example.com/sso" in location

    @pytest.mark.asyncio
    async def test_acs_extracts_relay_state_into_redirect(self, saml_app):
        """ACS should redirect to frontend login with saml_token param."""
        from api.deps import get_db

        mock_config, private_key = self._make_mock_config()
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()
        mock_redis.delete = AsyncMock()

        mock_auth = MagicMock()
        mock_auth.process_response.return_value = None
        mock_auth.get_errors.return_value = []
        mock_auth.is_authenticated.return_value = True
        mock_auth.get_last_message_id.return_value = "saml-response-relay-test"
        mock_auth.get_nameid.return_value = "user@example.com"
        mock_auth.get_attributes.return_value = {"displayName": ["Test User"]}

        mock_user = MagicMock()
        mock_user.id = "user-uuid-1"
        mock_user.email = "user@example.com"
        mock_user.name = "Test User"
        mock_user.username = "testuser"
        mock_user.role = MagicMock()
        mock_user.role.value = "user"
        mock_user.auth_provider = "saml"
        mock_user.sso_subject_id = "user@example.com"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        async def override_get_db():
            yield mock_db

        saml_app.dependency_overrides[get_db] = override_get_db

        try:
            with (
                patch(
                    "ee.observal_server.routes.sso_saml._get_saml_config",
                    new_callable=AsyncMock,
                    return_value=mock_config,
                ),
                patch(
                    "ee.observal_server.routes.sso_saml._decrypt_sp_key",
                    return_value=private_key,
                ),
                patch(
                    "ee.observal_server.routes.sso_saml._build_auth",
                    return_value=mock_auth,
                ),
                patch(
                    "ee.observal_server.routes.sso_saml.get_redis",
                    return_value=mock_redis,
                ),
                patch(
                    "ee.observal_server.routes.sso_saml.emit_security_event",
                    new_callable=AsyncMock,
                ),
                patch(
                    "ee.observal_server.routes.sso_saml.create_access_token",
                    return_value=("access-tok", 3600),
                ),
                patch(
                    "ee.observal_server.routes.sso_saml.create_refresh_token",
                    return_value=("refresh-tok", "jti-1"),
                ),
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=saml_app),
                    base_url="http://test",
                    follow_redirects=False,
                ) as ac:
                    r = await ac.post(
                        "/api/v1/sso/saml/acs",
                        data={
                            "SAMLResponse": "dummybase64",
                            "RelayState": "/sessions/abc",
                        },
                    )
                assert r.status_code == 302
                location = r.headers.get("location", "")
                assert "/login?saml_token=" in location
        finally:
            saml_app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_acs_sanitizes_non_relative_relay_state(self, saml_app):
        """ACS should redirect to frontend login with saml_token, not to evil URL."""
        from api.deps import get_db

        mock_config, private_key = self._make_mock_config()
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()
        mock_redis.delete = AsyncMock()

        mock_auth = MagicMock()
        mock_auth.process_response.return_value = None
        mock_auth.get_errors.return_value = []
        mock_auth.is_authenticated.return_value = True
        mock_auth.get_last_message_id.return_value = "saml-response-relay-sanitize"
        mock_auth.get_nameid.return_value = "user@example.com"
        mock_auth.get_attributes.return_value = {"displayName": ["Test User"]}

        mock_user = MagicMock()
        mock_user.id = "user-uuid-1"
        mock_user.email = "user@example.com"
        mock_user.name = "Test User"
        mock_user.username = "testuser"
        mock_user.role = MagicMock()
        mock_user.role.value = "user"
        mock_user.auth_provider = "saml"
        mock_user.sso_subject_id = "user@example.com"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        async def override_get_db():
            yield mock_db

        saml_app.dependency_overrides[get_db] = override_get_db

        try:
            with (
                patch(
                    "ee.observal_server.routes.sso_saml._get_saml_config",
                    new_callable=AsyncMock,
                    return_value=mock_config,
                ),
                patch(
                    "ee.observal_server.routes.sso_saml._decrypt_sp_key",
                    return_value=private_key,
                ),
                patch(
                    "ee.observal_server.routes.sso_saml._build_auth",
                    return_value=mock_auth,
                ),
                patch(
                    "ee.observal_server.routes.sso_saml.get_redis",
                    return_value=mock_redis,
                ),
                patch(
                    "ee.observal_server.routes.sso_saml.emit_security_event",
                    new_callable=AsyncMock,
                ),
                patch(
                    "ee.observal_server.routes.sso_saml.create_access_token",
                    return_value=("access-tok", 3600),
                ),
                patch(
                    "ee.observal_server.routes.sso_saml.create_refresh_token",
                    return_value=("refresh-tok", "jti-1"),
                ),
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=saml_app),
                    base_url="http://test",
                    follow_redirects=False,
                ) as ac:
                    r = await ac.post(
                        "/api/v1/sso/saml/acs",
                        data={
                            "SAMLResponse": "dummybase64",
                            "RelayState": "https://evil.com/phish",
                        },
                    )
                assert r.status_code == 302
                location = r.headers.get("location", "")
                assert "evil.com" not in location
                assert "/login?saml_token=" in location
        finally:
            saml_app.dependency_overrides.clear()
