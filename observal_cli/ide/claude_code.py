# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Claude Code IDE adapter."""

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


class ClaudeCodeAdapter(BaseAdapter):
    """Adapter for Claude Code (Anthropic)."""

    @property
    def ide_name(self) -> str:
        return "claude-code"

    def scan_home(self, home: Path | None = None) -> ScanResult:
        from observal_cli.cmd_scan import _scan_claude_home

        home = home or Path.home()
        claude_dir = home / ".claude"
        if not claude_dir.exists():
            return ScanResult()
        mcps, skills, hooks, agents = _scan_claude_home(claude_dir)
        return ScanResult(mcps=mcps, skills=skills, hooks=hooks, agents=agents)

    def scan_project(self, project_dir: Path) -> ScanResult:
        # Claude Code project scanning handled by generic _scan_project_dir
        return ScanResult()

    def get_hook_spec(self) -> HookSpec:
        return HookSpec(
            events=[
                "PreToolUse",
                "PostToolUse",
                "Notification",
                "Stop",
                "SubagentStop",
            ],
            format="command",
            markers=["observal", "OBSERVAL"],
        )

    def generate_hook_config(
        self,
        observal_url: str,
        api_key: str,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        from observal_cli.ide_specs.claude_code_hooks_spec import get_desired_hooks

        return get_desired_hooks()

    def detect_hooks(self, config_dir: Path) -> str:
        from observal_cli.cmd_scan import _has_observal_hooks_claude

        return _has_observal_hooks_claude(config_dir)

    def shim_status(self, mcps: list[DiscoveredMcp]) -> str:
        return super().shim_status(mcps)


register_adapter(ClaudeCodeAdapter())
