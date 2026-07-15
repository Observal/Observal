# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Compliance-grade audit logging via loguru."""

from .helpers import audit_detail
from .setup import setup_audit, shutdown_audit

AUDIT_ENABLED: bool = True

__all__ = ["AUDIT_ENABLED", "audit_detail", "setup_audit", "shutdown_audit"]
