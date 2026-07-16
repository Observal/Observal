# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""SAML health-probe hook.

The SAML route registers its health checker here during app setup. The public
SSO health endpoint calls it through this indirection so the probe remains easy
to replace in tests. An unregistered probe reports no SAML status.
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
