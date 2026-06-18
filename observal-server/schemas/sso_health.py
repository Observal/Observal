# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Per-check diagnostic schema for the SSO health validators.

Each probe contributes one check ``{name, label, status, message?, hint?}``.
The aggregate response is ``{ok, latency_ms, checks: [...], ...}`` where ``ok``
is False if *any* check has status "fail" — but every check still runs, so the
operator sees every problem in a single round-trip instead of fixing them one
at a time.
"""

from __future__ import annotations

from typing import Any


def make_check(
    name: str,
    label: str,
    status: str,
    message: str | None = None,
    hint: str | None = None,
) -> dict[str, Any]:
    """Build a single check entry. ``status`` is "pass", "fail", or "skip"."""
    out: dict[str, Any] = {"name": name, "label": label, "status": status}
    if message:
        out["message"] = message
    if hint:
        out["hint"] = hint
    return out


def all_pass(checks: list[dict[str, Any]]) -> bool:
    """Aggregate result is OK iff no check failed. Skipped checks don't fail."""
    return not any(c.get("status") == "fail" for c in checks)
