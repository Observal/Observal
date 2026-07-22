# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Pi harness adapter for scanning and hook detection."""

from __future__ import annotations

import json
from pathlib import Path

from observal_cli.harness import (
    DiscoveredMcp,
    DiscoveredSkill,
    HookSpec,
    ScanResult,
    register_adapter,
)
from observal_cli.harness.base import BaseAdapter
from observal_cli.shared.utils import extract_mcp_servers, first_content_line, parse_frontmatter_field


class PiAdapter(BaseAdapter):
    """Adapter for Pi.

    Pi is harness-centric: the entirety of pi IS one agent.
    MCP servers are managed via pi-mcp-adapter (reads ~/.pi/agent/mcp.json).
    Hooks are delivered as the observal-pi package.
    """

    home_markers = (".pi/agent",)
    managed_agent_profiles = ("user:AGENTS.md",)
    managed_skills = ("user:skills/{name}/SKILL.md",)

    @property
    def harness_name(self) -> str:
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
        """Check for the user-global Observal TypeScript extension."""
        return "installed" if (config_dir / "extensions" / "observal.ts").is_file() else "missing"

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

    def persist_active_agent(self, agent_id: str, name: str, version: str | None) -> None:
        from observal_cli.config import load, save

        config = load()
        config["active_agent"] = {"id": agent_id, "name": name, "version": version}
        save(config)

    def patch_hooks(self, dry_run: bool) -> bool:
        from observal_cli.cmd_doctor import _patch_pi

        return _patch_pi(dry_run)

    def cleanup_hooks(self, dry_run: bool) -> bool:
        from observal_cli.cmd_doctor import _cleanup_pi

        return _cleanup_pi(dry_run)


register_adapter(PiAdapter())
