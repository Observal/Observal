# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Progress reporting protocol for migration operations."""

from __future__ import annotations

from typing import Protocol


class ProgressReporter(Protocol):
    """Protocol for reporting migration progress.

    Callers inject an implementation that writes to a DB row (server),
    a rich console (CLI), or simply discards updates (tests).
    """

    async def update(self, *, phase: str, pct: int, message: str) -> None:
        """Report progress.

        Args:
            phase: Current phase name (e.g. 'pg_export', 'ch_import', 'validate').
            pct: Percentage complete (0-100).
            message: Human-readable description of the current step.
        """
        ...


class NullReporter:
    """No-op progress reporter for use in tests and non-interactive contexts."""

    async def update(self, *, phase: str, pct: int, message: str) -> None:
        """Discard progress updates."""
