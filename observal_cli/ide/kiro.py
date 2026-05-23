# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Kiro IDE adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from observal_cli.ide import (
    DiscoveredMcp,
    HookSpec,
    ScanResult,
    register_adapter,
)
from observal_cli.ide.base import BaseAdapter


class KiroAdapter(BaseAdapter):
    """Adapter for Kiro (AWS)."""

    @property
    def ide_name(self) -> str:
        return "kiro"

    def scan_home(self, home: Path | None = None) -> ScanResult:
        from observal_cli.cmd_scan import _scan_kiro_home

        home = home or Path.home()
        kiro_dir = home / ".kiro"
        if not kiro_dir.exists():
            return ScanResult()
        mcps, skills, hooks, agents = _scan_kiro_home(kiro_dir)
        return ScanResult(mcps=mcps, skills=skills, hooks=hooks, agents=agents)

    def scan_project(self, project_dir: Path) -> ScanResult:
        return ScanResult()

    def get_hook_spec(self) -> HookSpec:
        return HookSpec(
            events=[
                "on_agent_start",
                "on_agent_end",
                "on_tool_start",
                "on_tool_end",
                "on_error",
            ],
            format="http",
            markers=["observal", "OBSERVAL"],
        )

    def generate_hook_config(
        self,
        observal_url: str,
        api_key: str,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        from observal_cli.ide_specs.kiro_hooks_spec import build_kiro_hooks

        return build_kiro_hooks()

    def detect_hooks(self, config_dir: Path) -> str:
        from observal_cli.cmd_scan import _has_observal_hooks_kiro

        return _has_observal_hooks_kiro(config_dir)

    def shim_status(self, mcps: list[DiscoveredMcp]) -> str:
        return super().shim_status(mcps)


register_adapter(KiroAdapter())
