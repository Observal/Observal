# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Codex CLI IDE adapter."""

from __future__ import annotations

import json
from pathlib import Path

from observal_cli.ide import (
    DiscoveredMcp,
    HookSpec,
    ScanResult,
    register_adapter,
)
from observal_cli.ide.base import BaseAdapter
from observal_cli.shared.utils import _OBSERVAL_HOOK_MARKERS


def _load_toml(path: Path) -> dict:
    """Load a TOML file with graceful fallback across parser implementations."""
    try:
        import tomllib as toml

        return toml.loads(path.read_text())
    except ImportError:
        pass
    try:
        import tomli as toml  # type: ignore[no-redef]

        return toml.loads(path.read_text())
    except ImportError:
        pass
    try:
        import toml  # type: ignore[no-redef]

        return toml.loads(path.read_text())  # type: ignore[arg-type]
    except ImportError:
        return {}


class CodexAdapter(BaseAdapter):
    """Adapter for Codex CLI (OpenAI)."""

    managed_agent_files = ("user:AGENTS.md", "project:AGENTS.md")
    managed_mcp_files = ("user:config.toml",)

    @property
    def ide_name(self) -> str:
        return "codex"

    def scan_home(self, home: Path | None = None) -> ScanResult:
        home = home or Path.home()
        codex_dir = home / ".codex"
        if not codex_dir.exists():
            return ScanResult()
        config_file = codex_dir / "config.toml"
        if not config_file.exists():
            return ScanResult()
        try:
            data = _load_toml(config_file)
            servers = data.get("mcp", {}).get("servers", {})
            mcps = []
            for srv_name, srv_config in servers.items():
                if isinstance(srv_config, dict):
                    mcps.append(
                        DiscoveredMcp(
                            name=srv_name,
                            command=srv_config.get("command"),
                            args=srv_config.get("args", []),
                            url=srv_config.get("url"),
                            description=f"Codex MCP: {srv_name}",
                            source="codex:global",
                        )
                    )
            return ScanResult(mcps=mcps)
        except Exception:
            return ScanResult()

    def scan_project(self, project_dir: Path) -> ScanResult:
        config_file = project_dir / ".codex" / "config.toml"
        if not config_file.exists():
            return ScanResult()
        try:
            data = _load_toml(config_file)
            servers = data.get("mcp", {}).get("servers", {})
            mcps = []
            for srv_name, srv_config in servers.items():
                if isinstance(srv_config, dict):
                    mcps.append(
                        DiscoveredMcp(
                            name=srv_name,
                            command=srv_config.get("command"),
                            args=srv_config.get("args", []),
                            url=srv_config.get("url"),
                            description=f"Codex project MCP: {srv_name}",
                            source="codex:project",
                        )
                    )
            return ScanResult(mcps=mcps)
        except Exception:
            return ScanResult()

    def get_hook_spec(self) -> HookSpec:
        return HookSpec(
            events=["UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"],
            format="command",
            markers=["observal", "OBSERVAL", "codex_session_push"],
        )

    def detect_hooks(self, config_dir: Path) -> str:
        """Check ~/.codex/hooks.json for Observal markers."""
        home = Path.home()
        hooks_file = home / ".codex" / "hooks.json"
        if not hooks_file.exists():
            return "missing"
        try:
            data = json.loads(hooks_file.read_text())
        except (json.JSONDecodeError, OSError):
            return "missing"
        hooks = data.get("hooks", {})
        if not hooks:
            return "missing"
        for _evt, groups in hooks.items():
            if not isinstance(groups, list):
                continue
            for group in groups:
                if not isinstance(group, dict):
                    continue
                for h in group.get("hooks", []):
                    if isinstance(h, dict):
                        cmd = h.get("command", "")
                        if any(m in cmd for m in _OBSERVAL_HOOK_MARKERS):
                            return "installed"
        return "missing"

    def shim_status(self, mcps: list[DiscoveredMcp]) -> str:
        return super().shim_status(mcps)


register_adapter(CodexAdapter())
