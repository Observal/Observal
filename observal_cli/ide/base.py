# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Base adapter with default NotSupported implementations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from observal_cli.ide import (
    DiscoveredMcp,
    HookSpec,
    NotSupported,
    ScanResult,
)


class BaseAdapter:
    """Base class providing NotSupported defaults for all protocol methods.

    Subclasses override methods they support. Methods left unoverridden
    raise NotSupported when called.
    """

    @property
    def ide_name(self) -> str:
        raise NotImplementedError("Subclasses must define ide_name")

    def scan_home(self, home: Path | None = None) -> ScanResult:
        raise NotSupported(self.ide_name, "scan_home")

    def scan_project(self, project_dir: Path) -> ScanResult:
        raise NotSupported(self.ide_name, "scan_project")

    def get_hook_spec(self) -> HookSpec:
        return HookSpec()  # Empty spec for IDEs without hook_bridge

    def generate_hook_config(
        self,
        observal_url: str,
        api_key: str,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        raise NotSupported(self.ide_name, "generate_hook_config")

    def detect_hooks(self, config_dir: Path) -> str:
        return "none"

    def shim_status(self, mcps: list[DiscoveredMcp]) -> str:
        from observal_cli.shared.utils import is_already_shimmed

        if not mcps:
            return "none"
        shimmed = sum(1 for m in mcps if m.command and is_already_shimmed({"command": m.command, "args": m.args}))
        if shimmed == 0:
            return "none"
        if shimmed == len(mcps):
            return "all"
        return "partial"
