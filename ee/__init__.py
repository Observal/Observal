"""Enterprise edition module for Observal.

This module is loaded by main.py when DEPLOYMENT_MODE=enterprise.
Core imports from ee/ are NEVER allowed except in main.py.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

    from config import Settings

logger = logging.getLogger("observal.ee")


def register_enterprise_middleware(app: FastAPI, settings: Settings) -> list[str]:
    """Register enterprise middleware (must be called before app startup).

    Returns a list of config issues (empty = healthy).
    """
    from ee.observal_server.middleware.enterprise_guard import EnterpriseGuardMiddleware
    from ee.observal_server.services.config_validator import validate_enterprise_config

    issues = validate_enterprise_config(settings)

    if issues:
        app.add_middleware(EnterpriseGuardMiddleware, issues=issues)
        logger.warning("Enterprise mode has config issues: %s", issues)
    else:
        logger.info("Enterprise mode initialized successfully")

    app.state.enterprise_issues = issues
    return issues


def register_enterprise(app: FastAPI, settings: Settings) -> list[str]:
    """Bootstrap all enterprise features.  Returns a list of config issues (empty = healthy).

    Called once during app startup from main.py.  Responsibilities:
    1. Validate enterprise config + add middleware (before startup)
    2. Mount EE routes (SAML, SCIM, audit log)
    3. Register audit logging event bus handlers
    """
    from ee.observal_server.routes import mount_ee_routes
    from ee.observal_server.services.audit import register_audit_handlers

    issues = register_enterprise_middleware(app, settings)
    mount_ee_routes(app)
    register_audit_handlers()
    return issues
