# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Cursor IDE adapter."""

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
from observal_cli.shared.utils import extract_mcp_servers


class CursorAdapter(BaseAdapter):
    """Adapter for Cursor."""

    managed_agent_files = (
        "user:rules/{name}.mdc",
        "user:agents/{name}.md",
        "project:.cursor/rules/{name}.mdc",
        "project:.cursor/agents/{name}.md",
    )
    managed_skill_files = ("user:rules/{name}.mdc", "user:skills/{name}/SKILL.md")

    @property
    def ide_name(self) -> str:
        return "cursor"

    def scan_home(self, home: Path | None = None) -> ScanResult:
        home = home or Path.home()
        mcp_file = home / ".cursor" / "mcp.json"
        if not mcp_file.exists():
            return ScanResult()
        try:
            data = json.loads(mcp_file.read_text())
            servers = extract_mcp_servers(data)
            mcps = []
            for name, cfg in servers.items():
                if isinstance(cfg, dict):
                    mcps.append(
                        DiscoveredMcp(
                            name=name,
                            command=cfg.get("command"),
                            args=cfg.get("args", []),
                            url=cfg.get("url"),
                            description=f"Cursor global MCP: {name}",
                            source="cursor:global",
                        )
                    )
            return ScanResult(mcps=mcps)
        except (json.JSONDecodeError, OSError):
            return ScanResult()

    def scan_project(self, project_dir: Path) -> ScanResult:
        mcp_file = project_dir / ".cursor" / "mcp.json"
        if not mcp_file.exists():
            return ScanResult()
        try:
            data = json.loads(mcp_file.read_text())
            servers = extract_mcp_servers(data)
            mcps = []
            for name, cfg in servers.items():
                if isinstance(cfg, dict):
                    mcps.append(
                        DiscoveredMcp(
                            name=name,
                            command=cfg.get("command"),
                            args=cfg.get("args", []),
                            url=cfg.get("url"),
                            description=f"Cursor project MCP: {name}",
                            source="cursor:project",
                        )
                    )
            return ScanResult(mcps=mcps)
        except (json.JSONDecodeError, OSError):
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


register_adapter(CursorAdapter())
