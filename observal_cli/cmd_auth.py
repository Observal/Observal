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
def login(
    server: str = typer.Option(None, "--server", "-s", help="Server URL"),
    key: str = typer.Option(None, "--key", "-k", help="API key (skip prompt)"),
    email: str = typer.Option(None, "--email", "-e", help="Email (for password login)"),
    password: str = typer.Option(None, "--password", "-p", help="Password (for password login)"),
    code: str = typer.Option(None, "--code", "-c", help="Invite code (e.g. OBS-A7X9B2)"),
    name: str = typer.Option(None, "--name", "-n", help="Your name (used with invite/register)"),
):
    """Connect to Observal.

    On a fresh server: auto-creates admin, no prompts needed.
    With email+password: logs in with credentials.
    With an invite code: redeems it and creates your account.
    With --key: logs in with an API key.
    """
    server_url = server or typer.prompt("Server URL", default="http://localhost:8000")
    server_url = server_url.rstrip("/")

    # 1. Check connectivity + initialization state
    try:
        with spinner("Connecting..."):
            r = httpx.get(f"{server_url}/health", timeout=10)
            r.raise_for_status()
            health_data = r.json()
    except httpx.ConnectError:
        rprint(f"[red]Connection failed.[/red] Is the server running at {server_url}?")
        raise typer.Exit(1)
    except Exception as e:
        rprint(f"[red]Server error:[/red] {e!s}")
        raise typer.Exit(1)

    initialized = health_data.get("initialized", True)

    # 2. Fresh server → auto-bootstrap admin
    if not initialized:
        rprint("[green]Connected.[/green] No users yet — creating admin account.\n")
        try:
            with spinner("Bootstrapping..."):
                r = httpx.post(f"{server_url}/api/v1/auth/bootstrap", timeout=30)
                r.raise_for_status()
                data = r.json()

            api_key = data["api_key"]
            user = data["user"]
            config.save({"server_url": server_url, "api_key": api_key})

            rprint(f"[green]Logged in as {user['name']}[/green] ({user['email']}) [admin]")
            rprint(f"[dim]Config saved to {config.CONFIG_FILE}[/dim]\n")
            rprint("[bold]To invite team members:[/bold]")
            rprint("  observal admin invite")
            rprint("  [dim]Share the code — they run: observal auth login --code OBS-XXXX[/dim]")

            _configure_claude_code(server_url, api_key)

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400 and "already initialized" in e.response.text.lower():
                rprint("[yellow]Server was just initialized by someone else.[/yellow]")
                _do_key_login(server_url, key)
            else:
                rprint(f"[red]Bootstrap failed ({e.response.status_code}):[/red] {e.response.text}")
                raise typer.Exit(1)
        return

    rprint("[green]Connected.[/green]\n")

    # 3. Email+password provided via flags → password login
    if email and password:
        _do_password_login(server_url, email, password)
        return

    # 4. API key provided via flag → key login
    if key:
        _do_key_login(server_url, key)
        return

    # 5. Invite code → redeem
    if code:
        _do_invite_login(server_url, code, name)
        return

    # 6. Interactive: choose method
    choice = typer.prompt("Login with [E]mail, [K]ey, or [I]nvite code?", default="E")
    ch = choice.strip().upper()
    if ch.startswith("I"):
        invite_code = typer.prompt("Invite code")
        invite_name = typer.prompt("Your name", default="")
        _do_invite_login(server_url, invite_code, invite_name or None)
    elif ch.startswith("K"):
        _do_key_login(server_url, None)
    else:
        login_email = email or typer.prompt("Email")
        login_password = password or typer.prompt("Password", hide_input=True)
        _do_password_login(server_url, login_email, login_password)


@auth_app.command()
def register(
    server: str = typer.Option(None, "--server", "-s", help="Server URL"),
    email: str = typer.Option(None, "--email", "-e", help="Email"),
    password: str = typer.Option(None, "--password", "-p", help="Password"),
    name: str = typer.Option(None, "--name", "-n", help="Your name"),
):
    """Create a new account with email + password."""
    server_url = server or typer.prompt("Server URL", default="http://localhost:8000")
    server_url = server_url.rstrip("/")
    reg_email = email or typer.prompt("Email")
    reg_name = name or typer.prompt("Name")
    reg_password = password or typer.prompt("Password", hide_input=True)

    try:
        with spinner("Creating account..."):
            r = httpx.post(
                f"{server_url}/api/v1/auth/register",
                json={"email": reg_email, "name": reg_name, "password": reg_password},
                timeout=30,
            )
            r.raise_for_status()
            data = r.json()

        api_key = data["api_key"]
        user = data["user"]
        config.save({"server_url": server_url, "api_key": api_key})
        rprint(
            f"[green]Account created! Logged in as {user['name']}[/green] ({user['email']}) [{user.get('role', '')}]"
        )
        rprint(f"[dim]Config saved to {config.CONFIG_FILE}[/dim]")

        _configure_claude_code(server_url, api_key)

    except httpx.HTTPStatusError as e:
        detail = ""
        try:
            detail = e.response.json().get("detail", e.response.text)
        except Exception:
            detail = e.response.text
        rprint(f"[red]Registration failed:[/red] {detail}")
        raise typer.Exit(1)
    except httpx.ConnectError:
        rprint(f"[red]Connection failed.[/red] Is the server running at {server_url}?")
        raise typer.Exit(1)


@auth_app.command()
def init(
    server: str = typer.Option(None, "--server", "-s", help="Server URL"),
):
    """First-run setup (alias for login)."""
    login(server=server, key=None, email=None, password=None, code=None, name=None)


@auth_app.command()
def logout():
    """Clear saved credentials."""
    if config.CONFIG_FILE.exists():
        import json

        raw_cfg = json.loads(config.CONFIG_FILE.read_text())

        if "api_key" in raw_cfg:
            del raw_cfg["api_key"]
            config.CONFIG_FILE.write_text(json.dumps(raw_cfg, indent=2))

        rprint("[green]Logged out.[/green]")
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
    rprint(f"[yellow]{_DEPRECATION_MSG.format(cmd=cmd_name)}[/yellow]\n")


def register_deprecated_auth(app: typer.Typer):
    """Register deprecated root-level aliases."""

    @app.command(name="init", hidden=True)
    def deprecated_init(server: str = typer.Option(None, "--server", "-s", help="Server URL")):
        """[Deprecated] Use 'observal auth login' instead."""
        _deprecation_notice("login")
        login(server=server, key=None, email=None, password=None, code=None, name=None)

    @app.command(name="login", hidden=True)
    def deprecated_login(
        server: str = typer.Option(None, "--server", "-s", help="Server URL"),
        key: str = typer.Option(None, "--key", "-k", help="API key"),
        code: str = typer.Option(None, "--code", "-c", help="Invite code"),
    ):
        """[Deprecated] Use 'observal auth login' instead."""
        _deprecation_notice("login")
        login(server=server, key=key, email=None, password=None, code=code, name=None)

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


def _do_key_login(server_url: str, api_key: str | None = None):
    """Authenticate with an API key."""
    api_key = api_key or typer.prompt("API Key", hide_input=True)
    try:
        with spinner("Authenticating..."):
            r = httpx.post(
                f"{server_url}/api/v1/auth/login",
                json={"api_key": api_key},
                timeout=30,
            )
            r.raise_for_status()
            data = r.json()
        # Use the key returned by server (same key echoed back)
        config.save({"server_url": server_url, "api_key": data.get("api_key", api_key)})
        user = data.get("user", data)
        rprint(f"[green]Logged in as {user['name']}[/green] ({user['email']}) [{user.get('role', '')}]")
    except httpx.ConnectError:
        rprint(f"[red]Connection failed.[/red] Is the server running at {server_url}?")
        raise typer.Exit(1)
    except httpx.HTTPStatusError:
        rprint("[red]Invalid API key.[/red]")
        raise typer.Exit(1)


def _do_password_login(server_url: str, email: str, password: str):
    """Authenticate with email + password."""
    try:
        with spinner("Authenticating..."):
            r = httpx.post(
                f"{server_url}/api/v1/auth/login",
                json={"email": email, "password": password},
                timeout=30,
            )
            r.raise_for_status()
            data = r.json()

        api_key = data["api_key"]
        user = data["user"]
        config.save({"server_url": server_url, "api_key": api_key})
        rprint(f"[green]Logged in as {user['name']}[/green] ({user['email']}) [{user.get('role', '')}]")
        rprint(f"[dim]Config saved to {config.CONFIG_FILE}[/dim]")

        _configure_claude_code(server_url, api_key)

    except httpx.ConnectError:
        rprint(f"[red]Connection failed.[/red] Is the server running at {server_url}?")
        raise typer.Exit(1)
    except httpx.HTTPStatusError as e:
        detail = ""
        try:
            detail = e.response.json().get("detail", e.response.text)
        except Exception:
            detail = e.response.text
        rprint(f"[red]Login failed:[/red] {detail}")
        raise typer.Exit(1)


def _do_invite_login(server_url: str, code: str, name: str | None = None):
    """Redeem an invite code to create account and log in."""
    payload: dict = {"code": code.strip()}
    if name:
        payload["name"] = name
    try:
        with spinner("Redeeming invite code..."):
            r = httpx.post(
                f"{server_url}/api/v1/auth/redeem",
                json=payload,
                timeout=30,
            )
            r.raise_for_status()
            data = r.json()

        api_key = data["api_key"]
        user = data["user"]
        config.save({"server_url": server_url, "api_key": api_key})
        rprint(
            f"[green]Account created! Logged in as {user['name']}[/green] ({user['email']}) [{user.get('role', '')}]"
        )

        _configure_claude_code(server_url, api_key)

    except httpx.HTTPStatusError as e:
        detail = ""
        try:
            detail = e.response.json().get("detail", e.response.text)
        except Exception:
            detail = e.response.text
        rprint(f"[red]Failed:[/red] {detail}")
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


def _find_stop_hook_script() -> str | None:
    """Locate the observal-stop-hook.sh script."""
    # Check common locations
    candidates = [
        Path(__file__).parent / "hooks" / "observal-stop-hook.sh",
        Path(shutil.which("observal-stop-hook.sh") or ""),
    ]
    for p in candidates:
        if p.is_file():
            return str(p.resolve())
    return None


def _configure_claude_code(server_url: str, api_key: str):
    """Check for Claude Code and offer to configure its telemetry."""
    claude_dir = Path.home() / ".claude"
    claude_settings_file = claude_dir / "settings.json"

    try:
        claude_exists = claude_dir.is_dir() or shutil.which("claude")
        if not claude_exists:
            return

        if not typer.confirm(
            "\nDetected Claude Code. Configure telemetry -> Observal?",
            default=True,
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

        otel_env = {
            "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
            "OTEL_METRICS_EXPORTER": "otlp",
            "OTEL_LOGS_EXPORTER": "otlp",
            "OTEL_EXPORTER_OTLP_PROTOCOL": "grpc",
            "OTEL_EXPORTER_OTLP_HEADERS": f"Authorization=Bearer {api_key}",
        }

        from urllib.parse import urlparse

        parsed_url = urlparse(server_url)
        scheme = "http" if parsed_url.hostname == "localhost" else "https"
        otel_endpoint = f"{scheme}://{parsed_url.hostname}:4317"
        otel_env["OTEL_EXPORTER_OTLP_ENDPOINT"] = otel_endpoint

        if "env" not in settings:
            settings["env"] = {}
        settings["env"].update(otel_env)

        # ── Inject hooks for full content capture (prompts, tool I/O, MCP, agents) ──
        hooks_url = f"{server_url.rstrip('/')}/api/v1/otel/hooks"
        http_hook = [{"hooks": [{"type": "http", "url": hooks_url}]}]

        # Stop uses a command hook to read the transcript for Claude's response text
        stop_script = _find_stop_hook_script()
        stop_hook = [{"hooks": [{"type": "command", "command": stop_script}]}] if stop_script else http_hook

        settings["hooks"] = {
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

        # Set the hooks URL env var so the stop script knows where to POST
        settings["env"]["OBSERVAL_HOOKS_URL"] = hooks_url

        claude_dir.mkdir(exist_ok=True)
        with open(claude_settings_file, "w", encoding="utf-8") as f:
            _json.dump(settings, f, indent=2)

        rprint(f"Updated [dim]{claude_settings_file}[/dim] — telemetry + hooks will flow to Observal.")

    except Exception as e:
        rprint(f"\n[yellow]Could not configure Claude Code automatically: {e}[/yellow]")
        rprint("See documentation for manual configuration.")
