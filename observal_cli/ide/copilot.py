# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""GitHub Copilot IDE adapter."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from observal_cli.ide import (
    DiscoveredMcp,
    HookSpec,
    ScanResult,
    register_adapter,
)
from observal_cli.ide.base import BaseAdapter


def _vscode_user_settings_path(home: Path | None = None) -> Path:
    """Return the platform-specific path to VS Code user settings.json."""
    if home is None:
        home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "Code" / "User" / "settings.json"
    elif sys.platform == "win32":
        appdata = Path.home() / "AppData" / "Roaming"
        return appdata / "Code" / "User" / "settings.json"
    else:
        # Linux and other Unix
        return home / ".config" / "Code" / "User" / "settings.json"


class CopilotAdapter(BaseAdapter):
    """Adapter for GitHub Copilot (VS Code based)."""

    managed_agent_files = ("project:.github/agents/{name}.agent.md",)

    @property
    def ide_name(self) -> str:
        return "copilot"

    def get_hook_spec(self) -> HookSpec:
        return HookSpec(
            events=["SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"],
            format="command",
            markers=["observal", "OBSERVAL"],
        )

    def scan_home(self, home: Path | None = None) -> ScanResult:
        home = home or Path.home()
        vscode_dir = home / ".vscode"
        if not vscode_dir.exists():
            return ScanResult()
        mcp_file = vscode_dir / "mcp.json"
        if not mcp_file.exists():
            return ScanResult()
        try:
            data = json.loads(mcp_file.read_text())
            servers = data.get("servers", data.get("mcpServers", {}))
            mcps = []
            for srv_name, srv_config in servers.items():
                if isinstance(srv_config, dict):
                    mcps.append(
                        DiscoveredMcp(
                            name=srv_name,
                            command=srv_config.get("command"),
                            args=srv_config.get("args", []),
                            url=srv_config.get("url"),
                            description=f"Copilot MCP: {srv_name}",
                            source="copilot:global",
                        )
                    )
            return ScanResult(mcps=mcps)
        except (json.JSONDecodeError, OSError):
            return ScanResult()

    def scan_project(self, project_dir: Path) -> ScanResult:
        mcp_file = project_dir / ".vscode" / "mcp.json"
        if not mcp_file.exists():
            return ScanResult()
        try:
            data = json.loads(mcp_file.read_text())
            servers = data.get("servers", data.get("mcpServers", {}))
            mcps = []
            for name, cfg in servers.items():
                if isinstance(cfg, dict):
                    mcps.append(
                        DiscoveredMcp(
                            name=name,
                            command=cfg.get("command"),
                            args=cfg.get("args", []),
                            url=cfg.get("url"),
                            description=f"Copilot project MCP: {name}",
                            source="copilot:project",
                        )
                    )
            return ScanResult(mcps=mcps)
        except (json.JSONDecodeError, OSError):
            return ScanResult()

    def detect_hooks(self, config_dir: Path) -> str:
        """Detect telemetry hooks for Copilot.

        Checks for hook files at .github/hooks/*.json or ~/.copilot/hooks/*.json
        with observal markers.

        Returns "installed" when hooks are configured, "missing" otherwise.
        """
        # Check for hook files in the project
        hooks_dir = config_dir.parent / ".github" / "hooks" if config_dir.name == ".vscode" else config_dir
        if hooks_dir.is_dir():
            for hook_file in hooks_dir.glob("*.json"):
                try:
                    data = json.loads(hook_file.read_text())
                    hooks = data.get("hooks", {})
                    for entries in hooks.values():
                        if isinstance(entries, list):
                            for entry in entries:
                                if isinstance(entry, dict):
                                    cmd = entry.get("command", entry.get("bash", ""))
                                    if "observal" in cmd or "session_push" in cmd:
                                        return "installed"
                except (json.JSONDecodeError, OSError):
                    continue

        # Check user-level hooks
        user_hooks_dir = Path.home() / ".copilot" / "hooks"
        if user_hooks_dir.is_dir():
            for hook_file in user_hooks_dir.glob("*.json"):
                try:
                    data = json.loads(hook_file.read_text())
                    hooks = data.get("hooks", {})
                    for entries in hooks.values():
                        if isinstance(entries, list):
                            for entry in entries:
                                if isinstance(entry, dict):
                                    cmd = entry.get("command", entry.get("bash", ""))
                                    if "observal" in cmd or "session_push" in cmd:
                                        return "installed"
                except (json.JSONDecodeError, OSError):
                    continue

        return "missing"

    def shim_status(self, mcps: list[DiscoveredMcp]) -> str:
        return super().shim_status(mcps)


register_adapter(CopilotAdapter())
