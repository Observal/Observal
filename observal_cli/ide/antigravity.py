# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Antigravity CLI IDE adapter."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from observal_cli.ide import (
    DiscoveredAgent,
    DiscoveredHook,
    DiscoveredMcp,
    DiscoveredSkill,
    HookSpec,
    ScanResult,
    register_adapter,
)
from observal_cli.ide.base import BaseAdapter
from observal_cli.shared.utils import (
    extract_mcp_servers,
    first_content_line,
    parse_frontmatter_field,
)

if TYPE_CHECKING:
    from pathlib import Path


class AntigravityAdapter(BaseAdapter):
    """Adapter for Antigravity CLI."""

    @property
    def ide_name(self) -> str:
        return "antigravity"

    # -- Scanning ----------------------------------------------------------

    def _resolve_ag_dir(self, home: Path | None = None) -> Path | None:
        """Return the antigravity-cli config dir, with WSL Windows path fallback."""
        from observal_cli.shared.utils import resolve_antigravity_dir

        return resolve_antigravity_dir(home)

    def scan_home(self, home: Path | None = None) -> ScanResult:
        """Discover MCPs, skills, hooks, agents from ~/.gemini/antigravity-cli/."""
        ag_dir = self._resolve_ag_dir(home)
        if ag_dir is None:
            return ScanResult()

        mcps = self._scan_mcps(ag_dir / "mcp_config.json", "antigravity:global")
        skills = self._scan_skills(ag_dir / "skills")
        hooks = self._scan_hooks(ag_dir / "settings.json")
        agents = self._scan_agents(ag_dir / "agents")
        return ScanResult(mcps=mcps, skills=skills, hooks=hooks, agents=agents)

    def scan_project(self, project_dir: Path) -> ScanResult:
        """Discover MCPs, skills from .agents/ in a project."""
        ag_dir = project_dir / ".agents"
        if not ag_dir.exists():
            return ScanResult()

        mcps = self._scan_mcps(ag_dir / "mcp_config.json", "antigravity:project")
        skills = self._scan_skills(ag_dir / "skills")
        return ScanResult(mcps=mcps, skills=skills)

    # -- Hook detection ----------------------------------------------------

    def get_hook_spec(self) -> HookSpec:
        return HookSpec(
            events=["PreToolUse", "PostToolUse", "ToolError", "Stop", "SessionStart", "PreTurn", "PostTurn"],
            format="command",
            markers=["observal", "OBSERVAL"],
        )

    def generate_hook_config(
        self,
        observal_url: str,
        api_key: str,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        from observal_cli.ide_specs.antigravity_hooks_spec import build_antigravity_hooks

        return build_antigravity_hooks()

    def detect_hooks(self, config_dir: Path) -> str:
        """Check if Observal hooks are installed in ~/.gemini/config/hooks.json."""
        from observal_cli.ide_specs.antigravity_hooks_spec import _OBSERVAL_HOOK_NAME
        from observal_cli.shared.utils import resolve_antigravity_config_dir

        # Use config_dir directly if it has hooks.json (e.g. in tests), else resolve real path
        if (config_dir / "hooks.json").exists():
            hooks_file = config_dir / "hooks.json"
        else:
            resolved = resolve_antigravity_config_dir()
            hooks_file = (resolved / "hooks.json") if resolved else (config_dir / "hooks.json")
        if not hooks_file.exists():
            return "missing"
        try:
            data = json.loads(hooks_file.read_text())
        except (json.JSONDecodeError, OSError):
            return "missing"
        return "installed" if _OBSERVAL_HOOK_NAME in data else "missing"

    def shim_status(self, mcps: list[DiscoveredMcp]) -> str:
        return super().shim_status(mcps)

    # -- Private helpers ---------------------------------------------------

    def _scan_mcps(self, mcp_file: Path, source: str) -> list[DiscoveredMcp]:
        if not mcp_file.exists():
            return []
        try:
            data = json.loads(mcp_file.read_text())
            servers = extract_mcp_servers(data, "antigravity")
            return [
                DiscoveredMcp(
                    name=name,
                    command=cfg.get("command"),
                    args=cfg.get("args", []),
                    url=cfg.get("serverUrl") or cfg.get("url"),
                    description=f"Antigravity MCP: {name}",
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
                    source="antigravity:skills",
                )
            )
        return skills

    def _scan_hooks(self, settings_file: Path) -> list[DiscoveredHook]:
        if not settings_file.exists():
            return []
        try:
            data = json.loads(settings_file.read_text())
            hooks_data = data.get("hooks", {})
            hooks: list[DiscoveredHook] = []
            for event, entries in hooks_data.items():
                if isinstance(entries, list):
                    for h in entries:
                        if isinstance(h, dict):
                            hooks.append(
                                DiscoveredHook(
                                    name=h.get("command", event)[:40],
                                    event=event,
                                    handler_type="command",
                                    handler_config=h,
                                    description=f"Hook: {event}",
                                    source="antigravity:hooks",
                                )
                            )
            return hooks
        except (json.JSONDecodeError, OSError):
            return []

    def _scan_agents(self, agents_dir: Path) -> list[DiscoveredAgent]:
        if not agents_dir.is_dir():
            return []
        agents = []
        for agent_file in sorted(agents_dir.glob("*.md")):
            name = agent_file.stem
            content = ""
            desc = ""
            model = ""
            try:
                content = agent_file.read_text()
                desc = parse_frontmatter_field(content, "description") or ""
                model = parse_frontmatter_field(content, "model") or ""
            except OSError:
                pass
            agents.append(
                DiscoveredAgent(
                    name=name,
                    description=desc or f"Agent: {name}",
                    model_name=model,
                    prompt=content[:500],
                    source_file=str(agent_file),
                )
            )
        return agents


register_adapter(AntigravityAdapter())
