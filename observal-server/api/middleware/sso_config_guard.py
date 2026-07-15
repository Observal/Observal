# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Middleware that returns 503 on SSO routes when required config is missing."""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from services.config_validator import validate_runtime_config_async

if TYPE_CHECKING:
    from starlette.requests import Request

    from config import Settings

# Prefixes that require SSO and provisioning configuration.
SSO_ROUTE_PREFIXES = (
    "/api/v1/sso/",
    "/api/v1/scim/",
)
PUBLIC_SSO_PATHS = {"/api/v1/sso/saml/metadata"}


class SsoConfigGuardMiddleware(BaseHTTPMiddleware):
    """Return 503 Service Unavailable on SSO routes when config has issues.

    Uses the async validator which reads from Redis/DB directly,
    so settings changes via the UI take effect immediately across all workers.
    """

    def __init__(self, app, settings: Settings) -> None:
        super().__init__(app)
        self._settings = settings

    async def dispatch(self, request: Request, call_next):
        if request.url.path not in PUBLIC_SSO_PATHS and any(
            request.url.path.startswith(prefix) for prefix in SSO_ROUTE_PREFIXES
        ):
            issues = await validate_runtime_config_async(self._settings)
            if issues:
                return JSONResponse(
                    status_code=503,
                    content={
                        "detail": "SSO feature not available: configuration incomplete",
                        "issues": issues,
                    },
                )
        return await call_next(request)
