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
    name: str = typer.Option(None, "--name", "-n", help="Your name (used with register)"),
):
    """Connect to Observal.

    On a fresh server: prompts for email, name, and password to create admin.
    With email+password: logs in with credentials.
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
            config.save(
                {
                    "server_url": server_url,
                    "access_token": data["access_token"],
                    "refresh_token": data["refresh_token"],
                    "user_id": user.get("id", ""),
                    "user_name": user.get("name", ""),
                }
            )

            rprint(f"[green]Logged in as {user['name']}[/green] ({user['email']}) [admin]")
            rprint(f"[dim]Config saved to {config.CONFIG_FILE}[/dim]\n")
            _fetch_server_public_key(server_url)
            _configure_claude_code(server_url, data["access_token"])
            _configure_kiro(server_url)
            _configure_gemini_cli(server_url)
            _configure_codex(server_url)
            _configure_copilot(server_url)
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

    # 3. Email+password provided via flags → password login
    if email and password:
        _do_password_login(server_url, email, password)
        return

    # 4. Interactive: prompt for email + password
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

        user = data["user"]
        config.save(
            {
                "server_url": server_url,
                "access_token": data["access_token"],
                "refresh_token": data["refresh_token"],
                "user_id": user.get("id", ""),
                "user_name": user.get("name", ""),
            }
        )
        rprint(
            f"[green]Account created! Logged in as {user['name']}[/green] ({user['email']}) [{user.get('role', '')}]"
        )
        rprint(f"[dim]Config saved to {config.CONFIG_FILE}[/dim]")

        _fetch_server_public_key(server_url)
        _configure_claude_code(server_url, data["access_token"])
        _configure_kiro(server_url)
        _configure_gemini_cli(server_url)
        _configure_codex(server_url)
        _configure_copilot(server_url)
        _configure_opencode(server_url)
        _post_auth_onboarding()

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


def version_callback():
    """Show CLI version."""
    from importlib.metadata import version as pkg_version

    try:
        v = pkg_version("observal")
    except Exception:
        v = "dev"
    rprint(f"observal [bold]{v}[/bold]")


# ── Helper functions ────────────────────────────────────────


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

        user = data["user"]
        config.save(
            {
                "server_url": server_url,
                "access_token": data["access_token"],
                "refresh_token": data["refresh_token"],
                "user_id": user.get("id", ""),
                "user_name": user.get("name", ""),
            }
        )
        rprint(f"[green]Logged in as {user['name']}[/green] ({user['email']}) [{user.get('role', '')}]")
        rprint(f"[dim]Config saved to {config.CONFIG_FILE}[/dim]")

        _fetch_server_public_key(server_url)
        _configure_claude_code(server_url, data["access_token"])
        _configure_kiro(server_url)
        _configure_gemini_cli(server_url)
        _configure_codex(server_url)
        _configure_copilot(server_url)
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
            return str(p.resolve())
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
                        mcps = len(data.get("mcpServers", {}))
                    except Exception:
                        pass
            if agents > 0 or mcps > 0:
                found.append((label, ide_key, agents, mcps))

        if not found:
            return

        rprint()
        rprint("[bold]Detected local IDE components:[/bold]")
        rprint()
        for label, _key, agents, mcps in found:
            parts = []
            if agents:
                parts.append(f"{agents} agent{'s' if agents != 1 else ''}")
            if mcps:
                parts.append(f"{mcps} MCP{'s' if mcps != 1 else ''}")
            rprint(f"  [bold]{label}[/bold] — {', '.join(parts)} found")
        rprint()
        rprint("[dim]Telemetry hooks are now configured. Your IDE sessions will be tracked.[/dim]")
        rprint("[dim]Tip: Run 'observal scan --shim' in a project dir to wrap MCP configs with telemetry shims.[/dim]")
        rprint(
            "[dim]Tip: Run 'observal registry <type> submit <git_url>' to publish a component."
            " Only submit if you are the creator or point-of-contact.[/dim]"
        )

    except Exception as e:
        rprint(f"[yellow]Onboarding skipped: {e}[/yellow]")


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
        # If kiro_default.json doesn't exist, create it so hooks attach to the
        # built-in kiro_default agent instead of a separate workspace agent.
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
        default_agent = agents_dir / "kiro_default.json"
        if not default_agent.exists():
            cmd = _hook_cmd("kiro_default")
            stop = _stop_cmd("kiro_default")
            default_agent.write_text(
                _json.dumps(
                    {
                        "name": "kiro_default",
                        "hooks": {
                            "agentSpawn": [{"command": cmd}],
                            "userPromptSubmit": [{"command": cmd}],
                            "preToolUse": [{"matcher": "*", "command": cmd}],
                            "postToolUse": [{"matcher": "*", "command": cmd}],
                            "stop": [{"command": stop}],
                        },
                    },
                    indent=2,
                )
                + "\n"
            )
            changes += 1
            agent_files = sorted(agents_dir.glob("*.json"))

        for af in agent_files:
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
    """Check for Gemini CLI and offer to configure its OTLP telemetry.

    Writes the `telemetry` block in ~/.gemini/settings.json.  Non-destructive:
    all existing keys are preserved; only the telemetry sub-block is updated.
    A timestamped backup is created before any write.
    """
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

        from urllib.parse import urlparse

        from observal_cli.cmd_scan import inject_gemini_telemetry

        # Derive the OTLP HTTP endpoint from server_url: same host, port 4318.

        parsed = urlparse(server_url)
        otlp_endpoint = f"{parsed.scheme}://{parsed.hostname}:4318"

        gemini_settings = gemini_dir / "settings.json"
        written = inject_gemini_telemetry(otlp_endpoint)
        if written:
            rprint(f"[green]Configured Gemini CLI telemetry in {gemini_settings}[/green]")
            rprint(f"[dim]OTLP endpoint: {otlp_endpoint}[/dim]")
        else:
            rprint("[dim]Gemini CLI telemetry already configured.[/dim]")

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

        from urllib.parse import urlparse

        parsed = urlparse(server_url)
        otlp_base = f"{parsed.scheme}://{parsed.hostname}:4318"

        codex_config = codex_dir / "config.toml"

        # Load existing TOML (best-effort) to check if already configured.
        existing_content = ""
        already_configured = False
        if codex_config.exists():
            existing_content = codex_config.read_text()
            # Consider configured if both OTLP exporter sections are present.
            if "[otel.exporter.otlp-http]" in existing_content and "[otel.trace_exporter.otlp-http]" in existing_content:
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
    """Check for GitHub Copilot (VS Code) and surface install instructions.

    Copilot uses .vscode/mcp.json for MCP servers; telemetry collection
    requires wrapping individual MCP servers with observal-shim at install time.
    """
    try:
        vscode_mcp = Path.cwd() / ".vscode" / "mcp.json"
        has_copilot = vscode_mcp.exists() or shutil.which("code")
        if not has_copilot:
            return

        rprint(
            "\n[bold]Detected VS Code / GitHub Copilot.[/bold] "
            "Install MCPs via [bold]observal install <id> --ide copilot[/bold] to enable telemetry."
        )

    except Exception:
        pass


def _configure_opencode(server_url: str):
    """Check for OpenCode and surface install instructions.

    OpenCode has no global telemetry/OTLP settings block; telemetry collection
    requires wrapping individual MCP servers with observal-shim at install time.
    This function detects OpenCode and prints actionable guidance.
    """
    opencode_config = Path.home() / ".config" / "opencode" / "opencode.json"

    try:
        opencode_exists = opencode_config.exists() or shutil.which("opencode")
        if not opencode_exists:
            return

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
        desired_env = get_desired_env(server_url, hooks_token, user_id, user_name)

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
