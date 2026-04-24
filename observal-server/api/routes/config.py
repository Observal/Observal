from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from api.deps import get_db
from config import settings

router = APIRouter(prefix="/api/v1/config", tags=["config"])


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

    return {
        "deployment_mode": settings.DEPLOYMENT_MODE,
        "sso_enabled": bool(settings.OAUTH_CLIENT_ID),
        "sso_only": settings.SSO_ONLY,
        "saml_enabled": saml_enabled,
        "eval_configured": bool(settings.EVAL_MODEL_NAME),
    }
