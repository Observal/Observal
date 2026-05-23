# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""OpenCode IDE adapter."""

from __future__ import annotations

from pathlib import Path

from observal_cli.ide import (
    DiscoveredMcp,
    HookSpec,
    ScanResult,
    register_adapter,
)
from observal_cli.ide.base import BaseAdapter


class OpenCodeAdapter(BaseAdapter):
    """Adapter for OpenCode."""

    @property
    def ide_name(self) -> str:
        return "opencode"

    def scan_home(self, home: Path | None = None) -> ScanResult:
        from observal_cli.cmd_scan import _scan_opencode_home

        home = home or Path.home()
        opencode_dir = home / ".opencode"
        if not opencode_dir.exists():
            return ScanResult()
        mcps, skills, hooks, agents = _scan_opencode_home(opencode_dir)
        return ScanResult(mcps=mcps, skills=skills, hooks=hooks, agents=agents)

    def scan_project(self, project_dir: Path) -> ScanResult:
        return ScanResult()

    def get_hook_spec(self) -> HookSpec:
        return HookSpec(
            events=["tool_call", "tool_result"],
            format="http",
            markers=["observal", "OBSERVAL"],
        )

    def detect_hooks(self, config_dir: Path) -> str:
        return "none"

    def shim_status(self, mcps: list[DiscoveredMcp]) -> str:
        return super().shim_status(mcps)


register_adapter(OpenCodeAdapter())
