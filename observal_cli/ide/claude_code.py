# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Claude Code IDE adapter."""

from __future__ import annotations

import json
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
from observal_cli.shared.utils import (
    _OBSERVAL_HOOK_MARKERS,
    extract_body,
    extract_mcp_servers,
    first_content_line,
    parse_frontmatter_field,
)


class ClaudeCodeAdapter(BaseAdapter):
    """Adapter for Claude Code (Anthropic)."""

    managed_agent_files = ("user:agents/{name}.md", "project:.claude/agents/{name}.md")
    managed_skill_files = ("user:skills/{name}/SKILL.md",)

    @property
    def ide_name(self) -> str:
        return "claude-code"

    def scan_home(self, home: Path | None = None) -> ScanResult:
        home = home or Path.home()
        claude_dir = home / ".claude"
        if not claude_dir.exists():
            return ScanResult()
        return self._scan_claude_dir(claude_dir)

    def scan_project(self, project_dir: Path) -> ScanResult:
        # Claude Code uses .mcp.json at project root
        mcp_file = project_dir / ".mcp.json"
        if not mcp_file.exists():
            return ScanResult()
        try:
            data = json.loads(mcp_file.read_text())
            servers = extract_mcp_servers(data)
            mcps = []
            for name, cfg in servers.items():
                mcps.append(
                    DiscoveredMcp(
                        name=name,
                        command=cfg.get("command"),
                        args=cfg.get("args", []),
                        url=cfg.get("url"),
                        description=f"Claude Code project MCP: {name}",
                        source="claude-code:project",
                    )
                )
            return ScanResult(mcps=mcps)
        except (json.JSONDecodeError, OSError):
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
        settings = config_dir / "settings.json"
        if not settings.exists():
            return "missing"
        try:
            data = json.loads(settings.read_text())
        except (json.JSONDecodeError, OSError):
            return "missing"
        hooks = data.get("hooks", {})
        if not hooks:
            return "missing"
        found = 0
        for _evt, groups in hooks.items():
            if not isinstance(groups, list):
                continue
            for g in groups:
                for h in g.get("hooks", []):
                    cmd = h.get("command", "")
                    url = h.get("url", "")
                    if any(m in cmd or m in url for m in _OBSERVAL_HOOK_MARKERS):
                        found += 1
                        break
        return "installed" if found >= 3 else ("partial" if found > 0 else "missing")

    def shim_status(self, mcps: list[DiscoveredMcp]) -> str:
        return super().shim_status(mcps)

    # ── Private scanning helpers ──────────────────────────────────

    def _scan_claude_dir(self, claude_dir: Path) -> ScanResult:
        """Scan ~/.claude for all component types."""
        mcps: list[DiscoveredMcp] = []
        skills: list[DiscoveredSkill] = []
        hooks: list[DiscoveredHook] = []
        agents: list[DiscoveredAgent] = []

        settings_file = claude_dir / "settings.json"
        if not settings_file.exists():
            return ScanResult()

        try:
            settings = json.loads(settings_file.read_text())
        except (json.JSONDecodeError, OSError):
            return ScanResult()

        enabled_plugins = settings.get("enabledPlugins", {})
        active_plugins = {name for name, enabled in enabled_plugins.items() if enabled}

        # Load installed_plugins.json to get install paths
        installed_file = claude_dir / "plugins" / "installed_plugins.json"
        plugin_paths: dict[str, Path] = {}
        if installed_file.exists():
            try:
                installed = json.loads(installed_file.read_text())
                for plugin_key, entries in installed.get("plugins", {}).items():
                    if plugin_key in active_plugins and entries:
                        install_path = entries[0].get("installPath")
                        if install_path:
                            plugin_paths[plugin_key] = Path(install_path)
            except (json.JSONDecodeError, OSError):
                pass

        # Fallback: scan plugin cache directly
        cache_dir = claude_dir / "plugins" / "cache"
        if cache_dir.exists():
            for plugin_key in active_plugins:
                if plugin_key in plugin_paths:
                    continue
                parts = plugin_key.split("@", 1)
                name = parts[0]
                marketplace = parts[1] if len(parts) > 1 else ""
                market_dir = cache_dir / marketplace / name if marketplace else cache_dir / name / name
                if market_dir.exists():
                    versions = sorted(market_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
                    if versions:
                        plugin_paths[plugin_key] = versions[0]

        for plugin_key, plugin_dir in plugin_paths.items():
            if not plugin_dir.is_dir():
                continue

            plugin_name = plugin_key.split("@")[0]
            plugin_desc = f"Plugin: {plugin_name}"
            plugin_json = plugin_dir / ".claude-plugin" / "plugin.json"
            if plugin_json.exists():
                try:
                    meta = json.loads(plugin_json.read_text())
                    plugin_desc = meta.get("description", plugin_desc)
                except (json.JSONDecodeError, OSError):
                    pass

            mcp_file = plugin_dir / ".mcp.json"
            if mcp_file.exists():
                try:
                    mcp_data = json.loads(mcp_file.read_text())
                    servers = extract_mcp_servers(mcp_data)
                    for srv_name, srv_config in servers.items():
                        mcps.append(
                            DiscoveredMcp(
                                name=srv_name,
                                command=srv_config.get("command"),
                                args=srv_config.get("args", []),
                                url=srv_config.get("url"),
                                description=plugin_desc,
                                source=f"plugin:{plugin_name}",
                            )
                        )
                except (json.JSONDecodeError, OSError):
                    pass

            for skill_md in plugin_dir.rglob("SKILL.md"):
                skill_name_part = skill_md.parent.name
                full_name = f"{plugin_name}/{skill_name_part}"
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
                        name=full_name,
                        description=desc or f"Skill from {plugin_name}",
                        source=f"plugin:{plugin_name}",
                    )
                )

            for hooks_file in plugin_dir.rglob("hooks.json"):
                try:
                    hooks_data = json.loads(hooks_file.read_text())
                    hook_events = hooks_data.get("hooks", {})
                    for event_name, event_hooks in hook_events.items():
                        hook_full_name = f"{plugin_name}/{event_name}"
                        handler_type = "command"
                        handler_config = {}
                        if isinstance(event_hooks, list) and event_hooks:
                            first = event_hooks[0]
                            if isinstance(first, dict):
                                inner = first.get("hooks", [first])
                                if inner and isinstance(inner[0], dict):
                                    handler_type = inner[0].get("type", "command")
                                    handler_config = inner[0]
                        hooks.append(
                            DiscoveredHook(
                                name=hook_full_name,
                                event=event_name,
                                handler_type=handler_type,
                                handler_config=handler_config,
                                description=f"Hook from {plugin_name}: {event_name}",
                                source=f"plugin:{plugin_name}",
                            )
                        )
                except (json.JSONDecodeError, OSError):
                    pass

        # Skills from ~/.claude/skills/
        skills_dir = claude_dir / "skills"
        if skills_dir.is_dir():
            for skill_md in sorted(skills_dir.rglob("SKILL.md")):
                skill_name = skill_md.parent.name
                desc = ""
                task_type = "general"
                try:
                    content = skill_md.read_text()
                    desc = parse_frontmatter_field(content, "description") or ""
                    task_type = parse_frontmatter_field(content, "task_type") or "general"
                    if not desc:
                        desc = first_content_line(content)
                except OSError:
                    pass
                skills.append(
                    DiscoveredSkill(
                        name=skill_name,
                        description=desc or f"Skill: {skill_name}",
                        source="claude:skills",
                        task_type=task_type,
                    )
                )

        # Agents from ~/.claude/agents/
        agents_dir = claude_dir / "agents"
        if agents_dir.is_dir():
            for agent_md in sorted(agents_dir.glob("*.md")):
                try:
                    content = agent_md.read_text()
                    name = agent_md.stem
                    model = parse_frontmatter_field(content, "model") or ""
                    desc = first_content_line(content)
                    prompt_body = extract_body(content)
                    agents.append(
                        DiscoveredAgent(
                            name=name,
                            description=desc or f"Agent: {name}",
                            model_name=model,
                            prompt=prompt_body,
                            source_file=str(agent_md),
                        )
                    )
                except OSError:
                    pass

        return ScanResult(mcps=mcps, skills=skills, hooks=hooks, agents=agents)


register_adapter(ClaudeCodeAdapter())
