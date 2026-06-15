# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Compliance-grade audit logging via loguru.

Enterprise feature, gated by is_feature_licensed("audit").

Usage in route handlers (for adding business context only):

    from services.audit import audit_detail

    @router.get("/{session_id}")
    async def get_session(request: Request, session_id: str, ...):
        audit_detail(request, action="session.view", resource_type="session",
                     resource_id=session_id)
        ...
"""

from .helpers import audit_detail
from .setup import setup_audit, shutdown_audit

# License gate: audit is an enterprise feature.
AUDIT_LICENSED: bool = False
try:
    from ee.license import is_feature_licensed

    AUDIT_LICENSED = is_feature_licensed("audit")
except ImportError:
    pass

__all__ = ["AUDIT_LICENSED", "audit_detail", "setup_audit", "shutdown_audit"]
