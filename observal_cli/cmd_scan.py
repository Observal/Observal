# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-FileCopyrightText: 2026 Devaansh Dubey <devaanshdubey@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 Shreem Seth <shreemseth26@gmail.com>
# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""observal scan: read-only inventory of local IDE setup."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

import typer
from rich import print as rprint
from rich.table import Table

from observal_cli.ide import DiscoveredAgent, DiscoveredHook, DiscoveredMcp, DiscoveredSkill
from observal_cli.render import console, spinner
from observal_cli.shared.utils import (
    _OBSERVAL_HOOK_MARKERS,
)
from observal_cli.shared.utils import (
    extract_mcp_servers as _extract_mcp_servers,
)
from observal_cli.shared.utils import (
    is_already_shimmed as _is_already_shimmed,
)

_OBSERVAL_NS = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")


def _deterministic_mcp_id(name: str) -> str:
    """Generate a stable UUID for an MCP based on its name."""
    return str(uuid.uuid5(_OBSERVAL_NS, name))


# ── IDE config file locations (relative to project root) ────

_IDE_PROJECT_CONFIGS = {
    "cursor": ".cursor/mcp.json",
    "kiro": ".kiro/settings/mcp.json",
    "vscode": ".vscode/mcp.json",
    "copilot": ".vscode/mcp.json",
    "copilot-cli": ".mcp.json",
    "gemini-cli": ".gemini/settings.json",
    "opencode": "opencode.json",
    "codex": ".codex/config.toml",
}


# ── Data containers for discovered items ────────────────────

# ── Claude Code ~/.claude scanner ───────────────────────────


def _scan_claude_home(
    claude_dir: Path,
) -> tuple[list[DiscoveredMcp], list[DiscoveredSkill], list[DiscoveredHook], list[DiscoveredAgent]]:
    """Scan ~/.claude for all component types using the real plugin system."""
    mcps: list[DiscoveredMcp] = []
    skills: list[DiscoveredSkill] = []
    hooks: list[DiscoveredHook] = []
    agents: list[DiscoveredAgent] = []

    settings_file = claude_dir / "settings.json"
    if not settings_file.exists():
        return mcps, skills, hooks, agents

    try:
        settings = json.loads(settings_file.read_text())
    except (json.JSONDecodeError, OSError):
        return mcps, skills, hooks, agents

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

    # Fallback: also scan plugin cache directly for active plugins
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
                servers = _extract_mcp_servers(mcp_data)
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
                desc = _parse_frontmatter_field(content, "description") or ""
                if not desc:
                    desc = _first_content_line(content)
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

    skills_dir = claude_dir / "skills"
    if skills_dir.is_dir():
        for skill_md in sorted(skills_dir.rglob("SKILL.md")):
            skill_name = skill_md.parent.name
            desc = ""
            task_type = "general"
            try:
                content = skill_md.read_text()
                desc = _parse_frontmatter_field(content, "description") or ""
                task_type = _parse_frontmatter_field(content, "task_type") or "general"
                if not desc:
                    desc = _first_content_line(content)
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

    agents_dir = claude_dir / "agents"
    if agents_dir.is_dir():
        for agent_md in sorted(agents_dir.glob("*.md")):
            try:
                content = agent_md.read_text()
                name = agent_md.stem
                model = _parse_frontmatter_field(content, "model") or ""
                desc = _first_content_line(content)
                prompt_body = _extract_body(content)
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

    return mcps, skills, hooks, agents


# ── Kiro ~/.kiro scanner ────────────────────────────────────


def _scan_kiro_home(
    kiro_dir: Path,
) -> tuple[list[DiscoveredMcp], list[DiscoveredSkill], list[DiscoveredHook], list[DiscoveredAgent]]:
    """Scan ~/.kiro for agents, MCP servers, and hooks."""
    mcps: list[DiscoveredMcp] = []
    skills: list[DiscoveredSkill] = []
    hooks: list[DiscoveredHook] = []
    agents: list[DiscoveredAgent] = []

    mcp_file = kiro_dir / "settings" / "mcp.json"
    if mcp_file.exists():
        try:
            mcp_data = json.loads(mcp_file.read_text())
            servers = _extract_mcp_servers(mcp_data)
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
                desc = _parse_frontmatter_field(content, "description") or ""
                task_type = _parse_frontmatter_field(content, "task_type") or "general"
                if not desc:
                    has_frontmatter = content.startswith("---")
                    if has_frontmatter:
                        desc = _first_content_line(content)
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

    seen: set[str] = set()
    deduped: list[DiscoveredMcp] = []
    for m in mcps:
        if m.name not in seen:
            deduped.append(m)
            seen.add(m.name)
    mcps = deduped

    return mcps, skills, hooks, agents


def _scan_gemini_home(
    gemini_dir: Path,
) -> tuple[list[DiscoveredMcp], list[DiscoveredSkill], list[DiscoveredHook], list[DiscoveredAgent]]:
    """Scan ~/.gemini for MCP servers from settings.json."""
    mcps: list[DiscoveredMcp] = []
    skills: list[DiscoveredSkill] = []
    hooks: list[DiscoveredHook] = []
    agents: list[DiscoveredAgent] = []

    settings_file = gemini_dir / "settings.json"
    if settings_file.exists():
        try:
            settings = json.loads(settings_file.read_text())
            servers = _extract_mcp_servers(settings)
            for srv_name, srv_config in servers.items():
                mcps.append(
                    DiscoveredMcp(
                        name=srv_name,
                        command=srv_config.get("command"),
                        args=srv_config.get("args", []),
                        url=srv_config.get("url"),
                        description=f"Gemini MCP: {srv_name}",
                        source="gemini:global",
                    )
                )
        except (json.JSONDecodeError, OSError):
            pass

    return mcps, skills, hooks, agents


def _scan_codex_home(
    codex_dir: Path,
) -> tuple[list[DiscoveredMcp], list[DiscoveredSkill], list[DiscoveredHook], list[DiscoveredAgent]]:
    """Scan ~/.codex for MCP servers from config.toml."""
    mcps: list[DiscoveredMcp] = []
    skills: list[DiscoveredSkill] = []
    hooks: list[DiscoveredHook] = []
    agents: list[DiscoveredAgent] = []

    config_file = codex_dir / "config.toml"
    if config_file.exists():
        try:
            try:
                import tomllib as toml
            except ImportError:
                try:
                    import tomli as toml  # type: ignore[no-redef]
                except ImportError:
                    import toml  # type: ignore[no-redef]
            content = config_file.read_text()
            data = toml.loads(content) if hasattr(toml, "loads") else toml.load(config_file.open("rb"))  # type: ignore[call-arg]
            servers = data.get("mcp", {}).get("servers", {})
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
        except Exception:
            pass

    return mcps, skills, hooks, agents


def _scan_copilot_home(
    vscode_dir: Path,
) -> tuple[list[DiscoveredMcp], list[DiscoveredSkill], list[DiscoveredHook], list[DiscoveredAgent]]:
    """Scan ~/.vscode or project .vscode for Copilot MCP servers from mcp.json."""
    mcps: list[DiscoveredMcp] = []
    skills: list[DiscoveredSkill] = []
    hooks: list[DiscoveredHook] = []
    agents: list[DiscoveredAgent] = []

    mcp_file = vscode_dir / "mcp.json"
    if mcp_file.exists():
        try:
            data = json.loads(mcp_file.read_text())
            servers = data.get("servers", data.get("mcpServers", {}))
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
        except (json.JSONDecodeError, OSError):
            pass

    return mcps, skills, hooks, agents


def _scan_copilot_cli_home(
    copilot_dir: Path,
) -> tuple[list[DiscoveredMcp], list[DiscoveredSkill], list[DiscoveredHook], list[DiscoveredAgent]]:
    """Scan ~/.copilot for MCP servers from mcp-config.json."""
    mcps: list[DiscoveredMcp] = []
    skills: list[DiscoveredSkill] = []
    hooks: list[DiscoveredHook] = []
    agents: list[DiscoveredAgent] = []

    mcp_file = copilot_dir / "mcp-config.json"
    if mcp_file.exists():
        try:
            data = json.loads(mcp_file.read_text())
            servers = data.get("mcpServers", {})
            for srv_name, srv_config in servers.items():
                if isinstance(srv_config, dict):
                    mcps.append(
                        DiscoveredMcp(
                            name=srv_name,
                            command=srv_config.get("command"),
                            args=srv_config.get("args", []),
                            url=srv_config.get("url"),
                            description=f"Copilot CLI MCP: {srv_name}",
                            source="copilot-cli:global",
                        )
                    )
        except (json.JSONDecodeError, OSError):
            pass

    return mcps, skills, hooks, agents


def _scan_opencode_home(
    opencode_dir: Path,
) -> tuple[list[DiscoveredMcp], list[DiscoveredSkill], list[DiscoveredHook], list[DiscoveredAgent]]:
    """Scan ~/.config/opencode for MCP servers from opencode.json."""
    mcps: list[DiscoveredMcp] = []
    skills: list[DiscoveredSkill] = []
    hooks: list[DiscoveredHook] = []
    agents: list[DiscoveredAgent] = []

    config_file = opencode_dir / "opencode.json"
    if config_file.exists():
        try:
            data = json.loads(config_file.read_text())
            servers = data.get("mcp", {})
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
                            source="opencode:global",
                        )
                    )
        except (json.JSONDecodeError, OSError):
            pass

    return mcps, skills, hooks, agents


def _parse_frontmatter_field(content: str, field: str) -> str | None:
    """Extract a field from YAML frontmatter (--- delimited)."""
    match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return None
    for line in match.group(1).splitlines():
        if line.startswith(f"{field}:"):
            val = line[len(field) + 1 :].strip().strip('"').strip("'")
            return val
    return None


def _extract_body(content: str) -> str:
    """Extract everything after YAML frontmatter."""
    match = re.match(r"^---\s*\n.*?\n---\s*\n?", content, re.DOTALL)
    if match:
        return content[match.end() :]
    return content


def _first_content_line(content: str) -> str:
    """Get first non-empty, non-heading content line after frontmatter."""
    in_frontmatter = False
    past_frontmatter = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped == "---":
            if not in_frontmatter:
                in_frontmatter = True
                continue
            else:
                past_frontmatter = True
                continue
        if not past_frontmatter and in_frontmatter:
            continue
        if past_frontmatter and stripped and not stripped.startswith("#"):
            return stripped[:200]
    return ""


# ── Project-dir scanner (Cursor, VS Code, Kiro, Gemini) ────


def _scan_project_dir(project_dir: Path, ide_filter: str | None) -> list[tuple[str, str, DiscoveredMcp, Path, bool]]:
    """Scan project directory for IDE MCP configs. Returns (ide, name, mcp, config_path, shimmed) tuples."""
    found = []
    for ide, rel in _IDE_PROJECT_CONFIGS.items():
        if ide_filter and ide != ide_filter:
            continue
        config_path = project_dir / rel
        if not config_path.exists():
            continue

        try:
            if config_path.suffix == ".toml":
                try:
                    import tomllib as toml
                except ImportError:
                    try:
                        import tomli as toml
                    except ImportError:
                        try:
                            import toml
                        except ImportError:
                            rprint("[yellow]Warning: no toml parser found. Skipping .toml config.[/yellow]")
                            continue
                config = toml.loads(config_path.read_text())
            else:
                config = json.loads(config_path.read_text())
        except (Exception, OSError):
            continue

        servers = _parse_project_mcp_servers(config, ide)
        for name, entry in servers.items():
            shimmed = _is_already_shimmed(entry)
            found.append(
                (
                    ide,
                    name,
                    DiscoveredMcp(
                        name=name,
                        command=entry.get("command"),
                        args=entry.get("args", []),
                        url=entry.get("url"),
                        description=f"MCP from {ide} config",
                        source=f"ide:{ide}",
                    ),
                    config_path,
                    shimmed,
                )
            )
    return found


def _parse_project_mcp_servers(config: dict, ide: str) -> dict[str, dict]:
    """Extract MCP servers dict from project-level IDE config."""
    if ide in ("vscode", "copilot"):
        return config.get("servers", config.get("mcpServers", {}))
    if ide == "copilot-cli":
        return config.get("mcpServers", {})
    if ide == "opencode":
        return config.get("mcp", {})
    if ide == "codex":
        return config.get("mcp", {}).get("servers", {})
    return config.get("mcpServers", config.get("servers", {}))


# ── Hook status detection ─────────────────────────────────────


def _has_observal_hooks_claude(claude_dir: Path) -> str:
    """Return hook status for Claude Code: 'installed', 'partial', or 'missing'."""
    settings = claude_dir / "settings.json"
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


def _has_observal_hooks_kiro(kiro_dir: Path) -> str:
    """Return hook status for Kiro agents."""
    agents_dir = kiro_dir / "agents"
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


def _has_observal_hooks_gemini(gemini_dir: Path) -> str:
    """Return hook status for Gemini CLI."""
    settings = gemini_dir / "settings.json"
    if not settings.exists():
        return "missing"
    try:
        data = json.loads(settings.read_text())
    except (json.JSONDecodeError, OSError):
        return "missing"
    hooks = data.get("hooks", {})
    if not hooks:
        return "missing"
    for _evt, groups in hooks.items():
        if not isinstance(groups, list):
            continue
        for g in groups:
            for h in g.get("hooks", []):
                if any(m in h.get("command", "") for m in _OBSERVAL_HOOK_MARKERS):
                    return "installed"
    return "missing"


def _has_observal_hooks_copilot_cli(copilot_dir: Path) -> str:
    """Return hook status for Copilot CLI."""
    config = copilot_dir / "config.json"
    if not config.exists():
        return "missing"
    try:
        data = json.loads(config.read_text())
    except (json.JSONDecodeError, OSError):
        return "missing"
    hooks = data.get("hooks", {})
    if not hooks:
        return "missing"
    for _evt, entries in hooks.items():
        if isinstance(entries, list):
            for h in entries:
                if isinstance(h, dict) and "telemetry/hooks" in h.get("bash", ""):
                    return "installed"
    return "missing"


def _mcp_shim_status(mcps: list[DiscoveredMcp], project_entries: list) -> str:
    """Return shim summary like '3 of 5 shimmed' or 'all shimmed'."""
    total = 0
    shimmed = 0
    for m in mcps:
        if m.url:
            continue
        total += 1
        cmd = m.command or ""
        args_str = " ".join(str(a) for a in m.args)
        if "observal-shim" in cmd or "observal-shim" in args_str:
            shimmed += 1
    for _ide, _name, _mcp, _path, is_shimmed in project_entries:
        if _mcp.url:
            continue
        total += 1
        if is_shimmed:
            shimmed += 1
    if total == 0:
        return "n/a"
    if shimmed == total:
        return "all shimmed"
    if shimmed == 0:
        return "no shims"
    return f"{shimmed} of {total} shimmed"


def _otel_status_gemini(gemini_dir: Path) -> str:
    """Check if Gemini native OTLP is properly disabled."""
    settings = gemini_dir / "settings.json"
    if not settings.exists():
        return "n/a"
    try:
        data = json.loads(settings.read_text())
    except (json.JSONDecodeError, OSError):
        return "unknown"
    telemetry = data.get("telemetry", {})
    if isinstance(telemetry, dict) and telemetry.get("enabled") is False:
        return "ok (native OTLP disabled)"
    if isinstance(telemetry, dict) and telemetry.get("enabled", False):
        return "needs fix (native OTLP enabled)"
    return "ok"


# ── CLI command ─────────────────────────────────────────────


def register_scan(app: typer.Typer):
    @app.command(name="scan")
    def scan(
        ide: str | None = typer.Option(None, "--ide", "-i", help="Filter to a specific IDE"),
    ):
        """Show a read-only inventory of your local IDE setup.

        Scans all IDE home directories and the current project directory to
        discover agents, MCP servers, skills, and hooks. Shows what's
        instrumented (hooks/shims) and what's missing.

        Use --ide to filter to a specific IDE (e.g. --ide kiro).

        This command never modifies files. To instrument, run:
          observal doctor patch --all --all-ides

        Examples:
            observal scan
            observal scan --ide claude-code
            observal scan --ide kiro
        """
        all_mcps: list[DiscoveredMcp] = []
        all_skills: list[DiscoveredSkill] = []
        all_hooks: list[DiscoveredHook] = []
        all_agents: list[DiscoveredAgent] = []
        project_mcp_entries: list[tuple[str, str, DiscoveredMcp, Path, bool]] = []
        ide_status: list[tuple[str, str, str, str]] = []  # (name, hooks, shims, otel)

        home_scanners = [
            ("claude-code", Path.home() / ".claude", _scan_claude_home, "~/.claude"),
            ("kiro", Path.home() / ".kiro", _scan_kiro_home, "~/.kiro"),
            ("gemini-cli", Path.home() / ".gemini", _scan_gemini_home, "~/.gemini"),
            ("codex", Path.home() / ".codex", _scan_codex_home, "~/.codex"),
            ("copilot", Path.home() / ".vscode", _scan_copilot_home, "~/.vscode"),
            ("copilot-cli", Path.home() / ".copilot", _scan_copilot_cli_home, "~/.copilot"),
            ("opencode", Path.home() / ".config" / "opencode", _scan_opencode_home, "~/.config/opencode"),
        ]

        hook_checkers = {
            "claude-code": lambda: _has_observal_hooks_claude(Path.home() / ".claude"),
            "kiro": lambda: _has_observal_hooks_kiro(Path.home() / ".kiro"),
            "gemini-cli": lambda: _has_observal_hooks_gemini(Path.home() / ".gemini"),
            "copilot-cli": lambda: _has_observal_hooks_copilot_cli(Path.home() / ".copilot"),
        }

        for ide_name, dir_path, scan_fn, label in home_scanners:
            if ide and ide_name != ide:
                continue
            if not dir_path.is_dir():
                continue
            with spinner(f"Scanning {label}..."):
                h_mcps, h_skills, h_hooks, h_agents = scan_fn(dir_path)
            all_mcps.extend(h_mcps)
            all_skills.extend(h_skills)
            all_hooks.extend(h_hooks)
            all_agents.extend(h_agents)

            # Determine status for this IDE
            hook_check = hook_checkers.get(ide_name)
            hook_status = hook_check() if hook_check else "n/a"
            shim_status = _mcp_shim_status(h_mcps, [])
            otel = _otel_status_gemini(dir_path) if ide_name == "gemini-cli" else "n/a"
            ide_status.append((ide_name, hook_status, shim_status, otel))

        # Scan project directory
        root = Path(".").resolve()
        project_mcp_entries = _scan_project_dir(root, ide)
        seen_names = {m.name for m in all_mcps}
        for _ide_name, _name, mcp, _config_path, _shimmed in project_mcp_entries:
            if mcp.name not in seen_names:
                all_mcps.append(mcp)
                seen_names.add(mcp.name)

        if root != Path.home():
            home_project = _scan_project_dir(Path.home(), ide)
            for entry in home_project:
                if entry[2].name not in seen_names:
                    project_mcp_entries.append(entry)
                    all_mcps.append(entry[2])
                    seen_names.add(entry[2].name)

        total = len(all_mcps) + len(all_skills) + len(all_hooks) + len(all_agents)

        if total == 0 and not ide_status:
            rprint("[yellow]No IDE configurations found.[/yellow]")
            raise typer.Exit(1)

        rprint(f"\n[bold]Observal Scan[/bold] — {total} components discovered\n")

        # ── IDEs Detected table ──
        if ide_status:
            tbl = Table(title="IDEs Detected", show_lines=False, padding=(0, 1))
            tbl.add_column("IDE", style="bold")
            tbl.add_column("Hooks", style="cyan")
            tbl.add_column("Shims", style="cyan")
            tbl.add_column("OTel", style="dim")
            for name, hooks_s, shims_s, otel_s in ide_status:
                hooks_style = "green" if hooks_s == "installed" else ("yellow" if hooks_s == "partial" else "red")
                shims_style = (
                    "green"
                    if shims_s == "all shimmed"
                    else ("yellow" if "of" in shims_s else ("dim" if shims_s == "n/a" else "red"))
                )
                tbl.add_row(
                    name,
                    f"[{hooks_style}]{hooks_s}[/{hooks_style}]",
                    f"[{shims_style}]{shims_s}[/{shims_style}]",
                    otel_s,
                )
            console.print(tbl)
            rprint()

        # ── MCP Servers table ──
        if all_mcps:
            tbl = Table(title=f"MCP Servers ({len(all_mcps)})", show_lines=False, padding=(0, 1))
            tbl.add_column("Name", style="bold")
            tbl.add_column("Command/URL", style="dim")
            tbl.add_column("Source", style="cyan")
            tbl.add_column("Shimmed", style="cyan")
            for m in all_mcps:
                is_shimmed = _is_already_shimmed({"command": m.command or "", "args": m.args})
                shimmed_label = "[green]yes[/green]" if is_shimmed else ("[dim]n/a[/dim]" if m.url else "[red]no[/red]")
                tbl.add_row(m.name, m.display_cmd(), m.source, shimmed_label)
            console.print(tbl)
            rprint()

        # ── Skills summary ──
        if all_skills:
            by_plugin: dict[str, int] = {}
            for s in all_skills:
                by_plugin[s.source] = by_plugin.get(s.source, 0) + 1
            tbl = Table(title=f"Skills ({len(all_skills)})", show_lines=False, padding=(0, 1))
            tbl.add_column("Source Plugin", style="cyan")
            tbl.add_column("Count", style="bold", justify="right")
            for src, count in sorted(by_plugin.items()):
                tbl.add_row(src, str(count))
            console.print(tbl)
            rprint()

        # ── Hooks table ──
        if all_hooks:
            tbl = Table(title=f"Hooks ({len(all_hooks)})", show_lines=False, padding=(0, 1))
            tbl.add_column("Name", style="bold")
            tbl.add_column("Event", style="cyan")
            tbl.add_column("Source", style="dim")
            for h in all_hooks:
                tbl.add_row(h.name, h.event, h.source)
            console.print(tbl)
            rprint()

        # ── Agents table ──
        if all_agents:
            tbl = Table(title=f"Agents ({len(all_agents)})", show_lines=False, padding=(0, 1))
            tbl.add_column("Name", style="bold")
            tbl.add_column("Model", style="cyan")
            tbl.add_column("Description", style="dim", max_width=60)
            for a in all_agents:
                tbl.add_row(a.name, a.model_name or "-", a.description[:60])
            console.print(tbl)
            rprint()

        # ── Unregistered components (if authenticated) ──
        try:
            from observal_cli import config as obs_config

            cfg = obs_config.load()
            if cfg.get("access_token") and cfg.get("server_url"):
                import httpx

                server_url = cfg["server_url"].rstrip("/")
                headers = {"Authorization": f"Bearer {cfg['access_token']}"}

                registered_mcps: set[str] = set()
                registered_skills: set[str] = set()
                registered_agents: set[str] = set()

                try:
                    r = httpx.get(f"{server_url}/api/v1/mcp", headers=headers, timeout=5)
                    if r.status_code == 200:
                        for item in r.json():
                            registered_mcps.add(item.get("name", ""))
                except Exception:
                    pass
                try:
                    r = httpx.get(f"{server_url}/api/v1/skills", headers=headers, timeout=5)
                    if r.status_code == 200:
                        for item in r.json():
                            registered_skills.add(item.get("name", ""))
                except Exception:
                    pass
                try:
                    r = httpx.get(f"{server_url}/api/v1/agents", headers=headers, timeout=5)
                    if r.status_code == 200:
                        for item in r.json():
                            registered_agents.add(item.get("name", ""))
                except Exception:
                    pass

                unregistered: list[tuple[str, str]] = []
                for m in all_mcps:
                    if m.name not in registered_mcps:
                        unregistered.append(("mcp", m.name))
                for s in all_skills:
                    if s.name not in registered_skills:
                        unregistered.append(("skill", s.name))
                for a in all_agents:
                    if a.name not in registered_agents:
                        unregistered.append(("agent", a.name))

                if unregistered:
                    # Check if registered-agents-only mode is ON
                    from observal_cli import client as obs_client

                    _reg_only_enabled = obs_client.get_registered_agents_only()

                    if _reg_only_enabled:
                        rprint(
                            "[yellow bold]⚠ Registered-agents-only mode is ON.[/yellow bold] "
                            "Unregistered components below will NOT be traced."
                        )
                        rprint()

                    tbl = Table(
                        title=f"Unregistered Components ({len(unregistered)})", show_lines=False, padding=(0, 1)
                    )
                    tbl.add_column("Type", style="yellow")
                    tbl.add_column("Name", style="bold")
                    for comp_type, comp_name in unregistered[:30]:
                        tbl.add_row(comp_type, comp_name)
                    if len(unregistered) > 30:
                        tbl.add_row("...", f"and {len(unregistered) - 30} more")
                    console.print(tbl)
                    rprint()
        except Exception:
            pass

        # ── Footer with suggestions ──
        missing_hooks = any(h == "missing" or h == "partial" for _, h, _, _ in ide_status)
        missing_shims = any(s not in ("all shimmed", "n/a") for _, _, s, _ in ide_status)

        suggestions = []
        if missing_hooks and missing_shims:
            suggestions.append("Run [bold]observal doctor patch --all --all-ides[/bold] to instrument everything")
        elif missing_hooks:
            suggestions.append("Run [bold]observal doctor patch --hook --all-ides[/bold] to install telemetry hooks")
        elif missing_shims:
            suggestions.append("Run [bold]observal doctor patch --shim --all-ides[/bold] to wrap MCP servers")

        suggestions.append("Use [bold]observal registry <type> submit[/bold] to publish components to the registry")

        if suggestions:
            rprint("[dim]" + " | ".join(suggestions) + "[/dim]")
