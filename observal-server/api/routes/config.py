# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Request
from loguru import logger as optic
from sqlalchemy import select

from api.deps import get_db
from config import HAS_LICENSE, settings
from models.enterprise_config import EnterpriseConfig
from schemas.ide_registry import IDE_REGISTRY
from version import get_server_version

router = APIRouter(prefix="/api/v1/config", tags=["config"])


@router.get("/version")
async def get_version():
    """Server version and compatibility info. No auth required.

    The server_version is the canonical target: CLI and frontend must match it.
    """
    optic.debug("config.get_version called")
    import services.dynamic_settings as ds

    max_cli = await ds.get("misc.max_cli_version")
    api_version = await ds.get("misc.api_version")
    frontend_version = await ds.get("misc.frontend_version")

    server_ver = get_server_version()
    return {
        "server_version": server_ver,
        "max_cli_version": max_cli or None,
        "api_version": api_version or None,
        "frontend_version": frontend_version or server_ver,
        # Deprecated: kept for backward compat with CLIs < 1.0.0. Will be removed in 1.2.0.
        "recommended_cli_version": server_ver,
    }


async def derive_endpoints(request: Request | None = None) -> dict[str, str]:
    """Derive all endpoint URLs from settings, falling back to request context."""
    optic.debug("derive_endpoints called")
    import services.dynamic_settings as ds

    public_url_setting = await ds.get("deployment.public_url")
    public_url = public_url_setting.rstrip("/") if public_url_setting else ""
    if not public_url and request:
        public_url = str(request.base_url).rstrip("/")
    if not public_url:
        public_url = "http://localhost:8000"

    parsed = urlparse(public_url)
    hostname = parsed.hostname or "localhost"
    scheme = parsed.scheme or ("http" if hostname in ("localhost", "127.0.0.1") else "https")

    frontend_setting = await ds.get("deployment.frontend_url")
    web = frontend_setting.rstrip("/") if frontend_setting else f"{scheme}://{hostname}:3000"

    return {
        "api": public_url,
        "web": web,
    }


@router.get("/endpoints")
async def get_endpoints(request: Request):
    """Endpoint discovery: returns all service URLs. No auth required."""
    optic.debug("config.derive_endpoints called")
    return await derive_endpoints(request)


@router.get("/public")
async def get_public_config(db=Depends(get_db)):
    """Public configuration for frontend. No auth required."""
    optic.debug("config.get_public_config called")
    import services.dynamic_settings as ds

    # Deployment mode derived from license presence
    licensed = HAS_LICENSE

    # SAML: check DB-backed dynamic settings, then fall back to SamlConfig model
    saml_idp_entity = await ds.get("saml.idp_entity_id")
    saml_idp_sso = await ds.get("saml.idp_sso_url")
    saml_enabled = bool(saml_idp_entity and saml_idp_sso)

    if not saml_enabled and HAS_LICENSE:
        try:
            from models.saml_config import SamlConfig

            result = await db.execute(select(SamlConfig).where(SamlConfig.active.is_(True)).limit(1))
            saml_enabled = result.scalar_one_or_none() is not None
        except Exception:
            pass

    branding_logo = None
    branding_app_name = None
    branding_wordmark = None
    try:
        result = await db.execute(
            select(EnterpriseConfig).where(
                EnterpriseConfig.key.in_(["branding.logo", "branding.app_name", "branding.wordmark"])
            )
        )
        for cfg in result.scalars().all():
            if cfg.key == "branding.logo" and cfg.value:
                branding_logo = cfg.value
            elif cfg.key == "branding.app_name" and cfg.value:
                branding_app_name = cfg.value
            elif cfg.key == "branding.wordmark" and cfg.value:
                branding_wordmark = cfg.value
    except Exception:
        pass

    # Feature availability
    from services.insights import licensed_features as _get_licensed

    licensed_features: list[str] = _get_licensed()
    exec_dashboard_available = "all" in licensed_features or "exec_dashboard" in licensed_features

    sso_only = await ds.get_bool("deployment.sso_only")

    return {
        "licensed": licensed,
        "sso_enabled": bool(settings.OAUTH_CLIENT_ID),
        "sso_only": sso_only,
        "saml_enabled": saml_enabled,
        "exec_dashboard_available": exec_dashboard_available,
        "licensed_features": licensed_features,
        "branding_logo": branding_logo,
        "branding_app_name": branding_app_name,
        "branding_wordmark": branding_wordmark,
    }


@router.get("/sso-health")
async def sso_health(db=Depends(get_db)):
    """Public (unauthenticated) SSO health check for the login page.

    Exercises the same code paths as the real login — hits the IdP authorization
    endpoint with the real redirect_uri (OIDC) and builds the OneLogin auth object
    (SAML). If these succeed, the login button will work.
    """
    import time

    import httpx

    import services.dynamic_settings as ds_mod

    result = {"oidc": None, "saml": None}

    # ── OIDC: probe the authorization endpoint with real params ──
    if settings.OAUTH_CLIENT_ID and settings.OAUTH_SERVER_METADATA_URL:
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
                resp = await client.get(settings.OAUTH_SERVER_METADATA_URL)
                resp.raise_for_status()
                metadata = resp.json()
                authz_endpoint = metadata.get("authorization_endpoint")
                token_endpoint = metadata.get("token_endpoint")
                if not authz_endpoint:
                    result["oidc"] = {"ok": False, "error": "Missing authorization_endpoint in discovery"}
                else:
                    redirect_uri = (
                        ds_mod.get_sync("deployment.frontend_url", "http://localhost:3000").rstrip("/")
                        + "/api/v1/auth/oauth/callback"
                    )
                    ar = await client.get(
                        authz_endpoint,
                        params={
                            "client_id": settings.OAUTH_CLIENT_ID,
                            "redirect_uri": redirect_uri,
                            "response_type": "code",
                            "scope": "openid email profile groups",
                            "state": "observal_health_probe",
                            "nonce": "observal_health_nonce",
                        },
                    )
                    authz_ok = False
                    if ar.status_code in (301, 302, 303, 307, 308):
                        # A redirect to the IdP's own login page = accepted. A redirect that
                        # carries an OAuth error back to our redirect_uri = rejected.
                        location = ar.headers.get("location", "")
                        if "error=" in location:
                            result["oidc"] = {
                                "ok": False,
                                "error": "IdP returned an authorization error (check redirect URI / client config)",
                            }
                        else:
                            authz_ok = True
                    elif ar.status_code == 200:
                        # IdP rendered its hosted login form — params accepted. (Don't scan the
                        # body for "error"; every login page contains that word in its JS.)
                        authz_ok = True
                    else:
                        result["oidc"] = {
                            "ok": False,
                            "error": f"Authorization endpoint returned HTTP {ar.status_code}",
                        }

                    if authz_ok:
                        # client_secret correctness: exchange a bogus code; invalid_client/401 ⇒ wrong secret
                        secret_ok = True
                        if token_endpoint and settings.OAUTH_CLIENT_SECRET:
                            try:
                                tr = await client.post(
                                    token_endpoint,
                                    data={
                                        "grant_type": "authorization_code",
                                        "code": "observal_health_invalid_code",
                                        "redirect_uri": redirect_uri,
                                        "client_id": settings.OAUTH_CLIENT_ID,
                                        "client_secret": settings.OAUTH_CLIENT_SECRET,
                                    },
                                )
                                terr = ""
                                try:
                                    terr = (tr.json().get("error") or "").lower()
                                except Exception:
                                    pass
                                if tr.status_code == 401 or terr in ("invalid_client", "unauthorized_client"):
                                    secret_ok = False
                            except Exception:
                                pass
                        # email scope/claim must be advertised
                        scopes = [s.lower() for s in (metadata.get("scopes_supported") or [])]
                        claims = [c.lower() for c in (metadata.get("claims_supported") or [])]
                        email_ok = not scopes or "email" in scopes or "email" in claims

                        if not secret_ok:
                            result["oidc"] = {
                                "ok": False,
                                "error": "The IdP rejected our client credentials — client_secret is incorrect",
                            }
                        elif not email_ok:
                            result["oidc"] = {"ok": False, "error": "The IdP does not advertise an 'email' scope/claim"}
                        else:
                            result["oidc"] = {"ok": True, "latency_ms": round((time.monotonic() - start) * 1000)}
        except Exception as e:
            result["oidc"] = {"ok": False, "error": str(e)[:200]}

    # ── SAML: delegated to the enterprise layer via the registered hook so the
    # core package stays decoupled. Returns None when SAML is unavailable. ──
    from services.saml_health import run_saml_health_probe

    result["saml"] = await run_saml_health_probe(db)

    from fastapi.responses import JSONResponse

    return JSONResponse(content=result, headers={"Cache-Control": "no-store"})


@router.get("/ides")
async def get_ides():
    """Return the canonical IDE list from IDE_REGISTRY, filtered by allowlist."""
    from services.dynamic_settings import get

    optic.debug("config.get_ides called")

    allowlist_raw = await get("misc.ide_allowlist")
    requested_allowlist = [s.strip() for s in allowlist_raw.split(",") if s.strip()] if allowlist_raw else []
    valid_allowlist = [name for name in requested_allowlist if name in IDE_REGISTRY]
    allowlist = set(valid_allowlist) if valid_allowlist else None

    default_ide_raw = await get("misc.default_ide")

    ides = []
    for name, spec in IDE_REGISTRY.items():
        if allowlist and name not in allowlist:
            continue
        ides.append(
            {
                "name": name,
                "display_name": spec["display_name"],
                "features": sorted(spec["features"]),
                "accepts_model_choice": spec.get("accepts_model_choice", False),
            }
        )
    from fastapi.responses import JSONResponse

    available_names = {ide["name"] for ide in ides}
    default_ide = default_ide_raw if default_ide_raw in available_names else None

    return JSONResponse(
        content={"ides": ides, "default_ide": default_ide},
        headers={"Cache-Control": "no-store"},
    )
