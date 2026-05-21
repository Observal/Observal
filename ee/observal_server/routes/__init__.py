# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: LicenseRef-Observal-Enterprise

"""Enterprise route mounting."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI


def mount_ee_routes(app: FastAPI) -> None:
    """Mount enterprise routes, gating each behind its license feature."""
    from ee.license import is_feature_licensed
    from ee.observal_server.routes.admin_sso import router as admin_sso_router
    from ee.observal_server.routes.audit import router as audit_router

    app.include_router(audit_router)
    app.include_router(admin_sso_router)

    if is_feature_licensed("saml"):
        from ee.observal_server.routes.sso_saml import router as saml_router

        app.include_router(saml_router)

    if is_feature_licensed("scim"):
        from ee.observal_server.routes.scim import router as scim_router

        app.include_router(scim_router)

    if is_feature_licensed("exec_dashboard"):
        from ee.observal_server.routes.exec_dashboard import router as exec_dashboard_router

        app.include_router(exec_dashboard_router)
