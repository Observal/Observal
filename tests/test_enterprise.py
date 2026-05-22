# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Enterprise configuration validator tests."""

from unittest.mock import MagicMock, patch


def _mock_ds(sso_only=False, frontend_url="https://app.example.com", **saml_overrides):
    """Create a mock ds module with get_sync/get_sync_bool helpers."""
    defaults = {
        "deployment.sso_only": str(sso_only).lower(),
        "deployment.frontend_url": frontend_url,
        "saml.idp_entity_id": "",
        "saml.idp_sso_url": "",
        "saml.idp_x509_cert": "",
        "saml.sp_key_encryption_password": "strong-pass",
        "saml.sp_acs_url": "https://app.example.com/api/v1/sso/saml/acs",
    }
    defaults.update(saml_overrides)
    mock = MagicMock()
    mock.get_sync.side_effect = lambda key, *a, **kw: defaults.get(key, a[0] if a else "")
    mock.get_sync_bool.side_effect = lambda key, *a, **kw: defaults.get(key, "false").lower() in ("true", "1")
    return mock


class TestConfigValidator:
    def test_detects_default_secret_key(self):
        from ee.observal_server.services.config_validator import validate_enterprise_config

        settings = MagicMock()
        settings.SECRET_KEY = "change-me-to-a-random-string"
        settings.OAUTH_CLIENT_ID = "id"
        settings.OAUTH_CLIENT_SECRET = "secret"
        settings.OAUTH_SERVER_METADATA_URL = "https://idp.example.com"

        with patch("ee.observal_server.services.config_validator.ds", _mock_ds()):
            issues = validate_enterprise_config(settings)
        assert len(issues) == 1
        assert any("SECRET_KEY" in i for i in issues)

    def test_detects_missing_oauth_when_sso_only(self):
        from ee.observal_server.services.config_validator import validate_enterprise_config

        settings = MagicMock()
        settings.SECRET_KEY = "proper-random-secret-key-32chars!!"
        settings.OAUTH_CLIENT_ID = None
        settings.OAUTH_CLIENT_SECRET = None
        settings.OAUTH_SERVER_METADATA_URL = None

        with patch("ee.observal_server.services.config_validator.ds", _mock_ds(sso_only=True)):
            issues = validate_enterprise_config(settings)
        assert len(issues) == 3
        assert any("OAUTH_CLIENT_ID" in i for i in issues)

    def test_no_oauth_issues_when_sso_not_required(self):
        from ee.observal_server.services.config_validator import validate_enterprise_config

        settings = MagicMock()
        settings.SECRET_KEY = "proper-random-secret-key-32chars!!"
        settings.OAUTH_CLIENT_ID = None

        with patch("ee.observal_server.services.config_validator.ds", _mock_ds(sso_only=False)):
            issues = validate_enterprise_config(settings)
        assert len(issues) == 0

    def test_detects_localhost_frontend(self):
        from ee.observal_server.services.config_validator import validate_enterprise_config

        settings = MagicMock()
        settings.SECRET_KEY = "proper-random-secret-key-32chars!!"
        settings.OAUTH_CLIENT_ID = "id"

        with patch("ee.observal_server.services.config_validator.ds", _mock_ds(frontend_url="http://localhost:3000")):
            issues = validate_enterprise_config(settings)
        assert any("frontend_url" in i for i in issues)

    def test_healthy_config_returns_empty(self):
        from ee.observal_server.services.config_validator import validate_enterprise_config

        settings = MagicMock()
        settings.SECRET_KEY = "proper-random-secret-key-32chars!!"
        settings.OAUTH_CLIENT_ID = "id"
        settings.OAUTH_CLIENT_SECRET = "secret"
        settings.OAUTH_SERVER_METADATA_URL = "https://idp.example.com"

        with patch("ee.observal_server.services.config_validator.ds", _mock_ds()):
            issues = validate_enterprise_config(settings)
        assert issues == []

    def test_detects_missing_saml_idp_cert_when_saml_configured(self):
        from ee.observal_server.services.config_validator import validate_enterprise_config

        settings = MagicMock()
        settings.SECRET_KEY = "proper-random-secret-key-32chars!!"
        settings.OAUTH_CLIENT_ID = "id"

        ds_mock = _mock_ds(
            **{
                "saml.idp_entity_id": "https://idp.example.com/entity",
                "saml.idp_sso_url": "https://idp.example.com/sso",
                "saml.idp_x509_cert": "",
            }
        )
        with patch("ee.observal_server.services.config_validator.ds", ds_mock):
            issues = validate_enterprise_config(settings)
        assert any("x509_cert" in i for i in issues)
