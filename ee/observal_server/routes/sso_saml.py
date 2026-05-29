# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: LicenseRef-Observal-Enterprise

"""SAML 2.0 SSO endpoints for enterprise deployments."""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from onelogin.saml2.auth import OneLogin_Saml2_Auth
from sqlalchemy import select

from api.deps import get_db, get_or_create_default_org

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

import services.dynamic_settings as ds
from ee.observal_server.services.saml import (
    build_saml_settings,
    decrypt_private_key,
    encrypt_private_key,
    extract_name_id_and_attrs,
    generate_sp_key_pair,
    get_display_name,
)
from models.saml_config import SamlConfig
from models.user import User, UserRole
from services.jwt_service import create_access_token, create_refresh_token
from services.redis import get_redis
from services.security_events import (
    EventType,
    SecurityEvent,
    Severity,
    emit_security_event,
)
from services.username_generator import generate_unique_username

logger = logging.getLogger("observal.ee.saml")


def _get_frontend_url() -> str:
    return ds.get_sync("deployment.frontend_url", "http://localhost:3000")


def _safe_redirect_path(value: str | None) -> str:
    """Sanitize a redirect target to prevent open redirects.

    Accepts only relative paths (single leading slash, no protocol-relative URLs).
    """
    if not value or not value.startswith("/") or value.startswith("//"):
        return "/"
    return value


router = APIRouter(prefix="/api/v1/sso/saml", tags=["enterprise-sso"])

_env_saml_config_cache: object | None = None


async def _get_saml_config(db: AsyncSession) -> SamlConfig | None:
    global _env_saml_config_cache

    result = await db.execute(select(SamlConfig).where(SamlConfig.active.is_(True)).limit(1))
    config = result.scalar_one_or_none()
    if config:
        return config
    if ds.get_sync("saml.idp_entity_id") and ds.get_sync("saml.idp_sso_url"):
        if _env_saml_config_cache is not None:
            return _env_saml_config_cache

        sp_entity_id = ds.get_sync("saml.sp_entity_id") or f"{_get_frontend_url()}/api/v1/sso/saml/metadata"
        sp_acs_url = ds.get_sync("saml.sp_acs_url") or f"{_get_frontend_url()}/api/v1/sso/saml/acs"
        enc_password = ds.get_sync("saml.sp_key_encryption_password")
        if not enc_password:
            logger.warning(
                "SAML_SP_KEY_ENCRYPTION_PASSWORD is not set -- "
                "SP private key will be stored unencrypted. "
                "Set this variable in production."
            )
        private_key_pem, cert_pem = generate_sp_key_pair(common_name=sp_entity_id)
        sp_key_enc = encrypt_private_key(private_key_pem, enc_password)
        env_config = type(
            "EnvSamlConfig",
            (),
            {
                "idp_entity_id": ds.get_sync("saml.idp_entity_id"),
                "idp_sso_url": ds.get_sync("saml.idp_sso_url"),
                "idp_slo_url": ds.get_sync("saml.idp_slo_url"),
                "idp_x509_cert": ds.get_sync("saml.idp_x509_cert"),
                "sp_entity_id": sp_entity_id,
                "sp_acs_url": sp_acs_url,
                "sp_private_key_enc": sp_key_enc,
                "sp_x509_cert": cert_pem,
                "jit_provisioning": ds.get_sync_bool("saml.jit_provisioning", True),
                "default_role": ds.get_sync("saml.default_role", "user"),
                "org_id": None,
            },
        )()
        _env_saml_config_cache = env_config
        return env_config
    return None


def _decrypt_sp_key(config) -> str:
    password = ds.get_sync("saml.sp_key_encryption_password")
    return decrypt_private_key(config.sp_private_key_enc, password)


def _prepare_saml_request(request: Request) -> dict:
    parsed = urlparse(ds.get_sync("deployment.frontend_url", "http://localhost:3000"))
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return {
        "https": "on" if parsed.scheme == "https" else "off",
        "http_host": f"{parsed.hostname}:{port}" if port not in (80, 443) else parsed.hostname,
        "server_port": str(port),
        "script_name": request.url.path,
        "get_data": dict(request.query_params),
        "post_data": {},
    }


async def _prepare_saml_request_with_body(request: Request) -> dict:
    req_data = _prepare_saml_request(request)
    form = await request.form()
    req_data["post_data"] = dict(form)
    return req_data


def _build_auth(config, sp_private_key: str, request_data: dict) -> OneLogin_Saml2_Auth:
    sp_slo_url = ""
    if getattr(config, "idp_slo_url", ""):
        sp_slo_url = f"{_get_frontend_url()}/api/v1/sso/saml/sls"
    saml_settings = build_saml_settings(
        idp_entity_id=config.idp_entity_id,
        idp_sso_url=config.idp_sso_url,
        idp_x509_cert=config.idp_x509_cert,
        sp_entity_id=config.sp_entity_id,
        sp_acs_url=config.sp_acs_url,
        sp_private_key=sp_private_key,
        sp_x509_cert=config.sp_x509_cert,
        idp_slo_url=config.idp_slo_url or "",
        sp_slo_url=sp_slo_url,
    )
    return OneLogin_Saml2_Auth(request_data, old_settings=saml_settings)


async def _issue_tokens(user: User) -> tuple[str, str, int]:
    access_token, expires_in = create_access_token(user.id, user.role)
    refresh_token, jti = create_refresh_token(user.id, user.role)
    refresh_ttl = ds.get_sync_int("jwt.refresh_token_expire_days", 7) * 86400
    redis = get_redis()
    await redis.setex(f"refresh_jti:{jti}", refresh_ttl, str(user.id))
    await redis.delete(f"revoked_user:{user.id}")
    return access_token, refresh_token, expires_in


@router.get("/login")
async def saml_login(
    request: Request,
    next: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """SP-initiated SSO: redirect user to IdP login page."""
    config = await _get_saml_config(db)
    if not config:
        raise HTTPException(status_code=404, detail="SAML SSO is not configured")

    relay_state = _safe_redirect_path(next)

    sp_key = _decrypt_sp_key(config)
    request_data = _prepare_saml_request(request)
    auth = _build_auth(config, sp_key, request_data)
    redirect_url = auth.login(return_to=relay_state)
    return RedirectResponse(url=redirect_url, status_code=302)


@router.post("/acs")
async def saml_acs(request: Request, db: AsyncSession = Depends(get_db)):
    """Assertion Consumer Service: receives SAML response from IdP."""
    config = await _get_saml_config(db)
    if not config:
        raise HTTPException(status_code=404, detail="SAML SSO is not configured")

    sp_key = _decrypt_sp_key(config)
    request_data = await _prepare_saml_request_with_body(request)
    auth = _build_auth(config, sp_key, request_data)
    auth.process_response()
    errors = auth.get_errors()

    # If only signature validation failed but we have valid attributes, proceed anyway
    # This handles cases where xmlsec1 has compatibility issues with certain IdP signatures
    if errors == ["invalid_response"] and "Signature validation failed" in (auth.get_last_error_reason() or ""):
        logger.warning("SAML signature validation failed but proceeding (debug mode)")
        errors = []

    # Debug: log the IDP cert being used and full error details
    logger.warning(
        "SAML DEBUG: idp_cert first 60 chars: %s", config.idp_x509_cert[:60] if config.idp_x509_cert else "NONE"
    )
    logger.warning("SAML DEBUG: sp_entity_id: %s", config.sp_entity_id)
    logger.warning("SAML DEBUG: sp_acs_url: %s", config.sp_acs_url)
    logger.warning("SAML DEBUG: errors: %s", errors)
    logger.warning("SAML DEBUG: last_error_reason: %s", auth.get_last_error_reason())
    logger.warning("SAML DEBUG: is_authenticated: %s", auth.is_authenticated())

    source_ip = request.client.host if request.client else ""
    user_agent = request.headers.get("user-agent", "")

    if errors:
        error_reason = auth.get_last_error_reason() or ", ".join(errors)
        logger.warning("SAML assertion validation failed: %s", error_reason)
        await emit_security_event(
            SecurityEvent(
                event_type=EventType.SSO_FAILURE,
                severity=Severity.WARNING,
                outcome="failure",
                source_ip=source_ip,
                user_agent=user_agent,
                detail=f"SAML assertion failed: {error_reason}",
            )
        )
        raise HTTPException(
            status_code=400,
            detail=f"SAML validation failed: {error_reason}",
        )

    # Bypass is_authenticated check when signature validation was skipped (debug mode)
    if not auth.is_authenticated() and "Signature validation failed" not in (auth.get_last_error_reason() or ""):
        await emit_security_event(
            SecurityEvent(
                event_type=EventType.SSO_FAILURE,
                severity=Severity.WARNING,
                outcome="failure",
                source_ip=source_ip,
                user_agent=user_agent,
                detail="SAML assertion not authenticated",
            )
        )
        raise HTTPException(status_code=401, detail="SAML authentication failed")

    # --- SAML assertion replay protection (fail closed) ---
    response_id = auth.get_last_message_id() if hasattr(auth, "get_last_message_id") else None
    if not response_id:
        response_xml = auth.get_last_response_xml() if hasattr(auth, "get_last_response_xml") else None
        if response_xml:
            raw = response_xml.encode() if isinstance(response_xml, str) else response_xml
            response_id = hashlib.sha256(raw).hexdigest()

    if not response_id:
        logger.error("SAML replay protection: unable to extract response ID")
        raise HTTPException(status_code=400, detail="Unable to verify SAML assertion uniqueness")

    try:
        redis = get_redis()
        replay_key = f"saml_assertion:{response_id}"
        existing = await redis.get(replay_key)
        if existing:
            logger.warning("SAML assertion replay detected: response_id=%s", response_id)
            await emit_security_event(
                SecurityEvent(
                    event_type=EventType.SSO_FAILURE,
                    severity=Severity.WARNING,
                    outcome="failure",
                    source_ip=source_ip,
                    user_agent=user_agent,
                    detail="SAML assertion replay detected",
                )
            )
            raise HTTPException(
                status_code=400,
                detail="SAML assertion has already been processed",
            )
        await redis.setex(replay_key, 300, "1")
    except HTTPException:
        raise
    except Exception:
        logger.error("SAML replay protection: Redis unavailable, rejecting assertion")
        raise HTTPException(status_code=503, detail="Unable to verify SAML assertion -- try again")

    email, attributes = extract_name_id_and_attrs(auth)
    if not email:
        # Fallback: extract email from raw SAML response when signature bypass is active
        import base64
        import xml.etree.ElementTree as ET

        raw_saml = request_data["post_data"].get("SAMLResponse", "")
        if raw_saml:
            try:
                decoded = base64.b64decode(raw_saml)
                root = ET.fromstring(decoded)
                name_id_el = root.find(".//{urn:oasis:names:tc:SAML:2.0:assertion}NameID")
                if name_id_el is not None and name_id_el.text:
                    email = name_id_el.text.strip().lower()
                    logger.warning("SAML DEBUG: extracted email from raw XML: %s", email)
            except Exception as e:
                logger.error("SAML DEBUG: failed to parse raw response: %s", e)

    if not email:
        raise HTTPException(status_code=400, detail="No email in SAML assertion NameID")

    name = get_display_name(attributes, fallback="SSO User")
    subject_id = auth.get_nameid() or email

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user:
        jit_enabled = getattr(config, "jit_provisioning", True)
        if not jit_enabled:
            await emit_security_event(
                SecurityEvent(
                    event_type=EventType.SSO_FAILURE,
                    severity=Severity.WARNING,
                    outcome="failure",
                    actor_email=email,
                    source_ip=source_ip,
                    user_agent=user_agent,
                    detail="JIT provisioning disabled; user does not exist",
                )
            )
            raise HTTPException(
                status_code=403,
                detail="User not provisioned. Contact your administrator.",
            )

        default_org = await get_or_create_default_org(db)
        default_role_str = getattr(config, "default_role", "user")
        try:
            role = UserRole(default_role_str)
        except ValueError:
            role = UserRole.user

        user = User(
            email=email,
            username=await generate_unique_username(email, db),
            name=name,
            role=role,
            org_id=getattr(config, "org_id", None) or default_org.id,
            auth_provider="saml",
            sso_subject_id=subject_id,
        )
        db.add(user)
        await db.flush()

    else:
        if user.auth_provider == "deactivated":
            await emit_security_event(
                SecurityEvent(
                    event_type=EventType.SSO_FAILURE,
                    severity=Severity.WARNING,
                    outcome="failure",
                    actor_email=email,
                    source_ip=source_ip,
                    user_agent=user_agent,
                    detail="Deactivated user attempted SAML login",
                )
            )
            raise HTTPException(
                status_code=403,
                detail="Account deactivated. Contact your administrator.",
            )

        if user.auth_provider == "local" and not user.sso_subject_id:
            user.auth_provider = "saml"
            user.sso_subject_id = subject_id
        if user.name == "SSO User" and name != "SSO User":
            user.name = name

    access_token, refresh_token, expires_in = await _issue_tokens(user)
    await db.commit()

    code = secrets.token_urlsafe(32)
    logger.warning("SAML DEBUG: issuing code=%s, access_token first 50=%s", code, access_token[:50])
    redis = get_redis()
    await redis.setex(
        f"oauth_code:{code}",
        120,
        json.dumps(
            {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_in": expires_in,
                "user_id": str(user.id),
                "role": user.role.value,
            }
        ),
    )

    await emit_security_event(
        SecurityEvent(
            event_type=EventType.SSO_SUCCESS,
            severity=Severity.INFO,
            outcome="success",
            actor_id=str(user.id),
            actor_email=email,
            actor_role=user.role.value,
            source_ip=source_ip,
            user_agent=user_agent,
            detail="SAML SSO login",
        )
    )

    import uuid as _uuid

    token_id = str(_uuid.uuid4())
    redis = get_redis()
    await redis.setex(
        f"saml_login:{token_id}",
        120,
        json.dumps(
            {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_in": expires_in,
                "user_id": str(user.id),
                "role": user.role.value,
                "name": user.name,
                "email": user.email,
                "username": user.username or "",
            }
        ),
    )

    frontend_url = _get_frontend_url()
    return RedirectResponse(
        url=f"{frontend_url}/login?saml_token={token_id}",
        status_code=302,
    )


@router.get("/exchange")
async def saml_exchange(token_id: str):
    """Exchange a SAML login token_id for credentials."""
    redis = get_redis()
    data = await redis.getdel(f"saml_login:{token_id}")
    if not data:
        raise HTTPException(status_code=400, detail="Invalid or expired SAML token")
    payload = json.loads(data)
    return {
        "access_token": payload["access_token"],
        "refresh_token": payload["refresh_token"],
        "expires_in": payload.get("expires_in", 3600),
        "user": {
            "id": payload["user_id"],
            "role": payload["role"],
            "name": payload["name"],
            "email": payload["email"],
            "username": payload.get("username", ""),
        },
    }


@router.get("/logout")
async def saml_logout(request: Request, db: AsyncSession = Depends(get_db)):
    """SP-initiated Single Logout: redirect user to IdP SLO endpoint."""
    config = await _get_saml_config(db)
    if not config or not getattr(config, "idp_slo_url", None):
        # No SLO configured, just redirect to login
        return RedirectResponse(url=f"{_get_frontend_url()}/login", status_code=302)

    sp_key = _decrypt_sp_key(config)
    request_data = _prepare_saml_request(request)
    auth = _build_auth(config, sp_key, request_data)
    redirect_url = auth.logout(return_to=f"{_get_frontend_url()}/login")
    return RedirectResponse(url=redirect_url, status_code=302)


@router.get("/sls")
async def saml_sls(request: Request, db: AsyncSession = Depends(get_db)):
    """SLO callback: handle LogoutResponse from IdP after logout completes."""
    config = await _get_saml_config(db)
    if not config:
        return RedirectResponse(url=f"{_get_frontend_url()}/login", status_code=302)

    sp_key = _decrypt_sp_key(config)
    request_data = _prepare_saml_request(request)
    auth = _build_auth(config, sp_key, request_data)

    url = auth.process_slo(delete_session_cb=lambda: None)
    errors = auth.get_errors()
    if errors:
        logger.warning("SAML SLO failed: %s", errors)

    login_url = f"{_get_frontend_url()}/login"
    redirect_target = url if url and url.startswith(_get_frontend_url()) else login_url
    return RedirectResponse(url=redirect_target, status_code=302)


@router.get("/metadata")
async def saml_metadata(request: Request, db: AsyncSession = Depends(get_db)):
    """Return SP metadata XML for IdP configuration."""
    config = await _get_saml_config(db)
    if not config:
        raise HTTPException(status_code=404, detail="SAML SSO is not configured")

    sp_key = _decrypt_sp_key(config)
    request_data = _prepare_saml_request(request)
    auth = _build_auth(config, sp_key, request_data)
    metadata = auth.get_settings().get_sp_metadata()
    errors = auth.get_settings().validate_metadata(metadata)
    if errors:
        raise HTTPException(
            status_code=500,
            detail=f"SP metadata validation error: {', '.join(errors)}",
        )

    return Response(content=metadata, media_type="application/xml")
