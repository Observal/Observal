"""Middleware that returns 503 on enterprise routes when EE is misconfigured."""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from starlette.requests import Request

# Prefixes that require a fully configured enterprise deployment
EE_ROUTE_PREFIXES = (
    "/api/v1/sso/",
    "/api/v1/scim/",
)


class EnterpriseGuardMiddleware(BaseHTTPMiddleware):
    """Return 503 Service Unavailable on EE routes when enterprise config has issues."""

    def __init__(self, app, issues: list[str]) -> None:
        super().__init__(app)
        self.issues = issues

    async def dispatch(self, request: Request, call_next):
        if self.issues and any(request.url.path.startswith(p) for p in EE_ROUTE_PREFIXES):
            return JSONResponse(
                status_code=503,
                content={
                    "detail": "Enterprise feature not available — configuration incomplete",
                    "issues": self.issues,
                },
            )
        return await call_next(request)
