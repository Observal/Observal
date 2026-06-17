# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""SAML health-probe hook.

The core package must stay decoupled from the enterprise layer. The enterprise
layer registers its SAML health checker here at startup (via mount_ee_routes);
the public sso-health endpoint calls it through this indirection. When the
enterprise layer is unavailable, the probe is unregistered and the endpoint
reports no SAML status.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from typing import Any

_probe: Callable[[Any], Awaitable[dict | None]] | None = None


def register_saml_health_probe(fn: Callable[[Any], Awaitable[dict | None]]) -> None:
    global _probe
    _probe = fn


async def run_saml_health_probe(db: Any) -> dict | None:
    if _probe is None:
        return None
    return await _probe(db)
