# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Deterministic, bounded filesystem traversal for harness discovery."""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from observal_cli.discovery.models import DiagnosticCode, DiagnosticSeverity, DiscoveryDiagnostic
from observal_cli.discovery.redact import make_diagnostic

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


@dataclass(frozen=True)
class WalkLimits:
    max_files_per_root: int = 5_000
    max_file_bytes: int = 1024 * 1024
    max_depth: int = 8
    adapter_deadline_seconds: float = 10.0


@dataclass
class AggregateDiscoveryBudget:
    """Aggregate accounting shared by rich harness collection."""

    max_roots: int = 256
    max_files: int = 25_000
    max_evidence: int = 10_000
    max_diagnostics: int = 1_000
    ordinary_diagnostic_limit: int = 996
    roots: int = 0
    files: int = 0
    evidence: int = 0
    diagnostics: int = 0
    emitted_limits: set[DiagnosticCode] = field(default_factory=set)


_ACTIVE_BUDGET: ContextVar[AggregateDiscoveryBudget | None] = ContextVar("discovery_budget", default=None)
_ACTIVE_DEADLINE: ContextVar[float | None] = ContextVar("discovery_deadline", default=None)


@contextmanager
def discovery_budget(budget: AggregateDiscoveryBudget, *, deadline: float | None = None) -> Iterator[None]:
    """Apply aggregate limits to every walker created in this context."""
    budget_token = _ACTIVE_BUDGET.set(budget)
    deadline_token = _ACTIVE_DEADLINE.set(deadline)
    try:
        yield
    finally:
        _ACTIVE_DEADLINE.reset(deadline_token)
        _ACTIVE_BUDGET.reset(budget_token)


class BoundedWalker:
    """Inspect approved roots without escaping them or following directory links."""

    def __init__(
        self,
        root: Path,
        *,
        provider: str,
        limits: WalkLimits | None = None,
        budget: AggregateDiscoveryBudget | None = None,
        clock: Callable[[], float] = time.monotonic,
        deadline: float | None = None,
    ) -> None:
        self.root = root.expanduser().resolve(strict=False)
        self.provider = provider
        self.limits = limits or WalkLimits()
        self.budget = budget or _ACTIVE_BUDGET.get() or AggregateDiscoveryBudget()
        self._clock = clock
        local_deadline = deadline if deadline is not None else clock() + self.limits.adapter_deadline_seconds
        active_deadline = _ACTIVE_DEADLINE.get()
        self._deadline = min(local_deadline, active_deadline) if active_deadline is not None else local_deadline
        self._root_files = 0
        self._seen_files: set[Path] = set()
        self._diagnostics: list[DiscoveryDiagnostic] = []
        self._stopped = False
        self._approve_root()

    @property
    def diagnostics(self) -> list[DiscoveryDiagnostic]:
        return list(self._diagnostics)

    @property
    def stopped(self) -> bool:
        return self._stopped

    @property
    def deadline(self) -> float:
        return self._deadline

    def halt(self) -> None:
        self._stopped = True

    def _approve_root(self) -> None:
        if self.budget.roots >= self.budget.max_roots:
            self.limit(DiagnosticCode.APPROVED_ROOT_LIMIT_REACHED, "approved discovery root limit reached")
            self._stopped = True
            return
        self.budget.roots += 1

    def diagnostic(
        self,
        code: DiagnosticCode,
        message: str,
        *,
        source: Path | None = None,
        severity: DiagnosticSeverity = DiagnosticSeverity.WARNING,
        limit: bool = False,
    ) -> None:
        if limit and code in self.budget.emitted_limits:
            return
        if limit:
            self.budget.emitted_limits.add(code)
        elif self.budget.diagnostics >= self.budget.ordinary_diagnostic_limit:
            self.limit(DiagnosticCode.DIAGNOSTIC_LIMIT_REACHED, "discovery diagnostic limit reached")
            return
        if self.budget.diagnostics >= self.budget.max_diagnostics:
            return
        self._diagnostics.append(
            make_diagnostic(
                code=code,
                severity=severity,
                provider=self.provider,
                source=source,
                message=message,
            )
        )
        self.budget.diagnostics += 1

    def limit(self, code: DiagnosticCode, message: str, *, source: Path | None = None) -> None:
        self.diagnostic(code, message, source=source, limit=True)

    def _within_root(self, path: Path) -> bool:
        try:
            path.relative_to(self.root)
            return True
        except ValueError:
            return False

    def _deadline_ok(self) -> bool:
        if self._stopped:
            return False
        if self._clock() <= self._deadline:
            return True
        self.limit(DiagnosticCode.ADAPTER_DEADLINE_EXCEEDED, "adapter discovery deadline exceeded", source=self.root)
        self._stopped = True
        return False

    def _inspect(self, path: Path) -> Path | None:
        if not self._deadline_ok():
            return None
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            self.diagnostic(DiagnosticCode.PERMISSION_DENIED, f"unable to resolve discovery path: {exc}", source=path)
            return None
        if not self._within_root(resolved):
            code = DiagnosticCode.SYMLINK_ESCAPE if path.is_symlink() else DiagnosticCode.PATH_OUTSIDE_ROOT
            self.diagnostic(code, "discovery path resolves outside its approved root", source=path)
            return None
        inspected_path = path.absolute()
        if inspected_path in self._seen_files:
            return resolved
        if self._root_files >= self.limits.max_files_per_root:
            self.limit(DiagnosticCode.ITEM_LIMIT_REACHED, "approved root file limit reached", source=self.root)
            self._stopped = True
            return None
        if self.budget.files >= self.budget.max_files:
            self.limit(DiagnosticCode.COLLECTION_FILE_LIMIT_REACHED, "aggregate discovery file limit reached")
            self._stopped = True
            return None
        self._seen_files.add(inspected_path)
        self._root_files += 1
        self.budget.files += 1
        return resolved

    def read_text(self, path: Path) -> str | None:
        """Read one contained metadata file after size and deadline checks."""
        if not path.exists() and not path.is_symlink():
            return None
        resolved = self._inspect(path)
        if resolved is None:
            return None
        try:
            size = resolved.stat().st_size
            if size > self.limits.max_file_bytes:
                self.diagnostic(
                    DiagnosticCode.METADATA_TOO_LARGE,
                    f"metadata file exceeds {self.limits.max_file_bytes} byte limit",
                    source=path,
                )
                return None
            return resolved.read_text()
        except (OSError, UnicodeError) as exc:
            self.diagnostic(DiagnosticCode.PERMISSION_DENIED, f"unable to read discovery metadata: {exc}", source=path)
            return None

    def files(self, directory: Path, *, name: str | None = None, suffix: str | None = None) -> Iterator[Path]:
        """Yield matching files in stable order, bounded by depth and counters."""
        if self._stopped or not directory.exists():
            return
        try:
            start = directory.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            self.diagnostic(
                DiagnosticCode.PERMISSION_DENIED, f"unable to resolve discovery directory: {exc}", source=directory
            )
            return
        if not self._within_root(start):
            self.diagnostic(
                DiagnosticCode.PATH_OUTSIDE_ROOT, "discovery directory is outside its approved root", source=directory
            )
            return

        try:
            initial_depth = len(start.relative_to(self.root).parts)
        except ValueError:
            initial_depth = self.limits.max_depth + 1
        if initial_depth > self.limits.max_depth:
            self.limit(DiagnosticCode.RECURSION_LIMIT_REACHED, "discovery recursion limit reached", source=directory)
            return

        stack: list[tuple[Path, int]] = [(start, initial_depth)]
        depth_limited = False
        while stack and self._deadline_ok():
            current, depth = stack.pop()
            try:
                entries = sorted(os.scandir(current), key=lambda entry: entry.name.casefold())
            except OSError as exc:
                self.diagnostic(
                    DiagnosticCode.PERMISSION_DENIED, f"unable to inspect discovery directory: {exc}", source=current
                )
                continue
            directories: list[Path] = []
            for entry in entries:
                candidate = Path(entry.path)
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if depth >= self.limits.max_depth:
                            depth_limited = True
                        else:
                            directories.append(candidate)
                        continue
                    if not entry.is_file(follow_symlinks=False) and not entry.is_symlink():
                        continue
                except OSError as exc:
                    self.diagnostic(
                        DiagnosticCode.PERMISSION_DENIED, f"unable to inspect discovery path: {exc}", source=candidate
                    )
                    continue
                resolved = self._inspect(candidate)
                if resolved is None or not resolved.is_file():
                    if self._stopped:
                        break
                    continue
                if name is not None and entry.name != name:
                    continue
                if suffix is not None and candidate.suffix != suffix:
                    continue
                yield candidate
                if self._stopped:
                    break
            stack.extend((item, depth + 1) for item in reversed(directories))
        if depth_limited:
            self.limit(DiagnosticCode.RECURSION_LIMIT_REACHED, "discovery recursion limit reached", source=directory)
