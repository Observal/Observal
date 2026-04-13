"""Enterprise route mounting."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI


def mount_ee_routes(app: FastAPI) -> None:
    """Mount all enterprise-only routes on the app."""
    from ee.observal_server.routes.scim import router as scim_router
    from ee.observal_server.routes.sso_saml import router as saml_router

    app.include_router(saml_router)
    app.include_router(scim_router)
