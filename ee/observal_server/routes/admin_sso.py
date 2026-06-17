# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: LicenseRef-Observal-Enterprise

"""Admin endpoints for SAML config and SCIM token management."""

from __future__ import annotations

import logging
import secrets
import time
import uuid
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


import services.dynamic_settings as ds
from api.deps import get_db, get_or_create_default_org, require_role
from config import settings
from ee.observal_server.services.saml import (
    build_saml_settings,
    decrypt_private_key,
    encrypt_private_key,
    generate_sp_key_pair,
)
from ee.observal_server.services.scim_service import hash_scim_token
from models.saml_config import SamlConfig
from models.scim_token import ScimToken
from models.user import User, UserRole
from services.security_events import (
    EventType,
    SecurityEvent,
    Severity,
    emit_security_event,
)

logger = logging.getLogger("observal.ee.admin_sso")


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


def _normalize_cert(cert: str) -> str:
    """Strip PEM armor and whitespace so two cert encodings can be compared."""
    import re

    body = re.sub(r"-----(BEGIN|END) CERTIFICATE-----", "", cert or "")
    return re.sub(r"\s+", "", body)


async def _probe_oidc_client_secret(token_endpoint: str, redirect_uri: str) -> str | None:
    """Verify the client_secret by exchanging a deliberately-invalid code.

    A correct secret yields `invalid_grant` (the bogus code is rejected, but our
    credentials were accepted). A wrong secret yields `invalid_client`/401.
    Returns an error string on failure, or None if the secret is accepted.
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                token_endpoint,
                data={
                    "grant_type": "authorization_code",
                    "code": "observal_validate_invalid_code",
                    "redirect_uri": redirect_uri,
                    "client_id": settings.OAUTH_CLIENT_ID,
                    "client_secret": settings.OAUTH_CLIENT_SECRET,
                },
            )
        err = ""
        try:
            err = (resp.json().get("error") or "").lower()
        except Exception:
            pass
        if resp.status_code == 401 or err in ("invalid_client", "unauthorized_client"):
            return "The IdP rejected our client credentials — the client_secret is incorrect or the client is disabled."
        return None
    except Exception:
        # Network issues are surfaced by the authorization probe; don't double-fail here.
        return None


def _check_oidc_email_scope(metadata: dict) -> str | None:
    """Ensure the IdP advertises the email scope/claim that Observal needs for login."""
    scopes = [s.lower() for s in (metadata.get("scopes_supported") or [])]
    claims = [c.lower() for c in (metadata.get("claims_supported") or [])]
    if scopes and "email" not in scopes and "email" not in claims:
        return "The IdP does not advertise an 'email' scope or claim — Observal requires the user's email to create accounts."
    return None


async def _check_saml_idp_cert(configured_cert: str) -> str | None:
    """Compare the configured IdP cert against the IdP metadata signing cert(s).

    Only runs when `saml.idp_metadata_url` is set. Returns an error string if the
    configured cert matches nothing in the metadata, else None.
    """
    import re

    metadata_url = ds.get_sync("saml.idp_metadata_url", "")
    if not metadata_url:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(metadata_url)
            resp.raise_for_status()
            xml = resp.text
    except Exception:
        return None  # metadata not reachable — don't hard-fail on an optional check
    certs = re.findall(r"<[^>]*X509Certificate[^>]*>(.*?)</[^>]*X509Certificate>", xml, re.DOTALL)
    if not certs:
        return None
    norm_configured = _normalize_cert(configured_cert)
    if norm_configured and norm_configured not in [_normalize_cert(c) for c in certs]:
        return "The configured IdP X.509 certificate does not match any signing certificate in the IdP metadata — assertions will fail signature validation."
    return None


@router.post("/sso/validate-oidc")
async def validate_oidc(
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Validate OIDC/OAuth by simulating the exact authorization request the login makes.

    Hits the authorization endpoint with client_id, redirect_uri, scope — the same
    params the real flow uses. If the IdP returns an error (bad redirect_uri, disabled
    client, etc.) the validator catches it.
    """
    start = time.monotonic()

    if not settings.OAUTH_CLIENT_ID or not settings.OAUTH_CLIENT_SECRET:
        return {
            "success": False,
            "error": "OAUTH_CLIENT_ID or OAUTH_CLIENT_SECRET not configured",
            "hint": "Set OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET, and OAUTH_SERVER_METADATA_URL environment variables.",
        }

    metadata_url = settings.OAUTH_SERVER_METADATA_URL
    if not metadata_url:
        return {
            "success": False,
            "error": "OAUTH_SERVER_METADATA_URL not configured",
            "hint": "Set the OAUTH_SERVER_METADATA_URL environment variable to your IdP's .well-known/openid-configuration URL.",
        }

    # Step 1: Fetch discovery document
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(metadata_url)
            resp.raise_for_status()
            metadata = resp.json()
    except httpx.TimeoutException:
        return {
            "success": False,
            "error": f"Timeout fetching OIDC metadata from {metadata_url}",
            "hint": "The identity provider did not respond within 10 seconds.",
            "latency_ms": round((time.monotonic() - start) * 1000),
        }
    except httpx.HTTPStatusError as e:
        return {
            "success": False,
            "error": f"OIDC metadata endpoint returned HTTP {e.response.status_code}",
            "hint": f"Check that {metadata_url} is correct and accessible from the server.",
            "latency_ms": round((time.monotonic() - start) * 1000),
        }
    except Exception:
        logger.exception("validate_oidc: discovery fetch failed for %s", metadata_url)
        return {
            "success": False,
            "error": "Failed to fetch OIDC metadata",
            "hint": "Verify the OAUTH_SERVER_METADATA_URL is a valid URL reachable from this server. Check server logs for details.",
            "latency_ms": round((time.monotonic() - start) * 1000),
        }

    authorization_endpoint = metadata.get("authorization_endpoint")
    token_endpoint = metadata.get("token_endpoint")
    if not authorization_endpoint or not token_endpoint:
        return {
            "success": False,
            "error": "Missing authorization_endpoint or token_endpoint in discovery document",
            "hint": "The OIDC discovery document is incomplete. Verify your IdP configuration.",
            "latency_ms": round((time.monotonic() - start) * 1000),
        }

    # Step 2: Hit the authorization endpoint with the EXACT same redirect_uri the real
    # login flow uses. Don't follow redirects — we want to see what the IdP itself says.
    # A working config returns 302 (to login form). A broken config returns 400/error page.
    redirect_uri = (
        ds.get_sync("deployment.frontend_url", "http://localhost:3000").rstrip("/") + "/api/v1/auth/oauth/callback"
    )

    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            resp = await client.get(
                authorization_endpoint,
                params={
                    "client_id": settings.OAUTH_CLIENT_ID,
                    "redirect_uri": redirect_uri,
                    "response_type": "code",
                    "scope": "openid email profile groups",
                    "state": "observal_validate_probe",
                    "nonce": "observal_validate_nonce",
                },
            )

            # 3xx = redirect. To the IdP's own login page = accepted; back to our
            # redirect_uri carrying error=... = rejected.
            if resp.status_code in (301, 302, 303, 307, 308):
                if "error=" in resp.headers.get("location", ""):
                    return {
                        "success": False,
                        "error": "IdP returned an authorization error",
                        "hint": f"Ensure '{redirect_uri}' is registered as a redirect URI in your IdP and the client is enabled.",
                        "latency_ms": round((time.monotonic() - start) * 1000),
                    }
            # 200 = IdP rendered its hosted login form — params accepted. Do NOT scan the
            # body for "error"; every IdP login page contains that word in its JS/markup,
            # which produced false "rejected" results.
            elif resp.status_code == 200:
                pass
            # 400/401/403/etc = IdP explicitly rejected our request
            else:
                error_msg = f"IdP authorization endpoint returned HTTP {resp.status_code}"
                hint = f"Ensure '{redirect_uri}' is registered as a redirect URI in your IdP and the client is enabled."
                body_text = resp.text.lower()
                if "redirect_uri" in body_text or "redirect uri" in body_text:
                    error_msg = "IdP rejected the redirect_uri — it is not registered in the application"
                elif "invalid_client" in body_text:
                    error_msg = "IdP does not recognize this client_id"
                elif "unauthorized_client" in body_text:
                    error_msg = "Client is not authorized for this grant type"
                return {
                    "success": False,
                    "error": error_msg,
                    "hint": hint,
                    "latency_ms": round((time.monotonic() - start) * 1000),
                }
            # else: 3xx redirect to login form — params accepted, fall through to deeper checks
    except httpx.TimeoutException:
        return {
            "success": False,
            "error": "Timeout connecting to authorization endpoint",
            "hint": "The IdP did not respond. Check network connectivity.",
            "latency_ms": round((time.monotonic() - start) * 1000),
        }
    except Exception:
        logger.exception("validate_oidc: authorization endpoint probe failed")
        return {
            "success": False,
            "error": "Failed to reach authorization endpoint",
            "hint": "Check that the IdP is reachable from this server. Check server logs for details.",
            "latency_ms": round((time.monotonic() - start) * 1000),
        }

    # Step 3: Verify the client_secret by attempting a token exchange. The authorization
    # probe above never proves the secret is correct (that's only used at token time).
    secret_error = await _probe_oidc_client_secret(token_endpoint, redirect_uri)
    if secret_error:
        return {
            "success": False,
            "error": secret_error,
            "hint": "Check that OAUTH_CLIENT_SECRET matches the secret in your IdP application.",
            "latency_ms": round((time.monotonic() - start) * 1000),
        }

    # Step 4: Ensure the IdP advertises the email scope/claim Observal needs.
    scope_error = _check_oidc_email_scope(metadata)
    if scope_error:
        return {
            "success": False,
            "error": scope_error,
            "hint": "Enable the 'email' scope/claim for this application in your IdP.",
            "latency_ms": round((time.monotonic() - start) * 1000),
        }

    return {
        "success": True,
        "issuer": metadata.get("issuer"),
        "latency_ms": round((time.monotonic() - start) * 1000),
    }


@router.post("/sso/validate-saml")
async def validate_saml(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Validate SAML configuration by exercising the same code path as saml_login.

    This calls _get_saml_config, decrypts the SP key, and builds the OneLogin_Saml2_Auth
    object — the exact steps that fail with 500 if config is broken.
    """
    start = time.monotonic()

    from ee.observal_server.routes.sso_saml import _get_saml_config

    config = await _get_saml_config(db)
    if not config:
        return {
            "success": False,
            "error": "SAML is not configured",
            "hint": "Configure SAML via environment variables or the admin API.",
        }

    # Check required fields before attempting build
    errors = []
    if not getattr(config, "idp_entity_id", None):
        errors.append("IdP Entity ID is missing")
    if not getattr(config, "idp_sso_url", None):
        errors.append("IdP SSO URL is missing")
    if not getattr(config, "idp_x509_cert", None):
        errors.append("IdP X.509 certificate is missing")
    if not getattr(config, "sp_entity_id", None):
        errors.append("SP Entity ID is missing")
    if not getattr(config, "sp_acs_url", None):
        errors.append("SP ACS URL is missing")
    if not getattr(config, "sp_private_key_enc", None):
        errors.append("SP private key is missing")

    if errors:
        return {
            "success": False,
            "error": "; ".join(errors),
            "hint": "Complete the SAML configuration with all required fields.",
            "latency_ms": round((time.monotonic() - start) * 1000),
        }

    # Decrypt SP key — same as saml_login does
    try:
        sp_key = decrypt_private_key(
            config.sp_private_key_enc,
            ds.get_sync("saml.sp_key_encryption_password"),
        )
    except Exception:
        logger.exception("validate_saml: SP private key decryption failed")
        return {
            "success": False,
            "error": "Failed to decrypt SP private key",
            "hint": "Check SAML_SP_KEY_ENCRYPTION_PASSWORD is correct. See server logs for details.",
            "latency_ms": round((time.monotonic() - start) * 1000),
        }

    # Build the SAML auth object — this is where OneLogin validates settings and will
    # throw "idp_cert_or_fingerprint_not_found_and_required" if cert is bad
    try:
        from onelogin.saml2.auth import OneLogin_Saml2_Auth

        frontend_url = _get_frontend_url()
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

        sp_slo_url = ""
        if getattr(config, "idp_slo_url", ""):
            sp_slo_url = f"{frontend_url}/api/v1/sso/saml/sls"

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
    except Exception as e:
        # Classify the OneLogin exception locally without echoing its message into
        # the response (information-disclosure rule from CodeQL).
        msg_lower = str(e).lower()
        logger.exception("validate_saml: OneLogin settings build failed")
        if "idp_cert" in msg_lower:
            error_msg = "IdP X.509 certificate is missing or malformed"
            hint = "Re-import the IdP signing certificate from your identity provider."
        elif "sp" in msg_lower and "key" in msg_lower:
            error_msg = "SP private key or certificate is invalid"
            hint = "Regenerate the SP key pair from the admin SAML page."
        else:
            error_msg = "SAML settings validation failed"
            hint = "Check all SAML configuration values. See server logs for details."
        return {
            "success": False,
            "error": error_msg,
            "hint": hint,
            "latency_ms": round((time.monotonic() - start) * 1000),
        }

    # Try generating a login URL — this is what saml_login does last
    try:
        auth_obj.login(return_to="/")
    except Exception:
        logger.exception("validate_saml: AuthnRequest generation failed")
        return {
            "success": False,
            "error": "Failed to generate SAML AuthnRequest",
            "hint": "The SAML settings are valid but the login request could not be built. Check SP key and IdP SSO URL. See server logs for details.",
            "latency_ms": round((time.monotonic() - start) * 1000),
        }

    # Deeper check: if an IdP metadata URL is configured, confirm the stored signing
    # cert actually matches the IdP's current cert (catches silent cert rotations that
    # only surface as assertion-signature failures at the ACS step).
    cert_error = await _check_saml_idp_cert(config.idp_x509_cert)
    if cert_error:
        return {
            "success": False,
            "error": cert_error,
            "hint": "Re-import the IdP X.509 certificate from your identity provider's current metadata.",
            "latency_ms": round((time.monotonic() - start) * 1000),
        }

    latency_ms = round((time.monotonic() - start) * 1000)
    return {
        "success": True,
        "idp_entity_id": config.idp_entity_id,
        "latency_ms": latency_ms,
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
