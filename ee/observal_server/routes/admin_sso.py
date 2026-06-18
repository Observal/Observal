# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: LicenseRef-Observal-Enterprise

"""Admin endpoints for SAML config and SCIM token management."""

from __future__ import annotations

import secrets
import time
import uuid
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger as optic
from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


import services.dynamic_settings as ds
from api.deps import get_db, get_or_create_default_org, require_role
from config import settings
from ee.observal_server.services.saml import (
    build_saml_settings,
    check_cert_expiry,
    check_idp_cert_against_metadata,
    check_idp_sso_url_reachable,
    check_nameid_format,
    check_sp_cert_key_match,
    check_sp_host_consistency,
    decrypt_private_key,
    encrypt_private_key,
    generate_sp_key_pair,
)
from ee.observal_server.services.scim_service import hash_scim_token
from models.saml_config import SamlConfig
from models.scim_token import ScimToken
from models.user import User, UserRole
from schemas.sso_health import all_pass, make_check
from services.oidc_health import run_oidc_checks
from services.security_events import (
    EventType,
    SecurityEvent,
    Severity,
    emit_security_event,
)


def _get_frontend_url() -> str:
    return ds.get_sync("deployment.frontend_url", "http://localhost:3000")


router = APIRouter(prefix="/api/v1/admin", tags=["admin-sso"])


# ── SAML Configuration ─────────────────────────────────────


@router.get("/saml-config")
async def get_saml_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Get current SAML configuration (sensitive fields redacted)."""
    result = await db.execute(select(SamlConfig).where(SamlConfig.active.is_(True)).limit(1))
    config = result.scalar_one_or_none()

    if not config:
        has_env = bool(ds.get_sync("saml.idp_entity_id") and ds.get_sync("saml.idp_sso_url"))
        return {
            "configured": has_env,
            "source": "env" if has_env else "none",
            "idp_entity_id": ds.get_sync("saml.idp_entity_id") if has_env else None,
            "idp_sso_url": ds.get_sync("saml.idp_sso_url") if has_env else None,
            "idp_slo_url": ds.get_sync("saml.idp_slo_url") if has_env else None,
            "sp_entity_id": ds.get_sync("saml.sp_entity_id") if has_env else None,
            "sp_acs_url": ds.get_sync("saml.sp_acs_url") if has_env else None,
            "jit_provisioning": ds.get_sync_bool("saml.jit_provisioning", True) if has_env else None,
            "default_role": ds.get_sync("saml.default_role", "user") if has_env else None,
            "has_idp_cert": bool(ds.get_sync("saml.idp_x509_cert")) if has_env else False,
            "has_sp_key": False,
        }
    return {
        "configured": True,
        "source": "database",
        "id": str(config.id),
        "org_id": str(config.org_id),
        "idp_entity_id": config.idp_entity_id,
        "idp_sso_url": config.idp_sso_url,
        "idp_slo_url": config.idp_slo_url,
        "sp_entity_id": config.sp_entity_id,
        "sp_acs_url": config.sp_acs_url,
        "jit_provisioning": config.jit_provisioning,
        "default_role": config.default_role,
        "has_idp_cert": bool(config.idp_x509_cert),
        "has_sp_key": bool(config.sp_private_key_enc),
        "active": config.active,
        "created_at": config.created_at.isoformat() if config.created_at else None,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
    }


@router.put("/saml-config")
async def upsert_saml_config(
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Create or update SAML configuration. Auto-generates SP key pair."""
    idp_entity_id = body.get("idp_entity_id")
    idp_sso_url = body.get("idp_sso_url")
    idp_x509_cert = body.get("idp_x509_cert")

    if not idp_entity_id or not idp_sso_url or not idp_x509_cert:
        raise HTTPException(
            status_code=422,
            detail="idp_entity_id, idp_sso_url, and idp_x509_cert are required",
        )

    default_org = await get_or_create_default_org(db)
    org_id = current_user.org_id or default_org.id

    sp_entity_id = body.get("sp_entity_id") or f"{_get_frontend_url()}/api/v1/sso/saml/metadata"
    sp_acs_url = body.get("sp_acs_url") or f"{_get_frontend_url()}/api/v1/sso/saml/acs"

    result = await db.execute(select(SamlConfig).where(SamlConfig.org_id == org_id))
    config = result.scalar_one_or_none()

    enc_password = ds.get_sync("saml.sp_key_encryption_password")

    if not config:
        private_key_pem, cert_pem = generate_sp_key_pair(common_name=sp_entity_id)
        sp_key_enc = encrypt_private_key(private_key_pem, enc_password)

        config = SamlConfig(
            org_id=org_id,
            idp_entity_id=idp_entity_id,
            idp_sso_url=idp_sso_url,
            idp_slo_url=body.get("idp_slo_url", ""),
            idp_x509_cert=idp_x509_cert,
            sp_entity_id=sp_entity_id,
            sp_acs_url=sp_acs_url,
            sp_private_key_enc=sp_key_enc,
            sp_x509_cert=cert_pem,
            jit_provisioning=body.get("jit_provisioning", True),
            default_role=body.get("default_role", "user"),
            active=True,
        )
        db.add(config)
    else:
        config.idp_entity_id = idp_entity_id
        config.idp_sso_url = idp_sso_url
        config.idp_slo_url = body.get("idp_slo_url", config.idp_slo_url or "")
        config.idp_x509_cert = idp_x509_cert
        config.sp_entity_id = sp_entity_id
        config.sp_acs_url = sp_acs_url
        config.jit_provisioning = body.get("jit_provisioning", config.jit_provisioning)
        config.default_role = body.get("default_role", config.default_role)
        config.active = body.get("active", config.active)

        if body.get("regenerate_sp_key"):
            private_key_pem, cert_pem = generate_sp_key_pair(common_name=sp_entity_id)
            config.sp_private_key_enc = encrypt_private_key(private_key_pem, enc_password)
            config.sp_x509_cert = cert_pem

    await db.commit()
    await db.refresh(config)

    await emit_security_event(
        SecurityEvent(
            event_type=EventType.SETTING_CHANGED,
            severity=Severity.WARNING,
            outcome="success",
            actor_id=str(current_user.id),
            actor_email=current_user.email,
            actor_role=current_user.role.value,
            target_id=str(config.id),
            target_type="saml_config",
            detail="SAML configuration updated",
        )
    )

    return {
        "id": str(config.id),
        "idp_entity_id": config.idp_entity_id,
        "sp_entity_id": config.sp_entity_id,
        "sp_acs_url": config.sp_acs_url,
        "active": config.active,
        "message": "SAML configuration saved",
    }


@router.delete("/saml-config")
async def delete_saml_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Delete SAML configuration (disables SAML SSO)."""
    org_id = current_user.org_id
    if not org_id:
        default_org = await get_or_create_default_org(db)
        org_id = default_org.id

    result = await db.execute(select(SamlConfig).where(SamlConfig.org_id == org_id))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="No SAML configuration found")

    config_id = str(config.id)
    await db.delete(config)
    await db.commit()

    await emit_security_event(
        SecurityEvent(
            event_type=EventType.SETTING_CHANGED,
            severity=Severity.WARNING,
            outcome="success",
            actor_id=str(current_user.id),
            actor_email=current_user.email,
            actor_role=current_user.role.value,
            target_id=config_id,
            target_type="saml_config",
            detail="SAML configuration deleted",
        )
    )
    return {"deleted": config_id}


# ── SSO Validation ────────────────────────────────────────


def _first_failure(checks: list[dict]) -> tuple[str | None, str | None]:
    for c in checks:
        if c.get("status") == "fail":
            return c.get("message"), c.get("hint")
    return None, None


@router.post("/sso/validate-oidc")
async def validate_oidc(
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Validate OIDC/OAuth end-to-end and return per-check diagnostics.

    Note: server-side validation can only verify what the IdP exposes — the
    final assertion exchange and any per-user authorization decisions are not
    visible here, so a green result still depends on a real user login round-trip.
    """
    optic.info("admin.validate_oidc start")
    start = time.monotonic()

    if not settings.OAUTH_CLIENT_ID or not settings.OAUTH_CLIENT_SECRET:
        return {
            "success": False,
            "error": "OAUTH_CLIENT_ID or OAUTH_CLIENT_SECRET not configured",
            "hint": "Set OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET, and OAUTH_SERVER_METADATA_URL.",
            "checks": [],
        }
    if not settings.OAUTH_SERVER_METADATA_URL:
        return {
            "success": False,
            "error": "OAUTH_SERVER_METADATA_URL not configured",
            "hint": "Point this at your IdP's .well-known/openid-configuration URL.",
            "checks": [],
        }

    redirect_uri = (
        ds.get_sync("deployment.frontend_url", "http://localhost:3000").rstrip("/") + "/api/v1/auth/oauth/callback"
    )

    checks, metadata = await run_oidc_checks(
        settings.OAUTH_SERVER_METADATA_URL,
        settings.OAUTH_CLIENT_ID,
        settings.OAUTH_CLIENT_SECRET,
        redirect_uri,
    )
    success = all_pass(checks)
    err_msg, err_hint = (None, None) if success else _first_failure(checks)
    latency_ms = round((time.monotonic() - start) * 1000)
    optic.info("admin.validate_oidc done success={} checks={} latency_ms={}", success, len(checks), latency_ms)
    return {
        "success": success,
        "issuer": (metadata or {}).get("issuer"),
        "checks": checks,
        "latency_ms": latency_ms,
        **({"error": err_msg, "hint": err_hint} if not success else {}),
    }


async def _run_saml_checks(config, sp_key: str, frontend_url: str) -> list[dict]:
    """Assemble every SAML check; run-all semantics so the operator sees every issue."""
    from onelogin.saml2.auth import OneLogin_Saml2_Auth

    checks: list[dict] = []

    field_check = make_check("required_fields", "Required SAML fields populated", "pass")
    missing = []
    for attr, pretty in (
        ("idp_entity_id", "IdP Entity ID"),
        ("idp_sso_url", "IdP SSO URL"),
        ("idp_x509_cert", "IdP X.509 certificate"),
        ("sp_entity_id", "SP Entity ID"),
        ("sp_acs_url", "SP ACS URL"),
        ("sp_private_key_enc", "SP private key"),
    ):
        if not getattr(config, attr, None):
            missing.append(pretty)
    if missing:
        field_check = make_check(
            "required_fields",
            "Required SAML fields populated",
            "fail",
            f"Missing: {'; '.join(missing)}.",
            "Complete the SAML configuration with all required fields.",
        )
    checks.append(field_check)
    if missing:
        return checks

    parsed = urlparse(frontend_url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    request_data = {
        "https": "on" if parsed.scheme == "https" else "off",
        "http_host": f"{parsed.hostname}:{port}" if port not in (80, 443) else parsed.hostname,
        "server_port": str(port),
        "script_name": "/api/v1/sso/saml/login",
        "get_data": {},
        "post_data": {},
    }
    sp_slo_url = f"{frontend_url}/api/v1/sso/saml/sls" if getattr(config, "idp_slo_url", "") else ""

    try:
        saml_settings = build_saml_settings(
            idp_entity_id=config.idp_entity_id,
            idp_sso_url=config.idp_sso_url,
            idp_x509_cert=config.idp_x509_cert,
            sp_entity_id=config.sp_entity_id,
            sp_acs_url=config.sp_acs_url,
            sp_private_key=sp_key,
            sp_x509_cert=config.sp_x509_cert,
            idp_slo_url=getattr(config, "idp_slo_url", "") or "",
            sp_slo_url=sp_slo_url,
        )
        auth_obj = OneLogin_Saml2_Auth(request_data, old_settings=saml_settings)
        auth_obj.login(return_to="/")
        checks.append(make_check("onelogin_build", "OneLogin SAML settings load", "pass"))
        checks.append(make_check("authn_request", "AuthnRequest builds", "pass"))
    except Exception as e:
        msg_lower = str(e).lower()
        optic.exception("admin._run_saml_checks OneLogin build failed")
        if "idp_cert" in msg_lower:
            msg, hint = ("IdP X.509 certificate is missing or malformed.", "Re-import the IdP signing certificate.")
        elif "sp" in msg_lower and "key" in msg_lower:
            msg, hint = ("SP private key or certificate is invalid.", "Regenerate the SP key pair.")
        else:
            msg, hint = ("SAML settings validation failed.", "Check the configuration values; details in server logs.")
        checks.append(make_check("onelogin_build", "OneLogin SAML settings load", "fail", msg, hint))
        return checks

    for opt in (
        await check_idp_cert_against_metadata(config.idp_x509_cert),
        check_cert_expiry(config.idp_x509_cert, "IdP"),
        check_cert_expiry(config.sp_x509_cert, "SP"),
        check_sp_host_consistency(config.sp_acs_url, frontend_url),
        check_sp_cert_key_match(config.sp_x509_cert, sp_key),
        await check_idp_sso_url_reachable(config.idp_sso_url),
        await check_nameid_format("emailAddress"),
    ):
        if opt is not None:
            checks.append(opt)
    return checks


@router.post("/sso/validate-saml")
async def validate_saml(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Validate SAML configuration end-to-end and return per-check diagnostics.

    Note: server-side validation cannot replay a signed assertion, so a green
    result still depends on a real user login from your IdP. Some signals (e.g.
    NameIDFormat, signing cert rotation) are only visible if ``saml.idp_metadata_url``
    is configured.
    """
    optic.info("admin.validate_saml start")
    start = time.monotonic()

    from ee.observal_server.routes.sso_saml import _get_saml_config

    config = await _get_saml_config(db)
    if not config:
        return {
            "success": False,
            "error": "SAML is not configured",
            "hint": "Configure SAML via environment variables or the admin API.",
            "checks": [],
        }

    try:
        sp_key = decrypt_private_key(
            config.sp_private_key_enc,
            ds.get_sync("saml.sp_key_encryption_password"),
        )
    except Exception:
        optic.exception("admin.validate_saml SP key decrypt failed")
        return {
            "success": False,
            "error": "Failed to decrypt SP private key",
            "hint": "Check SAML_SP_KEY_ENCRYPTION_PASSWORD is correct.",
            "checks": [
                make_check(
                    "sp_key_decrypt",
                    "SP private key decrypts",
                    "fail",
                    "Decryption failed.",
                    "Check SAML_SP_KEY_ENCRYPTION_PASSWORD.",
                )
            ],
            "latency_ms": round((time.monotonic() - start) * 1000),
        }

    frontend_url = _get_frontend_url()
    checks = await _run_saml_checks(config, sp_key, frontend_url)
    success = all_pass(checks)
    err_msg, err_hint = (None, None) if success else _first_failure(checks)
    latency_ms = round((time.monotonic() - start) * 1000)
    optic.info("admin.validate_saml done success={} checks={} latency_ms={}", success, len(checks), latency_ms)
    return {
        "success": success,
        "idp_entity_id": config.idp_entity_id,
        "checks": checks,
        "latency_ms": latency_ms,
        **({"error": err_msg, "hint": err_hint} if not success else {}),
    }


# ── SCIM Token Management ──────────────────────────────────


@router.get("/scim-tokens")
async def list_scim_tokens(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """List all SCIM tokens (token values are not returned, only metadata)."""
    org_id = current_user.org_id
    if not org_id:
        default_org = await get_or_create_default_org(db)
        org_id = default_org.id

    result = await db.execute(select(ScimToken).where(ScimToken.org_id == org_id).order_by(ScimToken.created_at.desc()))
    tokens = result.scalars().all()
    return [
        {
            "id": str(t.id),
            "description": t.description,
            "active": t.active,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "token_prefix": t.token_hash[:8] + "...",
        }
        for t in tokens
    ]


@router.post("/scim-tokens")
async def create_scim_token(
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Generate a new SCIM bearer token. The plaintext token is returned ONCE."""
    org_id = current_user.org_id
    if not org_id:
        default_org = await get_or_create_default_org(db)
        org_id = default_org.id

    description = body.get("description", "")
    raw_token = secrets.token_urlsafe(48)
    token_hash = hash_scim_token(raw_token)

    token = ScimToken(
        org_id=org_id,
        token_hash=token_hash,
        description=description,
        active=True,
    )
    db.add(token)
    await db.commit()
    await db.refresh(token)

    await emit_security_event(
        SecurityEvent(
            event_type=EventType.SETTING_CHANGED,
            severity=Severity.INFO,
            outcome="success",
            actor_id=str(current_user.id),
            actor_email=current_user.email,
            actor_role=current_user.role.value,
            target_id=str(token.id),
            target_type="scim_token",
            detail="SCIM token created",
        )
    )

    return {
        "id": str(token.id),
        "token": raw_token,
        "description": description,
        "message": "Save this token now. It will not be shown again.",
    }


@router.delete("/scim-tokens/{token_id}")
async def revoke_scim_token(
    token_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Revoke (deactivate) a SCIM token."""
    try:
        tid = uuid.UUID(token_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Token not found")

    org_id = current_user.org_id
    if not org_id:
        default_org = await get_or_create_default_org(db)
        org_id = default_org.id

    result = await db.execute(select(ScimToken).where(ScimToken.id == tid, ScimToken.org_id == org_id))
    token = result.scalar_one_or_none()
    if not token:
        raise HTTPException(status_code=404, detail="Token not found")

    token.active = False
    await db.commit()

    await emit_security_event(
        SecurityEvent(
            event_type=EventType.SETTING_CHANGED,
            severity=Severity.WARNING,
            outcome="success",
            actor_id=str(current_user.id),
            actor_email=current_user.email,
            actor_role=current_user.role.value,
            target_id=str(token.id),
            target_type="scim_token",
            detail="SCIM token revoked",
        )
    )
    return {"revoked": str(token.id)}
