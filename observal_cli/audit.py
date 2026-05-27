# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""CLI-side audit event emission.

Best-effort POST to the server. Never blocks CLI UX.
"""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime

from loguru import logger as optic


def emit_cli_audit(
    action: str,
    *,
    resource_type: str = "",
    resource_id: str = "",
    resource_name: str = "",
    detail: str = "",
    sensitivity: str = "standard",
) -> None:
    """Fire-and-forget audit event to the server."""
    from observal_cli.config import load

    cfg = load()
    if not cfg.get("api_key") and not cfg.get("access_token"):
        return
    server_url = cfg.get("server_url", "").rstrip("/")
    token = cfg.get("api_key") or cfg.get("access_token", "")
    if not server_url or not token:
        return

    event = {
        "event_id": str(uuid.uuid4()),
        "timestamp": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:23],
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "resource_name": resource_name,
        "detail": detail,
        "sensitivity": sensitivity,
        "source": "cli",
    }

    def _send():
        try:
            import httpx

            resp = httpx.post(
                f"{server_url}/api/v1/audit/cli-event",
                json=event,
                headers={"Authorization": f"Bearer {token}"},
                timeout=5.0,
            )
            if resp.status_code >= 400:
                optic.debug("cli audit POST failed: status={}", resp.status_code)
        except Exception as e:
            optic.debug("cli audit POST error: {}", e)

    threading.Thread(target=_send, daemon=True).start()
