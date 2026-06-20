# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Structured security event logging for SIEM integration.

Emits security events to:
1. Python logging (observal.security) - picked up by OTEL Collector for SIEM forwarding
2. ClickHouse security_events table - in-app audit log queries

Events follow a consistent schema compatible with CEF/LEEF/RFC 5424 formats.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from loguru import logger as optic

logger = logging.getLogger("observal.security")

# Cache of actor_id -> org_id so repeated events from the same actor do not
# re-query the database on every emit.
_ACTOR_ORG_CACHE: dict[str, str] = {}


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class EventType(str, Enum):
    # Auth
    LOGIN_SUCCESS = "auth.login.success"
    LOGIN_FAILURE = "auth.login.failure"
    LOGOUT = "auth.logout"
    SSO_SUCCESS = "auth.sso.success"
    SSO_FAILURE = "auth.sso.failure"
    API_KEY_CREATED = "auth.api_key.created"
    API_KEY_REJECTED = "auth.api_key.rejected"
    PASSWORD_RESET_REQUEST = "auth.password_reset.request"
    PASSWORD_RESET_COMPLETE = "auth.password_reset.complete"
    REGISTRATION = "auth.registration"
    TOKEN_REFRESH = "auth.token.refresh"

    # Authorization
    PERMISSION_DENIED = "authz.permission_denied"
    ROLE_CHANGED = "authz.role_changed"

    # Admin
    USER_CREATED = "admin.user.created"
    USER_DELETED = "admin.user.deleted"
    SETTING_CHANGED = "admin.setting.changed"
    PENALTY_WEIGHTS_MODIFIED = "admin.penalty_weights.modified"
    CANARY_CREATED = "admin.canary.created"
    CANARY_DELETED = "admin.canary.deleted"
    INVITE_CREATED = "admin.invite.created"
    ALERT_RULE_CHANGED = "admin.alert_rule.changed"
    ADMIN_PASSWORD_RESET = "admin.password_reset"

    # Review
    REVIEW_APPROVED = "review.approved"
    REVIEW_REJECTED = "review.rejected"

    # Agent security
    INJECTION_DETECTED = "agent.injection_detected"

    # Ingestion
    SECRETS_REDACTED = "ingestion.secrets_redacted"
    MALFORMED_OTLP = "ingestion.malformed_otlp"


@dataclass(slots=True)
class SecurityEvent:
    event_type: EventType
    severity: Severity
    outcome: str  # "success" or "failure"
    actor_id: str = ""
    actor_email: str = ""
    actor_role: str = ""
    target_id: str = ""
    target_type: str = ""
    source_ip: str = ""
    user_agent: str = ""
    detail: str = ""
    org_id: str = ""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3])

    def to_log_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["event_type"] = self.event_type.value
        d["severity"] = self.severity.value
        return d

    def to_clickhouse_row(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "event_type": self.event_type.value,
            "severity": self.severity.value,
            "actor_id": self.actor_id,
            "actor_email": self.actor_email,
            "actor_role": self.actor_role,
            "target_id": self.target_id,
            "target_type": self.target_type,
            "outcome": self.outcome,
            "source_ip": self.source_ip,
            "user_agent": self.user_agent,
            "detail": self.detail,
            "org_id": self.org_id,
        }


async def emit_security_event(event: SecurityEvent) -> None:
    """Emit a security event to structured logging and ClickHouse."""
    optic.trace("emitting security event: {} ({})", event.event_type, event.severity)
    # Client callers never set org_id; resolve it from the actor so the event can
    # be scoped to a tenant before it is logged or persisted.
    if not event.org_id:
        event.org_id = await _resolve_actor_org_id(event.actor_id)
    log_data = event.to_log_dict()

    log_level = {
        Severity.INFO: logging.INFO,
        Severity.WARNING: logging.WARNING,
        Severity.CRITICAL: logging.CRITICAL,
    }[event.severity]

    logger.log(
        log_level,
        "security_event: %s",
        json.dumps(log_data, default=str),
    )

    try:
        from services.clickhouse import _query

        row = event.to_clickhouse_row()
        data = json.dumps(row, default=str)
        await _query("INSERT INTO security_events FORMAT JSONEachRow", data=data)
    except Exception:
        logger.debug("ClickHouse security_events insert skipped", exc_info=True)


async def _resolve_actor_org_id(actor_id: str) -> str:
    """Resolve an actor's org id from the database, caching the result per actor."""
    if not actor_id:
        return ""
    if actor_id in _ACTOR_ORG_CACHE:
        return _ACTOR_ORG_CACHE[actor_id]
    try:
        actor_uuid = uuid.UUID(actor_id)
    except ValueError:
        return ""
    try:
        from sqlalchemy import select

        from database import async_session
        from models.user import User

        async with async_session() as db:
            result = await db.execute(select(User.org_id).where(User.id == actor_uuid))
            org_id = result.scalar_one_or_none()
    except Exception:
        logger.debug("Security event actor org lookup skipped", exc_info=True)
        return ""
    resolved = str(org_id) if org_id else ""
    _ACTOR_ORG_CACHE[actor_id] = resolved
    return resolved


def _extract_request_info(request: Any) -> tuple[str, str]:
    """Extract source IP and user agent from a Starlette/FastAPI request."""
    source_ip = ""
    user_agent = ""
    if request is not None:
        client = getattr(request, "client", None)
        source_ip = client.host if client else ""
        user_agent = request.headers.get("user-agent", "")
    return source_ip, user_agent
