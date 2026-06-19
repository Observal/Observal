# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: LicenseRef-Observal-Enterprise

"""Admin endpoints for SAML config and SCIM token management."""

from __future__ import annotations

import re
import secrets
import time
import uuid
from typing import TYPE_CHECKING
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger as optic
from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


import services.dynamic_settings as ds
from api.deps import get_db, get_or_create_default_org, require_role
from api.ratelimit import limiter
from config import settings
from ee.observal_server.routes.sso_saml import _get_saml_config, _run_saml_check_suite
from ee.observal_server.services.saml import (
    decrypt_private_key,
    encrypt_private_key,
    generate_sp_key_pair,
)
from ee.observal_server.services.scim_service import hash_scim_token
from models.saml_config import SamlConfig
from models.scim_token import ScimToken
from models.user import User, UserRole
from schemas.sso_health import all_pass, make_check
from services import sso_diagnostics
from services.oidc_health import run_oidc_checks
from services.security_events import (
    EventType,
    SecurityEvent,
    Severity,
    emit_security_event,
)

_SAML_HEALTH_TIMEOUT = 10.0


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


def _required_field_check(config) -> dict | None:
    """Return a failing check dict if any required SAML field is empty, else None."""
    missing = [
        pretty
        for attr, pretty in (
            ("idp_entity_id", "IdP Entity ID"),
            ("idp_sso_url", "IdP SSO URL"),
            ("idp_x509_cert", "IdP X.509 certificate"),
            ("sp_entity_id", "SP Entity ID"),
            ("sp_acs_url", "SP ACS URL"),
            ("sp_private_key_enc", "SP private key"),
        )
        if not getattr(config, attr, None)
    ]
    if not missing:
        return None
    return make_check(
        "required_fields",
        "Required SAML fields populated",
        "fail",
        f"Missing: {'; '.join(missing)}.",
        "Complete the SAML configuration with all required fields.",
    )


@router.post("/sso/validate-saml")
async def validate_saml(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Validate SAML configuration end-to-end and return per-check diagnostics.

    Note: server-side validation cannot replay a signed assertion, so a green
    result still depends on a real user login. NameIDFormat and signing-cert
    rotation are only visible if ``saml.idp_metadata_url`` is configured.
    """
    optic.info("admin.validate_saml start")
    start = time.monotonic()

    config = await _get_saml_config(db)
    if not config:
        return {
            "success": False,
            "error": "SAML is not configured",
            "hint": "Configure SAML via environment variables or the admin API.",
            "checks": [],
        }

    field_failure = _required_field_check(config)
    if field_failure is not None:
        return {
            "success": False,
            "error": field_failure["message"],
            "hint": field_failure["hint"],
            "checks": [field_failure],
            "latency_ms": round((time.monotonic() - start) * 1000),
        }

    # NOTE: keep the return *outside* the except clause so CodeQL doesn't
    # taint the static response with the exception's stack trace.
    sp_key: str | None = None
    try:
        sp_key = decrypt_private_key(
            config.sp_private_key_enc,
            ds.get_sync("saml.sp_key_encryption_password"),
        )
    except Exception:
        optic.exception("admin.validate_saml SP key decrypt failed")
    if sp_key is None:
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
    async with httpx.AsyncClient(timeout=_SAML_HEALTH_TIMEOUT, follow_redirects=False) as client:
        checks = await _run_saml_check_suite(config, sp_key, frontend_url, client)
    checks.insert(0, make_check("sp_key_decrypt", "SP private key decrypts", "pass"))
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


# ── SSO End-to-End Test ───────────────────────────────────
#
# These endpoints run the real login flow against the real IdP -- the only
# step that isn't automated is the user typing credentials at the IdP. Every
# other step (token exchange, signature/audience validation, claim extraction,
# user lookup) is recorded as a pass/fail check so the operator sees exactly
# where the flow breaks.
#
# Critically, the e2e callback / ACS handlers:
#   * never issue a JWT or auth cookie
#   * never JIT-create a user (read-only DB lookup only)
#   * never count as a real login in security events
#
# So an admin can run the test repeatedly without polluting state.

_E2E_HTTP_TIMEOUT = 15.0


@router.post("/sso/e2e/oidc/start")
@limiter.limit(ds.get_sync("security.rate_limit_sso_health", "10/minute"))
async def e2e_oidc_start(
    request: Request,
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Begin an OIDC end-to-end test. Returns the IdP authorize URL.

    Runs the full validator suite first. If any check fails -- discovery
    unreachable, client_id wrong, redirect_uri not whitelisted, scope missing,
    signing alg unsupported -- we abort with the diagnostics *before* sending
    the operator to the IdP. The IdP would just show its own error page and
    never redirect back, leaving the admin tab polling forever.
    """
    if not settings.OAUTH_CLIENT_ID or not settings.OAUTH_SERVER_METADATA_URL:
        return {
            "success": False,
            "error": "OIDC is not configured on the server",
            "hint": "Set OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET, and OAUTH_SERVER_METADATA_URL.",
            "checks": [
                make_check(
                    "oidc_configured",
                    "OIDC client configured on server",
                    "fail",
                    "OAUTH_CLIENT_ID / OAUTH_CLIENT_SECRET / OAUTH_SERVER_METADATA_URL not set.",
                    "Configure OIDC in environment and restart the API.",
                ),
            ],
        }

    redirect_uri = (
        ds.get_sync("deployment.frontend_url", "http://localhost:3000").rstrip("/") + "/api/v1/auth/oauth/callback"
    )

    # ── Pre-flight: run the full validator suite. ────────────────────────
    # Every check the admin "Validate" button runs, plus a redirect_uri probe
    # against this specific URL, runs here. If anything fails we never send
    # the operator to the IdP -- we just show them what to fix.
    preflight_checks, metadata = await run_oidc_checks(
        settings.OAUTH_SERVER_METADATA_URL,
        settings.OAUTH_CLIENT_ID,
        settings.OAUTH_CLIENT_SECRET,
        redirect_uri,
    )
    if not all_pass(preflight_checks):
        first_fail = next((c for c in preflight_checks if c.get("status") == "fail"), None)
        optic.info(
            "admin.e2e_oidc_start preflight failed -- first={}",
            first_fail.get("name") if first_fail else "?",
        )
        return {
            "success": False,
            "error": (first_fail or {}).get("message") or "OIDC pre-flight checks failed",
            "hint": (first_fail or {}).get("hint"),
            "checks": preflight_checks,
        }
    if metadata is None:
        # All checks passed but metadata is None -- defensive fallback.
        return {
            "success": False,
            "error": "OIDC discovery document missing despite passing probes",
            "checks": preflight_checks,
        }

    authz_endpoint = metadata.get("authorization_endpoint")
    if not authz_endpoint:
        return {
            "success": False,
            "error": "Discovery document is missing authorization_endpoint",
            "checks": preflight_checks,
        }

    # ── Pre-flight passed. Now stage the e2e session. ────────────────────
    session_id, session = await sso_diagnostics.create_session("oidc", "e2e")
    session["nonce"] = secrets.token_urlsafe(24)
    session["authorization_endpoint"] = authz_endpoint
    session["token_endpoint"] = metadata.get("token_endpoint")
    session["jwks_uri"] = metadata.get("jwks_uri")
    session["issuer"] = metadata.get("issuer")
    # Seed the session with the preflight pass-list so the close-tab page
    # shows the full story (preflight + live login round-trip).
    initial_checks = [
        *preflight_checks,
        make_check("e2e_started", "End-to-end test initiated by admin", "pass"),
    ]
    await sso_diagnostics.finalize(session_id, checks=initial_checks)
    full = await sso_diagnostics.get_session(session_id)
    if full is not None:
        full.update(
            {
                "nonce": session["nonce"],
                "authorization_endpoint": authz_endpoint,
                "token_endpoint": metadata.get("token_endpoint"),
                "jwks_uri": metadata.get("jwks_uri"),
                "issuer": metadata.get("issuer"),
                "finished_at": None,
                "ok": None,
            }
        )
        await sso_diagnostics.save_session(full)

    state = f"__e2e:{session_id}"
    params = {
        "response_type": "code",
        "client_id": settings.OAUTH_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": "openid email profile groups",
        "state": state,
        "nonce": session["nonce"],
    }
    login_url = f"{authz_endpoint}?{urlencode(params)}"
    optic.info("admin.e2e_oidc_start session_id={} issuer={}", session_id, metadata.get("issuer"))
    return {
        "success": True,
        "session_id": session_id,
        "login_url": login_url,
        "redirect_uri": redirect_uri,
        "issuer": metadata.get("issuer"),
        "checks": preflight_checks,
        "instructions": (
            "Open the login URL in a new tab and authenticate with a real (test) user. "
            "The result will appear here once the IdP redirects back."
        ),
    }


@router.post("/sso/e2e/saml/start")
@limiter.limit(ds.get_sync("security.rate_limit_sso_health", "10/minute"))
async def e2e_saml_start(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Begin a SAML end-to-end test. Returns the SP-initiated login URL.

    Runs the full validator suite first so common misconfig (missing SP
    cert, cert/key mismatch, IdP SSO URL unreachable, NameIDFormat mismatch)
    surfaces before we send the operator to the IdP. The IdP would otherwise
    show its own error page and never POST the assertion back, leaving the
    admin tab polling forever.
    """
    config = await _get_saml_config(db)
    if not config:
        return {
            "success": False,
            "error": "SAML is not configured",
            "hint": "Configure SAML via environment variables or the admin API.",
            "checks": [
                make_check(
                    "saml_configured",
                    "SAML SSO is configured on server",
                    "fail",
                    "No SAML config found in DB or environment.",
                    "Configure SAML in the admin panel or via SAML_* env vars.",
                ),
            ],
        }

    # ── Pre-flight: required fields + full check suite. ──────────────────
    field_failure = _required_field_check(config)
    if field_failure is not None:
        return {
            "success": False,
            "error": field_failure["message"],
            "hint": field_failure["hint"],
            "checks": [field_failure],
        }

    sp_key: str | None = None
    try:
        sp_key = decrypt_private_key(
            config.sp_private_key_enc,
            ds.get_sync("saml.sp_key_encryption_password"),
        )
    except Exception:
        optic.exception("admin.e2e_saml_start SP key decrypt failed")
    if sp_key is None:
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
                ),
            ],
        }

    frontend_url = _get_frontend_url()
    async with httpx.AsyncClient(timeout=_SAML_HEALTH_TIMEOUT, follow_redirects=False) as client:
        preflight_checks = await _run_saml_check_suite(config, sp_key, frontend_url, client)
    preflight_checks.insert(0, make_check("sp_key_decrypt", "SP private key decrypts", "pass"))
    if not all_pass(preflight_checks):
        first_fail = next((c for c in preflight_checks if c.get("status") == "fail"), None)
        optic.info(
            "admin.e2e_saml_start preflight failed -- first={}",
            first_fail.get("name") if first_fail else "?",
        )
        return {
            "success": False,
            "error": (first_fail or {}).get("message") or "SAML pre-flight checks failed",
            "hint": (first_fail or {}).get("hint"),
            "checks": preflight_checks,
        }

    session_id, _ = await sso_diagnostics.create_session("saml", "e2e")
    initial_checks = [
        *preflight_checks,
        make_check("e2e_started", "End-to-end test initiated by admin", "pass"),
    ]
    await sso_diagnostics.finalize(session_id, checks=initial_checks)
    full = await sso_diagnostics.get_session(session_id)
    if full is not None:
        full["finished_at"] = None
        full["ok"] = None
        await sso_diagnostics.save_session(full)

    base = ds.get_sync("deployment.frontend_url", "http://localhost:3000").rstrip("/")
    login_url = f"{base}/api/v1/sso/saml/login?e2e={session_id}"
    optic.info("admin.e2e_saml_start session_id={}", session_id)
    return {
        "success": True,
        "session_id": session_id,
        "login_url": login_url,
        "idp_entity_id": getattr(config, "idp_entity_id", None),
        "checks": preflight_checks,
        "instructions": (
            "Open the login URL in a new tab and authenticate with a real (test) user. "
            "The result will appear here once the IdP posts the assertion back."
        ),
    }


@router.get("/sso/e2e/status/{session_id}")
async def e2e_status(
    session_id: str,
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Poll an end-to-end test session. Returns checks, ok, actor_email."""
    if not session_id or len(session_id) > 64 or not re.fullmatch(r"[A-Za-z0-9_\-]+", session_id):
        raise HTTPException(status_code=400, detail="Invalid session id")
    session = await sso_diagnostics.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    return sso_diagnostics.public_view(session)


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
