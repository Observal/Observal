"""observal scan: auto-detect IDE configs, register items, wrap with telemetry shims."""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

import typer
from rich import print as rprint
from rich.table import Table

from observal_cli import client
from observal_cli.render import console, spinner

# ── IDE config file locations (relative to project root) ────

_IDE_PROJECT_CONFIGS = {
    "cursor": ".cursor/mcp.json",
    "kiro": ".kiro/settings/mcp.json",
    "vscode": ".vscode/mcp.json",
    "gemini-cli": ".gemini/settings.json",
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
                desc = data.get("description", "")
                model = data.get("model", "")
                prompt = data.get("prompt", "")

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

    # Deduplicate MCPs by name (global + agent-level may overlap)
    seen: set[str] = set()
    deduped: list[DiscoveredMcp] = []
    for m in mcps:
        if m.name not in seen:
            deduped.append(m)
            seen.add(m.name)
    mcps = deduped

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
            config = json.loads(config_path.read_text())
        except (json.JSONDecodeError, OSError):
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
    if ide == "vscode":
        return config.get("servers", config.get("mcpServers", {}))
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


# ── CLI command ─────────────────────────────────────────────


def register_scan(app: typer.Typer):
    @app.command(name="scan")
    def scan(
        project_dir: str = typer.Argument(".", help="Project directory to scan"),
        ide: str | None = typer.Option(None, "--ide", "-i", help="Target IDE (auto-detected if omitted)"),
        home: bool = typer.Option(False, "--home", help="Scan IDE home directories for plugins, agents, skills, hooks"),
        all_ides: bool = typer.Option(
            False, "--all-ides", help="Scan home directories for ALL IDEs (Claude Code, Kiro, Cursor)"
        ),
        dry_run: bool = typer.Option(
            False, "--dry-run", "-n", help="Show what would be registered without making changes"
        ),
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
        shim: bool = typer.Option(
            False, "--shim", help="Rewrite project IDE configs to route MCPs through observal-shim"
        ),
    ):
        """Scan IDE configs and register discovered components with Observal.

        By default, scans the current project directory for Cursor, VS Code, Kiro,
        and Gemini CLI MCP configs.

        With --home, scans your IDE home directory. Use --ide to target a specific
        IDE (e.g. --home --ide kiro), or --all-ides to scan all IDEs at once.

        With --all-ides, scans ~/.claude, ~/.kiro, and ~/.cursor to discover
        all agents, MCP servers, skills, and hooks across every IDE you use.
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

        if all_ides:
            home = True  # --all-ides implies --home
            scan_claude = True
            scan_kiro = True
        elif home:
            if ide == "kiro":
                scan_kiro = True
            elif ide == "claude-code" or ide is None:
                scan_claude = True
                # When no --ide specified, also scan kiro if it exists
                if ide is None:
                    scan_kiro = True

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

        # ── Scan project directory ──────────────────
        root = Path(project_dir).resolve()
        if root.is_dir():
            project_mcp_entries = _scan_project_dir(root, ide)
            # Add project MCPs to the list (dedup by name)
            seen_names = {m.name for m in all_mcps}
            for _ide, _name, mcp, _path in project_mcp_entries:
                if mcp.name not in seen_names:
                    all_mcps.append(mcp)
                    seen_names.add(mcp.name)

        total = len(all_mcps) + len(all_skills) + len(all_hooks) + len(all_agents)
        if total == 0:
            rprint("[yellow]No components found.[/yellow]")
            if not home:
                rprint("[dim]Tip: use --home to scan IDE home dirs, or --all-ides to scan all IDEs.[/dim]")
            raise typer.Exit(1)

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
            return

        if not yes and not typer.confirm("Register these components with Observal?"):
            raise typer.Abort()

        # ── Register via bulk scan API ──────────────
        def _ide_from_source(source: str) -> str:
            """Infer source IDE from component source string."""
            if source.startswith("kiro:"):
                return "kiro"
            if source.startswith("plugin:") or source.startswith("claude:"):
                return "claude-code"
            return ide or "auto"

        scan_payload = {
            "ide": ide or ("multi" if all_ides else ("claude-code" if home else "auto")),
            "mcps": [
                {
                    "name": m.name,
                    "command": m.command,
                    "args": m.args,
                    "url": m.url,
                    "description": m.description,
                    "source_plugin": m.source,
                    "source_ide": _ide_from_source(m.source),
                }
                for m in all_mcps
            ],
            "skills": [
                {
                    "name": s.name,
                    "description": s.description,
                    "source_plugin": s.source,
                    "task_type": s.task_type,
                    "source_ide": _ide_from_source(s.source),
                }
                for s in all_skills
            ],
            "hooks": [
                {
                    "name": h.name,
                    "event": h.event,
                    "handler_type": h.handler_type,
                    "handler_config": h.handler_config,
                    "description": h.description,
                    "source_plugin": h.source,
                    "source_ide": _ide_from_source(h.source),
                }
                for h in all_hooks
            ],
            "agents": [
                {
                    "name": a.name,
                    "description": a.description,
                    "model_name": a.model_name,
                    "prompt": a.prompt,
                    "source_file": a.source_file,
                    "source_ide": _ide_from_source(
                        f"kiro:{a.source_file}" if a.source_file and ".kiro" in a.source_file else a.source_file or ""
                    ),
                }
                for a in all_agents
            ],
        }

        with spinner(f"Registering {total} components..."):
            try:
                result = client.post("/api/v1/scan", scan_payload)
            except (Exception, SystemExit) as e:
                rprint(f"[red]Failed to register: {e}[/red]")
                raise typer.Exit(1) from None

        # Show registration results
        new_count = 0
        existing_count = 0
        for reg in result.get("registered", []):
            if reg["status"] == "created":
                rprint(f"  [green]+ new[/green] [{reg['type']}] {reg['name']} -> {reg['id'][:8]}...")
                new_count += 1
            else:
                rprint(f"  [dim]= existing[/dim] [{reg['type']}] {reg['name']}")
                existing_count += 1

        rprint(f"\n[green]Done![/green] {new_count} new, {existing_count} existing.")

        # ── Optionally shim project MCP configs ─────
        if shim and project_mcp_entries:
            id_map = {r["name"]: r["id"] for r in result.get("registered", []) if r["type"] == "mcp"}
            shimmed_count = 0
            configs_to_update: dict[str, dict] = {}

            for ide_name, name, _mcp, config_path in project_mcp_entries:
                mcp_id = id_map.get(name)
                if not mcp_id:
                    continue
                path_str = str(config_path)
                if path_str not in configs_to_update:
                    configs_to_update[path_str] = json.loads(config_path.read_text())

                config = configs_to_update[path_str]
                servers = _parse_project_mcp_servers(config, ide_name)
                if name in servers and not _is_already_shimmed(servers[name]):
                    servers[name] = _wrap_with_shim(servers[name], mcp_id)
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
                [{"hooks": [{"type": "command", "command": str(stop_script.resolve())}]}]
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

            kiro_user_id = kcfg.get("user_id", "")

            def _kiro_sed_prefix(agent_name: str, model: str) -> str:
                """Build the sed expression that injects metadata into JSON."""
                meta_fields = (
                    f'"session_id":"kiro-\'$PPID\'",'
                    f'"service_name":"kiro-cli",'
                    f'"agent_name":"{agent_name}",'
                    f'"terminal_type":"\'$TERM\'",'
                    f'"shell":"\'$SHELL\'"'
                )
                if model:
                    meta_fields += f',"model":"{model}"'
                if kiro_user_id:
                    meta_fields += f',"user_id":"{kiro_user_id}"'
                return "cat | sed 's/^{/{" + meta_fields + ",/' "

            def _kiro_hook_cmd(agent_name: str, model: str) -> str:
                """Build a per-agent hook command with conversation_id lookup."""
                prefix = _kiro_sed_prefix(agent_name, model)
                if hook_script.is_file():
                    return f"{prefix}| python3 {hook_script.resolve()} --url {kiro_hooks_url}"
                return f'{prefix}| curl -sf -X POST {kiro_hooks_url} -H "Content-Type: application/json" -d @-'

            def _kiro_stop_cmd(agent_name: str, model: str) -> str:
                """Build the stop hook command with full SQLite enrichment."""
                prefix = _kiro_sed_prefix(agent_name, model)
                if stop_script.is_file():
                    return f"{prefix}| python3 {stop_script.resolve()} --url {kiro_hooks_url}"
                return f'{prefix}| curl -sf -X POST {kiro_hooks_url} -H "Content-Type: application/json" -d @-'

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
            if kiro_agents_dir.is_dir():
                injected_count = 0
                for agent_file in sorted(kiro_agents_dir.glob("*.json")):
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
                        agent_model = agent_data.get("model", "")

                        # Backup and inject
                        _backup_config(agent_file)
                        agent_data["hooks"] = _kiro_hooks_block(agent_name, agent_model)
                        agent_file.write_text(json.dumps(agent_data, indent=2) + "\n")
                        injected_count += 1
                    except (json.JSONDecodeError, OSError) as e:
                        rprint(f"  [yellow]Skipped {agent_file.name}: {e}[/yellow]")

                if injected_count:
                    rprint(f"\n[green]Injected Observal hooks into {injected_count} Kiro agents[/green]")
                    rprint(f"[dim]Hooks endpoint: {kiro_hooks_url}[/dim]")
                else:
                    rprint(f"\n[dim]Kiro agent hooks already configured -> {kiro_hooks_url}[/dim]")
