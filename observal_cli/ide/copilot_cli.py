# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""GitHub Copilot CLI IDE adapter."""

from __future__ import annotations

import json
from pathlib import Path

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
    _OBSERVAL_HOOK_MARKERS,
    first_content_line,
    parse_frontmatter_field,
)


class CopilotCliAdapter(BaseAdapter):
    """Adapter for GitHub Copilot CLI."""

    managed_agent_files = ("project:.github/agents/{name}.agent.md",)
    managed_skill_files = ("project:.agents/skills/{name}/SKILL.md", "user:skills/{name}/SKILL.md")

    @property
    def ide_name(self) -> str:
        return "copilot-cli"

    def scan_home(self, home: Path | None = None) -> ScanResult:
        home = home or Path.home()
        copilot_dir = home / ".copilot"
        if not copilot_dir.exists():
            return ScanResult()

        mcps = self._scan_mcps_file(copilot_dir / "mcp-config.json", "copilot-cli:global")
        skills = self._scan_skills_dir(copilot_dir / "skills")
        hooks = self._scan_hooks_dir(copilot_dir / "hooks")

        return ScanResult(mcps=mcps, skills=skills, hooks=hooks)

    def scan_project(self, project_dir: Path) -> ScanResult:
        mcps = self._scan_mcps_file(project_dir / ".mcp.json", "copilot-cli:project")
        skills = self._scan_skills_dir(project_dir / ".agents" / "skills")
        agents = self._scan_agents_dir(project_dir / ".github" / "agents")
        hooks = self._scan_hooks_dir(project_dir / ".github" / "hooks")

        return ScanResult(mcps=mcps, skills=skills, agents=agents, hooks=hooks)

    def get_hook_spec(self) -> HookSpec:
        return HookSpec(
            events=["sessionStart", "sessionEnd", "userPromptSubmitted", "preToolUse", "postToolUse"],
            format="command",
            markers=["observal", "OBSERVAL"],
        )

    def detect_hooks(self, config_dir: Path) -> str:
        """Check for Observal hooks in both project and user-level hook dirs."""
        # Check user-level hooks
        home = Path.home()
        user_hooks_dir = home / ".copilot" / "hooks"
        if self._has_observal_hooks(user_hooks_dir):
            return "installed"

        # Check project-level hooks (config_dir might be the project root)
        project_hooks_dir = config_dir / ".github" / "hooks"
        if self._has_observal_hooks(project_hooks_dir):
            return "installed"

        # Legacy: check config.json format
        config = config_dir / "config.json"
        if config.exists():
            try:
                data = json.loads(config.read_text())
                hooks = data.get("hooks", {})
                for _evt, entries in hooks.items():
                    if isinstance(entries, list):
                        for h in entries:
                            if isinstance(h, dict) and any(
                                m in h.get("bash", "") or m in h.get("command", "") for m in _OBSERVAL_HOOK_MARKERS
                            ):
                                return "installed"
            except (json.JSONDecodeError, OSError):
                pass

        return "missing"

    def shim_status(self, mcps: list[DiscoveredMcp]) -> str:
        return super().shim_status(mcps)

    # ── Private helpers ───────────────────────────────────────

    def _scan_mcps_file(self, mcp_file: Path, source: str) -> list[DiscoveredMcp]:
        if not mcp_file.exists():
            return []
        try:
            data = json.loads(mcp_file.read_text())
            servers = data.get("mcpServers", {})
            mcps = []
            for srv_name, srv_config in servers.items():
                if isinstance(srv_config, dict):
                    mcps.append(
                        DiscoveredMcp(
                            name=srv_name,
                            command=srv_config.get("command"),
                            args=srv_config.get("args", []),
                            url=srv_config.get("url"),
                            description=f"Copilot CLI MCP: {srv_name}",
                            source=source,
                        )
                    )
            return mcps
        except (json.JSONDecodeError, OSError):
            return []

    def _scan_skills_dir(self, skills_dir: Path) -> list[DiscoveredSkill]:
        """Scan a skills directory for SKILL.md files."""
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
                    source="copilot-cli:skills",
                )
            )
        return skills

    def _scan_agents_dir(self, agents_dir: Path) -> list[DiscoveredAgent]:
        """Scan .github/agents/ for .agent.md files."""
        if not agents_dir.is_dir():
            return []
        agents = []
        for agent_md in sorted(agents_dir.glob("*.agent.md")):
            try:
                content = agent_md.read_text()
                name = agent_md.stem.removesuffix(".agent")
                desc = parse_frontmatter_field(content, "description") or ""
                model = parse_frontmatter_field(content, "model") or ""
                if not desc:
                    desc = first_content_line(content)
                agents.append(
                    DiscoveredAgent(
                        name=name,
                        description=desc or f"Agent: {name}",
                        model_name=model,
                        prompt="",
                        source_file=str(agent_md),
                    )
                )
            except OSError:
                pass
        # Also scan plain .md files (VS Code picks these up too)
        for agent_md in sorted(agents_dir.glob("*.md")):
            if agent_md.name.endswith(".agent.md"):
                continue  # already handled above
            try:
                content = agent_md.read_text()
                name = agent_md.stem
                desc = parse_frontmatter_field(content, "description") or ""
                model = parse_frontmatter_field(content, "model") or ""
                if not desc:
                    desc = first_content_line(content)
                agents.append(
                    DiscoveredAgent(
                        name=name,
                        description=desc or f"Agent: {name}",
                        model_name=model,
                        prompt="",
                        source_file=str(agent_md),
                    )
                )
            except OSError:
                pass
        return agents

    def _scan_hooks_dir(self, hooks_dir: Path) -> list[DiscoveredHook]:
        """Scan a hooks directory for .json hook files."""
        if not hooks_dir.is_dir():
            return []
        hooks = []
        for hook_file in sorted(hooks_dir.glob("*.json")):
            try:
                data = json.loads(hook_file.read_text())
                hook_events = data.get("hooks", {})
                for event_name, entries in hook_events.items():
                    if not isinstance(entries, list):
                        continue
                    for entry in entries:
                        if not isinstance(entry, dict):
                            continue
                        hooks.append(
                            DiscoveredHook(
                                name=f"{hook_file.stem}/{event_name}",
                                event=event_name,
                                handler_type="command",
                                handler_config=entry,
                                description=f"Hook from {hook_file.stem}: {event_name}",
                                source="copilot-cli:hooks",
                            )
                        )
            except (json.JSONDecodeError, OSError):
                pass
        return hooks

    def _has_observal_hooks(self, hooks_dir: Path) -> bool:
        """Check if any hook file in the directory contains Observal markers."""
        if not hooks_dir.is_dir():
            return False
        for hook_file in hooks_dir.glob("*.json"):
            try:
                data = json.loads(hook_file.read_text())
                hook_events = data.get("hooks", {})
                for _evt, entries in hook_events.items():
                    if isinstance(entries, list):
                        for h in entries:
                            if isinstance(h, dict):
                                cmd = h.get("bash", "") + h.get("command", "")
                                if any(m in cmd for m in _OBSERVAL_HOOK_MARKERS):
                                    return True
            except (json.JSONDecodeError, OSError):
                pass
        return False


register_adapter(CopilotCliAdapter())
