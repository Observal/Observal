# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""OpenCode IDE adapter.

First-class adapter for OpenCode. Handles scanning of MCP servers, skills,
agents, and hooks from both project-level and global config directories.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

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

_JSONC_COMMENT_RE = re.compile(
    r'("(?:[^"\\]|\\.)*")|//[^\n]*|/\*.*?\*/',
    re.DOTALL,
)


def _strip_jsonc_comments(text: str) -> str:
    """Strip // and /* */ comments from JSONC, preserving strings."""

    def _replacer(m: re.Match) -> str:
        if m.group(1) is not None:
            return m.group(1)
        return ""

    return _JSONC_COMMENT_RE.sub(_replacer, text)


class OpenCodeAdapter(BaseAdapter):
    """Adapter for OpenCode."""

    managed_agent_files = ("user:agents/{name}.md", "project:.opencode/agents/{name}.md")
    managed_skill_files = ("user:skills/{name}/SKILL.md", "project:.opencode/skills/{name}/SKILL.md")

    @property
    def ide_name(self) -> str:
        return "opencode"

    def scan_home(self, home: Path | None = None) -> ScanResult:
        home = home or Path.home()
        opencode_dir = home / ".config" / "opencode"
        if not opencode_dir.exists():
            return ScanResult()
        return self._scan_opencode_dir(opencode_dir, "opencode:global", home=home)

    def scan_project(self, project_dir: Path) -> ScanResult:
        result = ScanResult()
        # Project-level opencode.json for MCP servers
        config_file = project_dir / "opencode.json"
        if config_file.exists():
            mcp_result = self._parse_opencode_config(config_file, "opencode:project")
            result.mcps.extend(mcp_result.mcps)

        # Project-level .opencode/ directory for agents, skills, plugins
        opencode_dir = project_dir / ".opencode"
        if opencode_dir.exists():
            dir_result = self._scan_opencode_project_dir(opencode_dir)
            result.skills.extend(dir_result.skills)
            result.agents.extend(dir_result.agents)
            result.hooks.extend(dir_result.hooks)
            result.mcps.extend(dir_result.mcps)

        return result

    def get_hook_spec(self) -> HookSpec:
        return HookSpec(
            events=[
                "session.created",
                "session.idle",
                "message.updated",
                "tool.execute.before",
                "tool.execute.after",
            ],
            format="plugin",
            markers=["observal", "Observal", "ObservalPlugin"],
        )

    def generate_hook_config(
        self,
        observal_url: str,
        api_key: str,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        from observal_cli.ide_specs.opencode_hooks_spec import build_hooks

        return build_hooks()

    def detect_hooks(self, config_dir: Path) -> str:
        """Detect if the Observal plugin is installed in OpenCode.

        Checks the global plugin directory (config_dir/plugins) which is
        the canonical install location for `observal pull` with user scope.
        """
        plugins_dir = config_dir / "plugins"
        if not plugins_dir.exists():
            return "missing"

        for plugin_file in plugins_dir.iterdir():
            if not plugin_file.is_file():
                continue
            if plugin_file.suffix not in (".ts", ".js", ".mjs"):
                continue
            try:
                content = plugin_file.read_text(errors="ignore")
                if "ObservalPlugin" in content or "observal" in content.lower():
                    return "installed"
            except OSError:
                continue

        return "missing"

    def shim_status(self, mcps: list[DiscoveredMcp]) -> str:
        return super().shim_status(mcps)

    # ── Internal helpers ──────────────────────────────────────────────

    def _scan_opencode_dir(self, opencode_dir: Path, source: str, home: Path | None = None) -> ScanResult:
        """Scan a global ~/.config/opencode/ directory for all components."""
        result = ScanResult()

        # MCP servers from opencode.json
        config_file = opencode_dir / "opencode.json"
        if not config_file.exists():
            config_file = opencode_dir / "opencode.jsonc"
        if config_file.exists():
            mcp_result = self._parse_opencode_config(config_file, source)
            result.mcps.extend(mcp_result.mcps)

        # Skills from skills/ directory
        skills_dir = opencode_dir / "skills"
        if skills_dir.exists():
            result.skills.extend(self._scan_skills_dir(skills_dir, source))

        # Agents from agents/ directory
        agents_dir = opencode_dir / "agents"
        if agents_dir.exists():
            result.agents.extend(self._scan_agents_dir(agents_dir, source))

        # Plugins/hooks from plugins/ directory
        plugins_dir = opencode_dir / "plugins"
        if plugins_dir.exists():
            result.hooks.extend(self._scan_plugins_dir(plugins_dir, source))

        return result

    def _scan_opencode_project_dir(self, opencode_dir: Path) -> ScanResult:
        """Scan a project-level .opencode/ directory."""
        result = ScanResult()
        source = "opencode:project"

        # Skills
        skills_dir = opencode_dir / "skills"
        if skills_dir.exists():
            result.skills.extend(self._scan_skills_dir(skills_dir, source))

        # Agents
        agents_dir = opencode_dir / "agents"
        if agents_dir.exists():
            result.agents.extend(self._scan_agents_dir(agents_dir, source))

        # Plugins (hooks)
        plugins_dir = opencode_dir / "plugins"
        if plugins_dir.exists():
            result.hooks.extend(self._scan_plugins_dir(plugins_dir, source))

        return result

    def _parse_opencode_config(self, config_file: Path, source: str) -> ScanResult:
        """Parse an opencode.json config and extract MCP servers."""
        try:
            raw = config_file.read_text()
            data = json.loads(_strip_jsonc_comments(raw))
            servers = data.get("mcp", {})
            mcps = []
            for srv_name, srv_config in servers.items():
                if isinstance(srv_config, dict):
                    cmd = srv_config.get("command")
                    if isinstance(cmd, list):
                        command = cmd[0] if cmd else None
                        args = cmd[1:] if len(cmd) > 1 else []
                    else:
                        command = cmd
                        args = srv_config.get("args", [])
                    mcps.append(
                        DiscoveredMcp(
                            name=srv_name,
                            command=command,
                            args=args,
                            url=srv_config.get("url"),
                            description=f"OpenCode MCP: {srv_name}",
                            source=source,
                        )
                    )
            return ScanResult(mcps=mcps)
        except (json.JSONDecodeError, OSError):
            return ScanResult()

    def _scan_skills_dir(self, skills_dir: Path, source: str) -> list[DiscoveredSkill]:
        """Scan a skills/ directory for SKILL.md files."""
        skills: list[DiscoveredSkill] = []
        if not skills_dir.is_dir():
            return skills

        for skill_folder in sorted(skills_dir.iterdir()):
            if not skill_folder.is_dir():
                continue
            skill_file = skill_folder / "SKILL.md"
            if not skill_file.exists():
                continue
            try:
                content = skill_file.read_text(errors="ignore")
                name = skill_folder.name
                description = self._extract_frontmatter_field(content, "description") or ""
                skills.append(
                    DiscoveredSkill(
                        name=name,
                        description=description,
                        source=source,
                    )
                )
            except OSError:
                continue
        return skills

    def _scan_agents_dir(self, agents_dir: Path, source: str) -> list[DiscoveredAgent]:
        """Scan an agents/ directory for markdown agent definitions."""
        agents: list[DiscoveredAgent] = []
        if not agents_dir.is_dir():
            return agents

        for agent_file in sorted(agents_dir.iterdir()):
            if not agent_file.is_file():
                continue
            if agent_file.suffix != ".md":
                continue
            try:
                content = agent_file.read_text(errors="ignore")
                name = agent_file.stem
                description = self._extract_frontmatter_field(content, "description") or ""
                agents.append(
                    DiscoveredAgent(
                        name=name,
                        description=description,
                        source=source,
                    )
                )
            except OSError:
                continue
        return agents

    def _scan_plugins_dir(self, plugins_dir: Path, source: str) -> list[DiscoveredHook]:
        """Scan a plugins/ directory for hook/plugin files."""
        hooks: list[DiscoveredHook] = []
        if not plugins_dir.is_dir():
            return hooks

        for plugin_file in sorted(plugins_dir.iterdir()):
            if not plugin_file.is_file():
                continue
            if plugin_file.suffix not in (".ts", ".js", ".mjs"):
                continue
            try:
                name = plugin_file.stem
                hooks.append(
                    DiscoveredHook(
                        name=name,
                        event="plugin",
                        source=source,
                    )
                )
            except OSError:
                continue
        return hooks

    def _extract_frontmatter_field(self, content: str, field: str) -> str | None:
        """Extract a top-level field from YAML frontmatter in a markdown file."""
        if not content.startswith("---"):
            return None
        parts = content.split("---", 2)
        if len(parts) < 3:
            return None
        frontmatter = parts[1]
        prefix = f"{field}:"
        for line in frontmatter.splitlines():
            # Only match top-level keys (no leading whitespace)
            if line.startswith((" ", "\t")):
                continue
            stripped = line.strip()
            if not stripped.startswith(prefix):
                continue
            value = stripped[len(prefix) :].strip()
            if value and value[0] in ('"', "'") and value[-1] == value[0]:
                value = value[1:-1]
            return value
        return None


register_adapter(OpenCodeAdapter())
