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


def register_enterprise(app: FastAPI, settings: Settings) -> list[str]:
    """Bootstrap enterprise features.  Returns a list of config issues (empty = healthy).

    Called once during app startup from main.py.  Responsibilities:
    1. Validate enterprise config
    2. Mount EE routes (SAML, SCIM — placeholders for now)
    3. Add EnterpriseGuardMiddleware (503 on misconfigured EE routes)
    4. Register event bus handlers for audit logging
    """
    from ee.observal_server.middleware.enterprise_guard import EnterpriseGuardMiddleware
    from ee.observal_server.routes import mount_ee_routes
    from ee.observal_server.services.config_validator import validate_enterprise_config

    # 1. Validate config
    issues = validate_enterprise_config(settings)

    # 2. Mount EE routes
    mount_ee_routes(app)

    # 3. Add middleware that returns 503 on EE routes when misconfigured
    if issues:
        app.add_middleware(EnterpriseGuardMiddleware, issues=issues)
        logger.warning("Enterprise mode has config issues: %s", issues)
    else:
        logger.info("Enterprise mode initialized successfully")

    # 4. Store issues for diagnostics endpoint
    app.state.enterprise_issues = issues

    return issues
