# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Admin system actions: manual API process restart.

Restart-required settings (OAuth client credentials, discovery URLs) only take
effect when the API process rebuilds its clients at startup. This endpoint
lets a super admin trigger that restart from the UI instead of SSHing to the
host. It relies on the container restart policy (``restart: unless-stopped``
on the API service) to bring the process back up.
"""

import asyncio
import os
import signal

from fastapi import Depends, Request
from loguru import logger as optic

from api.deps import require_super_admin
from api.ratelimit import limiter
from models.user import User
from services.security_events import EventType, SecurityEvent, Severity, emit_security_event

from ._router import router

# Long enough for the 202 response to flush to the client, short enough that
# the operator's polling loop doesn't race a still-alive old process.
_RESTART_DELAY_SECONDS = 1.0


def _terminate_api_process() -> None:
    """SIGTERM the API process tree so the container restart policy revives it.

    In the container the tree root is PID 1: the uvicorn master when running
    with ``--workers N``, or uvicorn itself when single-process. Signaling the
    root takes every worker down together -- terminating only the serving
    worker would leave sibling workers running with stale OAuth clients.
    Outside a container (dev), only our own process is signaled so a parent
    shell is never killed.
    """
    pid = os.getpid()
    ppid = os.getppid()
    target = 1 if (pid == 1 or ppid == 1) else pid
    optic.warning("API restart: sending SIGTERM to pid {} (self={}, parent={})", target, pid, ppid)
    os.kill(target, signal.SIGTERM)


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
