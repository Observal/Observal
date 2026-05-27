# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Yash Gadgil <yashgadgil08@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""CLI audit event ingestion endpoint."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from api.deps import get_current_user
from models.user import User  # noqa: TC001

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


class CliAuditEvent(BaseModel):
    """Schema for CLI-emitted audit events."""

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:23])
    action: str
    resource_type: str = ""
    resource_id: str = ""
    resource_name: str = ""
    detail: str = ""
    sensitivity: str = "standard"
    source: str = "cli"


@router.post("/cli-event")
async def receive_cli_audit_event(
    event: CliAuditEvent,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Receive and store an audit event from the CLI."""
    from services.audit import AUDIT_LICENSED

    if not AUDIT_LICENSED:
        return {"status": "skipped", "reason": "audit not licensed"}

    from services.clickhouse import insert_audit_log

    # Real IP is resolved by TrustedProxyMiddleware into request.scope["client"]
    ip = request.client.host if request.client else "127.0.0.1"

    row = {
        "event_id": event.event_id,
        "timestamp": event.timestamp,
        "actor_id": str(current_user.id),
        "actor_email": current_user.email or "",
        "actor_role": current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
        "action": event.action,
        "resource_type": event.resource_type,
        "resource_id": event.resource_id,
        "resource_name": event.resource_name,
        "http_method": "POST",
        "http_path": "/api/v1/audit/cli-event",
        "status_code": 200,
        "ip_address": ip,
        "user_agent": request.headers.get("user-agent", "")[:256],
        "detail": event.detail,
        "org_id": str(current_user.org_id) if hasattr(current_user, "org_id") and current_user.org_id else "",
        "sensitivity": event.sensitivity,
        "request_id": getattr(request.state, "request_id", ""),
        "outcome": "success",
        "duration_ms": 0.0,
        "chain_hash": "",
        "source": "cli",
    }

    await insert_audit_log([row])
    return {"status": "ok"}
