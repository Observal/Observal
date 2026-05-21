# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

from importlib.metadata import version as pkg_version
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from api.deps import get_db
from config import settings
from models.enterprise_config import EnterpriseConfig

router = APIRouter(prefix="/api/v1/config", tags=["config"])


def _server_version() -> str:
    try:
        return pkg_version("observal-server")
    except Exception:
        return "dev"


@router.get("/version")
async def get_version():
    """Server version and minimum compatible CLI version. No auth required."""
    return {
        "server_version": _server_version(),
        "min_cli_version": settings.MIN_CLI_VERSION,
    }


def derive_endpoints(request: Request | None = None) -> dict[str, str]:
    """Derive all endpoint URLs from settings, falling back to request context."""
    public_url = settings.PUBLIC_URL.rstrip("/") if settings.PUBLIC_URL else ""
    if not public_url and request:
        public_url = str(request.base_url).rstrip("/")
    if not public_url:
        public_url = "http://localhost:8000"

    parsed = urlparse(public_url)
    hostname = parsed.hostname or "localhost"
    scheme = parsed.scheme or ("http" if hostname in ("localhost", "127.0.0.1") else "https")

    otlp_http = settings.OTLP_HTTP_URL.rstrip("/") if settings.OTLP_HTTP_URL else public_url
    web = settings.FRONTEND_URL.rstrip("/") if settings.FRONTEND_URL else f"{scheme}://{hostname}:3000"

    return {
        "api": public_url,
        "otlp_http": otlp_http,
        "web": web,
    }


@router.get("/endpoints")
async def get_endpoints(request: Request):
    """Endpoint discovery — returns all service URLs. No auth required."""
    return derive_endpoints(request)


@router.get("/public")
async def get_public_config(db=Depends(get_db)):
    """Public configuration for frontend. No auth required."""
    saml_enabled = bool(settings.SAML_IDP_ENTITY_ID and settings.SAML_IDP_SSO_URL)

    if not saml_enabled and settings.DEPLOYMENT_MODE == "enterprise":
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

    from services.insights import INSIGHTS_AVAILABLE

    # Licensed features exposed through the insights gate — no direct ee/ import
    from services.insights import licensed_features as _lf

    licensed_features: list[str] = _lf()
    exec_dashboard_available = "all" in licensed_features or "exec_dashboard" in licensed_features

    return {
        "deployment_mode": settings.DEPLOYMENT_MODE,
        "sso_enabled": bool(settings.OAUTH_CLIENT_ID),
        "sso_only": settings.SSO_ONLY,
        "saml_enabled": saml_enabled,
        "eval_configured": bool(settings.EVAL_MODEL_NAME),
        "insights_available": INSIGHTS_AVAILABLE,
        "exec_dashboard_available": exec_dashboard_available,
        "licensed_features": licensed_features,
        "branding_logo": branding_logo,
        "branding_app_name": branding_app_name,
        "branding_wordmark": branding_wordmark,
    }
