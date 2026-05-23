# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from api.deps import get_db
from config import settings
from models.enterprise_config import EnterpriseConfig
from version import get_server_version

router = APIRouter(prefix="/api/v1/config", tags=["config"])


@router.get("/version")
async def get_version():
    """Server version and compatibility info. No auth required."""
    import services.dynamic_settings as ds

    min_cli = await ds.get("misc.min_cli_version")
    max_cli = await ds.get("misc.max_cli_version")
    api_version = await ds.get("misc.api_version")
    frontend_version = await ds.get("misc.frontend_version")
    recommended_cli = await ds.get("misc.recommended_cli_version")

    server_ver = get_server_version()
    return {
        "server_version": server_ver,
        "min_cli_version": min_cli,
        "max_cli_version": max_cli or None,
        "api_version": api_version or None,
        "frontend_version": frontend_version or server_ver,
        "recommended_cli_version": recommended_cli or server_ver,
    }


async def derive_endpoints(request: Request | None = None) -> dict[str, str]:
    """Derive all endpoint URLs from settings, falling back to request context."""
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

    otlp_setting = await ds.get("deployment.otlp_http_url")
    frontend_setting = await ds.get("deployment.frontend_url")
    otlp_http = otlp_setting.rstrip("/") if otlp_setting else public_url
    web = frontend_setting.rstrip("/") if frontend_setting else f"{scheme}://{hostname}:3000"

    return {
        "api": public_url,
        "otlp_http": otlp_http,
        "web": web,
    }


@router.get("/endpoints")
async def get_endpoints(request: Request):
    """Endpoint discovery: returns all service URLs. No auth required."""
    return await derive_endpoints(request)


@router.get("/public")
async def get_public_config(db=Depends(get_db)):
    """Public configuration for frontend. No auth required."""
    import services.dynamic_settings as ds

    # Deployment mode is a boot-time env var (controls route registration)
    deployment_mode = settings.DEPLOYMENT_MODE

    # SAML: check DB-backed dynamic settings, then fall back to SamlConfig model
    saml_idp_entity = await ds.get("saml.idp_entity_id")
    saml_idp_sso = await ds.get("saml.idp_sso_url")
    saml_enabled = bool(saml_idp_entity and saml_idp_sso)

    if not saml_enabled and deployment_mode == "enterprise":
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

    # Feature availability derived from license, no env var
    from services.insights import INSIGHTS_AVAILABLE
    from services.insights import licensed_features as _get_licensed

    licensed_features: list[str] = _get_licensed()
    exec_dashboard_available = "all" in licensed_features or "exec_dashboard" in licensed_features

    # eval_configured: check dynamic settings
    eval_model_name = await ds.get("eval.model_name")
    sso_only = await ds.get_bool("deployment.sso_only")

    return {
        "deployment_mode": deployment_mode,
        "sso_enabled": bool(settings.OAUTH_CLIENT_ID),
        "sso_only": sso_only,
        "saml_enabled": saml_enabled,
        "eval_configured": bool(eval_model_name),
        "insights_available": INSIGHTS_AVAILABLE,
        "exec_dashboard_available": exec_dashboard_available,
        "licensed_features": licensed_features,
        "branding_logo": branding_logo,
        "branding_app_name": branding_app_name,
        "branding_wordmark": branding_wordmark,
    }
