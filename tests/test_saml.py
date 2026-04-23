"""Tests for SAML service layer."""


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
        assert result["security"]["authnRequestsSigned"] is True


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
