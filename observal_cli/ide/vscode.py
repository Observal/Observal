# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""VS Code IDE adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from observal_cli.ide import (
    DiscoveredMcp,
    HookSpec,
    ScanResult,
    register_adapter,
)
from observal_cli.ide.base import BaseAdapter


class VscodeAdapter(BaseAdapter):
    """Adapter for VS Code."""

    @property
    def ide_name(self) -> str:
        return "vscode"

    def scan_home(self, home: Path | None = None) -> ScanResult:
        # VS Code uses project-level config
        return ScanResult()

    def scan_project(self, project_dir: Path) -> ScanResult:
        return ScanResult()

    def get_hook_spec(self) -> HookSpec:
        return HookSpec()  # VS Code has "rules" feature only

    def detect_hooks(self, config_dir: Path) -> str:
        return "none"

    def shim_status(self, mcps: list[DiscoveredMcp]) -> str:
        return super().shim_status(mcps)


register_adapter(VscodeAdapter())
