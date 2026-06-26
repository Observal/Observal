# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Enterprise configuration validator tests."""

from unittest.mock import MagicMock, patch


def _mock_ds(sso_only=False, frontend_url="https://app.example.com", **saml_overrides):
    """Create a mock ds module with get_sync/get_sync_bool helpers."""
    defaults = {
        "deployment.sso_only": str(sso_only).lower(),
        "deployment.frontend_url": frontend_url,
        "oauth.client_id": "id",
        "oauth.client_secret": "secret",
        "oauth.server_metadata_url": "https://idp.example.com",
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
        with patch("ee.observal_server.services.config_validator.ds", _mock_ds()):
            issues = validate_enterprise_config(settings)
        assert len(issues) == 1
        assert any("SECRET_KEY" in i for i in issues)

    def test_detects_missing_oauth_when_sso_only(self):
        from ee.observal_server.services.config_validator import validate_enterprise_config

        settings = MagicMock()
        settings.SECRET_KEY = "proper-random-secret-key-32chars!!"
        with patch(
            "ee.observal_server.services.config_validator.ds",
            _mock_ds(
                sso_only=True,
                **{
                    "oauth.client_id": "",
                    "oauth.client_secret": "",
                    "oauth.server_metadata_url": "",
                },
            ),
        ):
            issues = validate_enterprise_config(settings)
        assert len(issues) == 3
        assert any("oauth.client_id" in i for i in issues)

    def test_no_oauth_issues_when_sso_not_required(self):
        from ee.observal_server.services.config_validator import validate_enterprise_config

        settings = MagicMock()
        settings.SECRET_KEY = "proper-random-secret-key-32chars!!"
        with patch("ee.observal_server.services.config_validator.ds", _mock_ds(sso_only=False)):
            issues = validate_enterprise_config(settings)
        assert len(issues) == 0

    def test_detects_localhost_frontend(self):
        from ee.observal_server.services.config_validator import validate_enterprise_config

        settings = MagicMock()
        settings.SECRET_KEY = "proper-random-secret-key-32chars!!"
        with patch("ee.observal_server.services.config_validator.ds", _mock_ds(frontend_url="http://localhost:3000")):
            issues = validate_enterprise_config(settings)
        assert any("frontend_url" in i for i in issues)

    def test_healthy_config_returns_empty(self):
        from ee.observal_server.services.config_validator import validate_enterprise_config

        settings = MagicMock()
        settings.SECRET_KEY = "proper-random-secret-key-32chars!!"
        with patch("ee.observal_server.services.config_validator.ds", _mock_ds()):
            issues = validate_enterprise_config(settings)
        assert issues == []

    def test_detects_missing_saml_idp_cert_when_saml_configured(self):
        from ee.observal_server.services.config_validator import validate_enterprise_config

        settings = MagicMock()
        settings.SECRET_KEY = "proper-random-secret-key-32chars!!"
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
