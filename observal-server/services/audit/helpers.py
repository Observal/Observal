# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Helpers for route handlers to enrich audit entries."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.requests import Request


def audit_detail(
    request: Request,
    *,
    action: str = "",
    resource_type: str = "",
    resource_id: str = "",
    resource_name: str = "",
    detail: str = "",
) -> None:
    """Set business context on the request for the audit middleware."""
    if action:
        request.state.audit_action = action
    if resource_type:
        request.state.audit_resource_type = resource_type
    if resource_id:
        request.state.audit_resource_id = str(resource_id)
    if resource_name:
        request.state.audit_resource_name = resource_name
    if detail:
        request.state.audit_detail = detail
