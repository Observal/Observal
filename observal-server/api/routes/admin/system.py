# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Admin system actions: manual API process restart.

Restart-required settings (OAuth client credentials, discovery URLs) only take
effect when the API process rebuilds its clients at startup. This endpoint
lets a super admin trigger that restart from the UI instead of SSHing to the
host. It relies on the container restart policy (``restart: unless-stopped``
on the API service) to bring the process back up.
"""

import asyncio
import json
import os
import signal

from fastapi import Depends, Request
from loguru import logger as optic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db, require_role, require_super_admin
from api.ratelimit import limiter
from models.enterprise_config import RESTART_PENDING_KEY, EnterpriseConfig
from models.user import User, UserRole
from services.security_events import EventType, SecurityEvent, Severity, emit_security_event

from ._router import router

# Long enough for the 202 response to flush to the client, short enough that
# the operator's polling loop doesn't race a still-alive old process.
_RESTART_DELAY_SECONDS = 1.0


def _terminate_api_process() -> None:
    """SIGTERM the API process tree so the container restart policy revives it.

    In the container the tree root is PID 1: the uvicorn master when running
    with ``--workers N``, or uvicorn itself when single-process. Signaling the
    root takes every worker down together. Terminating only the serving
    worker would leave sibling workers running with stale OAuth clients.
    Outside a container (dev), only our own process is signaled so a parent
    shell is never killed.
    """
    pid = os.getpid()
    ppid = os.getppid()
    target = 1 if (pid == 1 or ppid == 1) else pid
    optic.warning("API restart: sending SIGTERM to pid {} (self={}, parent={})", target, pid, ppid)
    os.kill(target, signal.SIGTERM)


@router.get("/restart/status")
async def restart_status(
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(require_role(UserRole.admin)),
):
    """Return whether saved settings require an API restart."""
    result = await db.execute(select(EnterpriseConfig.value).where(EnterpriseConfig.key == RESTART_PENDING_KEY))
    raw = result.scalar_one_or_none()
    if not raw:
        return {"required": False, "changed_at": None, "keys": []}
    try:
        state = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        state = {}
    return {
        "required": True,
        "changed_at": state.get("changed_at"),
        "keys": state.get("keys", []),
    }


@router.post("/restart", status_code=202)
@limiter.limit("1/minute")
async def restart_api(
    request: Request,
    current_user: User = Depends(require_super_admin),
):
    """Schedule a graceful API restart. Super-admin only, rate-limited."""
    optic.warning("API restart requested by user={}", current_user.id)
    await emit_security_event(
        SecurityEvent(
            event_type=EventType.SETTING_CHANGED,
            severity=Severity.CRITICAL,
            outcome="success",
            actor_id=str(current_user.id),
            actor_email=current_user.email,
            actor_role=current_user.role.value,
            target_id="api_process",
            target_type="system",
            detail="API restart initiated from admin UI",
        )
    )
    asyncio.get_running_loop().call_later(_RESTART_DELAY_SECONDS, _terminate_api_process)
    return {
        "detail": "API restart scheduled",
        "delay_seconds": _RESTART_DELAY_SECONDS,
    }
