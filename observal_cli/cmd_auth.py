"""Auth & config CLI commands."""

from __future__ import annotations

import json as _json
import shutil
from pathlib import Path

import httpx
import typer
from rich import print as rprint

from observal_cli import client, config
from observal_cli.render import console, kv_panel, spinner, status_badge

# ── Auth subgroup ───────────────────────────────────────────

auth_app = typer.Typer(
    name="auth",
    help="Authentication and account commands",
    no_args_is_help=True,
)

config_app = typer.Typer(help="CLI configuration")


# ── Auth commands (registered on auth_app) ──────────────────


@auth_app.command()
def init(server: str = typer.Option(None, "--server", "-s", help="Server URL")):
    """First-run setup: connect to a team server or initialize a new local server."""
    server_url = server or typer.prompt("Server URL", default="http://localhost:8000")

    # 1. Verify Connectivity First
    try:
        with spinner("Checking server..."):
            r = httpx.get(f"{server_url.rstrip('/')}/health", timeout=10)
            r.raise_for_status()
    except httpx.ConnectError:
        rprint(f"[red]x Connection failed.[/red] Is the server running at {server_url}?")
        raise typer.Exit(1)
    except Exception as e:
        rprint(f"[red]x Server error:[/red] {e!s}")
        raise typer.Exit(1)

    rprint("[green]Connected to server[/green]\n")

    # 2. Smart Detection: Determine if we are a Developer (Connect) or Admin (Setup)
    setup_choice = typer.prompt(
        "Are you connecting to an existing team (C) or setting up a brand new server (N)?", default="C"
    )

    if setup_choice.lower().startswith("c"):
        # --- DEVELOPER PATH (No Docker, just API Key) ---
        api_key = typer.prompt("Your API Key", hide_input=True)
        _do_login(server_url, api_key)

    else:
        # --- ADMIN PATH (Provisioning the first account) ---
        admin_email = typer.prompt("Admin email")
        admin_name = typer.prompt("Admin name")
        try:
            with spinner("Creating admin account..."):
                r = httpx.post(
                    f"{server_url.rstrip('/')}/api/v1/auth/init",
                    json={"email": admin_email, "name": admin_name},
                    timeout=30,
                )
                r.raise_for_status()
                data = r.json()

            config.save({"server_url": server_url, "api_key": data["api_key"]})
            rprint(f"\n[green]Platform Initialized![/green] Config saved to [dim]{config.CONFIG_FILE}[/dim]")
            rprint("\n[bold]Your Admin API key:[/bold]")
            rprint(f"  {data['api_key']}")
            rprint("\n[dim]Keep this safe. You can now invite developers via the Web UI.[/dim]")

            _configure_claude_code(server_url, data["api_key"])

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400 and "already initialized" in e.response.text.lower():
                rprint("\n[yellow]System is already initialized.[/yellow]")
                rprint("Switching to login flow...")
                api_key = typer.prompt("API Key", hide_input=True)
                _do_login(server_url, api_key)
            else:
                rprint(f"[red]Error {e.response.status_code}: {e.response.text}[/red]")
                raise typer.Exit(1)


@auth_app.command()
def login(
    server: str = typer.Option(None, "--server", "-s", help="Server URL (skips prompt)"),
    key: str = typer.Option(None, "--key", "-k", help="API key (skips prompt)"),
):
    """Login with an existing API key."""
    server_url = server or typer.prompt("Server URL", default="http://localhost:8000")
    _do_login(server_url, key)


@auth_app.command()
def logout():
    """Clear saved credentials."""
    if config.CONFIG_FILE.exists():
        # Read strictly from disk to avoid mixing with env variables
        import json

        raw_cfg = json.loads(config.CONFIG_FILE.read_text())

        # Remove the key and save directly
        if "api_key" in raw_cfg:
            del raw_cfg["api_key"]
            config.CONFIG_FILE.write_text(json.dumps(raw_cfg, indent=2))

        rprint("[green]Logged out (removed from disk).[/green]")
    else:
        rprint("[dim]No config to clear.[/dim]")


@auth_app.command()
def whoami(
    output: str = typer.Option("table", "--output", "-o", help="Output format: table, json"),
):
    """Show current authenticated user."""
    with spinner("Checking..."):
        user = client.get("/api/v1/auth/whoami")
    if output == "json":
        from observal_cli.render import output_json

        output_json(user)
        return
    console.print(
        kv_panel(
            user["name"],
            [
                ("Email", user["email"]),
                ("Role", status_badge(user.get("role", "user"))),
                ("ID", f"[dim]{user['id']}[/dim]"),
            ],
        )
    )


@auth_app.command()
def status():
    """Check server connectivity and health."""
    cfg = config.load()
    url = cfg.get("server_url", "not set")
    has_key = bool(cfg.get("api_key"))
    ok, latency = client.health()

    rprint(f"  Server:  {url}")
    rprint(f"  API Key: {'[green]configured[/green]' if has_key else '[red]not set[/red]'}")
    if ok:
        color = "green" if latency < 200 else "yellow" if latency < 1000 else "red"
        rprint(f"  Health:  [{color}]ok[/{color}] ({latency:.0f}ms)")
    else:
        rprint("  Health:  [red]unreachable[/red]")


def version_callback():
    """Show CLI version."""
    from importlib.metadata import version as pkg_version

    try:
        v = pkg_version("observal-cli")
    except Exception:
        v = "dev"
    rprint(f"observal [bold]{v}[/bold]")


# ── Deprecated root-level wrappers ──────────────────────────

_DEPRECATION_MSG = "Deprecated: use 'observal auth {cmd}' instead"


def _deprecation_notice(cmd_name: str):
    """Print a deprecation warning for a root-level auth command."""
    rprint(f"[yellow]{_DEPRECATION_MSG.format(cmd=cmd_name)}[/yellow]\n")


def register_deprecated_auth(app: typer.Typer):
    """Register deprecated root-level aliases that delegate to auth subgroup commands."""

    @app.command(name="init", hidden=True)
    def deprecated_init(server: str = typer.Option(None, "--server", "-s", help="Server URL")):
        """[Deprecated] Use 'observal auth init' instead."""
        _deprecation_notice("init")
        init(server=server)

    @app.command(name="login", hidden=True)
    def deprecated_login(
        server: str = typer.Option(None, "--server", "-s", help="Server URL (skips prompt)"),
        key: str = typer.Option(None, "--key", "-k", help="API key (skips prompt)"),
    ):
        """[Deprecated] Use 'observal auth login' instead."""
        _deprecation_notice("login")
        login(server=server, key=key)

    @app.command(name="logout", hidden=True)
    def deprecated_logout():
        """[Deprecated] Use 'observal auth logout' instead."""
        _deprecation_notice("logout")
        logout()

    @app.command(name="whoami", hidden=True)
    def deprecated_whoami(
        output: str = typer.Option("table", "--output", "-o", help="Output format: table, json"),
    ):
        """[Deprecated] Use 'observal auth whoami' instead."""
        _deprecation_notice("whoami")
        whoami(output=output)

    @app.command(name="status", hidden=True)
    def deprecated_status():
        """[Deprecated] Use 'observal auth status' instead."""
        _deprecation_notice("status")
        status()

    @app.command(name="version", hidden=True)
    def deprecated_version():
        """[Deprecated] Use 'observal --version' instead."""
        rprint("[yellow]Deprecated: use 'observal --version' instead[/yellow]\n")
        version_callback()


# ── Helper functions ────────────────────────────────────────


def _do_login(server_url: str, api_key: str | None = None):
    api_key = api_key or typer.prompt("API Key", hide_input=True)
    try:
        with spinner("Authenticating..."):
            r = httpx.get(
                f"{server_url.rstrip('/')}/api/v1/auth/whoami",
                headers={"X-API-Key": api_key},
                timeout=30,
            )
            r.raise_for_status()
            user = r.json()
        config.save({"server_url": server_url, "api_key": api_key})
        rprint(f"[green]Logged in as {user['name']}[/green] ({user['email']}) [{user.get('role', '')}]")
    except httpx.ConnectError:
        rprint(f"[red]Connection failed.[/red] Is the server running at {server_url}?")
        raise typer.Exit(1)
    except httpx.HTTPStatusError:
        rprint("[red]Invalid API key.[/red]")
        raise typer.Exit(1)


def register_config(app: typer.Typer):
    """Register config subcommands."""

    @config_app.command(name="show")
    def config_show():
        """Show current CLI configuration."""
        cfg = config.load()
        safe = dict(cfg)
        if safe.get("api_key"):
            safe["api_key"] = safe["api_key"][:8] + "..." + safe["api_key"][-4:]
        console.print_json(_json.dumps(safe, indent=2))

    @config_app.command(name="set")
    def config_set(
        key: str = typer.Argument(..., help="Config key (output, color, server_url)"),
        value: str = typer.Argument(..., help="Config value"),
    ):
        """Set a CLI config value."""
        if key == "color":
            config.save({key: value.lower() in ("true", "1", "yes")})
        else:
            config.save({key: value})
        rprint(f"[green]Set {key}[/green]")

    @config_app.command(name="path")
    def config_path():
        """Show config file path."""
        rprint(str(config.CONFIG_FILE))

    @config_app.command(name="alias")
    def config_alias(
        name: str = typer.Argument(..., help="Alias name (used as @name)"),
        target: str = typer.Argument(None, help="Target ID (omit to remove)"),
    ):
        """Set or remove an alias for an MCP/agent ID."""
        aliases = config.load_aliases()
        if target:
            aliases[name] = target
            config.save_aliases(aliases)
            rprint(f"[green]@{name} -> {target}[/green]")
        else:
            removed = aliases.pop(name, None)
            config.save_aliases(aliases)
            if removed:
                rprint(f"[green]Removed @{name}[/green]")
            else:
                rprint(f"[yellow]Alias @{name} not found.[/yellow]")

    @config_app.command(name="aliases")
    def config_aliases():
        """List all aliases."""
        aliases = config.load_aliases()
        if not aliases:
            rprint("[dim]No aliases set. Use: observal config alias <name> <id>[/dim]")
            return
        for name, target in sorted(aliases.items()):
            rprint(f"  @{name} -> [dim]{target}[/dim]")

    app.add_typer(config_app, name="config")


def _configure_claude_code(server_url: str, api_key: str):
    """Check for Claude Code and offer to configure its telemetry."""
    claude_dir = Path.home() / ".claude"
    claude_settings_file = claude_dir / "settings.json"

    try:
        claude_exists = claude_dir.is_dir() or shutil.which("claude")
        if not claude_exists:
            return

        if not typer.confirm(
            "\nDetected Claude Code installation.\nConfigure Claude Code telemetry -> Observal?", default=True
        ):
            return

        settings = {}
        if claude_settings_file.exists():
            with open(claude_settings_file, encoding="utf-8") as f:
                try:
                    settings = _json.load(f)
                except _json.JSONDecodeError:
                    rprint(
                        f"[yellow]Warning: Could not parse {claude_settings_file}. A new file will be created.[/yellow]"
                    )
                    pass  # Will create a new file

        # Prepare OTEL config
        otel_env = {
            "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
            "OTEL_METRICS_EXPORTER": "otlp",
            "OTEL_LOGS_EXPORTER": "otlp",
            "OTEL_EXPORTER_OTLP_PROTOCOL": "grpc",
            "OTEL_EXPORTER_OTLP_HEADERS": f"Authorization=Bearer {api_key}",
        }

        # Set endpoint based on server_url
        # Assumes OTLP/gRPC is on port 4317 of the same host
        from urllib.parse import urlparse

        parsed_url = urlparse(server_url)
        scheme = "http" if parsed_url.hostname == "localhost" else "https"
        otel_endpoint = f"{scheme}://{parsed_url.hostname}:4317"
        otel_env["OTEL_EXPORTER_OTLP_ENDPOINT"] = otel_endpoint

        # Merge with existing settings
        if "env" not in settings:
            settings["env"] = {}
        settings["env"].update(otel_env)

        # Write back
        claude_dir.mkdir(exist_ok=True)
        with open(claude_settings_file, "w", encoding="utf-8") as f:
            _json.dump(settings, f, indent=2)

        rprint(f"Updated [dim]{claude_settings_file}[/dim] -- Claude Code will send traces to Observal.")
        rprint("\nYou're all set. Open Claude Code and traces will appear in the dashboard.")

    except Exception as e:
        rprint(f"\n[yellow]Could not configure Claude Code automatically: {e}[/yellow]")
        rprint("Please see documentation for manual configuration.")
