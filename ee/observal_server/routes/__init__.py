# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Enterprise route mounting."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI


def mount_ee_routes(app: FastAPI) -> None:
    """Mount all enterprise-only routes on the app."""
    from ee.observal_server.routes.admin_sso import router as admin_sso_router
    from ee.observal_server.routes.audit import router as audit_router
    from ee.observal_server.routes.scim import router as scim_router
    from ee.observal_server.routes.sso_saml import router as saml_router

    app.include_router(saml_router)
    app.include_router(scim_router)
    app.include_router(audit_router)
    app.include_router(admin_sso_router)
