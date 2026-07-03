# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: LicenseRef-Observal-Enterprise

"""Enterprise configuration validator.

Checks that required settings are properly configured for enterprise mode.
Returns a list of human-readable issue descriptions (empty = healthy).

Uses dynamic_settings for SSO values and config.settings for boot-time values.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import Settings


import services.dynamic_settings as ds


def validate_enterprise_config(settings: Settings) -> list[str]:
    """Validate enterprise-required configuration (sync, uses in-memory cache).

    Used at boot time for logging. For live request-time checks, use
    ``validate_enterprise_config_async`` which reads fresh values from Redis/DB.
    """
    issues: list[str] = []

    if settings.SECRET_KEY == "change-me-to-a-random-string":
        issues.append("SECRET_KEY is using default value")

    sso_only = ds.get_sync_bool("deployment.sso_only")
    if sso_only:
        if not ds.get_sync("oauth.client_id"):
            issues.append("oauth.client_id is not set (required when sso_only=true)")
        if not ds.get_sync("oauth.client_secret"):
            issues.append("oauth.client_secret is not set (required when sso_only=true)")
        if not ds.get_sync("oauth.server_metadata_url"):
            issues.append("oauth.server_metadata_url is not set (required when sso_only=true)")

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
            sp_enc_pw = ds.get_sync("saml.sp_key_encryption_password")
            if not sp_enc_pw:
                issues.append("saml.sp_key_encryption_password is not set (required when SAML IdP is configured)")
            sp_acs = ds.get_sync("saml.sp_acs_url")
            if sp_acs and not sp_acs.startswith("https://"):
                issues.append("saml.sp_acs_url should use HTTPS for production deployments")

    frontend_url = ds.get_sync("deployment.frontend_url")
    if frontend_url in ("http://localhost:3000", ""):
        issues.append("deployment.frontend_url is localhost or empty")

    return issues


async def validate_enterprise_config_async(settings: Settings) -> list[str]:
    """Validate enterprise-required configuration (async, reads from Redis/DB).

    Always returns fresh values — safe to call on every request without stale cache issues.
    """
    issues: list[str] = []

    if settings.SECRET_KEY == "change-me-to-a-random-string":
        issues.append("SECRET_KEY is using default value")

    sso_only = (await ds.get("deployment.sso_only")).lower() in ("true", "1", "yes")
    if sso_only:
        if not await ds.get("oauth.client_id"):
            issues.append("oauth.client_id is not set (required when sso_only=true)")
        if not await ds.get("oauth.client_secret"):
            issues.append("oauth.client_secret is not set (required when sso_only=true)")
        if not await ds.get("oauth.server_metadata_url"):
            issues.append("oauth.server_metadata_url is not set (required when sso_only=true)")

    saml_entity = await ds.get("saml.idp_entity_id")
    saml_sso = await ds.get("saml.idp_sso_url")
    if saml_entity or saml_sso:
        if saml_entity and not saml_sso:
            issues.append("saml.idp_sso_url is not set (required when saml.idp_entity_id is configured)")
        if saml_sso and not saml_entity:
            issues.append("saml.idp_entity_id is not set (required when saml.idp_sso_url is configured)")
        if saml_entity and saml_sso:
            if not await ds.get("saml.idp_x509_cert"):
                issues.append("saml.idp_x509_cert is not set (required when SAML IdP is configured)")
            if not await ds.get("saml.sp_key_encryption_password"):
                issues.append("saml.sp_key_encryption_password is not set (required when SAML IdP is configured)")
            sp_acs = await ds.get("saml.sp_acs_url")
            if sp_acs and not sp_acs.startswith("https://"):
                issues.append("saml.sp_acs_url should use HTTPS for production deployments")

    frontend_url = await ds.get("deployment.frontend_url")
    if frontend_url in ("http://localhost:3000", ""):
        issues.append("deployment.frontend_url is localhost or empty")

    return issues
