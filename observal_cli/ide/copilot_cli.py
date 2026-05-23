# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""GitHub Copilot CLI IDE adapter."""

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


class CopilotCliAdapter(BaseAdapter):
    """Adapter for GitHub Copilot CLI."""

    @property
    def ide_name(self) -> str:
        return "copilot-cli"

    def scan_home(self, home: Path | None = None) -> ScanResult:
        from observal_cli.cmd_scan import _scan_copilot_cli_home

        home = home or Path.home()
        copilot_dir = home / ".copilot-cli"
        if not copilot_dir.exists():
            return ScanResult()
        mcps, skills, hooks, agents = _scan_copilot_cli_home(copilot_dir)
        return ScanResult(mcps=mcps, skills=skills, hooks=hooks, agents=agents)

    def scan_project(self, project_dir: Path) -> ScanResult:
        return ScanResult()

    def get_hook_spec(self) -> HookSpec:
        return HookSpec(
            events=["tool_call", "tool_result", "session_start", "session_end"],
            format="http",
            markers=["observal", "OBSERVAL"],
        )

    def generate_hook_config(
        self,
        observal_url: str,
        api_key: str,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        # Copilot CLI hooks use the same HTTP hook format
        env = {"OBSERVAL_API_KEY": api_key, "OBSERVAL_URL": observal_url}
        if agent_id:
            env["OBSERVAL_AGENT_ID"] = agent_id
        return {"hooks": {"url": f"{observal_url}/api/v1/hooks"}, "env": env}

    def detect_hooks(self, config_dir: Path) -> str:
        from observal_cli.cmd_scan import _has_observal_hooks_copilot_cli

        return _has_observal_hooks_copilot_cli(config_dir)

    def shim_status(self, mcps: list[DiscoveredMcp]) -> str:
        return super().shim_status(mcps)


register_adapter(CopilotCliAdapter())
