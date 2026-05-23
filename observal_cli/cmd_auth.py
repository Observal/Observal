# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-FileCopyrightText: 2026 Harishankar <harishankar0301@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Santhosh Raja <santhoshpkraja2004@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 Shreem Seth <shreemseth26@gmail.com>
# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Auth & config CLI commands."""

from __future__ import annotations

import json as _json
import os
import re
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


_PASSWORD_REQUIREMENTS = [
    ("At least 12 characters", lambda p: len(p) >= 12),
    ("One uppercase letter", lambda p: bool(re.search(r"[A-Z]", p))),
    ("One number", lambda p: bool(re.search(r"[0-9]", p))),
    ("One special character", lambda p: bool(re.search(r"[^A-Za-z0-9]", p))),
]


def _validate_password(password: str) -> list[str]:
    """Return list of unmet requirement descriptions, empty if valid."""
    return [label for label, check in _PASSWORD_REQUIREMENTS if not check(password)]


def _prompt_password(prompt_text: str = "New password") -> str:
    """Prompt for a password, show requirements, retry until valid."""
    rprint("\n[dim]Password requirements:[/dim]")
    for label, _ in _PASSWORD_REQUIREMENTS:
        rprint(f"  [dim]· {label}[/dim]")

    while True:
        pw = typer.prompt(f"\n{prompt_text}", hide_input=True)
        failed = _validate_password(pw)
        if not failed:
            return pw
        rprint("\n[yellow]Password does not meet requirements:[/yellow]")
        for f in failed:
            rprint(f"  [red]✗[/red] {f}")


@auth_app.command()
def login(
    server: str = typer.Option(None, "--server", "-s", help="Server URL"),
    email: str = typer.Option(None, "--email", "-e", help="Email"),
    password: str = typer.Option(None, "--password", "-p", help="Password"),
    name: str = typer.Option(None, "--name", "-n", help="Your name (used for admin setup)"),
    sso: bool = typer.Option(False, "--sso", help="Authenticate via browser SSO"),
):
    """Connect to Observal.

    On a fresh server: prompts for email, name, and password to create the
    first admin account. On an initialized server: logs in with credentials
    or SSO. After login, runs `observal doctor` to check IDE instrumentation.

    If the server has SSO enabled, you can choose browser-based login via
    the device authorization flow (opens your default browser).

    Examples:
        observal auth login
        observal auth login --server http://observal.internal:80
        observal auth login -e admin@example.com -p 'MyP@ss1234!'
        observal auth login --sso
    """
    welcome_banner()
    server_url = server or typer.prompt("Server URL", default="http://localhost:80")
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

    # Check CLI/server version compatibility
    client.check_version_compatibility(server_url)

    # 2. Fresh server → prompt for admin credentials and initialize
    if not initialized:
        rprint("[green]Connected.[/green] No users yet — let's set up your admin account.\n")

        admin_email = email or typer.prompt("Admin email")
        admin_name = name or typer.prompt("Admin name", default="admin")
        if password:
            admin_password = password
        else:
            admin_password = _prompt_password("Admin password")
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
            _post_login_setup()

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
    """[Removed] Use 'observal auth login' + 'observal agent pull' instead.

    This command has been removed. The login command now handles server
    initialization automatically, and agent pull fetches configs.

    Examples:
        observal auth login
        observal agent pull my-agent
    """
    rprint("[yellow]'observal auth init' has been removed.[/yellow]")
    rprint()
    rprint("Use these commands instead:")
    rprint("  [bold]observal auth login[/bold]   — connect to your server")
    rprint("  [bold]observal agent pull[/bold]   — pull agent config to your IDE")
    raise typer.Exit(1)


@auth_app.command()
def logout():
    """Clear saved credentials.

    Revokes tokens on the server (best-effort), then removes access and
    refresh tokens from the local config file. The server URL and other
    settings are preserved. IDE hooks will stop sending telemetry after
    logout.

    Examples:
        observal auth logout
    """
    # Best-effort: revoke tokens on the server before clearing locally
    if config.CONFIG_FILE.exists():
        import json

        raw_cfg = json.loads(config.CONFIG_FILE.read_text())

        access_token = raw_cfg.get("access_token")
        refresh_token = raw_cfg.get("refresh_token")
        server_url = raw_cfg.get("server_url", "").rstrip("/")

        if access_token and server_url:
            try:
                resp = httpx.post(
                    f"{server_url}/api/v1/auth/logout",
                    json={"refresh_token": refresh_token or None},
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=5,
                )
                resp.raise_for_status()
            except Exception:
                pass  # Best-effort — proceed with local cleanup regardless

        for key in ("access_token", "refresh_token", "api_key"):
            raw_cfg.pop(key, None)
        config.CONFIG_FILE.write_text(json.dumps(raw_cfg, indent=2))

        rprint("[green]Logged out.[/green]")
        rprint(
            "[dim]Note: IDE hooks will stop sending telemetry. "
            "To remove hook scripts from your IDE, run [bold]observal doctor unpatch[/bold].[/dim]"
        )
    else:
        rprint("[dim]No config to clear.[/dim]")


@auth_app.command()
def whoami(
    output: str = typer.Option("table", "--output", "-o", help="Output format: table, json"),
):
    """Show current authenticated user.

    Queries the server for the user associated with the stored access
    token. Displays username, email, role, and user ID.

    Examples:
        observal auth whoami
        observal auth whoami --output json
    """
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
    """Check server connectivity and health.

    Shows the configured server URL, whether auth is configured, server
    reachability with latency, and local telemetry buffer stats. Useful
    for diagnosing connectivity issues.

    Examples:
        observal auth status
    """
    cfg = config.load()
    url = cfg.get("server_url", "not set")
    has_token = bool(cfg.get("access_token"))
    ok, latency = client.health()

    rprint(f"  Server:  {url}")
    rprint(f"  Auth:    {'[green]configured[/green]' if has_token else '[red]not set[/red]'}")
    if ok:
        color = "green" if latency < 200 else "yellow" if latency < 1000 else "red"
        rprint(f"  Health:  [{color}]ok[/{color}] ({latency:.0f}ms)")
        client.check_version_compatibility(url)
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
                rprint("  [dim]Session data is pushed incrementally; run `observal doctor` to diagnose.[/dim]")
    except Exception:
        pass


@auth_app.command(name="change-password")
def change_password():
    """Change your password.

    Prompts for your current password, then asks for a new password that
    meets the security requirements (12+ chars, uppercase, number, and
    special character). Requires an active login session.

    Examples:
        observal auth change-password
    """
    cfg = config.load()
    server_url = cfg.get("server_url")
    token = cfg.get("access_token")
    if not server_url or not token:
        rprint("[red]Not logged in.[/red] Run [bold]observal auth login[/bold] first.")
        raise typer.Exit(1)

    current = typer.prompt("Current password", hide_input=True)
    new_pw = _prompt_password("New password")
    confirm = typer.prompt("Confirm new password", hide_input=True)
    if new_pw != confirm:
        rprint("[red]Passwords do not match.[/red]")
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
    """Set or update your username.

    Usernames must be 3 to 32 characters, lowercase alphanumeric with
    hyphens allowed. Once set, your username can be used for login and
    is displayed as @username in the UI.

    Examples:
        observal auth set-username alice
        observal auth set-username my-dev-handle
    """
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
        v = pkg_version("observal-cli")
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
        _post_login_setup()

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
                _post_login_setup()
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
        """Show current CLI configuration.

        Prints all config values as JSON. Access and refresh tokens are
        masked for safety. The config file lives at ~/.observal/config.json.

        Examples:
            observal config show
        """
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
        """Set a CLI config value.

        Persists the given key/value pair to ~/.observal/config.json.
        Common keys: output (table/json/plain), color (true/false),
        server_url.

        Examples:
            observal config set output json
            observal config set color false
            observal config set server_url http://observal.internal:80
        """
        if key == "color":
            config.save({key: value.lower() in ("true", "1", "yes")})
        else:
            config.save({key: value})
        rprint(f"[green]Set {key}[/green]")

    @config_app.command(name="path")
    def config_path():
        """Show config file path.

        Prints the absolute path to the CLI config file. Useful for
        scripting or manual edits.

        Examples:
            observal config path
            cat $(observal config path)
        """
        rprint(str(config.CONFIG_FILE))

    @config_app.command(name="alias")
    def config_alias(
        name: str = typer.Argument(..., help="Alias name (used as @name)"),
        target: str = typer.Argument(None, help="Target ID (omit to remove)"),
    ):
        """Set or remove an alias for an MCP/agent ID.

        Aliases let you reference agents or components by short names
        instead of UUIDs. Use @name in any command that accepts an ID.
        Omit the target argument to remove an existing alias.

        Examples:
            observal config alias myagent 550e8400-e29b-41d4-a716-446655440000
            observal config alias myagent
        """
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
        """List all aliases.

        Shows all configured @name to ID mappings. Aliases are stored
        in ~/.observal/aliases.json.

        Examples:
            observal config aliases
        """
        aliases = config.load_aliases()
        if not aliases:
            rprint("[dim]No aliases set. Use: observal config alias <name> <id>[/dim]")
            return
        for name, target in sorted(aliases.items()):
            rprint(f"  @{name} -> [dim]{target}[/dim]")

    app.add_typer(config_app, name="config")


def _post_login_setup():
    """Post-login setup: run observal doctor which checks and offers to fix everything."""
    import subprocess
    import sys

    rprint()
    try:
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        subprocess.run(
            [sys.executable, "-m", "observal_cli.main", "doctor"],
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            env=env,
        )
    except Exception as e:
        rprint(f"[yellow]Could not run doctor: {e}[/yellow]")
        rprint("  Run [bold]observal doctor[/bold] manually to configure your IDEs.")


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


def _install_observal_skill():
    """Install the bundled Observal skill to all detected IDE skill directories.

    This makes the 'observal' skill available to LLMs in every IDE that supports
    skills, enabling commands like `/observal create an agent` or
    `kiro-cli chat --agent observal`.
    """
    import json as _json

    from observal_cli.ide_registry import IDE_REGISTRY

    skill_source = Path(__file__).parent / "skills" / "observal" / "SKILL.md"
    if not skill_source.exists():
        return

    content = skill_source.read_text(encoding="utf-8")
    installed: list[str] = []

    # Additional user-scope skill paths not formally in the registry but known to work.
    # Kiro supports ~/.kiro/skills/<name>/SKILL.md at user scope even though the
    # registry only documents the project-scope path.
    _extra_user_paths: dict[str, str] = {
        "kiro": "~/.kiro/skills/{name}/SKILL.md",
    }

    for ide, spec in IDE_REGISTRY.items():
        skill_file_spec = spec.get("skill_file") or {}

        # Install to user scope (global)
        user_path = skill_file_spec.get("user") or _extra_user_paths.get(ide)
        if not user_path:
            continue

        # Replace {name} placeholder with 'observal'
        resolved = user_path.replace("{name}", "observal")
        dest = Path(resolved.replace("~", str(Path.home())))

        # Only install if the IDE directory exists (IDE is installed)
        ide_config_dir = Path.home() / spec.get("config_dir", "")
        if not ide_config_dir.exists():
            continue

        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
            installed.append(spec["display_name"])
        except OSError:
            pass

    # Kiro-specific: ensure the active agent has skill resources wired up.
    # Without this, skills in ~/.kiro/skills/ are invisible to the agent.
    _kiro_skill_resource = "skill://~/.kiro/skills/*/SKILL.md"
    kiro_settings = Path.home() / ".kiro" / "settings" / "cli.json"
    if kiro_settings.exists():
        try:
            settings_data = _json.loads(kiro_settings.read_text())
            active_agent = settings_data.get("chat.defaultAgent", "")
            if active_agent:
                agent_file = Path.home() / ".kiro" / "agents" / f"{active_agent}.json"
                if agent_file.exists():
                    agent_data = _json.loads(agent_file.read_text())
                    resources = agent_data.get("resources", [])
                    if _kiro_skill_resource not in resources:
                        resources.append(_kiro_skill_resource)
                        agent_data["resources"] = resources
                        agent_file.write_text(_json.dumps(agent_data, indent=2) + "\n")
        except (OSError, _json.JSONDecodeError):
            pass

    if installed:
        rprint(f"\n[green]✓ Observal skill installed for:[/green] {', '.join(installed)}")
        rprint('[dim]  LLMs can now use Observal commands directly (e.g. "create a PR agent for kiro")[/dim]')


def _run_doctor_patch(ide_name: str):
    """Run 'observal doctor patch --all --ide <name>' as a subprocess."""
    import subprocess
    import sys

    try:
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        result = subprocess.run(
            [sys.executable, "-m", "observal_cli.main", "doctor", "patch", "--all", "--ide", ide_name],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            env=env,
        )
        if result.stdout:
            rprint(result.stdout.rstrip())
        if result.returncode != 0 and result.stderr:
            rprint(f"[yellow]{result.stderr.rstrip()}[/yellow]")
    except Exception as e:
        rprint(f"[yellow]Could not run doctor patch: {e}[/yellow]")
        rprint(f"Run [bold]observal doctor patch --all --ide {ide_name}[/bold] manually.")


def _configure_cursor(server_url: str):
    """Check for Cursor (IDE or CLI) and offer to configure its telemetry hooks."""
    cursor_dir = Path.home() / ".cursor"

    try:
        cursor_exists = cursor_dir.is_dir() or shutil.which("cursor")
        if not cursor_exists:
            return

        if not typer.confirm(
            "\nDetected Cursor. Configure telemetry -> Observal?",
            default=True,
        ):
            return

        _run_doctor_patch("cursor")

    except Exception as e:
        rprint(f"\n[yellow]Could not configure Cursor automatically: {e}[/yellow]")
        rprint("Run [bold]observal doctor patch --all --ide cursor[/bold] to set up manually.")


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
    try:
        # The gemini binary is the definitive signal.
        # ~/.gemini/settings.json can be created by a previous observal doctor patch,
        # so its presence alone doesn't mean Gemini CLI is actually installed.
        if not shutil.which("gemini"):
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
        if not vscode_dir.is_dir():
            return

        # Check for an actual Copilot extension rather than just VS Code existing.
        extensions_dir = vscode_dir / "extensions"
        has_copilot = extensions_dir.is_dir() and any(
            p.name.startswith("github.copilot") for p in extensions_dir.iterdir()
        )
        if not has_copilot:
            return

        if not typer.confirm(
            "\nDetected GitHub Copilot. Configure telemetry -> Observal?",
            default=True,
        ):
            return

        _run_doctor_patch("copilot")

    except Exception:
        pass


def _configure_copilot_cli(server_url: str):
    """Check for Copilot CLI and configure telemetry via doctor patch."""
    try:
        # The copilot binary is the definitive signal.
        # ~/.copilot/config.json can be created by a previous observal doctor patch,
        # so its presence alone doesn't mean Copilot CLI is actually installed.
        if not shutil.which("copilot"):
            return

        if not typer.confirm(
            "\nDetected Copilot CLI. Configure telemetry -> Observal?",
            default=True,
        ):
            return

        _run_doctor_patch("copilot-cli")

    except Exception:
        pass


def _configure_opencode(server_url: str):
    """Check for OpenCode and configure telemetry via doctor patch."""
    try:
        # The opencode binary is the strongest signal.
        # ~/.config/opencode/opencode.json can be created by a previous observal
        # doctor patch, so also accept it only if the binary is present.
        if not shutil.which("opencode"):
            return

        if not typer.confirm(
            "\nDetected OpenCode. Configure telemetry -> Observal?",
            default=True,
        ):
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
