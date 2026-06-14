# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Pi IDE adapter - scanning, hook detection, shim status."""

from __future__ import annotations

import json
from pathlib import Path

from observal_cli.ide import (
    DiscoveredMcp,
    DiscoveredSkill,
    HookSpec,
    ScanResult,
    register_adapter,
)
from observal_cli.ide.base import BaseAdapter
from observal_cli.shared.utils import extract_mcp_servers, first_content_line, parse_frontmatter_field


class PiAdapter(BaseAdapter):
    """Adapter for Pi.

    Pi is harness-centric: the entirety of pi IS one agent.
    MCP servers are managed via pi-mcp-adapter (reads ~/.pi/agent/mcp.json).
    Hooks are delivered as the observal-pi package.
    """

    managed_agent_files = ("user:AGENTS.md",)
    managed_skill_files = ("user:skills/{name}/SKILL.md",)

    @property
    def ide_name(self) -> str:
        return "pi"

    # ── Scanning ──────────────────────────────────────────────

    def scan_home(self, home: Path | None = None) -> ScanResult:
        """Discover MCPs from ~/.pi/agent/mcp.json, skills from ~/.pi/agent/skills/."""
        home = home or Path.home()
        pi_dir = home / ".pi" / "agent"
        if not pi_dir.exists():
            return ScanResult()

        mcps = self._scan_mcps(pi_dir / "mcp.json", "pi:global")
        skills = self._scan_skills(pi_dir / "skills")
        return ScanResult(mcps=mcps, skills=skills)

    def scan_project(self, project_dir: Path) -> ScanResult:
        """Discover MCPs from .pi/mcp.json, skills from .pi/skills/."""
        pi_dir = project_dir / ".pi"
        if not pi_dir.exists():
            return ScanResult()

        mcps = self._scan_mcps(pi_dir / "mcp.json", "pi:project")
        skills = self._scan_skills(pi_dir / "skills")
        return ScanResult(mcps=mcps, skills=skills)

    # ── Hook detection ────────────────────────────────────────

    def get_hook_spec(self) -> HookSpec:
        return HookSpec(
            events=[],
            format="extension",
            markers=["observal-pi"],
        )

    def detect_hooks(self, config_dir: Path) -> str:
        """Check if observal-pi is in settings.json packages."""
        settings = config_dir / "settings.json"
        if not settings.exists():
            return "missing"
        try:
            data = json.loads(settings.read_text())
        except (json.JSONDecodeError, OSError):
            return "missing"

        packages = data.get("packages", [])
        has_observal = any(
            "observal-pi" in (p if isinstance(p, str) else p.get("source", ""))
            or "pi-extension" in (p if isinstance(p, str) else p.get("source", ""))
            for p in packages
        )
        return "installed" if has_observal else "missing"

    # ── Private helpers ───────────────────────────────────────

    def _scan_mcps(self, mcp_file: Path, source: str) -> list[DiscoveredMcp]:
        if not mcp_file.exists():
            return []
        try:
            data = json.loads(mcp_file.read_text())
            servers = extract_mcp_servers(data)
            return [
                DiscoveredMcp(
                    name=name,
                    command=cfg.get("command"),
                    args=cfg.get("args", []),
                    url=cfg.get("url"),
                    description=f"Pi MCP: {name}",
                    source=source,
                )
                for name, cfg in servers.items()
                if isinstance(cfg, dict)
            ]
        except (json.JSONDecodeError, OSError):
            return []

    def _scan_skills(self, skills_dir: Path) -> list[DiscoveredSkill]:
        if not skills_dir.is_dir():
            return []
        skills = []
        for skill_md in sorted(skills_dir.rglob("SKILL.md")):
            name = skill_md.parent.name
            desc = ""
            try:
                content = skill_md.read_text()
                desc = parse_frontmatter_field(content, "description") or ""
                if not desc:
                    desc = first_content_line(content)
            except OSError:
                pass
            skills.append(
                DiscoveredSkill(
                    name=name,
                    description=desc or f"Skill: {name}",
                    source="pi:skills",
                )
            )
        return skills


register_adapter(PiAdapter())
