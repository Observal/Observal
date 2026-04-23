"""observal scan: auto-detect IDE configs and wrap with telemetry shims."""

from __future__ import annotations

import json
import re
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path

import typer
from rich import print as rprint
from rich.table import Table

from observal_cli.render import console, spinner

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
    "gemini-cli": ".gemini/settings.json",
    "opencode": "opencode.json",
    "codex": ".codex/config.toml",
}


# ── Data containers for discovered items ────────────────────


class DiscoveredMcp:
    def __init__(self, name: str, command: str | None, args: list[str], url: str | None, description: str, source: str):
        self.name = name
        self.command = command
        self.args = args
        self.url = url
        self.description = description
        self.source = source

    def display_cmd(self) -> str:
        if self.url:
            return self.url[:60]
        cmd = f"{self.command or '?'} {' '.join(self.args[:3])}"
        return cmd[:60] + "..." if len(cmd) > 60 else cmd


class DiscoveredSkill:
    def __init__(self, name: str, description: str, source: str, task_type: str = "general"):
        self.name = name
        self.description = description
        self.source = source
        self.task_type = task_type


class DiscoveredHook:
    def __init__(self, name: str, event: str, handler_type: str, handler_config: dict, description: str, source: str):
        self.name = name
        self.event = event
        self.handler_type = handler_type
        self.handler_config = handler_config
        self.description = description
        self.source = source


class DiscoveredAgent:
    def __init__(self, name: str, description: str, model_name: str, prompt: str, source_file: str):
        self.name = name
        self.description = description
        self.model_name = model_name
        self.prompt = prompt
        self.source_file = source_file


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
            # Parse "name@marketplace" format
            parts = plugin_key.split("@", 1)
            name = parts[0]
            marketplace = parts[1] if len(parts) > 1 else ""
            # Try to find in cache
            market_dir = cache_dir / marketplace / name if marketplace else cache_dir / name / name
            if market_dir.exists():
                # Pick latest version directory
                versions = sorted(market_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
                if versions:
                    plugin_paths[plugin_key] = versions[0]

    # Scan each active plugin directory
    for plugin_key, plugin_dir in plugin_paths.items():
        if not plugin_dir.is_dir():
            continue

        plugin_name = plugin_key.split("@")[0]

        # Read plugin metadata
        plugin_desc = f"Plugin: {plugin_name}"
        plugin_json = plugin_dir / ".claude-plugin" / "plugin.json"
        if plugin_json.exists():
            try:
                meta = json.loads(plugin_json.read_text())
                plugin_desc = meta.get("description", plugin_desc)
            except (json.JSONDecodeError, OSError):
                pass

        # ── Discover MCPs ───────────────────────────
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

        # ── Discover Skills ─────────────────────────
        for skill_md in plugin_dir.rglob("SKILL.md"):
            skill_name_part = skill_md.parent.name
            # Unique name: plugin/skill
            full_name = f"{plugin_name}/{skill_name_part}"
            desc = ""
            try:
                content = skill_md.read_text()
                desc = _parse_frontmatter_field(content, "description") or ""
                # If no description in frontmatter, use first non-empty line after frontmatter
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

        # ── Discover Hooks ──────────────────────────
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

    # ── Discover standalone skills from ~/.claude/skills/ ──
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

    # ── Discover Agents from ~/.claude/agents/ ──────
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

    # ── Global MCP servers from ~/.kiro/settings/mcp.json ──
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

    # ── Agents from ~/.kiro/agents/*.json ──
    agents_dir = kiro_dir / "agents"
    if agents_dir.is_dir():
        for agent_file in sorted(agents_dir.glob("*.json")):
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

                # ── Agent-level MCP servers ──
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

                # ── Agent-level hooks ──
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

    # Skills from ~/.kiro/skills/*/SKILL.md
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

    # Deduplicate MCPs by name (global + agent-level may overlap)
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


def _extract_mcp_servers(mcp_data: dict) -> dict[str, dict]:
    """Extract server entries from .mcp.json, handling both formats.

    Format 1 (bare): {"server-name": {"command": "...", "args": [...]}}
    Format 2 (wrapped): {"mcpServers": {"server-name": {"command": "...", "args": [...]}}}
    """
    if "mcpServers" in mcp_data:
        return mcp_data["mcpServers"]
    # Bare format: every top-level key is a server name
    servers = {}
    for key, val in mcp_data.items():
        if isinstance(val, dict) and ("command" in val or "url" in val or "type" in val):
            servers[key] = val
    return servers


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


def _scan_project_dir(project_dir: Path, ide_filter: str | None) -> list[tuple[str, str, DiscoveredMcp, Path]]:
    """Scan project directory for IDE MCP configs. Returns (ide, name, mcp, config_path) tuples."""
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
            if _is_already_shimmed(entry):
                continue
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
                )
            )
    return found


def _parse_project_mcp_servers(config: dict, ide: str) -> dict[str, dict]:
    """Extract MCP servers dict from project-level IDE config."""
    if ide in ("vscode", "copilot"):
        return config.get("servers", config.get("mcpServers", {}))
    if ide == "opencode":
        return config.get("mcp", {})
    if ide == "codex":
        return config.get("mcp", {}).get("servers", {})
    # cursor, kiro, gemini-cli all use mcpServers at top level
    return config.get("mcpServers", config.get("servers", {}))


def _is_already_shimmed(entry: dict) -> bool:
    """Check if an MCP entry is already wrapped with observal-shim."""
    cmd = entry.get("command", "")
    args = entry.get("args", [])
    if cmd == "observal-shim" or "observal-shim" in cmd:
        return True
    return bool(any("observal-shim" in str(a) for a in args))


def _wrap_with_shim(entry: dict, mcp_id: str) -> dict:
    """Wrap an MCP server entry with observal-shim for telemetry."""
    if entry.get("url"):
        return entry

    original_cmd = entry.get("command", "")
    original_args = entry.get("args", [])

    shimmed = dict(entry)
    shimmed["command"] = "observal-shim"
    shimmed["args"] = ["--mcp-id", mcp_id, "--", original_cmd, *original_args]
    return shimmed


def _backup_config(config_path: Path) -> Path:
    """Create a timestamped backup of the config file."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = config_path.with_suffix(f".pre-observal.{ts}.bak")
    shutil.copy2(config_path, backup)
    return backup


def _auto_shim_home_config(config_path: Path, ide: str):
    """Auto-wrap un-shimmed MCP servers in a home-directory config file.

    For IDEs without native hook/telemetry systems (Codex, Copilot, OpenCode),
    wrapping MCP servers with observal-shim is the primary telemetry path.
    Uses the MCP server name as the shim correlation key.
    """
    if not config_path.exists():
        return

    try:
        if config_path.suffix == ".toml":
            try:
                import tomllib as toml
            except ImportError:
                try:
                    import tomli as toml  # type: ignore[no-redef]
                except ImportError:
                    return
            data = toml.loads(config_path.read_text()) if hasattr(toml, "loads") else toml.load(config_path.open("rb"))  # type: ignore[call-arg]
        else:
            data = json.loads(config_path.read_text())

        servers = _parse_project_mcp_servers(data, ide)
        shimmed = 0
        for name, entry in servers.items():
            if not _is_already_shimmed(entry):
                servers[name] = _wrap_with_shim(entry, name)
                shimmed += 1

        if shimmed:
            _backup_config(config_path)
            config_path.write_text(json.dumps(data, indent=2) + "\n")
            rprint(f"\n[green]Shimmed {shimmed} MCP entries in {config_path}[/green]")
            rprint("[dim]Telemetry will be collected via observal-shim.[/dim]")
    except Exception as e:
        rprint(f"\n[yellow]Could not auto-shim {config_path}: {e}[/yellow]")


def inject_gemini_telemetry(otlp_endpoint: str) -> bool:
    """Disable Gemini CLI's native OTLP telemetry (uses gRPC, incompatible).

    Gemini CLI hardcodes GrpcExporterTransport which can't connect to
    Observal's HTTP/JSON OTLP endpoint. Telemetry is captured via the
    hook bridge instead. This disables native OTLP to suppress gRPC
    error noise.

    Non-destructive: preserves all existing keys, only updates the `telemetry`
    block. Creates a timestamped backup before any write.

    Returns True if a write was performed, False if already up to date.
    """
    gemini_settings = Path.home() / ".gemini" / "settings.json"
    gemini_data: dict = {}
    if gemini_settings.exists():
        gemini_data = json.loads(gemini_settings.read_text())

    telemetry = gemini_data.get("telemetry", {})
    if not isinstance(telemetry, dict):
        telemetry = {}

    # Disable native OTLP (gRPC-only, can't reach Observal HTTP endpoint).
    # Keep logPrompts=true so hook payloads include prompt content.
    needs_update = (
        telemetry.get("enabled") is not False
        or telemetry.get("logPrompts") is not True
    )

    if not needs_update:
        return False

    if gemini_settings.exists():
        _backup_config(gemini_settings)
    gemini_data.setdefault("telemetry", {})
    gemini_data["telemetry"]["enabled"] = False
    gemini_data["telemetry"]["logPrompts"] = True
    # Remove stale OTLP fields that would only apply if native OTLP worked
    gemini_data["telemetry"].pop("target", None)
    gemini_data["telemetry"].pop("otlpEndpoint", None)
    gemini_settings.parent.mkdir(parents=True, exist_ok=True)
    gemini_settings.write_text(json.dumps(gemini_data, indent=2) + "\n")
    return True


# ── CLI command ─────────────────────────────────────────────


def register_scan(app: typer.Typer):
    @app.command(name="scan")
    def scan(
        project_dir: str = typer.Argument(".", help="Project directory to scan"),
        ide: str | None = typer.Option(None, "--ide", "-i", help="Target IDE (auto-detected if omitted)"),
        home: bool = typer.Option(False, "--home", help="Scan IDE home directories for plugins, agents, skills, hooks"),
        all_ides: bool = typer.Option(False, "--all-ides", help="Scan home directories for ALL supported IDEs"),
        dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Show discovered components without instrumenting"),
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
        shim: bool = typer.Option(
            False, "--shim", help="Rewrite project IDE configs to route MCPs through observal-shim"
        ),
    ):
        """Discover IDE components and instrument for telemetry.

        By default, scans the current project directory. If nothing is found,
        automatically falls back to scanning IDE home directories (~/.claude,
        ~/.kiro, ~/.gemini, etc.).

        Use --home to explicitly scan home directories, --ide to target a
        specific IDE (e.g. --home --ide kiro), or --all-ides to scan all at once.

        With --all-ides, scans ~/.claude, ~/.kiro, ~/.gemini, ~/.codex,
        ~/.vscode, and ~/.config/opencode to discover all agents, MCP servers,
        skills, and hooks across every IDE you use.

        Components are NOT published to the registry. Use 'observal registry <type>
        submit' to explicitly publish when ready.
        """
        all_mcps: list[DiscoveredMcp] = []
        all_skills: list[DiscoveredSkill] = []
        all_hooks: list[DiscoveredHook] = []
        all_agents: list[DiscoveredAgent] = []
        project_mcp_entries: list[tuple[str, str, DiscoveredMcp, Path]] = []
        scanned_ides: list[str] = []

        # ── Determine which IDE home dirs to scan ──
        scan_claude = False
        scan_kiro = False
        scan_gemini = False
        scan_codex = False
        scan_copilot = False
        scan_opencode = False

        if all_ides:
            home = True  # --all-ides implies --home
            scan_claude = True
            scan_kiro = True
            scan_gemini = True
            scan_codex = True
            scan_copilot = True
            scan_opencode = True
        elif home:
            if ide == "kiro":
                scan_kiro = True
            elif ide == "gemini-cli":
                scan_gemini = True
            elif ide == "codex":
                scan_codex = True
            elif ide == "copilot":
                scan_copilot = True
            elif ide == "opencode":
                scan_opencode = True
            elif ide == "claude-code" or ide is None:
                scan_claude = True
                if ide is None:
                    scan_kiro = True
                    scan_gemini = True
                    scan_codex = True
                    scan_copilot = True
                    scan_opencode = True

        # ── Scan ~/.claude ─────────────────────────────
        if scan_claude:
            claude_dir = Path.home() / ".claude"
            if claude_dir.is_dir():
                with spinner("Scanning ~/.claude..."):
                    h_mcps, h_skills, h_hooks, h_agents = _scan_claude_home(claude_dir)
                all_mcps.extend(h_mcps)
                all_skills.extend(h_skills)
                all_hooks.extend(h_hooks)
                all_agents.extend(h_agents)
                scanned_ides.append("claude-code")
            elif not all_ides:
                rprint("[yellow]~/.claude directory not found.[/yellow]")

        # ── Scan ~/.kiro ───────────────────────────────
        if scan_kiro:
            kiro_dir = Path.home() / ".kiro"
            if kiro_dir.is_dir():
                with spinner("Scanning ~/.kiro..."):
                    k_mcps, k_skills, k_hooks, k_agents = _scan_kiro_home(kiro_dir)
                all_mcps.extend(k_mcps)
                all_skills.extend(k_skills)
                all_hooks.extend(k_hooks)
                all_agents.extend(k_agents)
                scanned_ides.append("kiro")
            elif not all_ides:
                rprint("[yellow]~/.kiro directory not found.[/yellow]")

        # ── Scan ~/.gemini ────────────────────────────
        if scan_gemini:
            gemini_dir = Path.home() / ".gemini"
            if gemini_dir.is_dir():
                with spinner("Scanning ~/.gemini..."):
                    g_mcps, g_skills, g_hooks, g_agents = _scan_gemini_home(gemini_dir)
                all_mcps.extend(g_mcps)
                all_skills.extend(g_skills)
                all_hooks.extend(g_hooks)
                all_agents.extend(g_agents)
                scanned_ides.append("gemini-cli")
            elif not all_ides:
                rprint("[yellow]~/.gemini directory not found.[/yellow]")

        # ── Scan ~/.codex ────────────────────────────
        if scan_codex:
            codex_dir = Path.home() / ".codex"
            if codex_dir.is_dir():
                with spinner("Scanning ~/.codex..."):
                    cx_mcps, cx_skills, cx_hooks, cx_agents = _scan_codex_home(codex_dir)
                all_mcps.extend(cx_mcps)
                all_skills.extend(cx_skills)
                all_hooks.extend(cx_hooks)
                all_agents.extend(cx_agents)
                scanned_ides.append("codex")
            elif not all_ides:
                rprint("[yellow]~/.codex directory not found.[/yellow]")

        # ── Scan ~/.vscode (Copilot) ─────────────────
        if scan_copilot:
            vscode_dir = Path.home() / ".vscode"
            if vscode_dir.is_dir():
                with spinner("Scanning ~/.vscode..."):
                    cp_mcps, cp_skills, cp_hooks, cp_agents = _scan_copilot_home(vscode_dir)
                all_mcps.extend(cp_mcps)
                all_skills.extend(cp_skills)
                all_hooks.extend(cp_hooks)
                all_agents.extend(cp_agents)
                scanned_ides.append("copilot")
            elif not all_ides:
                rprint("[yellow]~/.vscode directory not found.[/yellow]")

        # ── Scan ~/.config/opencode ──────────────────
        if scan_opencode:
            opencode_dir = Path.home() / ".config" / "opencode"
            if opencode_dir.is_dir():
                with spinner("Scanning ~/.config/opencode..."):
                    oc_mcps, oc_skills, oc_hooks, oc_agents = _scan_opencode_home(opencode_dir)
                all_mcps.extend(oc_mcps)
                all_skills.extend(oc_skills)
                all_hooks.extend(oc_hooks)
                all_agents.extend(oc_agents)
                scanned_ides.append("opencode")
            elif not all_ides:
                rprint("[yellow]~/.config/opencode directory not found.[/yellow]")

        # ── Scan project directory (or home) ────────
        # If --home is passed, we should also scan the home directory using _IDE_PROJECT_CONFIGS
        # (which maps to ~/.gemini, ~/.codex, etc.)
        root = Path(project_dir).resolve()

        def _do_project_scan(target: Path):
            if not target.is_dir():
                return
            entries = _scan_project_dir(target, ide)
            seen_names = {m.name for m in all_mcps}
            for _ide, _name, mcp, config_path in entries:
                project_mcp_entries.append((_ide, _name, mcp, config_path))
                if mcp.name not in seen_names:
                    all_mcps.append(mcp)
                    seen_names.add(mcp.name)

        _do_project_scan(root)

        if home and root != Path.home():
            _do_project_scan(Path.home())

        total = len(all_mcps) + len(all_skills) + len(all_hooks) + len(all_agents)

        if total == 0 and not home:
            rprint("[dim]No components in project directory. Scanning IDE home dirs...[/dim]")
            home = True
            scan_claude = True
            scan_kiro = True
            scan_gemini = True
            scan_codex = True
            scan_copilot = True
            scan_opencode = True

            for _ide_name, _dir_path, _scan_fn, _label in [
                ("claude-code", Path.home() / ".claude", _scan_claude_home, "~/.claude"),
                ("kiro", Path.home() / ".kiro", _scan_kiro_home, "~/.kiro"),
                ("gemini-cli", Path.home() / ".gemini", _scan_gemini_home, "~/.gemini"),
                ("codex", Path.home() / ".codex", _scan_codex_home, "~/.codex"),
                ("copilot", Path.home() / ".vscode", _scan_copilot_home, "~/.vscode"),
                ("opencode", Path.home() / ".config" / "opencode", _scan_opencode_home, "~/.config/opencode"),
            ]:
                if _dir_path.is_dir():
                    with spinner(f"Scanning {_label}..."):
                        h_mcps, h_skills, h_hooks, h_agents = _scan_fn(_dir_path)
                    all_mcps.extend(h_mcps)
                    all_skills.extend(h_skills)
                    all_hooks.extend(h_hooks)
                    all_agents.extend(h_agents)
                    scanned_ides.append(_ide_name)

            if root != Path.home():
                _do_project_scan(Path.home())

            total = len(all_mcps) + len(all_skills) + len(all_hooks) + len(all_agents)

        if total == 0 and not home:
            rprint("[yellow]No components found.[/yellow]")
            raise typer.Exit(1)
        elif total == 0:
            rprint("[dim]No MCP/skill/hook components found, but configuring IDE telemetry...[/dim]")

        # ── Display discovery results ───────────────
        rprint(f"\n[bold]Discovered {total} components[/bold]\n")

        if all_mcps:
            tbl = Table(title=f"MCP Servers ({len(all_mcps)})", show_lines=False, padding=(0, 1))
            tbl.add_column("Name", style="bold")
            tbl.add_column("Command/URL", style="dim")
            tbl.add_column("Source", style="cyan")
            for m in all_mcps:
                tbl.add_row(m.name, m.display_cmd(), m.source)
            console.print(tbl)
            rprint()

        if all_skills:
            # Show summary for skills (can be hundreds)
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

        if all_hooks:
            tbl = Table(title=f"Hooks ({len(all_hooks)})", show_lines=False, padding=(0, 1))
            tbl.add_column("Name", style="bold")
            tbl.add_column("Event", style="cyan")
            tbl.add_column("Source", style="dim")
            for h in all_hooks:
                tbl.add_row(h.name, h.event, h.source)
            console.print(tbl)
            rprint()

        if all_agents:
            tbl = Table(title=f"Agents ({len(all_agents)})", show_lines=False, padding=(0, 1))
            tbl.add_column("Name", style="bold")
            tbl.add_column("Model", style="cyan")
            tbl.add_column("Description", style="dim", max_width=60)
            for a in all_agents:
                tbl.add_row(a.name, a.model_name or "-", a.description[:60])
            console.print(tbl)
            rprint()

        if dry_run:
            rprint("[yellow]Dry run — no changes made.[/yellow]")
            rprint(
                "[dim]Tip: Use 'observal registry <type> submit <git_url>' to publish components."
                " Only submit if you are the creator or point-of-contact.[/dim]"
            )
            return

        if total > 0 and not yes and not typer.confirm("Instrument these components for telemetry?"):
            raise typer.Abort()

        # ── Optionally shim project MCP configs ─────
        if shim and project_mcp_entries:
            shimmed_count = 0
            configs_to_update: dict[str, dict] = {}

            for ide_name, name, _mcp, config_path in project_mcp_entries:
                path_str = str(config_path)
                if path_str not in configs_to_update:
                    configs_to_update[path_str] = json.loads(config_path.read_text())

                config = configs_to_update[path_str]
                servers = _parse_project_mcp_servers(config, ide_name)
                if name in servers and not _is_already_shimmed(servers[name]):
                    servers[name] = _wrap_with_shim(servers[name], name)
                    shimmed_count += 1

            for path_str, config in configs_to_update.items():
                config_path = Path(path_str)
                backup = _backup_config(config_path)
                config_path.write_text(json.dumps(config, indent=2) + "\n")
                rprint(f"  [dim]Backup: {backup.name}[/dim]")

            if shimmed_count:
                rprint(f"[green]Shimmed {shimmed_count} MCP entries for telemetry.[/green]")

        # ── Auto-inject hooks into ~/.claude/settings.json ─────
        if scan_claude:
            from observal_cli.config import load as _load_config

            cfg = _load_config()
            server_url = cfg.get("server_url", "http://localhost:8000").rstrip("/")
            hooks_url = f"{server_url}/api/v1/otel/hooks"
            hook_def: dict = {"type": "http", "url": hooks_url}
            if cfg.get("user_id"):
                hook_def["headers"] = {"X-Observal-User-Id": cfg["user_id"]}
            http_hook = [{"hooks": [hook_def]}]

            # Stop uses a command hook to read transcript for Claude's response
            stop_script = Path(__file__).parent / "hooks" / "observal-stop-hook.sh"
            stop_hook = (
                [{"hooks": [{"type": "command", "command": stop_script.resolve().as_posix()}]}]
                if stop_script.is_file()
                else http_hook
            )

            hooks_block = {
                "SessionStart": http_hook,
                "UserPromptSubmit": http_hook,
                "PreToolUse": http_hook,
                "PostToolUse": http_hook,
                "PostToolUseFailure": http_hook,
                "SubagentStart": http_hook,
                "SubagentStop": http_hook,
                "Stop": stop_hook,
                "StopFailure": http_hook,
                "Notification": http_hook,
                "TaskCreated": http_hook,
                "TaskCompleted": http_hook,
                "PreCompact": http_hook,
                "PostCompact": http_hook,
                "WorktreeCreate": http_hook,
                "WorktreeRemove": http_hook,
                "Elicitation": http_hook,
                "ElicitationResult": http_hook,
            }

            claude_settings = Path.home() / ".claude" / "settings.json"
            try:
                settings: dict = {}
                if claude_settings.exists():
                    settings = json.loads(claude_settings.read_text())

                existing_hooks = settings.get("hooks", {})
                needs_update = False

                # Check if hooks already point to the right URL
                for event_name, _entry in hooks_block.items():
                    if event_name not in existing_hooks:
                        needs_update = True
                        break
                    # Check URL or command matches
                    existing_target = ""
                    try:
                        h = existing_hooks[event_name][0]["hooks"][0]
                        existing_target = h.get("url") or h.get("command", "")
                    except (KeyError, IndexError, TypeError):
                        pass
                    expected_target = hooks_block[event_name][0]["hooks"][0].get("url") or hooks_block[event_name][0][
                        "hooks"
                    ][0].get("command", "")
                    if existing_target != expected_target:
                        needs_update = True
                        break

                if needs_update:
                    settings["hooks"] = {**existing_hooks, **hooks_block}
                    # Ensure the stop hook env var is set
                    if "env" not in settings:
                        settings["env"] = {}
                    settings["env"]["OBSERVAL_HOOKS_URL"] = hooks_url
                    if cfg.get("user_id"):
                        settings["env"]["OBSERVAL_USER_ID"] = cfg["user_id"]
                    claude_settings.write_text(json.dumps(settings, indent=2) + "\n")
                    rprint(f"\n[green]Injected hooks config into {claude_settings}[/green]")
                    rprint(f"[dim]Hooks endpoint: {hooks_url}[/dim]")
                    rprint("[dim]Captures: prompts, tool I/O, MCP responses, subagents, elicitations[/dim]")
                else:
                    rprint(f"\n[dim]Hooks already configured -> {hooks_url}[/dim]")
            except Exception as e:
                rprint(f"\n[yellow]Could not auto-inject hooks: {e}[/yellow]")
                rprint("[dim]Add hooks manually — see docs.[/dim]")

        # ── Auto-inject hooks into ~/.kiro/agents/*.json ──────
        if scan_kiro:
            from observal_cli.config import load as _load_kiro_config

            kcfg = _load_kiro_config()
            kiro_server_url = kcfg.get("server_url", "http://localhost:8000").rstrip("/")
            kiro_hooks_url = f"{kiro_server_url}/api/v1/otel/hooks"

            hooks_dir = Path(__file__).parent / "hooks"
            hook_script = hooks_dir / "kiro_hook.py"
            stop_script = hooks_dir / "kiro_stop_hook.py"

            def _kiro_hook_cmd(agent_name: str, model: str) -> str:
                """Build a per-agent hook command (kiro_hook.py handles metadata natively)."""
                args = f"--url {kiro_hooks_url} --agent-name {agent_name}"
                if model:
                    args += f" --model {model}"
                if sys.platform == "win32" and hook_script.is_file():
                    return f"python {hook_script.resolve().as_posix()} {args}"
                if hook_script.is_file():
                    return f"cat | python3 {hook_script.resolve().as_posix()} {args}"
                return f'cat | curl -sf -X POST {kiro_hooks_url} -H "Content-Type: application/json" -d @-'

            def _kiro_stop_cmd(agent_name: str, model: str) -> str:
                """Build the stop hook command with full SQLite enrichment."""
                args = f"--url {kiro_hooks_url} --agent-name {agent_name}"
                if model:
                    args += f" --model {model}"
                if sys.platform == "win32" and stop_script.is_file():
                    return f"python {stop_script.resolve().as_posix()} {args}"
                if stop_script.is_file():
                    return f"cat | python3 {stop_script.resolve().as_posix()} {args}"
                return f'cat | curl -sf -X POST {kiro_hooks_url} -H "Content-Type: application/json" -d @-'

            def _kiro_hooks_block(agent_name: str, model: str) -> dict:
                cmd = _kiro_hook_cmd(agent_name, model)
                stop_cmd = _kiro_stop_cmd(agent_name, model)
                return {
                    "agentSpawn": [{"command": cmd}],
                    "userPromptSubmit": [{"command": cmd}],
                    "preToolUse": [{"matcher": "*", "command": cmd}],
                    "postToolUse": [{"matcher": "*", "command": cmd}],
                    "stop": [{"command": stop_cmd}],
                }

            kiro_agents_dir = Path.home() / ".kiro" / "agents"
            kiro_agents_dir.mkdir(parents=True, exist_ok=True)

            # Migrate: remove old default.json created by earlier Observal versions.
            old_default = kiro_agents_dir / "default.json"
            if old_default.exists():
                try:
                    od = json.loads(old_default.read_text())
                    if od.get("name") == "default" and any(
                        "otel/hooks" in h.get("command", "")
                        for hs in od.get("hooks", {}).values()
                        if isinstance(hs, list)
                        for h in hs
                    ):
                        old_default.unlink()
                        kiro_bin = shutil.which("kiro-cli") or shutil.which("kiro") or shutil.which("kiro-cli-chat")
                        if kiro_bin:
                            import subprocess

                            subprocess.run(
                                [kiro_bin, "agent", "set-default", "kiro_default"],
                                capture_output=True,
                                timeout=10,
                            )
                        rprint("[green]Removed old default agent (migrated to kiro_default)[/green]")
                except (ValueError, OSError):
                    pass

            kiro_agent_files = sorted(kiro_agents_dir.glob("*.json"))

            # Create kiro_default agent config if it doesn't exist, so hooks attach
            # to the built-in kiro_default agent instead of a separate workspace agent.
            default_agent_path = kiro_agents_dir / "kiro_default.json"
            if not default_agent_path.exists():
                default_agent_path.write_text(
                    json.dumps(
                        {
                            "name": "kiro_default",
                            "hooks": _kiro_hooks_block("kiro_default", ""),
                        },
                        indent=2,
                    )
                    + "\n"
                )
                rprint("[green]Created kiro_default agent with Observal hooks[/green]")
                kiro_agent_files = sorted(kiro_agents_dir.glob("*.json"))

            if kiro_agent_files:
                injected_count = 0
                for agent_file in kiro_agent_files:
                    try:
                        agent_data = json.loads(agent_file.read_text())
                        existing = agent_data.get("hooks", {})

                        # Check if already pointing to correct URL
                        already_configured = False
                        for _evt, handlers in existing.items():
                            if isinstance(handlers, list) and handlers:
                                cmd = handlers[0].get("command", "")
                                if kiro_hooks_url in cmd:
                                    already_configured = True
                                    break

                        if already_configured:
                            continue

                        # Extract agent metadata for per-agent hook enrichment
                        agent_name = agent_data.get("name", agent_file.stem)
                        agent_model = agent_data.get("model") or ""

                        # Backup and merge (preserve existing user hooks)
                        _backup_config(agent_file)
                        desired = _kiro_hooks_block(agent_name, agent_model)
                        merged = dict(existing)
                        for evt, handlers in desired.items():
                            cur = merged.get(evt, [])
                            has_obs = any("otel/hooks" in h.get("command", "") for h in cur)
                            if not has_obs:
                                merged[evt] = cur + handlers
                        agent_data["hooks"] = merged
                        agent_file.write_text(json.dumps(agent_data, indent=2) + "\n")
                        injected_count += 1
                    except (json.JSONDecodeError, OSError) as e:
                        rprint(f"  [yellow]Skipped {agent_file.name}: {e}[/yellow]")

                if injected_count:
                    rprint(f"\n[green]Injected Observal hooks into {injected_count} Kiro agents[/green]")
                    rprint(f"[dim]Hooks endpoint: {kiro_hooks_url}[/dim]")
                else:
                    rprint(f"\n[dim]Kiro agent hooks already configured -> {kiro_hooks_url}[/dim]")

            # ── Global IDE-format hooks in ~/.kiro/hooks/ ─────────
            # These fire for ALL Kiro sessions (including agentless chat)
            kiro_global_hooks_dir = Path.home() / ".kiro" / "hooks"
            kiro_global_hooks_dir.mkdir(parents=True, exist_ok=True)

            global_hook_cmd = _kiro_hook_cmd("global", "")
            global_stop_cmd = _kiro_stop_cmd("global", "")

            _ide_hook_defs = [
                ("observal-prompt-submit", "promptSubmit", global_hook_cmd),
                ("observal-pre-tool-use", "preToolUse", global_hook_cmd),
                ("observal-post-tool-use", "postToolUse", global_hook_cmd),
                ("observal-agent-stop", "agentStop", global_stop_cmd),
            ]

            global_injected = 0
            for hook_id, event_type, cmd in _ide_hook_defs:
                hook_file = kiro_global_hooks_dir / f"{hook_id}.json"
                hook_json = {
                    "id": hook_id,
                    "name": f"Observal: {event_type}",
                    "comment": "Auto-injected by Observal for telemetry collection",
                    "when": {"type": event_type},
                    "then": {"type": "runCommand", "command": cmd},
                }
                # Only write if missing or stale (different URL)
                if hook_file.exists():
                    try:
                        existing_hook = json.loads(hook_file.read_text())
                        if kiro_hooks_url in existing_hook.get("then", {}).get("command", ""):
                            continue
                    except (json.JSONDecodeError, OSError):
                        pass
                    _backup_config(hook_file)
                hook_file.write_text(json.dumps(hook_json, indent=2) + "\n")
                global_injected += 1

            if global_injected:
                rprint(f"[green]Installed {global_injected} global Kiro hooks in ~/.kiro/hooks/[/green]")
                rprint("[dim]These capture all Kiro sessions, including agentless chat.[/dim]")
            else:
                rprint("[dim]Global Kiro hooks already configured.[/dim]")

        # ── Auto-inject telemetry into ~/.gemini/settings.json ──
        if scan_gemini:
            from observal_cli.config import load as _load_gemini_config

            gcfg = _load_gemini_config()
            otlp_endpoint = gcfg.get("otlp_http_url") or gcfg.get("otlp_endpoint", "http://localhost:4318")
            gemini_settings = Path.home() / ".gemini" / "settings.json"

            try:
                written = inject_gemini_telemetry(otlp_endpoint)
                if written:
                    rprint(f"\n[green]Disabled native OTLP in {gemini_settings} (gRPC incompatible)[/green]")
                    rprint("[dim]Telemetry is captured via hooks instead.[/dim]")
                else:
                    rprint(f"\n[dim]Gemini CLI native OTLP already disabled.[/dim]")
            except Exception as e:
                rprint(f"\n[yellow]Could not configure Gemini CLI telemetry: {e}[/yellow]")
                rprint("[dim]Add telemetry settings manually to ~/.gemini/settings.json.[/dim]")

        # ── Auto-inject hooks into ~/.gemini/settings.json ─────
        if scan_gemini:
            from observal_cli.config import load as _load_gemini_hooks_config

            ghcfg = _load_gemini_hooks_config()
            gemini_server_url = ghcfg.get("server_url", "http://localhost:8000").rstrip("/")
            gemini_hooks_url = f"{gemini_server_url}/api/v1/otel/hooks"

            gemini_hooks_dir = Path(__file__).parent / "hooks"
            gemini_hook_script = gemini_hooks_dir / "gemini_hook.py"
            gemini_stop_script = gemini_hooks_dir / "gemini_stop_hook.py"

            def _gemini_hook_cmd(script: Path) -> str:
                """Build the Gemini hook command string for a given script."""
                if sys.platform == "win32":
                    return f"python {script.resolve().as_posix()}"
                return f"python3 {script.resolve().as_posix()}"

            def _gemini_hook_entry(script: Path) -> list:
                return [{"hooks": [{"type": "command", "command": _gemini_hook_cmd(script)}]}]

            cmd_hook = _gemini_hook_entry(gemini_hook_script)
            stop_hook = _gemini_hook_entry(gemini_stop_script)

            gemini_hooks_block = {
                "SessionStart": cmd_hook,
                "BeforeAgent": cmd_hook,
                "AfterAgent": stop_hook,
                "AfterModel": cmd_hook,
                "BeforeTool": cmd_hook,
                "AfterTool": cmd_hook,
                "SessionEnd": stop_hook,
                "Notification": cmd_hook,
            }

            gemini_settings = Path.home() / ".gemini" / "settings.json"
            try:
                gdata: dict = {}
                if gemini_settings.exists():
                    gdata = json.loads(gemini_settings.read_text())

                existing_ghooks = gdata.get("hooks", {})
                ghooks_needs_update = False

                for event_name, entry in gemini_hooks_block.items():
                    if event_name not in existing_ghooks:
                        ghooks_needs_update = True
                        break
                    # Check if command matches
                    existing_cmd = ""
                    try:
                        existing_cmd = existing_ghooks[event_name][0]["hooks"][0].get("command", "")
                    except (KeyError, IndexError, TypeError):
                        pass
                    expected_cmd = entry[0]["hooks"][0].get("command", "")
                    if existing_cmd != expected_cmd:
                        ghooks_needs_update = True
                        break

                if ghooks_needs_update:
                    _backup_config(gemini_settings)
                    gdata["hooks"] = {**existing_ghooks, **gemini_hooks_block}
                    # Set env vars so hook scripts can resolve the endpoint
                    if "env" not in gdata:
                        gdata["env"] = {}
                    gdata["env"]["OBSERVAL_HOOKS_URL"] = gemini_hooks_url
                    if ghcfg.get("user_id"):
                        gdata["env"]["OBSERVAL_USER_ID"] = ghcfg["user_id"]
                    if ghcfg.get("user_name"):
                        gdata["env"]["OBSERVAL_USERNAME"] = ghcfg["user_name"]
                    gemini_settings.parent.mkdir(parents=True, exist_ok=True)
                    gemini_settings.write_text(json.dumps(gdata, indent=2) + "\n")
                    rprint(f"\n[green]Injected hooks config into {gemini_settings}[/green]")
                    rprint(f"[dim]Hooks endpoint: {gemini_hooks_url}[/dim]")
                    rprint("[dim]Captures: prompts, tool I/O, agent responses, session lifecycle[/dim]")
                else:
                    rprint(f"\n[dim]Gemini hooks already configured -> {gemini_hooks_url}[/dim]")
            except Exception as e:
                rprint(f"\n[yellow]Could not auto-inject Gemini hooks: {e}[/yellow]")
                rprint("[dim]Add hooks manually to ~/.gemini/settings.json — see docs.[/dim]")

        # ── Auto-shim Codex home MCP servers ──
        if scan_codex:
            _auto_shim_home_config(
                Path.home() / ".codex" / "config.toml",
                "codex",
            )

        # ── Auto-shim Copilot home MCP servers ──
        if scan_copilot:
            _auto_shim_home_config(
                Path.home() / ".vscode" / "mcp.json",
                "copilot",
            )

        # ── Auto-shim OpenCode home MCP servers ──
        if scan_opencode:
            _auto_shim_home_config(
                Path.home() / ".config" / "opencode" / "opencode.json",
                "opencode",
            )

        rprint()
        rprint(
            "[dim]Tip: Use 'observal registry <type> submit <git_url>' to publish components to the shared registry."
            " Only submit if you are the creator or point-of-contact.[/dim]"
        )
