# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Enterprise configuration validator.

Checks that required settings are properly configured for enterprise mode.
Returns a list of human-readable issue descriptions (empty = healthy).

Uses dynamic_settings for runtime-tunable values and config.settings for
boot-time values (SECRET_KEY, OAUTH_*).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import Settings


import services.dynamic_settings as ds


def validate_enterprise_config(settings: Settings) -> list[str]:
    """Validate enterprise-required configuration.  Returns list of issues."""
    issues: list[str] = []

    if settings.SECRET_KEY == "change-me-to-a-random-string":
        issues.append("SECRET_KEY is using default value")

    sso_only = ds.get_sync_bool("deployment.sso_only")
    if sso_only:
        if not settings.OAUTH_CLIENT_ID:
            issues.append("OAUTH_CLIENT_ID is not set (required when sso_only=true)")
        if not settings.OAUTH_CLIENT_SECRET:
            issues.append("OAUTH_CLIENT_SECRET is not set (required when sso_only=true)")
        if not settings.OAUTH_SERVER_METADATA_URL:
            issues.append("OAUTH_SERVER_METADATA_URL is not set (required when sso_only=true)")

    saml_entity = ds.get_sync("saml.idp_entity_id")
    saml_sso = ds.get_sync("saml.idp_sso_url")
    if saml_entity or saml_sso:
        if saml_entity and not saml_sso:
            issues.append("saml.idp_sso_url is not set (required when saml.idp_entity_id is configured)")
        if saml_sso and not saml_entity:
            issues.append("saml.idp_entity_id is not set (required when saml.idp_sso_url is configured)")
        if saml_entity and saml_sso:
            saml_cert = ds.get_sync("saml.idp_x509_cert")
            if not saml_cert:
                issues.append("saml.idp_x509_cert is not set (required when SAML IdP is configured)")
            enc_password = ds.get_sync("saml.sp_key_encryption_password")
            if not enc_password:
                issues.append("saml.sp_key_encryption_password is empty (SP private key will be stored unencrypted)")
            sp_acs = ds.get_sync("saml.sp_acs_url")
            if sp_acs and not sp_acs.startswith("https://"):
                issues.append("saml.sp_acs_url should use HTTPS for production deployments")

    frontend_url = ds.get_sync("deployment.frontend_url")
    if frontend_url in ("http://localhost:3000", ""):
        issues.append("deployment.frontend_url is localhost or empty")

    return issues
