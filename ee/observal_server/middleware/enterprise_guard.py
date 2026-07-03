# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: LicenseRef-Observal-Enterprise

"""Middleware that returns 503 on enterprise routes when EE is misconfigured."""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from starlette.requests import Request

    from config import Settings

# Prefixes that require a fully configured enterprise deployment
EE_ROUTE_PREFIXES = (
    "/api/v1/sso/",
    "/api/v1/scim/",
)


class EnterpriseGuardMiddleware(BaseHTTPMiddleware):
    """Return 503 Service Unavailable on EE routes when enterprise config has issues.

    Uses the async validator which reads from Redis/DB directly,
    so settings changes via the UI take effect immediately across all workers.
    """

    def __init__(self, app, settings: Settings) -> None:
        super().__init__(app)
        self._settings = settings

    async def dispatch(self, request: Request, call_next):
        if any(request.url.path.startswith(p) for p in EE_ROUTE_PREFIXES):
            from ee.observal_server.services.config_validator import (
                validate_enterprise_config_async,
            )

            issues = await validate_enterprise_config_async(self._settings)
            if issues:
                return JSONResponse(
                    status_code=503,
                    content={
                        "detail": "Enterprise feature not available — configuration incomplete",
                        "issues": issues,
                    },
                )
        return await call_next(request)
