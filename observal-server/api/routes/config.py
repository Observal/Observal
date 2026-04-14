from fastapi import APIRouter

from config import settings

router = APIRouter(prefix="/api/v1/config", tags=["config"])


@router.get("/public")
async def get_public_config():
    """Public configuration for frontend. No auth required."""
    return {
        "deployment_mode": settings.DEPLOYMENT_MODE,
        "sso_enabled": bool(settings.OAUTH_CLIENT_ID),
        "saml_enabled": False,  # placeholder for future ee/ SAML
        "eval_configured": bool(settings.EVAL_MODEL_NAME),
    }
