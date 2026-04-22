"""Audit logging service for enterprise compliance (SOC 2 / ISO 27001 / HIPAA).

Registers event bus handlers that buffer events and batch-insert to the
ClickHouse audit_log table.  Only active when DEPLOYMENT_MODE=enterprise.

Buffer is flushed every 2 seconds or when it reaches 500 rows, whichever
comes first.  A background asyncio.Task handles the periodic flush.
"""

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime

from services.clickhouse import insert_audit_log
from services.events import (
    AgentLifecycleEvent,
    AlertRuleChanged,
    AuditableAction,
    LoginFailure,
    LoginSuccess,
    RoleChanged,
    SettingsChanged,
    UserCreated,
    UserDeleted,
    bus,
)
from services.request_context import get_request_context

logger = logging.getLogger("observal.ee.audit")

_FLUSH_INTERVAL_S = 2.0
_FLUSH_THRESHOLD = 500

_audit_buffer: list[dict] = []
_buffer_lock = asyncio.Lock()
_flush_task: asyncio.Task | None = None


def _make_row(
    *,
    actor_id: str,
    actor_email: str,
    actor_role: str = "",
    action: str,
    resource_type: str,
    resource_id: str = "",
    resource_name: str = "",
    http_method: str = "",
    http_path: str = "",
    status_code: int = 0,
    ip_address: str = "",
    user_agent: str = "",
    detail: str = "",
) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "timestamp": datetime.now(UTC).isoformat(),
        "actor_id": actor_id,
        "actor_email": actor_email,
        "actor_role": actor_role,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "resource_name": resource_name,
        "http_method": http_method,
        "http_path": http_path,
        "status_code": status_code,
        "ip_address": ip_address,
        "user_agent": user_agent,
        "detail": detail,
    }


def _enrich_with_http_context(row: dict) -> dict:
    ctx = get_request_context()
    row["http_method"] = ctx.method
    row["http_path"] = ctx.path
    row["ip_address"] = ctx.ip
    row["user_agent"] = ctx.user_agent
    return row


async def _buffer_row(row: dict) -> None:
    async with _buffer_lock:
        _audit_buffer.append(row)
        if len(_audit_buffer) >= _FLUSH_THRESHOLD:
            await _flush_locked()


async def _flush_locked() -> None:
    if not _audit_buffer:
        return
    batch = _audit_buffer.copy()
    _audit_buffer.clear()
    try:
        await insert_audit_log(batch)
        logger.debug("Flushed %d audit rows to ClickHouse", len(batch))
    except Exception:
        logger.exception("Failed to flush %d audit rows", len(batch))


async def _periodic_flush() -> None:
    while True:
        await asyncio.sleep(_FLUSH_INTERVAL_S)
        try:
            async with _buffer_lock:
                await _flush_locked()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Periodic audit flush failed")


async def flush_audit_buffer() -> int:
    async with _buffer_lock:
        count = len(_audit_buffer)
        await _flush_locked()
        return count


def register_audit_handlers():
    """Register event bus handlers for audit logging.  Called during enterprise startup."""
    global _flush_task
    _flush_task = asyncio.get_running_loop().create_task(_periodic_flush())

    @bus.on(AuditableAction)
    async def _audit_generic(event: AuditableAction):
        ctx = get_request_context()
        row = _make_row(
            actor_id=event.actor_id,
            actor_email=event.actor_email,
            actor_role=event.actor_role,
            action=event.action,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            resource_name=event.resource_name,
            http_method=ctx.method,
            http_path=ctx.path,
            ip_address=ctx.ip,
            user_agent=ctx.user_agent,
            detail=event.detail,
        )
        await _buffer_row(row)

    @bus.on(UserCreated)
    async def _audit_user_created(event: UserCreated):
        row = _make_row(
            actor_id=event.user_id,
            actor_email=event.email,
            actor_role=event.role,
            action="user.created",
            resource_type="user",
            resource_id=event.user_id,
            resource_name=event.email,
            detail=json.dumps({"is_demo": event.is_demo}),
        )
        _enrich_with_http_context(row)
        await _buffer_row(row)

    @bus.on(UserDeleted)
    async def _audit_user_deleted(event: UserDeleted):
        row = _make_row(
            actor_id=event.user_id,
            actor_email=event.email,
            action="user.deleted",
            resource_type="user",
            resource_id=event.user_id,
            resource_name=event.email,
        )
        _enrich_with_http_context(row)
        await _buffer_row(row)

    @bus.on(LoginSuccess)
    async def _audit_login_success(event: LoginSuccess):
        row = _make_row(
            actor_id=event.user_id,
            actor_email=event.email,
            action="auth.login_success",
            resource_type="session",
            detail=json.dumps({"method": event.method}),
        )
        _enrich_with_http_context(row)
        await _buffer_row(row)

    @bus.on(LoginFailure)
    async def _audit_login_failure(event: LoginFailure):
        row = _make_row(
            actor_id="",
            actor_email=event.email,
            action="auth.login_failure",
            resource_type="session",
            detail=json.dumps({"method": event.method, "reason": event.reason}),
        )
        _enrich_with_http_context(row)
        await _buffer_row(row)

    @bus.on(RoleChanged)
    async def _audit_role_changed(event: RoleChanged):
        row = _make_row(
            actor_id=event.user_id,
            actor_email=event.email,
            action="user.role_changed",
            resource_type="user",
            resource_id=event.user_id,
            resource_name=event.email,
            detail=json.dumps({"old_role": event.old_role, "new_role": event.new_role}),
        )
        _enrich_with_http_context(row)
        await _buffer_row(row)

    @bus.on(SettingsChanged)
    async def _audit_settings_changed(event: SettingsChanged):
        row = _make_row(
            actor_id="system",
            actor_email="",
            action="settings.changed",
            resource_type="config",
            resource_name=event.key,
            detail=json.dumps({"value": event.value}),
        )
        _enrich_with_http_context(row)
        await _buffer_row(row)

    @bus.on(AlertRuleChanged)
    async def _audit_alert_changed(event: AlertRuleChanged):
        row = _make_row(
            actor_id=event.actor_id,
            actor_email=event.actor_email,
            action=f"alert.{event.action}",
            resource_type="alert_rule",
            resource_id=event.alert_id,
        )
        _enrich_with_http_context(row)
        await _buffer_row(row)

    @bus.on(AgentLifecycleEvent)
    async def _audit_agent_lifecycle(event: AgentLifecycleEvent):
        row = _make_row(
            actor_id=event.actor_id,
            actor_email=event.actor_email,
            action=f"agent.{event.action}",
            resource_type="agent",
            resource_id=event.agent_id,
        )
        _enrich_with_http_context(row)
        await _buffer_row(row)

    logger.info(
        "Audit logging handlers registered (%d event types), periodic flush every %.1fs",
        9,
        _FLUSH_INTERVAL_S,
    )


async def shutdown_audit() -> None:
    global _flush_task
    if _flush_task is not None:
        _flush_task.cancel()
        try:
            await _flush_task
        except asyncio.CancelledError:
            pass
        _flush_task = None
    flushed = await flush_audit_buffer()
    if flushed:
        logger.info("Shutdown: flushed %d remaining audit rows", flushed)
