# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Kiro IDE adapter."""

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
    extract_mcp_servers,
    first_content_line,
    parse_frontmatter_field,
)


class KiroAdapter(BaseAdapter):
    """Adapter for Kiro (AWS)."""

    managed_agent_files = ("user:agents/{name}.json", "project:.kiro/agents/{name}.json")
    managed_skill_files = ("user:skills/{name}/SKILL.md",)

    @property
    def ide_name(self) -> str:
        return "kiro"

    def scan_home(self, home: Path | None = None) -> ScanResult:
        home = home or Path.home()
        kiro_dir = home / ".kiro"
        if not kiro_dir.exists():
            return ScanResult()
        return self._scan_kiro_dir(kiro_dir)

    def scan_project(self, project_dir: Path) -> ScanResult:
        mcp_file = project_dir / ".kiro" / "settings" / "mcp.json"
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
                        description=f"Kiro project MCP: {name}",
                        source="kiro:project",
                    )
                )
            return ScanResult(mcps=mcps)
        except (json.JSONDecodeError, OSError):
            return ScanResult()

    def get_hook_spec(self) -> HookSpec:
        return HookSpec(
            events=[
                "on_agent_start",
                "on_agent_end",
                "on_tool_start",
                "on_tool_end",
                "on_error",
            ],
            format="http",
            markers=["observal", "OBSERVAL"],
        )

    def generate_hook_config(
        self,
        observal_url: str,
        api_key: str,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        from observal_cli.ide_specs.kiro_hooks_spec import build_kiro_hooks

        return build_kiro_hooks()

    def detect_hooks(self, config_dir: Path) -> str:
        agents_dir = config_dir / "agents"
        if not agents_dir.is_dir():
            return "missing"
        agent_files = [f for f in agents_dir.glob("*.json") if f.stem != "kiro_default"]
        if not agent_files:
            return "missing"
        hooked = 0
        for af in agent_files:
            try:
                data = json.loads(af.read_text())
                hooks = data.get("hooks", {})
                for _evt, entries in hooks.items():
                    if isinstance(entries, list) and any(
                        any(m in h.get("command", "") for m in _OBSERVAL_HOOK_MARKERS)
                        for h in entries
                        if isinstance(h, dict)
                    ):
                        hooked += 1
                        break
            except (json.JSONDecodeError, OSError):
                pass
        if hooked == len(agent_files):
            return "installed"
        return "partial" if hooked > 0 else "missing"

    def shim_status(self, mcps: list[DiscoveredMcp]) -> str:
        return super().shim_status(mcps)

    # ── Private scanning helpers ──────────────────────────────────

    def _scan_kiro_dir(self, kiro_dir: Path) -> ScanResult:
        """Scan ~/.kiro for agents, MCP servers, and hooks."""
        mcps: list[DiscoveredMcp] = []
        skills: list[DiscoveredSkill] = []
        hooks: list[DiscoveredHook] = []
        agents: list[DiscoveredAgent] = []

        mcp_file = kiro_dir / "settings" / "mcp.json"
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
                            description=f"Kiro global MCP: {srv_name}",
                            source="kiro:global",
                        )
                    )
            except (json.JSONDecodeError, OSError):
                pass

        agents_dir = kiro_dir / "agents"
        if agents_dir.is_dir():
            for agent_file in sorted(agents_dir.glob("*.json")):
                if agent_file.stem == "kiro_default":
                    continue
                try:
                    data = json.loads(agent_file.read_text())
                    name = data.get("name", agent_file.stem)
                    desc = data.get("description") or ""
                    model = data.get("model") or ""
                    prompt = data.get("prompt") or ""

                    agents.append(
                        DiscoveredAgent(
                            name=name,
                            description=desc or f"Kiro agent: {name}",
                            model_name=model,
                            prompt=prompt,
                            source_file=str(agent_file),
                        )
                    )

                    agent_mcps = data.get("mcpServers", {})
                    for srv_name, srv_config in agent_mcps.items():
                        if isinstance(srv_config, dict):
                            mcps.append(
                                DiscoveredMcp(
                                    name=srv_name,
                                    command=srv_config.get("command"),
                                    args=srv_config.get("args", []),
                                    url=srv_config.get("url"),
                                    description=f"From Kiro agent: {name}",
                                    source=f"kiro:agent:{name}",
                                )
                            )

                    agent_hooks = data.get("hooks", {})
                    for event_name, event_handlers in agent_hooks.items():
                        hook_name = f"kiro:{name}/{event_name}"
                        handler_config = {}
                        if isinstance(event_handlers, list) and event_handlers:
                            handler_config = event_handlers[0] if isinstance(event_handlers[0], dict) else {}
                        hooks.append(
                            DiscoveredHook(
                                name=hook_name,
                                event=event_name,
                                handler_type="command",
                                handler_config=handler_config,
                                description=f"Kiro hook: {event_name} on agent {name}",
                                source=f"kiro:agent:{name}",
                            )
                        )
                except (json.JSONDecodeError, OSError):
                    pass

        skills_dir = kiro_dir / "skills"
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
                        has_frontmatter = content.startswith("---")
                        if has_frontmatter:
                            desc = first_content_line(content)
                        else:
                            for line in content.splitlines():
                                stripped = line.strip()
                                if stripped and not stripped.startswith("#"):
                                    desc = stripped[:200]
                                    break
                except OSError:
                    pass
                skills.append(
                    DiscoveredSkill(
                        name=skill_name,
                        description=desc or f"Kiro skill: {skill_name}",
                        source="kiro:skills",
                        task_type=task_type,
                    )
                )

        # Deduplicate MCPs
        seen: set[str] = set()
        deduped: list[DiscoveredMcp] = []
        for m in mcps:
            if m.name not in seen:
                deduped.append(m)
                seen.add(m.name)

        return ScanResult(mcps=deduped, skills=skills, hooks=hooks, agents=agents)


register_adapter(KiroAdapter())
