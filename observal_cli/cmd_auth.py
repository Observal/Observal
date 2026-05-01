"""Auth & config CLI commands."""

from __future__ import annotations

import json as _json
import shutil
from pathlib import Path

import httpx
import typer
from rich import print as rprint

from observal_cli import client, config
from observal_cli.branding import welcome_banner
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
                cfg_data["otlp_url"] = endpoints.get("otlp_http", "")
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
    """[Removed] Use 'observal auth login' + 'observal agent pull' instead."""
    rprint("[yellow]'observal auth init' has been removed.[/yellow]")
    rprint()
    rprint("Use these commands instead:")
    rprint("  [bold]observal auth login[/bold]   — connect to your server")
    rprint("  [bold]observal agent pull[/bold]   — pull agent config to your IDE")
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

    Returns a dict with api, otlp_http, web URLs.
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
        r = httpx.get(f"{server_url.rstrip('/')}/api/v1/sessions/crypto/public-key", timeout=5)
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
            cfg_data["otlp_url"] = endpoints.get("otlp_http", "")
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
                    cfg_data["otlp_url"] = endpoints.get("otlp_http", "")
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
        rprint("[dim]Run `observal doctor patch --all --all-ides` to instrument telemetry.[/dim]")

    except Exception:
        pass


def _run_doctor_patch(ide_name: str):
    """Run 'observal doctor patch --all --ide <name>' as a subprocess."""
    import subprocess
    import sys

    try:
        result = subprocess.run(
            [sys.executable, "-m", "observal_cli.main", "doctor", "patch", "--all", "--ide", ide_name],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.stdout:
            rprint(result.stdout.rstrip())
        if result.returncode != 0 and result.stderr:
            rprint(f"[yellow]{result.stderr.rstrip()}[/yellow]")
    except Exception as e:
        rprint(f"[yellow]Could not run doctor patch: {e}[/yellow]")
        rprint(f"Run [bold]observal doctor patch --all --ide {ide_name}[/bold] manually.")


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

        _run_doctor_patch("kiro")

    except Exception as e:
        rprint(f"\n[yellow]Could not configure Kiro automatically: {e}[/yellow]")
        rprint("Run [bold]observal doctor patch --all --ide kiro[/bold] to set up manually.")


def _configure_gemini_cli(server_url: str):
    """Check for Gemini CLI and configure telemetry via doctor patch."""
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

        _run_doctor_patch("gemini-cli")

    except Exception as e:
        rprint(f"\n[yellow]Could not configure Gemini CLI automatically: {e}[/yellow]")
        rprint("Run [bold]observal doctor patch --all --ide gemini-cli[/bold] to set up manually.")


def _configure_codex(server_url: str):
    """Check for Codex CLI and configure telemetry via doctor patch."""
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

        _run_doctor_patch("codex")

    except Exception as e:
        rprint(f"\n[yellow]Could not configure Codex automatically: {e}[/yellow]")
        rprint("Run [bold]observal doctor patch --all --ide codex[/bold] manually.")


def _configure_copilot(server_url: str):
    """Check for GitHub Copilot (VS Code) and configure telemetry via doctor patch."""
    try:
        vscode_dir = Path.home() / ".vscode"
        has_copilot = vscode_dir.is_dir() or shutil.which("code")
        if not has_copilot:
            return

        _run_doctor_patch("copilot")

    except Exception:
        pass


def _configure_copilot_cli(server_url: str):
    """Check for Copilot CLI and configure telemetry via doctor patch."""
    try:
        copilot_dir = Path.home() / ".copilot"
        if not copilot_dir.is_dir() and not shutil.which("copilot"):
            return

        _run_doctor_patch("copilot-cli")

    except Exception:
        pass


def _configure_opencode(server_url: str):
    """Check for OpenCode and configure telemetry via doctor patch."""
    try:
        opencode_config = Path.home() / ".config" / "opencode" / "opencode.json"
        if not opencode_config.exists() and not shutil.which("opencode"):
            return

        _run_doctor_patch("opencode")

    except Exception:
        pass


def _configure_claude_code(server_url: str, access_token: str):
    """Check for Claude Code and configure telemetry via doctor patch.

    Fetches a long-lived hooks token first (needed by the patch command),
    then delegates to 'observal doctor patch --all --ide claude-code'.
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

        # Fetch a long-lived hooks token and save to config before patching
        hooks_token = _fetch_hooks_token(server_url, access_token)
        if hooks_token:
            cfg = config.load()
            cfg["api_key"] = hooks_token
            config.save(cfg)

        _run_doctor_patch("claude-code")

    except Exception as e:
        rprint(f"\n[yellow]Could not configure Claude Code automatically: {e}[/yellow]")
        rprint("Run [bold]observal doctor patch --all --ide claude-code[/bold] manually.")


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
