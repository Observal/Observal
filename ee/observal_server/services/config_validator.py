# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Enterprise configuration validator.

Checks that required settings are properly configured for enterprise mode.
Returns a list of human-readable issue descriptions (empty = healthy).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import Settings


def validate_enterprise_config(settings: Settings) -> list[str]:
    """Validate enterprise-required configuration.  Returns list of issues."""
    issues: list[str] = []

    if settings.SECRET_KEY == "change-me-to-a-random-string":
        issues.append("SECRET_KEY is using default value")

    if settings.SSO_ONLY:
        if not settings.OAUTH_CLIENT_ID:
            issues.append("OAUTH_CLIENT_ID is not set (required when SSO_ONLY=true)")
        if not settings.OAUTH_CLIENT_SECRET:
            issues.append("OAUTH_CLIENT_SECRET is not set (required when SSO_ONLY=true)")
        if not settings.OAUTH_SERVER_METADATA_URL:
            issues.append("OAUTH_SERVER_METADATA_URL is not set (required when SSO_ONLY=true)")

    saml_entity = getattr(settings, "SAML_IDP_ENTITY_ID", "")
    saml_sso = getattr(settings, "SAML_IDP_SSO_URL", "")
    if saml_entity or saml_sso:
        if saml_entity and not saml_sso:
            issues.append("SAML_IDP_SSO_URL is not set (required when SAML_IDP_ENTITY_ID is configured)")
        if saml_sso and not saml_entity:
            issues.append("SAML_IDP_ENTITY_ID is not set (required when SAML_IDP_SSO_URL is configured)")
        if saml_entity and saml_sso:
            saml_cert = getattr(settings, "SAML_IDP_X509_CERT", "")
            if not saml_cert:
                issues.append("SAML_IDP_X509_CERT is not set (required when SAML IdP is configured)")
            enc_password = getattr(settings, "SAML_SP_KEY_ENCRYPTION_PASSWORD", "")
            if not enc_password:
                issues.append("SAML_SP_KEY_ENCRYPTION_PASSWORD is empty (SP private key will be stored unencrypted)")
            sp_acs = getattr(settings, "SAML_SP_ACS_URL", "")
            if sp_acs and not sp_acs.startswith("https://"):
                issues.append("SAML_SP_ACS_URL should use HTTPS for production deployments")

    if settings.FRONTEND_URL in ("http://localhost:3000", ""):
        issues.append("FRONTEND_URL is localhost or empty")

    return issues
