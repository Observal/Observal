"""observal doctor: diagnose IDE settings that conflict with Observal telemetry."""

import json
import os
from pathlib import Path

import typer
from rich import print as rprint

doctor_app = typer.Typer(help="Diagnose IDE settings for Observal compatibility")


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
}


# ── Check functions ──────────────────────────────────────


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _check_claude_code(path: Path, data: dict, issues: list, warnings: list):
    """Check Claude Code settings for Observal conflicts."""
    # Hooks disabled entirely
    if data.get("disableAllHooks"):
        issues.append(f"{path}: `disableAllHooks` is true. Observal hook telemetry will not fire.")

    # allowedHttpHookUrls blocks our endpoint
    allowed_urls = data.get("allowedHttpHookUrls")
    if isinstance(allowed_urls, list) and len(allowed_urls) > 0:
        has_observal = any("localhost:8000" in u or "observal" in u.lower() for u in allowed_urls)
        if not has_observal:
            issues.append(
                f"{path}: `allowedHttpHookUrls` is set but does not include Observal's URL. "
                "Add `http://localhost:8000/*` to allow hook telemetry."
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
                "Observal telemetry POSTs to localhost:8000."
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


def _check_cursor(path: Path, data: dict, issues: list, warnings: list):
    """Check Cursor MCP config for Observal conflicts."""
    servers = data.get("mcpServers", {})
    for name, config in servers.items():
        cmd = config.get("command", "")
        args = config.get("args", [])
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
    for name, config in servers.items():
        cmd = config.get("command", "")
        args = config.get("args", [])
        full_cmd = f"{cmd} {' '.join(str(a) for a in args)}"
        if "observal-shim" not in full_cmd and "observal-proxy" not in full_cmd:
            warnings.append(
                f"{path}: MCP server `{name}` is not wrapped with observal-shim. "
                "Install via `observal install <id> --ide gemini-cli` to enable telemetry."
            )


def _check_mcp_json(path: Path, data: dict, issues: list, warnings: list):
    """Check .mcp.json for unwrapped servers."""
    servers = data.get("mcpServers", {})
    for name, config in servers.items():
        cmd = config.get("command", "")
        args = config.get("args", [])
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
        issues.append("~/.observal/config.json not found. Run `observal init` first.")
        return

    data = _load_json(config_path)
    if data is None:
        issues.append("~/.observal/config.json is not valid JSON.")
        return

    if not data.get("api_key"):
        issues.append("No API key in ~/.observal/config.json. Run `observal login`.")

    if not data.get("server_url"):
        issues.append("No server_url in ~/.observal/config.json. Run `observal init`.")

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
    for ep in ["observal-shim", "observal-proxy", "observal-sandbox-run", "observal-graphrag-proxy"]:
        if os.system(f"which {ep} > /dev/null 2>&1") != 0:
            warnings.append(f"`{ep}` not found in PATH. Run `uv tool install --editable .` from the Observal repo.")


# ── Main doctor command ──────────────────────────────────


@doctor_app.callback(invoke_without_command=True)
def doctor(
    ide: str = typer.Option(None, help="Check specific IDE only (claude-code, kiro, cursor, gemini-cli)"),
    fix: bool = typer.Option(False, help="Show suggested fixes"),
):
    """Diagnose IDE and Observal settings for compatibility issues."""
    issues: list[str] = []
    warnings: list[str] = []

    rprint("[bold]Observal Doctor[/bold]\n")

    # 1. Check Observal itself
    rprint("[cyan]Checking Observal config...[/cyan]")
    _check_observal_config(issues, warnings)

    # 2. Check environment
    rprint("[cyan]Checking environment...[/cyan]")
    _check_environment(issues, warnings)

    # 3. Check IDE configs
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
        }.get(ide_name)

        found_any = False
        for path_list_key in ["user_settings", "project_settings"]:
            for path in config[path_list_key]:
                if path.exists():
                    found_any = True
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
                rprint('  Add `"http://localhost:8000/*"` to `allowedHttpHookUrls`')
            elif "OBSERVAL_API_KEY" in issue and "httpHookAllowedEnvVars" in issue:
                rprint('  Add `"OBSERVAL_API_KEY"` to `httpHookAllowedEnvVars`')
            elif "allowManagedHooksOnly" in issue:
                rprint("  Set `allowManagedHooksOnly: false` or add Observal hooks to managed config")
            elif "observal init" in issue:
                rprint("  Run: observal init")
            elif "observal login" in issue:
                rprint("  Run: observal login")
            elif "Cannot reach" in issue:
                rprint("  Start the server: cd docker && docker compose up -d")

    raise typer.Exit(1 if issues else 0)
