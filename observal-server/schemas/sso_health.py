# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Per-check diagnostic schema for the SSO health validators.

Each probe contributes one check ``{name, label, status, message?, hint?}``.
The aggregate response is ``{ok, latency_ms, checks: [...], ...}`` where ``ok``
is False if *any* check has status "fail" — but every check still runs, so the
operator sees every problem in a single round-trip.
"""

from __future__ import annotations

from typing import Any, Literal

from loguru import logger as optic

CheckStatus = Literal["pass", "fail", "skip"]
_VALID_STATUS: frozenset[str] = frozenset({"pass", "fail", "skip"})


def make_check(
    name: str,
    label: str,
    status: CheckStatus,
    message: str | None = None,
    hint: str | None = None,
) -> dict[str, Any]:
    """Build a single check entry. ``status`` is "pass", "fail", or "skip"."""
    if status not in _VALID_STATUS:
        optic.error("schemas.sso_health.make_check unknown status={} name={}", status, name)
        status = "fail"  # treat as fail so the operator sees something is wrong
    out: dict[str, Any] = {"name": name, "label": label, "status": status}
    if message:
        out["message"] = message
    if hint:
        out["hint"] = hint
    return out


def all_pass(checks: list[dict[str, Any]]) -> bool:
    """Aggregate result is OK iff no check failed. Skipped/unknown don't fail.

    Unknown statuses are logged so a typo doesn't silently pass aggregation.
    """
    for c in checks:
        status = c.get("status")
        if status not in _VALID_STATUS:
            optic.warning("schemas.sso_health.all_pass unknown status={} name={}", status, c.get("name"))
        if status == "fail":
            return False
    return True
