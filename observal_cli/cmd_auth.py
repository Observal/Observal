"""Auth & config CLI commands."""

from __future__ import annotations

import json as _json
import shutil
from pathlib import Path

import httpx
import typer
from rich import print as rprint

from observal_cli import client, config, settings_reconciler
from observal_cli.branding import welcome_banner
from observal_cli.hooks_spec import get_desired_env, get_desired_hooks
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
    email: str = typer.Option(None, "--email", "-e", help="Email"),
    password: str = typer.Option(None, "--password", "-p", help="Password"),
    name: str = typer.Option(None, "--name", "-n", help="Your name (used for admin setup)"),
    sso: bool = typer.Option(False, "--sso", help="Authenticate via browser SSO"),
):
    """Connect to Observal.

    On a fresh server: prompts for email, name, and password to create admin.
    With email+password: logs in with credentials.
    With --sso: authenticates via browser-based SSO using the device flow.
    """
    welcome_banner()
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

    # 2. Fresh server → prompt for admin credentials and initialize
    if not initialized:
        rprint("[green]Connected.[/green] No users yet — let's set up your admin account.\n")

        admin_email = email or typer.prompt("Admin email")
        admin_name = name or typer.prompt("Admin name", default="admin")
        if password:
            admin_password = password
        else:
            admin_password = typer.prompt("Admin password", hide_input=True)
            confirm = typer.prompt("Confirm password", hide_input=True)
            if admin_password != confirm:
                rprint("[red]Passwords do not match.[/red]")
                raise typer.Exit(1)

        try:
            with spinner("Creating admin account..."):
                r = httpx.post(
                    f"{server_url}/api/v1/auth/init",
                    json={"email": admin_email, "name": admin_name, "password": admin_password},
                    timeout=30,
                )
                r.raise_for_status()
                data = r.json()

            user = data["user"]
            endpoints = _fetch_endpoints(server_url)
            cfg_data = {
                "server_url": server_url,
                "access_token": data["access_token"],
                "refresh_token": data["refresh_token"],
                "user_id": user.get("id", ""),
                "user_name": user.get("name", ""),
            }
            if endpoints:
                cfg_data["otlp_http_url"] = endpoints.get("otlp_http", "")
                cfg_data["otlp_grpc_url"] = endpoints.get("otlp_grpc", "")
                cfg_data["web_url"] = endpoints.get("web", "")
            config.save(cfg_data)

            rprint(f"[green]Logged in as {user['name']}[/green] ({user['email']}) [admin]")
            rprint(f"[dim]Config saved to {config.CONFIG_FILE}[/dim]\n")
            _fetch_server_public_key(server_url)
            _configure_claude_code(server_url, data["access_token"])
            _configure_kiro(server_url)
            _configure_gemini_cli(server_url)
            _configure_codex(server_url)
            _configure_copilot(server_url)
            _configure_copilot_cli(server_url)
            _configure_opencode(server_url)
            _post_auth_onboarding()

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400 and "already initialized" in e.response.text.lower():
                rprint("[yellow]Server was just initialized by someone else.[/yellow]")
                rprint("Please log in with your email and password.")
            else:
                rprint(f"[red]Setup failed ({e.response.status_code}):[/red] {e.response.text}")
                raise typer.Exit(1)
        return

    rprint("[green]Connected.[/green]\n")

    # 3. Check if we should use device flow (SSO)
    sso_mode = False
    sso_available = False
    try:
        config_r = httpx.get(f"{server_url}/api/v1/config/public", timeout=5)
        if config_r.status_code == 200:
            pub_config = config_r.json()
            sso_available = pub_config.get("sso_enabled") or pub_config.get("saml_enabled")
            sso_only = pub_config.get("sso_only", False)
            # Use device flow if --sso flag passed, or if sso_only mode (no password option)
            if sso or sso_only:
                sso_mode = True
    except Exception:
        pass

    # If SSO available but not required, offer a choice (unless flags already decide)
    if not sso_mode and not (email or password):
        rprint("  [1] Email/username + password")
        if sso_available:
            rprint("  [2] SSO (opens browser)")
        rprint("  [3] Sign in via browser")
        choice = typer.prompt("Login method", default="1")
        if (choice == "2" and sso_available) or choice == "3":
            sso_mode = True

    if sso_mode:
        _do_device_flow_login(server_url)
        return

    # 4. Email+password provided via flags -> password login
    if email and password:
        _do_password_login(server_url, email, password)
        return

    # 5. Interactive: prompt for email/username + password
    login_email = email or typer.prompt("Email or username")
    login_password = password or typer.prompt("Password", hide_input=True)
    _do_password_login(server_url, login_email, login_password)


@auth_app.command()
def init():
    """[Removed] Use 'observal auth login' + 'observal pull' instead."""
    rprint("[yellow]'observal auth init' has been removed.[/yellow]")
    rprint()
    rprint("Use these commands instead:")
    rprint("  [bold]observal auth login[/bold]   — connect to your server")
    rprint("  [bold]observal pull[/bold]          — pull your configuration")
    raise typer.Exit(1)


@auth_app.command()
def logout():
    """Clear saved credentials."""
    if config.CONFIG_FILE.exists():
        import json

        raw_cfg = json.loads(config.CONFIG_FILE.read_text())

        for key in ("access_token", "refresh_token", "api_key"):
            raw_cfg.pop(key, None)
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
                ("Username", f"@{user['username']}" if user.get("username") else "[dim]not set[/dim]"),
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
    has_token = bool(cfg.get("access_token"))
    ok, latency = client.health()

    rprint(f"  Server:  {url}")
    rprint(f"  Auth:    {'[green]configured[/green]' if has_token else '[red]not set[/red]'}")
    if ok:
        color = "green" if latency < 200 else "yellow" if latency < 1000 else "red"
        rprint(f"  Health:  [{color}]ok[/{color}] ({latency:.0f}ms)")
    else:
        rprint("  Health:  [red]unreachable[/red]")

    # Show local telemetry buffer summary
    try:
        from observal_cli.telemetry_buffer import stats as buffer_stats

        buf = buffer_stats()
        if buf["total"] > 0:
            rprint()
            pending = buf["pending"]
            label = f"[yellow]{pending} pending[/yellow]" if pending else "[green]0 pending[/green]"
            rprint(f"  Buffer:  {label}, {buf['failed']} failed, {buf['sent']} sent")
            if buf["oldest_pending"]:
                rprint(f"  Oldest:  {buf['oldest_pending']} UTC")
            if pending and not ok:
                rprint("  [dim]Run `observal ops sync` when the server is back online.[/dim]")
    except Exception:
        pass


@auth_app.command(name="change-password")
def change_password():
    """Change your password."""
    cfg = config.load()
    server_url = cfg.get("server_url")
    token = cfg.get("access_token")
    if not server_url or not token:
        rprint("[red]Not logged in.[/red] Run [bold]observal auth login[/bold] first.")
        raise typer.Exit(1)

    current = typer.prompt("Current password", hide_input=True)
    new_pw = typer.prompt("New password", hide_input=True)
    confirm = typer.prompt("Confirm new password", hide_input=True)
    if new_pw != confirm:
        rprint("[red]Passwords do not match.[/red]")
        raise typer.Exit(1)
    if len(new_pw) < 8:
        rprint("[red]Password must be at least 8 characters.[/red]")
        raise typer.Exit(1)

    try:
        with spinner("Changing password..."):
            r = httpx.put(
                f"{server_url}/api/v1/auth/profile/password",
                json={"current_password": current, "new_password": new_pw},
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
            )
            r.raise_for_status()
        rprint("[green]Password changed successfully.[/green]")
    except httpx.HTTPStatusError as e:
        detail = ""
        try:
            detail = e.response.json().get("detail", e.response.text)
        except Exception:
            detail = e.response.text
        rprint(f"[red]Failed:[/red] {detail}")
        raise typer.Exit(1)


@auth_app.command(name="set-username")
def set_username(
    username: str = typer.Argument(..., help="Username (3-32 chars, lowercase alphanumeric and hyphens)"),
):
    """Set or update your username."""
    from observal_cli import client as _client

    try:
        with spinner("Updating username..."):
            result = _client.put("/api/v1/auth/profile/username", {"username": username})
        rprint(f"[green]Username set to @{result.get('username', username)}[/green]")
    except Exception as e:
        rprint(f"[red]Failed:[/red] {e}")
        raise typer.Exit(1)


def version_callback():
    """Show CLI version."""
    from importlib.metadata import version as pkg_version

    try:
        v = pkg_version("observal")
    except Exception:
        v = "dev"
    rprint(f"observal [bold]{v}[/bold]")


# ── Helper functions ────────────────────────────────────────


def _fetch_endpoints(server_url: str) -> dict:
    """Fetch service endpoint URLs from the discovery endpoint.

    Returns a dict with api, otlp_http, otlp_grpc, web URLs.
    Falls back to sensible defaults if the endpoint is unavailable.
    """
    try:
        r = httpx.get(f"{server_url.rstrip('/')}/api/v1/config/endpoints", timeout=5)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}


def _fetch_server_public_key(server_url: str):
    """Fetch and cache the server's ECIES public key for payload encryption.

    Best-effort: silently ignored if the server doesn't expose the endpoint
    yet (older server versions) or if connectivity fails.
    """
    try:
        r = httpx.get(f"{server_url.rstrip('/')}/api/v1/otel/crypto/public-key", timeout=5)
        if r.status_code == 200:
            data = r.json()
            pub_pem = data.get("public_key_pem")
            if pub_pem:
                key_dir = Path.home() / ".observal" / "keys"
                key_dir.mkdir(parents=True, exist_ok=True)
                (key_dir / "server_public.pem").write_text(pub_pem)
    except Exception:
        pass  # Server may not support encryption yet


def _do_password_login(server_url: str, email: str, password: str):
    """Authenticate with email/username + password."""
    try:
        with spinner("Authenticating..."):
            r = httpx.post(
                f"{server_url}/api/v1/auth/login",
                json={"email": email, "password": password},
                timeout=30,
            )
            r.raise_for_status()
            data = r.json()

        user = data["user"]

        if data.get("must_change_password"):
            rprint("[yellow]Your admin has required a password change.[/yellow]\n")
            access_token = data["access_token"]
            new_pw = typer.prompt("New password", hide_input=True)
            confirm = typer.prompt("Confirm new password", hide_input=True)
            if new_pw != confirm:
                rprint("[red]Passwords do not match.[/red]")
                raise typer.Exit(1)
            if len(new_pw) < 8:
                rprint("[red]Password must be at least 8 characters.[/red]")
                raise typer.Exit(1)
            with spinner("Changing password..."):
                cr = httpx.put(
                    f"{server_url}/api/v1/auth/profile/password",
                    json={"current_password": password, "new_password": new_pw},
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=30,
                )
                cr.raise_for_status()
            rprint("[green]Password changed.[/green]\n")

        endpoints = _fetch_endpoints(server_url)
        cfg_data = {
            "server_url": server_url,
            "access_token": data["access_token"],
            "refresh_token": data["refresh_token"],
            "user_id": user.get("id", ""),
            "user_name": user.get("name", ""),
        }
        if endpoints:
            cfg_data["otlp_http_url"] = endpoints.get("otlp_http", "")
            cfg_data["otlp_grpc_url"] = endpoints.get("otlp_grpc", "")
            cfg_data["web_url"] = endpoints.get("web", "")
        config.save(cfg_data)
        rprint(f"[green]Logged in as {user['name']}[/green] ({user['email']}) [{user.get('role', '')}]")
        rprint(f"[dim]Config saved to {config.CONFIG_FILE}[/dim]")

        _fetch_server_public_key(server_url)
        _configure_claude_code(server_url, data["access_token"])
        _configure_kiro(server_url)
        _configure_gemini_cli(server_url)
        _configure_codex(server_url)
        _configure_copilot(server_url)
        _configure_copilot_cli(server_url)
        _configure_opencode(server_url)
        _post_auth_onboarding()

    except httpx.HTTPStatusError as e:
        detail = ""
        try:
            detail = e.response.json().get("detail", e.response.text)
        except Exception:
            detail = e.response.text
        rprint(f"[red]Login failed:[/red] {detail}")
        raise typer.Exit(1)


def _do_device_flow_login(server_url: str):
    """Authenticate via browser-based SSO using the device authorization flow."""
    import time
    import webbrowser

    # 1. Request device authorization
    try:
        with spinner("Requesting device authorization..."):
            r = httpx.post(
                f"{server_url}/api/v1/auth/device/authorize",
                json={},
                timeout=10,
            )
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPStatusError as e:
        rprint(f"[red]Device authorization failed ({e.response.status_code}):[/red] {e.response.text}")
        raise typer.Exit(1)

    device_code = data["device_code"]
    user_code = data["user_code"]
    verification_uri = data["verification_uri"]
    verification_uri_complete = data["verification_uri_complete"]
    expires_in = data["expires_in"]
    interval = data.get("interval", 5)

    # 2. Display instructions
    rprint()
    rprint("[bold]To sign in, open this URL in your browser:[/bold]")
    rprint()
    rprint(f"  [link={verification_uri_complete}]{verification_uri}[/link]")
    rprint()
    rprint(f"  Then enter code: [bold cyan]{user_code}[/bold cyan]")
    rprint()

    # Try to open browser automatically
    try:
        webbrowser.open(verification_uri_complete)
        rprint("[dim]Browser opened automatically.[/dim]")
    except Exception:
        rprint("[dim]Could not open browser automatically. Please open the URL manually.[/dim]")

    rprint()
    rprint("[dim]Waiting for authorization...[/dim]", end="")

    # 3. Poll for token
    deadline = time.monotonic() + expires_in
    while time.monotonic() < deadline:
        time.sleep(interval)
        try:
            r = httpx.post(
                f"{server_url}/api/v1/auth/device/token",
                json={
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
                timeout=10,
            )

            if r.status_code == 200:
                # Success!
                token_data = r.json()
                rprint(" [green]authorized![/green]")
                rprint()

                user = token_data.get("user", {})
                endpoints = _fetch_endpoints(server_url)
                cfg_data = {
                    "server_url": server_url,
                    "access_token": token_data["access_token"],
                    "refresh_token": token_data["refresh_token"],
                    "user_id": user.get("id", ""),
                    "user_name": user.get("name", ""),
                }
                if endpoints:
                    cfg_data["otlp_http_url"] = endpoints.get("otlp_http", "")
                    cfg_data["otlp_grpc_url"] = endpoints.get("otlp_grpc", "")
                    cfg_data["web_url"] = endpoints.get("web", "")
                config.save(cfg_data)

                rprint(
                    f"[green]Logged in as {user.get('name', 'unknown')}[/green]"
                    f" ({user.get('email', '')}) [{user.get('role', '')}]"
                )
                rprint(f"[dim]Config saved to {config.CONFIG_FILE}[/dim]")

                _fetch_server_public_key(server_url)
                _configure_claude_code(server_url, token_data["access_token"])
                _configure_kiro(server_url)
                _configure_gemini_cli(server_url)
                _configure_codex(server_url)
                _configure_copilot(server_url)
                _configure_copilot_cli(server_url)
                _configure_opencode(server_url)
                _post_auth_onboarding()
                return

            if r.status_code == 428:
                # Still pending, keep polling
                rprint(".", end="", flush=True)
                continue

            # Error response
            error_data = r.json()
            error = error_data.get("error", "unknown_error")
            if error == "expired_token":
                rprint(" [red]expired[/red]")
                rprint("[red]Device code expired. Please try again.[/red]")
                raise typer.Exit(1)
            elif error == "access_denied":
                rprint(" [red]denied[/red]")
                rprint("[red]Authorization was denied.[/red]")
                raise typer.Exit(1)
            else:
                rprint(f" [red]error: {error}[/red]")
                raise typer.Exit(1)

        except httpx.RequestError:
            # Network error, keep trying
            rprint(".", end="", flush=True)
            continue

    rprint(" [red]timed out[/red]")
    rprint("[red]Authorization timed out. Please try again.[/red]")
    raise typer.Exit(1)


def register_config(app: typer.Typer):
    """Register config subcommands."""

    @config_app.command(name="show")
    def config_show():
        """Show current CLI configuration."""
        cfg = config.load()
        safe = dict(cfg)
        if safe.get("access_token"):
            t = safe["access_token"]
            safe["access_token"] = t[:8] + "..." + t[-4:] if len(t) > 12 else "***"
        if safe.get("refresh_token"):
            t = safe["refresh_token"]
            safe["refresh_token"] = t[:8] + "..." + t[-4:] if len(t) > 12 else "***"
        # Clean up legacy key if present
        safe.pop("api_key", None)
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


def _find_hook_script(name: str) -> str | None:
    """Locate a hook script by filename."""
    candidates = [
        Path(__file__).parent / "hooks" / name,
        Path(shutil.which(name) or ""),
    ]
    for p in candidates:
        if p.is_file():
            return p.resolve().as_posix()
    return None


def _post_auth_onboarding():
    """Detect local IDE configs and show what was found."""
    try:
        _ide_dirs = {
            "Claude Code": (Path.home() / ".claude", "claude-code"),
            "Kiro CLI": (Path.home() / ".kiro", "kiro"),
            "Cursor": (Path.home() / ".cursor", "cursor"),
            "Gemini CLI": (Path.home() / ".gemini", "gemini-cli"),
            "Codex": (Path.home() / ".codex", "codex"),
            "Copilot": (Path.home() / ".vscode", "copilot"),
            "OpenCode": (Path.home() / ".config" / "opencode", "opencode"),
        }

        found: list[tuple[str, str, int, int]] = []  # (label, ide_key, agents, mcps)
        for label, (dir_path, ide_key) in _ide_dirs.items():
            if not dir_path.is_dir():
                continue
            agents = mcps = 0
            if ide_key == "claude-code":
                from observal_cli.cmd_scan import _scan_claude_home

                m, _s, _h, a = _scan_claude_home(dir_path)
                agents, mcps = len(a), len(m)
            elif ide_key == "kiro":
                from observal_cli.cmd_scan import _scan_kiro_home

                m, _s, _h, a = _scan_kiro_home(dir_path)
                agents, mcps = len(a), len(m)
            elif ide_key == "gemini-cli":
                from observal_cli.cmd_scan import _scan_gemini_home

                m, _s, _h, _a = _scan_gemini_home(dir_path)
                mcps = len(m)
            elif ide_key == "codex":
                # Codex: parse ~/.codex/config.toml for [mcp.servers]
                toml_file = dir_path / "config.toml"
                if toml_file.exists():
                    try:
                        try:
                            import tomllib as _toml
                        except ImportError:
                            try:
                                import tomli as _toml  # type: ignore[no-redef]
                            except ImportError:
                                import toml as _toml  # type: ignore[no-redef]
                        content = toml_file.read_text()
                        data = _toml.loads(content) if hasattr(_toml, "loads") else _toml.load(toml_file.open("rb"))  # type: ignore[call-arg]
                        mcps = len(data.get("mcp", {}).get("servers", {}))
                    except Exception:
                        pass
            elif ide_key == "opencode":
                # OpenCode: parse ~/.config/opencode/opencode.json for `mcp` key
                oc_file = dir_path / "opencode.json"
                if oc_file.exists():
                    try:
                        import json as _j

                        oc_data = _j.loads(oc_file.read_text())
                        mcps = len(oc_data.get("mcp", {}))
                    except Exception:
                        pass
            else:
                mcp_file = dir_path / "mcp.json"
                if mcp_file.exists():
                    try:
                        import json as _j

                        data = _j.loads(mcp_file.read_text())
                        mcps = len(data.get("mcpServers", data.get("servers", {})))
                    except Exception:
                        pass
            if agents > 0 or mcps > 0:
                found.append((label, ide_key, agents, mcps))

        if not found:
            return

        rprint()
        rprint("[bold]\N{ELECTRIC LIGHT BULB} Detected local IDE configs.[/bold]")
        rprint()
        for label, _key, agents, mcps in found:
            parts = []
            if agents:
                parts.append(f"{agents} agent{'s' if agents != 1 else ''}")
            if mcps:
                parts.append(f"{mcps} MCP{'s' if mcps != 1 else ''}")
            rprint(f"  [bold]{label}[/bold] — {', '.join(parts)} found")
        rprint()
        rprint("[dim]Run `observal scan --all-ides` to wrap MCP servers with telemetry shims.[/dim]")

    except Exception:
        pass


def _configure_kiro(server_url: str):
    """Check for Kiro CLI and offer to configure its telemetry hooks."""
    kiro_dir = Path.home() / ".kiro"

    try:
        kiro_exists = kiro_dir.is_dir() or shutil.which("kiro-cli") or shutil.which("kiro")
        if not kiro_exists:
            return

        if not typer.confirm(
            "\nDetected Kiro CLI. Configure telemetry -> Observal?",
            default=True,
        ):
            return

        hooks_url = f"{server_url.rstrip('/')}/api/v1/otel/hooks"

        hook_py = _find_hook_script("kiro_hook.py")
        stop_py = _find_hook_script("kiro_stop_hook.py")

        def _hook_cmd(agent_name: str) -> str:
            if hook_py:
                return f"cat | python3 {hook_py} --url {hooks_url} --agent-name {agent_name}"
            return f'cat | curl -sf -X POST {hooks_url} -H "Content-Type: application/json" -d @-'

        def _stop_cmd(agent_name: str) -> str:
            if stop_py:
                return f"cat | python3 {stop_py} --url {hooks_url} --agent-name {agent_name}"
            return f'cat | curl -sf -X POST {hooks_url} -H "Content-Type: application/json" -d @-'

        changes = 0

        # 1. Inject into agent JSON files (merge, preserve existing hooks)
        agents_dir = kiro_dir / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)

        # Migrate: remove old default.json created by earlier Observal versions.
        # It shadowed the built-in kiro_default agent.
        old_default = agents_dir / "default.json"
        if old_default.exists():
            try:
                od = _json.loads(old_default.read_text())
                if od.get("name") == "default" and any(
                    "otel/hooks" in h.get("command", "")
                    for hs in od.get("hooks", {}).values()
                    if isinstance(hs, list)
                    for h in hs
                ):
                    old_default.unlink()
                    import subprocess

                    kiro_bin = shutil.which("kiro-cli") or shutil.which("kiro") or shutil.which("kiro-cli-chat")
                    if kiro_bin:
                        subprocess.run(
                            [kiro_bin, "agent", "set-default", "kiro_default"],
                            capture_output=True,
                            timeout=10,
                        )
                    changes += 1
            except (ValueError, OSError):
                pass

        agent_files = sorted(agents_dir.glob("*.json"))

        for af in agent_files:
            # Skip kiro_default — only trace registered agents
            if af.stem == "kiro_default":
                continue
            try:
                data = _json.loads(af.read_text())
                existing = data.get("hooks", {})
                already = any(
                    "otel/hooks" in h.get("command", "")
                    for handlers in existing.values()
                    if isinstance(handlers, list)
                    for h in handlers
                )
                if already:
                    continue
                name = data.get("name") or af.stem
                cmd = _hook_cmd(name)
                stop = _stop_cmd(name)
                desired = {
                    "agentSpawn": [{"command": cmd}],
                    "userPromptSubmit": [{"command": cmd}],
                    "preToolUse": [{"matcher": "*", "command": cmd}],
                    "postToolUse": [{"matcher": "*", "command": cmd}],
                    "stop": [{"command": stop}],
                }
                merged = dict(existing)
                for evt, handlers in desired.items():
                    cur = merged.get(evt, [])
                    has_obs = any("otel/hooks" in h.get("command", "") for h in cur)
                    if not has_obs:
                        merged[evt] = cur + handlers
                data["hooks"] = merged
                af.write_text(_json.dumps(data, indent=2) + "\n")
                changes += 1
            except (ValueError, OSError):
                pass

        # 2. Install global IDE-format hooks for agentless chat
        global_hooks_dir = kiro_dir / "hooks"
        global_hooks_dir.mkdir(parents=True, exist_ok=True)
        g_cmd = _hook_cmd("global")
        g_stop = _stop_cmd("global")
        for hook_id, event_type, cmd in [
            ("observal-prompt-submit", "promptSubmit", g_cmd),
            ("observal-pre-tool-use", "preToolUse", g_cmd),
            ("observal-post-tool-use", "postToolUse", g_cmd),
            ("observal-agent-stop", "agentStop", g_stop),
        ]:
            hf = global_hooks_dir / f"{hook_id}.json"
            if hf.exists():
                try:
                    ex = _json.loads(hf.read_text())
                    if hooks_url in ex.get("then", {}).get("command", ""):
                        continue
                except (ValueError, OSError):
                    pass
            hf.write_text(
                _json.dumps(
                    {
                        "id": hook_id,
                        "name": f"Observal: {event_type}",
                        "comment": "Auto-injected by Observal for telemetry collection",
                        "when": {"type": event_type},
                        "then": {"type": "runCommand", "command": cmd},
                    },
                    indent=2,
                )
                + "\n"
            )
            changes += 1

        if changes:
            rprint(f"[green]Configured Kiro telemetry ({changes} hooks updated)[/green]")
        else:
            rprint("[dim]Kiro hooks already configured.[/dim]")

    except Exception as e:
        rprint(f"\n[yellow]Could not configure Kiro automatically: {e}[/yellow]")
        rprint("Run [bold]observal scan --ide kiro --home[/bold] to set up manually.")


def _configure_gemini_cli(server_url: str):
    """Check for Gemini CLI and configure hooks + disable native OTLP.

    Gemini CLI hardcodes gRPC for OTLP export (incompatible with Observal's
    HTTP/JSON endpoint). We disable native OTLP and inject command-type hooks
    into ~/.gemini/settings.json for telemetry capture.
    """
    import sys

    gemini_dir = Path.home() / ".gemini"

    try:
        gemini_exists = gemini_dir.is_dir() or shutil.which("gemini")
        if not gemini_exists:
            return

        if not typer.confirm(
            "\nDetected Gemini CLI. Configure telemetry -> Observal?",
            default=True,
        ):
            return

        from observal_cli.cmd_scan import inject_gemini_telemetry

        cfg = config.load()
        gemini_settings = gemini_dir / "settings.json"
        changes = 0

        # 1. Disable native OTLP (gRPC-only, incompatible with Observal)
        written = inject_gemini_telemetry("")
        if written:
            rprint(f"[green]Disabled native OTLP in {gemini_settings} (gRPC incompatible)[/green]")
            changes += 1

        # 2. Inject hooks for telemetry capture
        hooks_url = f"{server_url.rstrip('/')}/api/v1/otel/hooks"
        hooks_dir = Path(__file__).parent / "hooks"
        hook_script = hooks_dir / "gemini_hook.py"
        stop_script = hooks_dir / "gemini_stop_hook.py"

        def _hook_cmd(script: Path) -> str:
            if sys.platform == "win32":
                return f"python {script.resolve().as_posix()}"
            return f"python3 {script.resolve().as_posix()}"

        def _hook_entry(script: Path) -> list:
            return [{"hooks": [{"type": "command", "command": _hook_cmd(script)}]}]

        cmd_hook = _hook_entry(hook_script)
        stop_hook = _hook_entry(stop_script)

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

        gdata: dict = {}
        if gemini_settings.exists():
            gdata = _json.loads(gemini_settings.read_text())

        existing_hooks = gdata.get("hooks", {})
        hooks_need_update = False

        for event_name, entry in gemini_hooks_block.items():
            if event_name not in existing_hooks:
                hooks_need_update = True
                break
            existing_cmd = ""
            try:
                existing_cmd = existing_hooks[event_name][0]["hooks"][0].get("command", "")
            except (KeyError, IndexError, TypeError):
                pass
            expected_cmd = entry[0]["hooks"][0].get("command", "")
            if existing_cmd != expected_cmd:
                hooks_need_update = True
                break

        if hooks_need_update:
            gdata["hooks"] = {**existing_hooks, **gemini_hooks_block}
            if "env" not in gdata:
                gdata["env"] = {}
            gdata["env"]["OBSERVAL_HOOKS_URL"] = hooks_url
            if cfg.get("user_id"):
                gdata["env"]["OBSERVAL_USER_ID"] = cfg["user_id"]
            if cfg.get("user_name"):
                gdata["env"]["OBSERVAL_USERNAME"] = cfg["user_name"]
            gemini_settings.parent.mkdir(parents=True, exist_ok=True)
            gemini_settings.write_text(_json.dumps(gdata, indent=2) + "\n")
            rprint(f"[green]Injected hooks into {gemini_settings}[/green]")
            rprint(f"[dim]Hooks endpoint: {hooks_url}[/dim]")
            changes += 1

        if changes == 0:
            rprint("[dim]Gemini CLI already configured for Observal.[/dim]")

    except Exception as e:
        rprint(f"\n[yellow]Could not configure Gemini CLI automatically: {e}[/yellow]")
        rprint("Run [bold]observal scan --ide gemini-cli --home[/bold] to set up manually.")


def _configure_codex(server_url: str):
    """Check for Codex CLI and offer to configure its OTLP telemetry.

    Appends [otel] / [otel.exporter.otlp-http] / [otel.trace_exporter.otlp-http]
    blocks to ~/.codex/config.toml when they are not already present.
    A timestamped backup is created before any write.
    """
    codex_dir = Path.home() / ".codex"

    try:
        codex_exists = codex_dir.is_dir() or shutil.which("codex")
        if not codex_exists:
            return

        if not typer.confirm(
            "\nDetected Codex CLI. Configure OTLP telemetry -> Observal?",
            default=True,
        ):
            return

        cfg = config.load()
        otlp_base = cfg.get("otlp_http_url", "")
        if not otlp_base:
            from urllib.parse import urlparse

            parsed = urlparse(server_url)
            scheme = "http" if parsed.hostname in ("localhost", "127.0.0.1") else "https"
            otlp_base = f"{scheme}://{parsed.hostname}:4318"

        codex_config = codex_dir / "config.toml"

        # Load existing TOML (best-effort) to check if already configured.
        existing_content = ""
        already_configured = False
        if codex_config.exists():
            existing_content = codex_config.read_text()
            # Consider configured if both OTLP exporter sections are present.
            if (
                "[otel.exporter.otlp-http]" in existing_content
                and "[otel.trace_exporter.otlp-http]" in existing_content
            ):
                already_configured = True

        if already_configured:
            rprint("[dim]Codex OTLP telemetry already configured.[/dim]")
            return

        toml_block = f"""
[otel]
environment = "production"
log_user_prompt = true

[otel.exporter.otlp-http]
endpoint = "{otlp_base}/v1/logs"
protocol = "http"

[otel.trace_exporter.otlp-http]
endpoint = "{otlp_base}/v1/traces"
protocol = "http"
"""

        if codex_config.exists():
            from datetime import datetime

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = codex_config.with_suffix(f".pre-observal.{ts}.bak")
            import shutil as _shutil

            _shutil.copy2(codex_config, backup)

        codex_dir.mkdir(parents=True, exist_ok=True)
        with codex_config.open("a") as f:
            f.write(toml_block)

        rprint(f"[green]Configured Codex OTLP telemetry in {codex_config}[/green]")
        rprint(f"[dim]OTLP endpoint: {otlp_base}[/dim]")

    except Exception as e:
        rprint(f"\n[yellow]Could not configure Codex automatically: {e}[/yellow]")
        rprint("Add OTLP settings manually to ~/.codex/config.toml.")


def _configure_copilot(server_url: str):
    """Check for GitHub Copilot (VS Code) and auto-shim existing MCP servers.

    Copilot uses .vscode/mcp.json for MCP servers; telemetry collection
    requires wrapping individual MCP servers with observal-shim at install time.
    This function detects existing configs and auto-shims un-shimmed servers.
    """
    try:
        vscode_dir = Path.home() / ".vscode"
        home_mcp = vscode_dir / "mcp.json"
        project_mcp = Path.cwd() / ".vscode" / "mcp.json"
        has_copilot = vscode_dir.is_dir() or home_mcp.exists() or project_mcp.exists() or shutil.which("code")
        if not has_copilot:
            return

        from observal_cli.cmd_scan import _auto_shim_home_config

        shimmed_any = False
        for mcp_path in (home_mcp, project_mcp):
            if mcp_path.exists():
                _auto_shim_home_config(mcp_path, "copilot")
                shimmed_any = True

        if not shimmed_any:
            rprint(
                "\n[bold]Detected VS Code / GitHub Copilot.[/bold] "
                "Install MCPs via [bold]observal install <id> --ide copilot[/bold] to enable telemetry."
            )

    except Exception:
        pass


def _configure_copilot_cli(server_url: str):
    """Check for Copilot CLI and auto-shim existing MCP servers.

    Copilot CLI uses ~/.copilot/mcp-config.json for MCP servers; telemetry
    collection requires wrapping servers with observal-shim at install time.
    """
    copilot_cli_config = Path.home() / ".copilot" / "mcp-config.json"

    try:
        if not copilot_cli_config.exists():
            return

        from observal_cli.cmd_scan import _auto_shim_home_config

        _auto_shim_home_config(copilot_cli_config, "copilot-cli")

    except Exception:
        pass


def _configure_opencode(server_url: str):
    """Check for OpenCode and auto-shim existing MCP servers.

    OpenCode has no global telemetry/OTLP settings block; telemetry collection
    requires wrapping individual MCP servers with observal-shim at install time.
    This function detects existing configs and auto-shims un-shimmed servers.
    """
    opencode_config = Path.home() / ".config" / "opencode" / "opencode.json"

    try:
        opencode_exists = opencode_config.exists() or shutil.which("opencode")
        if not opencode_exists:
            return

        if opencode_config.exists():
            from observal_cli.cmd_scan import _auto_shim_home_config

            _auto_shim_home_config(opencode_config, "opencode")
        else:
            rprint(
                "\n[bold]Detected OpenCode.[/bold] "
                "Install MCPs via [bold]observal install <id> --ide opencode[/bold] to enable telemetry."
            )

    except Exception:
        pass  # Detection is best-effort; never block login


def _configure_claude_code(server_url: str, access_token: str):
    """Check for Claude Code and offer to configure its telemetry.

    Uses declarative reconciliation: computes desired state from hooks_spec,
    diffs against current ~/.claude/settings.json, and applies minimal changes.
    Non-Observal hooks and env vars are preserved untouched.
    """
    claude_dir = Path.home() / ".claude"

    try:
        claude_exists = claude_dir.is_dir() or shutil.which("claude")
        if not claude_exists:
            return

        if not typer.confirm(
            "\nDetected Claude Code. Configure telemetry -> Observal?",
            default=True,
        ):
            return

        # Fetch a long-lived hooks token for OTEL env vars
        hooks_token = _fetch_hooks_token(server_url, access_token)

        # Build desired state from the declarative spec
        hooks_url = f"{server_url.rstrip('/')}/api/v1/otel/hooks"
        hook_script = _find_hook_script("observal-hook.sh")
        stop_script = _find_hook_script("observal-stop-hook.sh")
        cfg = config.load()
        user_id = cfg.get("user_id", "")
        user_name = cfg.get("user_name", "")

        desired_hooks = get_desired_hooks(hook_script, stop_script, hooks_url, user_id)
        otlp_grpc_url = cfg.get("otlp_grpc_url", "")
        desired_env = get_desired_env(server_url, hooks_token, user_id, user_name, otlp_grpc_url=otlp_grpc_url)

        # Reconcile: non-destructive merge preserving foreign hooks/env
        changes = settings_reconciler.reconcile(desired_hooks, desired_env)

        if changes:
            rprint(f"Updated [dim]{settings_reconciler.CLAUDE_SETTINGS_PATH}[/dim]:")
            for change in changes:
                rprint(f"  {change}")
        else:
            rprint("[dim]Claude Code settings already up to date.[/dim]")

    except Exception as e:
        rprint(f"\n[yellow]Could not configure Claude Code automatically: {e}[/yellow]")
        rprint("See documentation for manual configuration.")


def _fetch_hooks_token(server_url: str, access_token: str) -> str:
    """Call /auth/hooks-token to get a long-lived token for OTEL hooks.

    Falls back to the session access_token if the endpoint fails.
    """
    try:
        r = httpx.post(
            f"{server_url.rstrip('/')}/api/v1/auth/hooks-token",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        if r.status_code == 200:
            return r.json().get("access_token", access_token)
    except Exception:
        pass
    return access_token
