"""observal doctor: diagnose IDE settings that conflict with Observal telemetry."""

import json
import os
import shutil
import sys
from pathlib import Path

import typer
from rich import print as rprint

from observal_cli import config, settings_reconciler
from observal_cli.claude_code_spec import MANAGED_ENV_KEYS, OBSERVAL_METADATA_KEY, get_desired_env, get_desired_hooks

doctor_app = typer.Typer(help="Diagnose IDE settings for Observal compatibility")


# ── Markers that identify Observal-injected content ──────

_OBSERVAL_HOOK_MARKERS = (
    "observal-hook",
    "observal-stop-hook",
    "observal_cli",
    "telemetry/hooks",
    "otel/hooks",
    "kiro_hook",
    "kiro_stop_hook",
    "gemini_hook",
    "gemini_stop_hook",
    "copilot_cli_hook",
    "copilot_cli_stop_hook",
)


def _is_observal_hook_entry(entry: dict) -> bool:
    cmd = entry.get("command", "")
    url = entry.get("url", "")
    return any(m in cmd or m in url for m in _OBSERVAL_HOOK_MARKERS)


def _is_observal_matcher_group(group: dict) -> bool:
    if OBSERVAL_METADATA_KEY in group:
        return True
    return any(_is_observal_hook_entry(h) for h in group.get("hooks", []))


@doctor_app.command(name="cleanup")
def doctor_cleanup(
    ide: str = typer.Option(
        None,
        "--ide",
        "-i",
        help="Target IDE only (claude-code, kiro, gemini-cli). Default: all.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Show what would be removed without doing it"),
):
    """Remove ALL Observal hooks, env vars, and telemetry config from IDEs.

    Strips Observal-managed hooks from Claude Code, Kiro, and Gemini CLI
    settings. Removes OTEL env vars, shim wrappers, and hook entries.
    Leaves non-Observal hooks and settings untouched.
    """
    targets = [ide] if ide else ["claude-code", "kiro", "gemini-cli"]
    any_changes = False

    rprint("[bold]Observal Doctor — Cleanup[/bold]\n")

    for target in targets:
        if target in ("claude-code", "claude_code"):
            changed = _cleanup_claude_code(dry_run)
            any_changes = any_changes or changed

        elif target in ("kiro", "kiro-cli"):
            changed = _cleanup_kiro(dry_run)
            any_changes = any_changes or changed

        elif target in ("gemini-cli", "gemini_cli"):
            changed = _cleanup_gemini(dry_run)
            any_changes = any_changes or changed

        else:
            rprint(f"[yellow]Unknown IDE: {target}[/yellow]")

    if any_changes and not dry_run:
        rprint("\n[green]✓ Cleanup complete.[/green] Restart your IDE sessions to take effect.")
    elif not any_changes:
        rprint("\n[dim]Nothing to clean up — no Observal artifacts found.[/dim]")


def _cleanup_claude_code(dry_run: bool) -> bool:
    rprint("[cyan]Claude Code[/cyan]")
    settings_path = Path.home() / ".claude" / "settings.json"
    if not settings_path.exists():
        rprint("  [dim]No settings.json found — skipping[/dim]")
        return False

    try:
        data = json.loads(settings_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        rprint(f"  [red]Failed to read settings: {e}[/red]")
        return False

    changed = False

    # Remove Observal-managed env vars
    env = data.get("env", {})
    removed_env = []
    for key in list(env):
        if key in MANAGED_ENV_KEYS:
            removed_env.append(key)
            if not dry_run:
                del env[key]
            changed = True
    if removed_env:
        verb = "Would remove" if dry_run else "Removed"
        rprint(f"  {verb} env vars: {', '.join(removed_env)}")

    # Remove Observal hooks from each event
    hooks = data.get("hooks", {})
    removed_events = []
    for event, groups in list(hooks.items()):
        if not isinstance(groups, list):
            continue
        cleaned = [g for g in groups if not _is_observal_matcher_group(g)]
        if len(cleaned) < len(groups):
            removed_events.append(f"{event} ({len(groups) - len(cleaned)} removed)")
            if not dry_run:
                if cleaned:
                    hooks[event] = cleaned
                else:
                    del hooks[event]
            changed = True
    if removed_events:
        verb = "Would remove" if dry_run else "Removed"
        rprint(f"  {verb} hooks: {', '.join(removed_events)}")

    if changed and not dry_run:
        settings_path.write_text(json.dumps(data, indent=2) + "\n")
        rprint(f"  [green]Written {settings_path}[/green]")

    if not changed:
        rprint("  [dim]No Observal artifacts found[/dim]")

    return changed


def _cleanup_kiro(dry_run: bool) -> bool:
    rprint("[cyan]Kiro[/cyan]")
    agents_dir = Path.home() / ".kiro" / "agents"
    if not agents_dir.is_dir():
        rprint("  [dim]No ~/.kiro/agents/ found — skipping[/dim]")
        return False

    changed = False
    for agent_file in sorted(agents_dir.glob("*.json")):
        if agent_file.name == "agent_config.json.example":
            continue
        try:
            agent_data = json.loads(agent_file.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        agent_changed = False

        # Remove hooks that reference Observal
        hooks = agent_data.get("hooks", {})
        if isinstance(hooks, dict):
            for event, entries in list(hooks.items()):
                if not isinstance(entries, list):
                    continue
                cleaned = [e for e in entries if not _is_observal_hook_entry(e)]
                if len(cleaned) < len(entries):
                    agent_changed = True
                    if not dry_run:
                        if cleaned:
                            hooks[event] = cleaned
                        else:
                            del hooks[event]

        # Remove Observal MCP shim entries
        mcps = agent_data.get("mcpServers", {})
        if isinstance(mcps, dict):
            for name, cfg in list(mcps.items()):
                cmd = cfg.get("command", "")
                args = " ".join(cfg.get("args", []))
                if "observal-shim" in cmd or "observal-shim" in args:
                    agent_changed = True
                    if not dry_run:
                        del mcps[name]

        if agent_changed:
            changed = True
            verb = "Would clean" if dry_run else "Cleaned"
            rprint(f"  {verb} {agent_file.name}")
            if not dry_run:
                agent_file.write_text(json.dumps(agent_data, indent=2) + "\n")

    if not changed:
        rprint("  [dim]No Observal artifacts found in Kiro agents[/dim]")

    return changed


def _cleanup_gemini(dry_run: bool) -> bool:
    rprint("[cyan]Gemini CLI[/cyan]")
    settings_path = Path.home() / ".gemini" / "settings.json"
    if not settings_path.exists():
        rprint("  [dim]No settings.json found — skipping[/dim]")
        return False

    try:
        data = json.loads(settings_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        rprint(f"  [red]Failed to read settings: {e}[/red]")
        return False

    changed = False

    # Remove Observal env vars
    env = data.get("env", {})
    removed_env = []
    for key in list(env):
        if key.startswith("OBSERVAL_") or key in MANAGED_ENV_KEYS:
            removed_env.append(key)
            if not dry_run:
                del env[key]
            changed = True
    if removed_env:
        verb = "Would remove" if dry_run else "Removed"
        rprint(f"  {verb} env vars: {', '.join(removed_env)}")

    # Remove Observal hooks
    hooks = data.get("hooks", {})
    removed_events = []
    for event, groups in list(hooks.items()):
        if not isinstance(groups, list):
            continue
        cleaned = []
        for g in groups:
            hook_entries = g.get("hooks", [g] if "command" in g else [])
            is_observal = any(_is_observal_hook_entry(h) for h in hook_entries)
            if not is_observal:
                cleaned.append(g)
        if len(cleaned) < len(groups):
            removed_events.append(f"{event} ({len(groups) - len(cleaned)} removed)")
            if not dry_run:
                if cleaned:
                    hooks[event] = cleaned
                else:
                    del hooks[event]
            changed = True
    if removed_events:
        verb = "Would remove" if dry_run else "Removed"
        rprint(f"  {verb} hooks: {', '.join(removed_events)}")

    if changed and not dry_run:
        data.pop("env", None) if not data.get("env") else None
        data.pop("hooks", None) if not data.get("hooks") else None
        settings_path.write_text(json.dumps(data, indent=2) + "\n")
        rprint(f"  [green]Written {settings_path}[/green]")

    if not changed:
        rprint("  [dim]No Observal artifacts found[/dim]")

    return changed


# ── IDE config locations ─────────────────────────────────

IDE_CONFIGS = {
    "claude-code": {
        "user_settings": [
            Path.home() / ".claude" / "settings.json",
        ],
        "project_settings": [
            Path(".claude") / "settings.json",
            Path(".claude") / "settings.local.json",
        ],
        "mcp": [
            Path(".mcp.json"),
        ],
    },
    "kiro": {
        "user_settings": [
            Path.home() / ".kiro" / "settings" / "cli.json",
            Path.home() / ".kiro" / "settings.json",
        ],
        "project_settings": [
            Path(".kiro") / "settings.json",
            Path(".kiro") / "settings" / "cli.json",
        ],
        "mcp": [],
    },
    "cursor": {
        "user_settings": [
            Path.home() / ".cursor" / "mcp.json",
        ],
        "project_settings": [
            Path(".cursor") / "mcp.json",
        ],
        "mcp": [],
    },
    "gemini-cli": {
        "user_settings": [
            Path.home() / ".gemini" / "settings.json",
        ],
        "project_settings": [
            Path(".gemini") / "settings.json",
        ],
        "mcp": [],
    },
    "copilot": {
        "user_settings": [],
        "project_settings": [
            Path(".vscode") / "mcp.json",
        ],
        "mcp": [],
    },
    "copilot-cli": {
        "user_settings": [
            Path.home() / ".copilot" / "config.json",
            Path.home() / ".copilot" / "mcp-config.json",
        ],
        "project_settings": [
            Path(".mcp.json"),
        ],
        "mcp": [],
    },
    "opencode": {
        "user_settings": [
            Path.home() / ".config" / "opencode" / "opencode.json",
        ],
        "project_settings": [
            Path("opencode.json"),
        ],
        "mcp": [],
    },
    "codex": {
        "user_settings": [
            Path.home() / ".codex" / "config.toml",
        ],
        "project_settings": [
            Path(".codex") / "config.toml",
        ],
        "mcp": [],
    },
}


# ── Check functions ──────────────────────────────────────


def _load_json(path: Path) -> dict | None:
    try:
        text = path.read_text()
        # Strip // line comments (JSONC format used by Copilot CLI and others)
        stripped = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("//"))
        return json.loads(stripped)
    except Exception:
        return None


def _check_claude_code(path: Path, data: dict, issues: list, warnings: list):
    """Check Claude Code settings for Observal conflicts."""
    cfg = config.load()
    server_url = cfg.get("server_url", "http://localhost:8000")

    # Hooks disabled entirely
    if data.get("disableAllHooks"):
        issues.append(f"{path}: `disableAllHooks` is true. Observal hook telemetry will not fire.")

    # allowedHttpHookUrls blocks our endpoint
    allowed_urls = data.get("allowedHttpHookUrls")
    if isinstance(allowed_urls, list) and len(allowed_urls) > 0:
        from urllib.parse import urlparse

        parsed = urlparse(server_url)
        host_port = f"{parsed.hostname}:{parsed.port or 8000}"
        has_observal = any(host_port in u or "observal" in u.lower() for u in allowed_urls)
        if not has_observal:
            issues.append(
                f"{path}: `allowedHttpHookUrls` is set but does not include Observal's URL. "
                f"Add `{server_url}/*` to allow hook telemetry."
            )

    # httpHookAllowedEnvVars blocks OBSERVAL_API_KEY
    allowed_env = data.get("httpHookAllowedEnvVars")
    if isinstance(allowed_env, list) and "OBSERVAL_API_KEY" not in allowed_env:
        issues.append(
            f"{path}: `httpHookAllowedEnvVars` does not include `OBSERVAL_API_KEY`. "
            "Observal hooks need this env var for authentication."
        )

    # allowManagedHooksOnly blocks project/user hooks
    if data.get("allowManagedHooksOnly"):
        issues.append(
            f"{path}: `allowManagedHooksOnly` is true. "
            "Only managed hooks will run. Observal hooks installed at project/user level will be blocked."
        )

    # Permissions denying our tools
    perms = data.get("permissions", {})
    deny_list = perms.get("deny", [])
    for rule in deny_list:
        if isinstance(rule, str) and ("observal" in rule.lower() or rule == "WebFetch"):
            warnings.append(f"{path}: deny rule `{rule}` may block Observal telemetry.")

    # MCP servers: check if observal-shim is being bypassed
    # (project .mcp.json or user mcpServers)

    # Sandbox settings that block network
    sandbox = data.get("sandbox", {})
    network = sandbox.get("network", {})
    allowed_domains = network.get("allowedDomains", [])
    if isinstance(allowed_domains, list) and len(allowed_domains) > 0:
        has_localhost = any("localhost" in d for d in allowed_domains)
        if not has_localhost:
            warnings.append(
                f"{path}: sandbox `network.allowedDomains` does not include `localhost`. "
                f"Observal telemetry POSTs to {server_url}."
            )

    # env vars that override Observal
    env = data.get("env", {})
    if env.get("OBSERVAL_KEY") or env.get("OBSERVAL_SERVER"):
        warnings.append(f"{path}: env overrides for OBSERVAL_KEY/OBSERVAL_SERVER found. Verify they are correct.")


def _check_kiro(path: Path, data: dict, issues: list, warnings: list):
    """Check Kiro CLI/IDE settings for Observal conflicts."""
    # Telemetry disabled
    if data.get("telemetry.enabled") is False or data.get("telemetry", {}).get("enabled") is False:
        warnings.append(
            f"{path}: Kiro telemetry is disabled. This does not affect Observal, but may indicate a preference against data collection."
        )

    # MCP init timeout too low
    mcp_timeout = data.get("mcp.initTimeout") or data.get("mcp", {}).get("initTimeout")
    if mcp_timeout is not None and mcp_timeout < 10:
        warnings.append(
            f"{path}: `mcp.initTimeout` is {mcp_timeout}s. "
            "observal-shim adds a small overhead to MCP startup. Consider 10s+."
        )

    # Auto-compaction may lose telemetry context
    if data.get("chat.disableAutoCompaction") is False or data.get("chat", {}).get("disableAutoCompaction") is False:
        pass  # default, fine


def _check_kiro_installation(issues: list, warnings: list):
    """Check Kiro CLI installation and agent hook configuration."""
    # Check kiro-cli binary
    if os.system("which kiro-cli > /dev/null 2>&1") != 0:
        warnings.append("`kiro-cli` not found in PATH. Install with: curl -fsSL https://cli.kiro.dev/install | bash")
    else:
        # Check if kiro-cli is authenticated
        if os.system("kiro-cli whoami > /dev/null 2>&1") != 0:
            warnings.append("`kiro-cli` is installed but not authenticated. Run `kiro-cli login`.")

    # Check for Kiro agents directory
    agents_dir = Path.home() / ".kiro" / "agents"
    if agents_dir.exists():
        agent_files = list(agents_dir.glob("*.json"))
        if agent_files:
            # Check if any agents have Observal hooks configured
            has_observal_hooks = False
            for af in agent_files:
                agent_data = _load_json(af)
                if agent_data and "hooks" in agent_data:
                    hooks = agent_data["hooks"]
                    for _event, hook_list in hooks.items():
                        for h in hook_list if isinstance(hook_list, list) else []:
                            cmd = h.get("command", "")
                            if "observal" in cmd or "telemetry/hooks" in cmd:
                                has_observal_hooks = True
                                break
            if not has_observal_hooks:
                warnings.append(
                    "No Kiro agents have Observal telemetry hooks. "
                    "Run `observal scan --ide kiro --home` to inject hooks."
                )

    # Check MCP config for observal-shim
    mcp_path = Path.home() / ".kiro" / "settings" / "mcp.json"
    if mcp_path.exists():
        mcp_data = _load_json(mcp_path)
        if mcp_data:
            servers = mcp_data.get("mcpServers", {})
            unwrapped = [
                n
                for n, c in servers.items()
                if isinstance(c, dict)
                and "observal-shim" not in c.get("command", "")
                and "observal-proxy" not in c.get("command", "")
                and "url" not in c  # HTTP transport doesn't need shim
            ]
            if unwrapped:
                warnings.append(
                    f"Kiro MCP servers not wrapped with observal-shim: {', '.join(unwrapped)}. "
                    "Run `observal scan --ide kiro` to wrap them."
                )


def _check_cursor(path: Path, data: dict, issues: list, warnings: list):
    """Check Cursor MCP config for Observal conflicts."""
    servers = data.get("mcpServers", {})
    for name, srv_cfg in servers.items():
        cmd = srv_cfg.get("command", "")
        args = srv_cfg.get("args", [])
        full_cmd = f"{cmd} {' '.join(str(a) for a in args)}"
        # Check if MCP is wrapped with observal-shim
        if "observal-shim" not in full_cmd and "observal-proxy" not in full_cmd:
            warnings.append(
                f"{path}: MCP server `{name}` is not wrapped with observal-shim. "
                "Install via `observal install <id> --ide cursor` to enable telemetry."
            )


def _check_gemini(path: Path, data: dict, issues: list, warnings: list):
    """Check Gemini CLI settings for Observal conflicts."""
    servers = data.get("mcpServers", {})
    for name, srv_cfg in servers.items():
        if "url" in srv_cfg:
            continue  # HTTP transport doesn't need shim
        cmd = srv_cfg.get("command", "")
        args = srv_cfg.get("args", [])
        full_cmd = f"{cmd} {' '.join(str(a) for a in args)}"
        if "observal-shim" not in full_cmd and "observal-proxy" not in full_cmd:
            warnings.append(
                f"{path}: MCP server `{name}` is not wrapped with observal-shim. "
                "Install via `observal install <id> --ide gemini-cli` to enable telemetry."
            )

    # Native OTLP telemetry: Gemini CLI hardcodes gRPC which is incompatible
    # with Observal's HTTP/JSON endpoint. We intentionally disable it and use
    # hooks instead. Only warn if telemetry is enabled (causes gRPC errors).
    telemetry = data.get("telemetry", {})
    if isinstance(telemetry, dict) and telemetry.get("enabled", False):
        warnings.append(
            f"{path}: Gemini native OTLP telemetry is enabled but uses gRPC (incompatible with Observal). "
            "Run `observal scan --ide gemini-cli --home` to disable it — hooks handle telemetry instead."
        )

    # Check hooks configuration
    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict) or not hooks:
        warnings.append(
            f"{path}: No Observal hooks configured for Gemini CLI. "
            "Run `observal scan --ide gemini-cli --home` to inject hook bridge for telemetry collection."
        )
    else:
        # Verify hooks point to Observal scripts
        has_observal_hook = False
        for _evt, handlers in hooks.items():
            if not isinstance(handlers, list):
                continue
            for handler_group in handlers:
                for h in handler_group.get("hooks") or []:
                    cmd = h.get("command", "")
                    if "gemini_hook" in cmd or "gemini_stop_hook" in cmd:
                        has_observal_hook = True
                        break
                if has_observal_hook:
                    break
            if has_observal_hook:
                break
        if not has_observal_hook:
            warnings.append(
                f"{path}: Hooks block exists but no Observal hooks found. "
                "Run `observal scan --ide gemini-cli --home` to inject hook bridge for telemetry collection."
            )


def _check_gemini_installation(issues: list, warnings: list):
    """Check Gemini CLI installation and telemetry configuration."""
    # Check for gemini binary
    if shutil.which("gemini"):
        pass  # Installed
    else:
        warnings.append("`gemini` CLI not found in PATH. Install it to use MCP servers and telemetry with Observal.")

    # Check ~/.gemini/settings.json for telemetry configuration
    gemini_settings = Path.home() / ".gemini" / "settings.json"
    if gemini_settings.exists():
        data = _load_json(gemini_settings)
        if data:
            _check_gemini(gemini_settings, data, issues, warnings)
    # Also check MCP servers in user settings
    mcp_path = Path.home() / ".gemini" / "settings.json"
    if mcp_path.exists():
        data = _load_json(mcp_path)
        if data:
            servers = data.get("mcpServers", {})
            unwrapped = [
                n
                for n, c in servers.items()
                if isinstance(c, dict)
                and "observal-shim" not in c.get("command", "")
                and "observal-proxy" not in c.get("command", "")
                and "url" not in c  # HTTP transport doesn't need shim
            ]
            if unwrapped:
                warnings.append(
                    f"Gemini MCP servers not wrapped with observal-shim: {', '.join(unwrapped)}. "
                    "Run `observal scan --ide gemini-cli` to wrap them."
                )


def _check_copilot(path: Path, data: dict, issues: list, warnings: list):
    """Check GitHub Copilot (VS Code) MCP config for Observal conflicts."""
    servers = data.get("servers", data.get("mcpServers", {}))
    for name, srv_cfg in servers.items():
        cmd = srv_cfg.get("command", "")
        args = srv_cfg.get("args", [])
        full_cmd = f"{cmd} {' '.join(str(a) for a in args)}"
        if "observal-shim" not in full_cmd and "observal-proxy" not in full_cmd:
            warnings.append(
                f"{path}: MCP server `{name}` is not wrapped with observal-shim. "
                "Install via `observal install <id> --ide copilot` to enable telemetry."
            )


def _check_copilot_cli(path: Path, data: dict, issues: list, warnings: list):
    """Check Copilot CLI settings for Observal conflicts."""
    path_name = path.name

    if path_name == "config.json":
        # Check hooks configuration
        if data.get("disableAllHooks"):
            issues.append(f"{path}: `disableAllHooks` is true. Observal hook telemetry will not fire.")

        hooks = data.get("hooks", {})
        if not hooks:
            warnings.append(
                f"{path}: No Observal hooks configured for Copilot CLI. "
                "Run `observal scan --ide copilot-cli --home` to inject hook bridge."
            )
        else:
            has_observal_hook = False
            for _evt, handlers in hooks.items():
                if not isinstance(handlers, list):
                    continue
                for h in handlers:
                    if isinstance(h, dict) and "telemetry/hooks" in h.get("bash", ""):
                        has_observal_hook = True
                        break
                if has_observal_hook:
                    break
            if not has_observal_hook:
                warnings.append(
                    f"{path}: Hooks block exists but no Observal hooks found. "
                    "Run `observal scan --ide copilot-cli --home` to inject hook bridge."
                )

    elif path_name == "mcp-config.json":
        servers = data.get("mcpServers", {})
        for name, srv_cfg in servers.items():
            if not isinstance(srv_cfg, dict):
                continue
            if "url" in srv_cfg:
                continue
            cmd = srv_cfg.get("command", "")
            args = srv_cfg.get("args", [])
            full_cmd = f"{cmd} {' '.join(str(a) for a in args)}"
            if "observal-shim" not in full_cmd and "observal-proxy" not in full_cmd:
                warnings.append(
                    f"{path}: MCP server `{name}` is not wrapped with observal-shim. "
                    "Run `observal scan --ide copilot-cli --home` to wrap them."
                )


def _check_copilot_cli_installation(issues: list, warnings: list):
    """Check Copilot CLI installation and hook configuration."""
    if not shutil.which("copilot"):
        warnings.append(
            "`copilot` CLI not found in PATH. Install with: curl -fsSL https://gh.io/copilot-install | bash"
        )

    copilot_config = Path.home() / ".copilot" / "config.json"
    if copilot_config.exists():
        data = _load_json(copilot_config)
        if data:
            hooks = data.get("hooks", {})
            has_observal = any(
                "telemetry/hooks" in h.get("bash", "")
                for handlers in hooks.values()
                if isinstance(handlers, list)
                for h in handlers
                if isinstance(h, dict)
            )
            if not has_observal:
                warnings.append(
                    "Copilot CLI config exists but no Observal hooks found. "
                    "Run `observal scan --ide copilot-cli --home` to inject hooks."
                )

    mcp_path = Path.home() / ".copilot" / "mcp-config.json"
    if mcp_path.exists():
        data = _load_json(mcp_path)
        if data:
            servers = data.get("mcpServers", {})
            unwrapped = [
                n
                for n, c in servers.items()
                if isinstance(c, dict)
                and "observal-shim" not in c.get("command", "")
                and "observal-proxy" not in c.get("command", "")
                and "url" not in c
            ]
            if unwrapped:
                warnings.append(
                    f"Copilot CLI MCP servers not wrapped with observal-shim: {', '.join(unwrapped)}. "
                    "Run `observal scan --ide copilot-cli --home` to wrap them."
                )


def _check_opencode(path: Path, data: dict, issues: list, warnings: list):
    """Check OpenCode config for Observal conflicts."""
    mcp = data.get("mcp", {})
    for name, srv_cfg in mcp.items():
        if not isinstance(srv_cfg, dict):
            continue
        cmd = srv_cfg.get("command", [])
        cmd_str = " ".join(str(c) for c in cmd) if isinstance(cmd, list) else str(cmd)
        if "observal-shim" not in cmd_str and "observal-proxy" not in cmd_str:
            warnings.append(
                f"{path}: MCP server `{name}` is not wrapped with observal-shim. "
                "Install via `observal install <id> --ide opencode` to enable telemetry."
            )


def _check_codex(data: dict, issues: list, warnings: list, path: Path | None = None):
    """Check Codex config.toml for Observal compatibility.

    Codex uses TOML (not JSON), so data is a parsed dict from tomllib/toml.
    """
    mcp = data.get("mcp", {})
    servers = mcp.get("servers", {})
    for name, srv_cfg in servers.items():
        if not isinstance(srv_cfg, dict):
            continue
        if "url" in srv_cfg:
            continue
        cmd = srv_cfg.get("command", "")
        args = srv_cfg.get("args", [])
        full_cmd = f"{cmd} {' '.join(str(a) for a in args)}"
        if "observal-shim" not in full_cmd and "observal-proxy" not in full_cmd:
            label = f"{path}: " if path else ""
            warnings.append(
                f"{label}MCP server `{name}` is not wrapped with observal-shim. "
                "Install via `observal install <id> --ide codex` to enable telemetry."
            )

    otel = data.get("otel", {})
    if otel:
        exporter = otel.get("exporter", {}).get("otlp-http", {})
        trace_exporter = otel.get("trace_exporter", {}).get("otlp-http", {})
        if not exporter and not trace_exporter:
            warnings.append(
                f"{path}: OTel config exists but no OTLP exporters configured. "
                "Observal needs [otel.exporter.otlp-http] and [otel.trace_exporter.otlp-http] in config.toml."
            )
    elif not mcp:
        path_label = f"{path}: " if path else ""
        warnings.append(
            f"{path_label}No OTel or MCP configuration found. "
            "Run `observal scan --ide codex` or `observal install <id> --ide codex` to configure."
        )


def _load_toml(path: Path) -> dict | None:
    try:
        try:
            import tomllib
        except ImportError:
            try:
                import tomli as tomllib
            except ImportError:
                try:
                    import toml as tomllib
                except ImportError:
                    return None
        content = path.read_text()
        if hasattr(tomllib, "loads"):
            return tomllib.loads(content)
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return None


def _check_codex_installation(issues: list, warnings: list):
    """Check Codex CLI installation and configuration."""
    if shutil.which("codex"):
        pass
    else:
        warnings.append("`codex` CLI not found in PATH. Install it to use MCP servers and telemetry with Observal.")

    codex_config = Path.home() / ".codex" / "config.toml"
    if codex_config.exists():
        data = _load_toml(codex_config)
        if data is None:
            issues.append(f"{codex_config}: file exists but is not valid TOML.")
        else:
            _check_codex(data, issues, warnings, codex_config)


def _check_mcp_json(path: Path, data: dict, issues: list, warnings: list):
    """Check .mcp.json for unwrapped servers."""
    servers = data.get("mcpServers", {})
    for name, srv_cfg in servers.items():
        cmd = srv_cfg.get("command", "")
        args = srv_cfg.get("args", [])
        full_cmd = f"{cmd} {' '.join(str(a) for a in args)}"
        if "observal-shim" not in full_cmd and "observal-proxy" not in full_cmd:
            warnings.append(
                f"{path}: MCP server `{name}` is not wrapped with observal-shim/proxy. "
                "Telemetry will not be collected for this server."
            )


# ── Observal config checks ──────────────────────────────


def _check_observal_config(issues: list, warnings: list):
    """Check Observal's own config."""
    config_path = Path.home() / ".observal" / "config.json"
    if not config_path.exists():
        issues.append("~/.observal/config.json not found. Run `observal auth login` first.")
        return

    data = _load_json(config_path)
    if data is None:
        issues.append("~/.observal/config.json is not valid JSON.")
        return

    if not data.get("access_token"):
        issues.append("No access token in ~/.observal/config.json. Run `observal auth login`.")

    if not data.get("server_url"):
        issues.append("No server_url in ~/.observal/config.json. Run `observal auth login`.")

    # Check server is reachable
    server_url = data.get("server_url", "")
    if server_url:
        try:
            import httpx

            resp = httpx.get(f"{server_url}/health", timeout=5)
            if resp.status_code != 200:
                issues.append(f"Observal server at {server_url} returned status {resp.status_code}.")
        except Exception as e:
            issues.append(f"Cannot reach Observal server at {server_url}: {e}")


# ── Environment checks ───────────────────────────────────


def _check_environment(issues: list, warnings: list):
    """Check environment variables."""
    if os.environ.get("OBSERVAL_KEY"):
        pass  # good
    elif not (Path.home() / ".observal" / "config.json").exists():
        warnings.append("OBSERVAL_KEY env var not set and no config file found.")

    # Check if Docker is available (for sandbox runner)
    if os.system("docker info > /dev/null 2>&1") != 0:
        warnings.append("Docker is not running. `observal-sandbox-run` requires Docker.")

    # Check entry points
    for ep in ["observal-shim", "observal-proxy", "observal-sandbox-run"]:
        if not shutil.which(ep):
            warnings.append(f"`{ep}` not found in PATH. Run `uv tool install --editable .` from the Observal repo.")


# ── Main doctor command ──────────────────────────────────


@doctor_app.callback(invoke_without_command=True)
def doctor(
    ctx: typer.Context,
    ide: str = typer.Option(
        None,
        help="Check specific IDE only (claude-code, kiro, cursor, gemini-cli, copilot, copilot-cli, opencode, codex)",
    ),
    fix: bool = typer.Option(False, help="Show suggested fixes"),
):
    """Diagnose IDE and Observal settings for compatibility issues."""
    if ctx.invoked_subcommand is not None:
        return  # Let the subcommand handle it
    issues: list[str] = []
    warnings: list[str] = []

    rprint("[bold]Observal Doctor[/bold]\n")

    # 1. Check Observal itself
    rprint("[cyan]Checking Observal config...[/cyan]")
    _check_observal_config(issues, warnings)

    # 2. Check environment
    rprint("[cyan]Checking environment...[/cyan]")
    _check_environment(issues, warnings)

    # 3. Kiro-specific installation checks
    if not ide or ide in ("kiro", "kiro-cli"):
        rprint("[cyan]Checking Kiro installation...[/cyan]")
        _check_kiro_installation(issues, warnings)

    # 3b. Gemini CLI-specific installation checks
    if not ide or ide == "gemini-cli":
        rprint("[cyan]Checking Gemini CLI installation...[/cyan]")
        _check_gemini_installation(issues, warnings)

    # 3c. Copilot CLI-specific installation checks
    if not ide or ide == "copilot-cli":
        rprint("[cyan]Checking Copilot CLI installation...[/cyan]")
        _check_copilot_cli_installation(issues, warnings)

    # 3d. Codex-specific installation checks
    if not ide or ide == "codex":
        rprint("[cyan]Checking Codex installation...[/cyan]")
        _check_codex_installation(issues, warnings)

    # 4. Check IDE configs
    ides_to_check = [ide] if ide else list(IDE_CONFIGS.keys())

    for ide_name in ides_to_check:
        if ide_name not in IDE_CONFIGS:
            rprint(f"[yellow]Unknown IDE: {ide_name}[/yellow]")
            continue

        config = IDE_CONFIGS[ide_name]
        rprint(f"[cyan]Checking {ide_name}...[/cyan]")

        check_fn = {
            "claude-code": _check_claude_code,
            "kiro": _check_kiro,
            "cursor": _check_cursor,
            "gemini-cli": _check_gemini,
            "copilot": _check_copilot,
            "copilot-cli": _check_copilot_cli,
            "opencode": _check_opencode,
        }.get(ide_name)

        found_any = False
        for path_list_key in ["user_settings", "project_settings"]:
            for path in config[path_list_key]:
                if path.exists():
                    found_any = True
                    if path.suffix == ".toml":
                        # Codex uses TOML config — load with tomllib
                        data = _load_toml(path)
                        if data is None:
                            issues.append(f"{path}: file exists but is not valid TOML.")
                        elif ide_name == "codex":
                            _check_codex(data, issues, warnings, path)
                    else:
                        data = _load_json(path)
                        if data is None:
                            issues.append(f"{path}: file exists but is not valid JSON.")
                        elif check_fn:
                            check_fn(path, data, issues, warnings)

        for path in config.get("mcp", []):
            if path.exists():
                found_any = True
                data = _load_json(path)
                if data is not None:
                    _check_mcp_json(path, data, issues, warnings)

        if not found_any:
            rprint(f"  [dim]No config files found for {ide_name}[/dim]")

    # 4. Report
    rprint("")
    if not issues and not warnings:
        rprint("[bold green]All clear![/bold green] No issues found.")
        raise typer.Exit(0)

    if issues:
        rprint(f"[bold red]{len(issues)} issue(s):[/bold red]")
        for i, issue in enumerate(issues, 1):
            rprint(f"  [red]{i}.[/red] {issue}")

    if warnings:
        rprint(f"\n[bold yellow]{len(warnings)} warning(s):[/bold yellow]")
        for i, warning in enumerate(warnings, 1):
            rprint(f"  [yellow]{i}.[/yellow] {warning}")

    if fix and issues:
        rprint("\n[bold]Suggested fixes:[/bold]")
        for issue in issues:
            if "disableAllHooks" in issue:
                rprint("  Set `disableAllHooks: false` in your Claude Code settings.json")
            elif "allowedHttpHookUrls" in issue:
                cfg = config.load()
                srv = cfg.get("server_url", "http://localhost:8000")
                rprint(f'  Add `"{srv}/*"` to `allowedHttpHookUrls`')
            elif "OBSERVAL_API_KEY" in issue and "httpHookAllowedEnvVars" in issue:
                rprint('  Add `"OBSERVAL_API_KEY"` to `httpHookAllowedEnvVars`')
            elif "allowManagedHooksOnly" in issue:
                rprint("  Set `allowManagedHooksOnly: false` or add Observal hooks to managed config")
            elif "observal auth login" in issue:
                rprint("  Run: observal auth login")
            elif "Cannot reach" in issue:
                rprint("  Start the server: cd docker && docker compose up -d")
            elif "kiro-cli" in issue and "not found" in issue:
                rprint("  Install: curl -fsSL https://cli.kiro.dev/install | bash")
            elif "kiro-cli" in issue and "not authenticated" in issue:
                rprint("  Run: kiro-cli login")
            elif "Observal telemetry hooks" in issue:
                rprint("  Run: observal scan --ide kiro --home")
            elif "observal-shim" in issue and "Kiro" in issue:
                rprint("  Run: observal scan --ide kiro")
            elif "native OTLP" in issue and "gRPC" in issue:
                rprint("  Run: observal scan --ide gemini-cli --home")
            elif "observal-shim" in issue and "gemini-cli" in issue:
                rprint("  Run: observal install <id> --ide gemini-cli")

    raise typer.Exit(1 if issues else 0)


# ── SLI: reinstall hooks ──────────────────────────────────

# Kiro camelCase event mapping and all supported events
_KIRO_EVENT_MAP = {
    "SessionStart": "agentSpawn",
    "UserPromptSubmit": "userPromptSubmit",
    "PreToolUse": "preToolUse",
    "PostToolUse": "postToolUse",
    "Stop": "stop",
}

# All Claude Code events that should have hooks
_ALL_EVENTS = [
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "SubagentStart",
    "SubagentStop",
    "Stop",
    "StopFailure",
    "Notification",
    "TaskCreated",
    "TaskCompleted",
    "PreCompact",
    "PostCompact",
    "WorktreeCreate",
    "WorktreeRemove",
    "Elicitation",
    "ElicitationResult",
]


def _find_hook_script(name: str) -> str | None:
    """Locate a hook script by filename."""
    candidates = [
        Path(__file__).parent / "hooks" / name,
        Path(shutil.which(name) or ""),
    ]
    for p in candidates:
        if p.is_file():
            return str(p.resolve())
    return None


def _install_claude_code_hooks(server_url: str, api_key: str) -> list[str]:
    """Reconcile Claude Code hooks into ~/.claude/settings.json."""
    hooks_url = f"{server_url.rstrip('/')}/api/v1/telemetry/hooks"
    hook_script = _find_hook_script("observal-hook.sh")
    stop_script = _find_hook_script("observal-stop-hook.sh")
    cfg = config.load()
    user_id = cfg.get("user_id", "")

    desired_hooks = get_desired_hooks(hook_script, stop_script, hooks_url, user_id)
    desired_env = get_desired_env(server_url, api_key, user_id)

    return settings_reconciler.reconcile(desired_hooks, desired_env)


def _install_kiro_hooks(server_url: str) -> tuple[list[str], bool]:
    """Install Observal hooks into all Kiro agent configs.

    Returns (messages, changed) where changed is True if any file was modified.
    """
    agents_dir = Path.home() / ".kiro" / "agents"
    changes: list[str] = []
    changed = False

    agents_dir.mkdir(parents=True, exist_ok=True)

    agent_files = list(agents_dir.glob("*.json"))

    hooks_url = f"{server_url.rstrip('/')}/api/v1/telemetry/hooks"

    # Migrate: remove old default.json created by earlier Observal versions.
    old_default = agents_dir / "default.json"
    if old_default.exists():
        try:
            od = json.loads(old_default.read_text())
            if od.get("name") == "default" and any(
                "telemetry/hooks" in h.get("command", "")
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
                changes.append("- default: removed (migrated to kiro_default)")
                changed = True
        except (ValueError, OSError):
            pass
    agent_files = list(agents_dir.glob("*.json"))

    for af in agent_files:
        agent_name = af.stem
        # Skip kiro_default — only trace registered agents
        if agent_name == "kiro_default":
            continue
        try:
            data = json.loads(af.read_text())
        except (json.JSONDecodeError, OSError):
            changes.append(f"[yellow]⚠ {agent_name}: could not parse, skipped[/yellow]")
            continue

        py = sys.executable
        generic_cmd = f"{py} -m observal_cli.hooks.kiro_hook --url {hooks_url} --agent-name {agent_name}"
        stop_cmd = f"{py} -m observal_cli.hooks.kiro_stop_hook --url {hooks_url} --agent-name {agent_name}"

        desired_kiro_hooks: dict[str, list[dict]] = {}
        for event in _ALL_EVENTS:
            kiro_event = _KIRO_EVENT_MAP.get(event)
            if not kiro_event:
                continue
            if kiro_event == "stop":
                desired_kiro_hooks[kiro_event] = [{"command": stop_cmd}]
            else:
                entry: dict = {"command": generic_cmd}
                if kiro_event in ("preToolUse", "postToolUse"):
                    entry["matcher"] = "*"
                desired_kiro_hooks[kiro_event] = [entry]

        current_hooks = data.get("hooks", {})
        updated = False

        for kiro_event, desired_entries in desired_kiro_hooks.items():
            existing = current_hooks.get(kiro_event, [])
            # Check if Observal hook already present
            has_observal = any(
                "observal" in h.get("command", "") or "telemetry/hooks" in h.get("command", "") for h in existing
            )
            if not has_observal:
                # Append our hooks, keep existing ones
                current_hooks[kiro_event] = existing + desired_entries
                updated = True

        if updated:
            data["hooks"] = current_hooks
            af.write_text(json.dumps(data, indent=2) + "\n")
            changes.append(f"+ {agent_name}: added Observal hooks")
            changed = True
        else:
            changes.append(f"[dim]  {agent_name}: already has Observal hooks[/dim]")

    return changes, changed


def _install_copilot_cli_hooks(server_url: str) -> tuple[list[str], bool]:
    """Install Observal hooks into ~/.copilot/config.json.

    Returns (messages, changed) where changed is True if the file was modified.
    """
    import sys

    changes: list[str] = []
    changed = False

    hooks_url = f"{server_url.rstrip('/')}/api/v1/telemetry/hooks"

    def _hook_entry(event: str, is_stop: bool = False) -> dict:
        module = "observal_cli.hooks.copilot_cli_stop_hook" if is_stop else "observal_cli.hooks.copilot_cli_hook"
        py = sys.executable
        cmd = f"{py} -m {module} --url {hooks_url} --event-name {event}"
        return {"type": "command", "bash": cmd, "powershell": cmd, "timeoutSec": 10}

    desired_hooks = {
        "sessionStart": [_hook_entry("sessionStart")],
        "userPromptSubmitted": [_hook_entry("userPromptSubmitted")],
        "preToolUse": [_hook_entry("preToolUse")],
        "postToolUse": [_hook_entry("postToolUse")],
        "sessionEnd": [_hook_entry("sessionEnd", is_stop=True)],
        "errorOccurred": [_hook_entry("errorOccurred")],
    }

    copilot_config = Path.home() / ".copilot" / "config.json"
    try:
        data: dict = {}
        if copilot_config.exists():
            data = _load_json(copilot_config) or {}

        existing = data.get("hooks", {})

        for evt, entries in desired_hooks.items():
            cur = existing.get(evt, [])
            has_obs = any("telemetry/hooks" in h.get("bash", "") for h in cur if isinstance(h, dict))
            if not has_obs:
                existing[evt] = cur + entries
                changed = True
                changes.append(f"+ {evt}: added Observal hook")
            else:
                # Check if URL matches
                obs_bash = next(
                    (h.get("bash", "") for h in cur if isinstance(h, dict) and "telemetry/hooks" in h.get("bash", "")),
                    "",
                )
                if hooks_url not in obs_bash:
                    existing[evt] = [
                        h for h in cur if not isinstance(h, dict) or "telemetry/hooks" not in h.get("bash", "")
                    ] + entries
                    changed = True
                    changes.append(f"~ {evt}: updated Observal hook URL")
                else:
                    changes.append(f"[dim]  {evt}: already configured[/dim]")

        if changed:
            data["hooks"] = existing
            copilot_config.parent.mkdir(parents=True, exist_ok=True)
            copilot_config.write_text(json.dumps(data, indent=2) + "\n")
    except Exception as e:
        return [f"[red]Error updating {copilot_config}: {e}[/red]"], False

    return changes, changed


@doctor_app.command(name="sli")
def doctor_sli(
    ide: str = typer.Option(
        None,
        "--ide",
        "-i",
        help="Target IDE only (claude-code, kiro, copilot-cli, gemini-cli). Default: all.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Show changes without applying"),
):
    """Re-install Observal telemetry hooks into Claude Code, Kiro, Copilot CLI, and/or Gemini CLI.

    Repairs missing or outdated hooks non-destructively — your existing
    hooks and settings are preserved.
    """
    cfg = config.load()
    server_url = cfg.get("server_url")
    api_key = cfg.get("api_key", "")

    if not server_url:
        rprint("[red]Not configured. Run [bold]observal auth login[/bold] first.[/red]")
        raise typer.Exit(1)

    targets = [ide] if ide else ["claude-code", "kiro", "copilot-cli", "gemini-cli"]
    any_changes = False

    for target in targets:
        if target == "claude-code":
            claude_dir = Path.home() / ".claude"
            if not claude_dir.is_dir() and not shutil.which("claude"):
                rprint("[dim]Claude Code not detected — skipping[/dim]")
                continue

            rprint("[cyan]Claude Code[/cyan]")
            if dry_run:
                hooks_url = f"{server_url.rstrip('/')}/api/v1/telemetry/hooks"
                hook_script = _find_hook_script("observal-hook.sh")
                stop_script = _find_hook_script("observal-stop-hook.sh")
                user_id = cfg.get("user_id", "")
                desired_hooks = get_desired_hooks(hook_script, stop_script, hooks_url, user_id)
                desired_env = get_desired_env(server_url, api_key, user_id)
                changes = settings_reconciler.reconcile(desired_hooks, desired_env, dry_run=True)
            else:
                changes = _install_claude_code_hooks(server_url, api_key)

            if changes:
                any_changes = True
                for c in changes:
                    rprint(f"  {c}")
            else:
                rprint("  [dim]Already up to date[/dim]")

        elif target in ("kiro", "kiro-cli"):
            rprint("[cyan]Kiro[/cyan]")
            if dry_run:
                rprint("  [yellow]Dry run not supported for Kiro — use without --dry-run[/yellow]")
                continue

            messages, kiro_changed = _install_kiro_hooks(server_url)
            if kiro_changed:
                any_changes = True
            for c in messages:
                rprint(f"  {c}")

        elif target in ("copilot-cli", "copilot_cli"):
            rprint("[cyan]Copilot CLI[/cyan]")
            copilot_dir = Path.home() / ".copilot"
            if not copilot_dir.is_dir() and not shutil.which("copilot"):
                rprint("[dim]Copilot CLI not detected — skipping[/dim]")
                continue

            if dry_run:
                rprint("  [yellow]Dry run not supported for Copilot CLI — use without --dry-run[/yellow]")
                continue

            messages, ccli_changed = _install_copilot_cli_hooks(server_url)
            if ccli_changed:
                any_changes = True
            for c in messages:
                rprint(f"  {c}")

        elif target in ("gemini-cli", "gemini_cli"):
            rprint("[cyan]Gemini CLI[/cyan]")
            gemini_settings = Path.home() / ".gemini" / "settings.json"
            gemini_data: dict = {}
            if gemini_settings.exists():
                try:
                    gemini_data = json.loads(gemini_settings.read_text())
                except (json.JSONDecodeError, OSError):
                    pass

            telemetry = gemini_data.get("telemetry", {})
            # Native OTLP should be disabled (gRPC incompatible), hooks handle telemetry
            needs_update = (
                not isinstance(telemetry, dict)
                or telemetry.get("enabled") is not False
                or telemetry.get("logPrompts") is not True
            )

            if needs_update:
                if dry_run:
                    rprint("  [yellow]Would disable native OTLP in ~/.gemini/settings.json[/yellow]")
                else:
                    gemini_data.setdefault("telemetry", {})
                    gemini_data["telemetry"]["enabled"] = False
                    gemini_data["telemetry"]["logPrompts"] = True
                    gemini_data["telemetry"].pop("target", None)
                    gemini_data["telemetry"].pop("otlpEndpoint", None)
                    gemini_settings.parent.mkdir(parents=True, exist_ok=True)
                    gemini_settings.write_text(json.dumps(gemini_data, indent=2) + "\n")
                    rprint(f"  + Disabled native OTLP in {gemini_settings} (hooks handle telemetry)")
                    any_changes = True
            else:
                rprint("  [dim]Gemini native OTLP already disabled[/dim]")

        else:
            rprint(
                f"[yellow]Unknown IDE: {target}. Use 'claude-code', 'kiro', 'copilot-cli', or 'gemini-cli'.[/yellow]"
            )

    if any_changes:
        rprint("\n[green]✓ Hooks installed.[/green] Restart your IDE session to pick up changes.")
    elif not dry_run:
        rprint("\n[dim]All hooks already up to date.[/dim]")
