"""MCP server CLI commands."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import typer
from rich import print as rprint
from rich.table import Table

from observal_cli import client, config
from observal_cli.analyzer import analyze_local
from observal_cli.constants import VALID_IDES, VALID_MCP_CATEGORIES
from observal_cli.prompts import fuzzy_select, select_one
from observal_cli.render import (
    console,
    ide_tags,
    kv_panel,
    output_json,
    relative_time,
    spinner,
    status_badge,
)

mcp_app = typer.Typer(help="MCP server registry commands")


# ── Env var configuration helpers ────────────────────────────


def _parse_env_file(file_path: str) -> list[dict]:
    """Parse a .env-style file and return env var dicts."""
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        rprint(f"[red]File not found:[/red] {path}")
        return []

    env_vars: list[dict] = []
    for line in path.read_text(errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key = line.split("=", 1)[0].strip()
        if key and key == key.upper():
            env_vars.append({"name": key, "description": "", "required": True})
    return env_vars


def _configure_env_vars_interactive(detected: list[dict]) -> list[dict]:
    """Interactive env var configuration at submit time.

    Offers three paths:
      1. Review and edit auto-detected vars
      2. Load from an env file path
      3. Enter manually
    """
    is_tty = sys.stdin.isatty()

    if detected:
        rprint(f"\n[bold]Auto-detected {len(detected)} env var(s):[/bold]")
        for ev in detected:
            rprint(f"  [cyan]*[/cyan] {ev['name']}")

    rprint("\n[bold]How would you like to configure environment variables?[/bold]")

    if is_tty:
        choices = []
        if detected:
            choices.append("Review auto-detected vars")
        choices.extend(["Load from .env file", "Enter manually", "Skip (no env vars)"])
        choice = select_one("Env var configuration", choices)
    else:
        if detected:
            rprint("  1. Review auto-detected vars")
            rprint("  2. Load from .env file")
            rprint("  3. Enter manually")
            rprint("  4. Skip (no env vars)")
            raw = typer.prompt("Choose", default="1")
        else:
            rprint("  1. Load from .env file")
            rprint("  2. Enter manually")
            rprint("  3. Skip (no env vars)")
            raw = typer.prompt("Choose", default="3")
        choice_map = {
            "1": "Review auto-detected vars" if detected else "Load from .env file",
            "2": "Load from .env file" if detected else "Enter manually",
            "3": "Enter manually" if detected else "Skip (no env vars)",
            "4": "Skip (no env vars)",
        }
        choice = choice_map.get(raw, "Skip (no env vars)")

    if choice == "Skip (no env vars)":
        return []

    if choice == "Load from .env file":
        file_path = typer.prompt("Path to .env file (e.g. .env.example)")
        env_vars = _parse_env_file(file_path)
        if not env_vars:
            rprint("[yellow]No variables found in file.[/yellow]")
            return []
        rprint(f"\n[green]Loaded {len(env_vars)} var(s) from file.[/green]")
        return _review_env_vars(env_vars)

    if choice == "Enter manually":
        return _enter_env_vars_manually()

    # Review auto-detected
    return _review_env_vars(detected)


def _review_env_vars(env_vars: list[dict]) -> list[dict]:
    """Let the developer review, remove, and annotate each env var."""
    reviewed: list[dict] = []

    rprint("\n[bold]Review each variable[/bold]\n")

    for ev in env_vars:
        action = typer.prompt(
            f"  {ev['name']} — keep? [Enter=keep / r=remove / o=optional]",
            default="",
            show_default=False,
        )
        action = action.strip().lower()

        if action == "r":
            rprint("    [dim]removed[/dim]")
            continue

        required = action != "o"
        desc = ev.get("description", "")
        if not desc:
            desc = typer.prompt(f"    Description for {ev['name']} (optional)", default="")

        reviewed.append({"name": ev["name"], "description": desc, "required": required})
        status = "[green]required[/green]" if required else "[yellow]optional[/yellow]"
        rprint(f"    {status}")

    # Offer to add more
    while True:
        add_more = typer.prompt("\n  Add another env var? (name or Enter to finish)", default="")
        if not add_more:
            break
        desc = typer.prompt(f"    Description for {add_more} (optional)", default="")
        req = typer.confirm("    Required?", default=True)
        reviewed.append({"name": add_more.strip().upper(), "description": desc, "required": req})

    return reviewed


def _enter_env_vars_manually() -> list[dict]:
    """Prompt the developer to enter env vars one by one."""
    env_vars: list[dict] = []
    rprint("\n[bold]Enter env vars one at a time[/bold] [dim](empty name to finish)[/dim]\n")

    while True:
        name = typer.prompt("  Variable name (or Enter to finish)", default="")
        if not name:
            break
        name = name.strip().upper()
        desc = typer.prompt(f"    Description for {name} (optional)", default="")
        req = typer.confirm("    Required?", default=True)
        env_vars.append({"name": name, "description": desc, "required": req})

    return env_vars


# ── Dollar-sign variable detection ──────────────────────────

_DOLLAR_VAR_RE = re.compile(r"\$\{?([A-Z][A-Z0-9_]+)\}?")


def _extract_dollar_vars(args: list[str], env: dict[str, str]) -> list[str]:
    """Extract unique $VAR / ${VAR} references from args and env values.

    Returns a sorted list of uppercase variable names found in the args list
    and the *values* (not keys) of the env dict, filtered to exclude
    system/infrastructure vars (PATH, HOME, CI_*, etc.).
    """
    from observal_cli.analyzer import _is_filtered_env_var

    found: set[str] = set()
    for arg in args:
        found.update(_DOLLAR_VAR_RE.findall(arg))
    for value in env.values():
        if isinstance(value, str):
            found.update(_DOLLAR_VAR_RE.findall(value))
    return sorted(name for name in found if not _is_filtered_env_var(name))


# ── Direct config helpers ────────────────────────────────────


def _unwrap_mcp_config(cfg: dict) -> tuple[dict, str | None]:
    """Unwrap nested mcpServers / named-server wrappers.

    Accepts three shapes:
      1. {"mcpServers": {"name": {config}}}
      2. {"name": {config}}  (single key whose value has command/url/type)
      3. {config}            (bare config with command/args or url)

    Returns (inner_config, server_name | None).
    """
    # Shape 1: wrapped under mcpServers
    if "mcpServers" in cfg and isinstance(cfg["mcpServers"], dict):
        servers = cfg["mcpServers"]
        if len(servers) == 1:
            server_name, inner = next(iter(servers.items()))
            if isinstance(inner, dict):
                return inner, server_name
        return cfg, None

    # Shape 3: bare config — has a direct config key
    if cfg.get("command") or cfg.get("url") or cfg.get("type"):
        return cfg, None

    # Shape 2: single named key wrapping a config dict
    if len(cfg) == 1:
        server_name, inner = next(iter(cfg.items()))
        if isinstance(inner, dict) and (inner.get("command") or inner.get("url") or inner.get("type")):
            return inner, server_name

    return cfg, None


def _parse_direct_config(cfg: dict) -> dict:
    """Normalize a JSON config dict (mcp.json style) into submit-ready fields.

    Accepts wrapped (mcpServers) or bare configs.
    Handles two transport shapes:
    - stdio: {command, args, env}
    - SSE/HTTP: {url, type, headers, autoApprove}
    """
    inner, server_name = _unwrap_mcp_config(cfg)
    parsed: dict = {}
    if server_name:
        parsed["_server_name"] = server_name

    if inner.get("url") and not inner.get("command"):
        # SSE / streamable-http transport
        transport = inner.get("type", "sse")
        parsed["transport"] = transport
        parsed["url"] = inner["url"]

        # Convert headers dict {name: value} → list of {name, description, required}
        raw_headers = inner.get("headers") or {}
        if isinstance(raw_headers, dict):
            parsed["headers"] = [{"name": k, "description": "", "required": True} for k in raw_headers]
        elif isinstance(raw_headers, list):
            parsed["headers"] = raw_headers

        if inner.get("autoApprove"):
            parsed["auto_approve"] = inner["autoApprove"]

        # env as environment_variables
        raw_env = inner.get("env") or {}
        if isinstance(raw_env, dict):
            parsed["environment_variables"] = [{"name": k, "description": "", "required": True} for k in raw_env]

        # Detect $VAR references in env values
        dollar_vars = _extract_dollar_vars([], raw_env)
        existing_names = {ev["name"] for ev in parsed.get("environment_variables", [])}
        for var_name in dollar_vars:
            if var_name not in existing_names:
                parsed.setdefault("environment_variables", []).append(
                    {"name": var_name, "description": "", "required": True}
                )
                existing_names.add(var_name)
        if dollar_vars:
            parsed["_dollar_vars_detected"] = dollar_vars

    elif inner.get("command"):
        # stdio transport
        parsed["transport"] = "stdio"
        parsed["command"] = inner["command"]
        parsed["args"] = inner.get("args") or []

        # Derive framework from command
        cmd = inner["command"]
        if cmd == "docker":
            parsed["framework"] = "docker"
            # Extract docker_image: last non-flag arg
            args = parsed["args"]
            for arg in reversed(args):
                if not arg.startswith("-"):
                    parsed["docker_image"] = arg
                    break
        elif cmd in ("python", "python3"):
            parsed["framework"] = "python"
        elif cmd in ("npx", "node"):
            parsed["framework"] = "typescript"
        else:
            parsed["framework"] = None

        # env as environment_variables
        raw_env = inner.get("env") or {}
        if isinstance(raw_env, dict):
            parsed["environment_variables"] = [{"name": k, "description": "", "required": True} for k in raw_env]

        # Detect $VAR references in args and env values
        dollar_vars = _extract_dollar_vars(parsed["args"], raw_env)
        existing_names = {ev["name"] for ev in parsed.get("environment_variables", [])}
        for var_name in dollar_vars:
            if var_name not in existing_names:
                parsed.setdefault("environment_variables", []).append(
                    {"name": var_name, "description": "", "required": True}
                )
                existing_names.add(var_name)
        if dollar_vars:
            parsed["_dollar_vars_detected"] = dollar_vars

        if inner.get("autoApprove"):
            parsed["auto_approve"] = inner["autoApprove"]

    return parsed


def _build_config_preview(server_name: str, parsed: dict) -> dict:
    """Build a mcp.json-style preview dict for display during submit."""
    preview: dict = {}

    if parsed.get("url"):
        # SSE / streamable-http preview
        preview["type"] = parsed.get("transport", "sse")
        preview["url"] = parsed["url"]
        if parsed.get("headers"):
            preview["headers"] = {h["name"]: f"<{h['name']}>" for h in parsed["headers"]}
        env_vars = parsed.get("environment_variables") or []
        if env_vars:
            preview["env"] = {ev["name"]: f"<{ev['name']}>" for ev in env_vars}
        if parsed.get("auto_approve"):
            preview["autoApprove"] = parsed["auto_approve"]
        preview["disabled"] = False
    else:
        # stdio preview
        command = parsed.get("command", "")
        args = list(parsed.get("args") or [])

        # Inject -e flags for docker env vars
        env_vars = parsed.get("environment_variables") or []
        if command == "docker" and env_vars:
            # Find the image position (last non-flag arg) and inject -e before it
            insert_idx = len(args)
            for i in range(len(args) - 1, -1, -1):
                if not args[i].startswith("-"):
                    insert_idx = i
                    break
            for ev in reversed(env_vars):
                args.insert(insert_idx, f"{ev['name']}=<{ev['name']}>")
                args.insert(insert_idx, "-e")

        preview["command"] = command
        preview["args"] = args
        if env_vars:
            preview["env"] = {ev["name"]: f"<{ev['name']}>" for ev in env_vars}

    return {server_name: preview}


# ── Implementation functions (shared by canonical + deprecated) ──


def _submit_impl(git_url, name, category, yes, direct_config=False, draft=False):
    # ── Path B/C: Direct JSON config (no git URL needed) ─────
    if direct_config:
        rprint("[bold]Paste your MCP server JSON config below.[/bold]")
        rprint("[dim]Press Enter on an empty line when done.[/dim]\n")
        lines: list[str] = []
        has_content = False
        while True:
            try:
                line = input()
            except EOFError:
                break
            if line.strip() == "":
                if has_content:
                    break
            else:
                has_content = True
                lines.append(line)
        raw_text = "\n".join(lines).strip()
        if not raw_text:
            rprint("[red]No input received.[/red]")
            raise typer.Exit(1)
        try:
            cfg = json.loads(raw_text)
        except json.JSONDecodeError:
            # Long single-line pastes can get split by the terminal — retry without newlines
            try:
                cfg = json.loads("".join(part.strip() for part in lines))
            except json.JSONDecodeError as e:
                rprint(f"[red]Invalid JSON:[/red] {e}")
                raise typer.Exit(1)

        parsed = _parse_direct_config(cfg)
        _name = name or parsed.pop("_server_name", None) or "my-mcp-server"

        # Notify about dollar-sign input variables
        dollar_vars = parsed.pop("_dollar_vars_detected", None)
        if dollar_vars:
            rprint("\n[bold yellow]Input variables detected:[/bold yellow]")
            rprint(
                "[dim]Dollar-sign variables in args/env will become install-time"
                " dependencies — users will be prompted for these values.[/dim]\n"
            )
            for var in dollar_vars:
                rprint(f"  [cyan]$[/cyan]{var}")
            rprint()

        rprint("\n[bold]Config preview:[/bold]")
        console.print_json(json.dumps(_build_config_preview(_name, parsed), indent=2))

        if not yes:
            if not typer.confirm("\nSubmit this config?", default=True):
                raise typer.Abort()

            # Let creator review/confirm input dependencies
            if dollar_vars:
                rprint("\n[bold]Confirm input dependencies:[/bold]")
                parsed["environment_variables"] = _review_env_vars(parsed.get("environment_variables", []))

            _name = name or typer.prompt("Server name", default=_name)
            _desc = typer.prompt("Description (what does this server do?)", default="")
            _owner = typer.prompt("Owner / Team (e.g. your GitHub username)", default="default")
            _category = category or select_one("Category", VALID_MCP_CATEGORIES, default="general")
        else:
            if dollar_vars:
                rprint(f"\n[dim]Auto-detected {len(dollar_vars)} input variable(s) from $VAR patterns.[/dim]")
            _desc = ""
            _owner = "default"
            _category = category or "general"

        supported_ides = list(VALID_IDES)
        submit_payload: dict = {
            "name": _name,
            "version": "0.1.0",
            "category": _category,
            "description": _desc,
            "owner": _owner,
            "supported_ides": supported_ides,
            "environment_variables": parsed.get("environment_variables", []),
        }
        if parsed.get("command"):
            submit_payload["command"] = parsed["command"]
        if parsed.get("args") is not None:
            submit_payload["args"] = parsed["args"]
        if parsed.get("url"):
            submit_payload["url"] = parsed["url"]
        if parsed.get("headers"):
            submit_payload["headers"] = parsed["headers"]
        if parsed.get("auto_approve"):
            submit_payload["auto_approve"] = parsed["auto_approve"]
        if parsed.get("transport"):
            submit_payload["transport"] = parsed["transport"]
        if parsed.get("framework"):
            submit_payload["framework"] = parsed["framework"]
        if parsed.get("docker_image"):
            submit_payload["docker_image"] = parsed["docker_image"]

        endpoint = "/api/v1/mcps/draft" if draft else "/api/v1/mcps/submit"
        label = "Saving draft..." if draft else "Submitting..."
        with spinner(label):
            result = client.post(endpoint, submit_payload)
        msg = "Draft saved!" if draft else "Submitted!"
        rprint(f"\n[green]{msg}[/green] ID: [bold]{result['id']}[/bold]")
        rprint(f"  Status: {status_badge(result.get('status', 'pending'))}")
        return

    # ── Path A: Git URL analysis ─────────────────────────────
    analyzed_locally = False
    with spinner("Analyzing repository..."):
        try:
            prefill = analyze_local(git_url)
            if prefill.get("error"):
                rprint(f"[yellow]Local analysis issue:[/yellow] {prefill['error']}")
                rprint("[dim]Falling back to server-side analysis...[/dim]")
                try:
                    prefill = client.post("/api/v1/mcps/analyze", {"git_url": git_url})
                except (Exception, SystemExit):
                    rprint("[yellow]Server analysis also failed. Fill in details manually.[/yellow]")
                    prefill = {}
            else:
                analyzed_locally = True
        except Exception:
            try:
                prefill = client.post("/api/v1/mcps/analyze", {"git_url": git_url})
            except (Exception, SystemExit):
                rprint("[yellow]Could not analyze repo. Fill in details manually.[/yellow]")
                prefill = {}

    # ── Analysis summary ──────────────────────────────────────
    detected_name = prefill.get("name", "")
    detected_desc = prefill.get("description", "")
    detected_ver = prefill.get("version", "0.1.0")
    detected_framework = prefill.get("framework", "")
    tools = prefill.get("tools", [])

    detected_env_vars = prefill.get("environment_variables", [])
    issues = prefill.get("issues", [])
    error = prefill.get("error", "")

    # Extract command/args/docker fields from analysis
    detected_command = prefill.get("command")
    detected_args = prefill.get("args")
    detected_docker_image = prefill.get("docker_image")
    detected_docker_suggested = prefill.get("docker_image_suggested", False)

    rprint("\n[bold]--- Analysis Results ---[/bold]")

    if error:
        rprint(f"  [bold red]Error:[/bold red] {error}")
        rprint("  [dim]You can still submit manually, but the server could not be analyzed.[/dim]")
        if not yes and not typer.confirm("Continue with manual submission?", default=False):
            raise typer.Abort()
    else:
        if detected_name:
            rprint(f"  Server name:  [cyan]{detected_name}[/cyan]")
        if detected_desc:
            rprint(f"  Description:  [dim]{detected_desc[:80]}{'...' if len(detected_desc) > 80 else ''}[/dim]")
        if tools:
            rprint(f"  Tools found:  [green]{len(tools)}[/green]")
            for t in tools[:10]:
                doc = t.get("docstring", t.get("description", ""))
                rprint(f"    [cyan]*[/cyan] {t.get('name', '?')}: {doc[:60] if doc else '[dim](no description)[/dim]'}")
            if len(tools) > 10:
                rprint(f"    [dim]...and {len(tools) - 10} more[/dim]")
        if detected_env_vars:
            rprint(f"  Env vars:     [green]{len(detected_env_vars)}[/green]")
            for ev in detected_env_vars:
                ev_name = ev.get("name", ev) if isinstance(ev, dict) else ev
                rprint(f"    [cyan]*[/cyan] {ev_name}")
        if not detected_name and not tools:
            rprint("  [dim]No MCP metadata detected. You will need to fill in all fields manually.[/dim]")

        if issues:
            rprint(f"\n  [bold yellow]Warnings ({len(issues)}):[/bold yellow]")
            for issue in issues:
                rprint(f"    [yellow]![/yellow] {issue}")
            rprint()
            if not yes and not typer.confirm("This server has quality issues. Submit anyway?", default=False):
                raise typer.Abort()

    rprint("[bold]------------------------[/bold]\n")

    # ── Auto-accept detected fields, only prompt for missing/required ──
    # MCP servers are IDE-agnostic — config generation handles all IDEs.
    supported_ides = list(VALID_IDES)

    # Build parsed dict from analysis for config preview
    parsed: dict = {}
    if detected_command:
        parsed["command"] = detected_command
        parsed["args"] = detected_args or []
        parsed["transport"] = "stdio"
        parsed["environment_variables"] = detected_env_vars
        if detected_docker_image:
            parsed["docker_image"] = detected_docker_image

    # Derive framework from command
    _framework: str | None = None
    if detected_command:
        if detected_command == "docker":
            _framework = "docker"
        elif detected_command in ("python", "python3"):
            _framework = "python"
        elif detected_command in ("npx", "node"):
            _framework = "typescript"
        elif detected_framework:
            fw_lower = detected_framework.lower()
            if "typescript" in fw_lower or "ts" in fw_lower:
                _framework = "typescript"
            elif "go" in fw_lower:
                _framework = "go"
            elif "docker" in fw_lower:
                _framework = "docker"
            else:
                _framework = "python"
    elif detected_framework:
        fw_lower = detected_framework.lower()
        if "typescript" in fw_lower or "ts" in fw_lower:
            _framework = "typescript"
        elif "go" in fw_lower:
            _framework = "go"
        elif "docker" in fw_lower:
            _framework = "docker"
        else:
            _framework = "python"
    elif prefill.get("entry_point"):
        _framework = "python"

    # Command/args confirmation
    _command = detected_command
    _args = detected_args
    _docker_image = detected_docker_image

    if yes:
        _name = name or detected_name
        _version = detected_ver
        _desc = detected_desc
        _owner = "default"
        _category = category or "general"
        if not _framework:
            _framework = "python"
        _setup = ""
        _changelog = "Initial release"
        # Detect $VAR patterns in args and merge into env vars
        dollar_vars = _extract_dollar_vars(_args or [], {})
        existing_names = {(ev.get("name", ev) if isinstance(ev, dict) else ev) for ev in detected_env_vars}
        for var_name in dollar_vars:
            if var_name not in existing_names:
                detected_env_vars.append({"name": var_name, "description": "", "required": True})
                existing_names.add(var_name)
        if dollar_vars:
            rprint(f"\n[dim]Auto-detected {len(dollar_vars)} input variable(s) from $VAR patterns in args.[/dim]")
        env_vars = detected_env_vars
    else:
        # Show config preview if command was detected
        if detected_command:
            preview_name = name or detected_name or "my-server"
            rprint("[bold]Startup config:[/bold]")
            console.print_json(json.dumps(_build_config_preview(preview_name, parsed), indent=2))
            if detected_docker_suggested:
                rprint(
                    f"  [dim](Docker image [cyan]{detected_docker_image}[/cyan]"
                    " was inferred from the GitHub URL — verify it exists)[/dim]"
                )
            choice = (
                typer.prompt(
                    "Startup config looks correct? [Y/n/edit]",
                    default="Y",
                    show_default=False,
                )
                .strip()
                .lower()
            )
            if choice == "n":
                raise typer.Abort()
            elif choice == "edit":
                _command = typer.prompt("Command", default=detected_command or "")
                raw_args = typer.prompt(
                    "Args (space-separated)",
                    default=" ".join(detected_args) if detected_args else "",
                )
                _args = raw_args.split() if raw_args.strip() else []
                # Re-derive framework
                if _command == "docker":
                    _framework = "docker"
                    for arg in reversed(_args):
                        if not arg.startswith("-"):
                            _docker_image = arg
                            break
                elif _command in ("python", "python3"):
                    _framework = "python"
                elif _command in ("npx", "node"):
                    _framework = "typescript"
        elif not detected_command:
            rprint("[dim]No startup command was detected.[/dim]")
            custom_cmd = typer.prompt("Command (e.g. docker, python, npx — Enter to skip)", default="")
            if custom_cmd:
                _command = custom_cmd
                raw_args = typer.prompt("Args (space-separated)", default="")
                _args = raw_args.split() if raw_args.strip() else []
                if _command == "docker":
                    _framework = "docker"
                    for arg in reversed(_args):
                        if not arg.startswith("-"):
                            _docker_image = arg
                            break
                elif _command in ("python", "python3"):
                    _framework = "python"
                elif _command in ("npx", "node"):
                    _framework = "typescript"

        # Name: auto-accept if detected, otherwise ask
        if name:
            _name = name
        elif detected_name:
            _name = detected_name
            rprint(f"  Server name: [cyan]{_name}[/cyan] [dim](from analysis)[/dim]")
        else:
            _name = typer.prompt("Server name")

        # Version: auto-accept detected
        _version = detected_ver
        rprint(f"  Version:     [cyan]{_version}[/cyan]")

        # Description: auto-accept if detected, otherwise ask
        if detected_desc:
            _desc = detected_desc
            rprint(
                f"  Description: [cyan]{_desc[:60]}{'...' if len(_desc) > 60 else ''}[/cyan] [dim](from analysis)[/dim]"
            )
        else:
            _desc = typer.prompt("Description (what does this server do?)")

        _owner = typer.prompt("\nOwner / Team (e.g. your GitHub username)")
        rprint()

        _category = category or select_one("Category", VALID_MCP_CATEGORIES, default="general")

        _setup = typer.prompt("Setup instructions (optional, press Enter to skip)", default="")
        _changelog = typer.prompt("Changelog", default="Initial release")

        # Detect $VAR patterns in final args and merge into detected env vars
        dollar_vars = _extract_dollar_vars(_args or [], {})
        existing_names = {(ev.get("name", ev) if isinstance(ev, dict) else ev) for ev in detected_env_vars}
        for var_name in dollar_vars:
            if var_name not in existing_names:
                detected_env_vars.append({"name": var_name, "description": "", "required": True})
                existing_names.add(var_name)
        if dollar_vars:
            rprint("\n[bold yellow]Input variables detected in args:[/bold yellow]")
            rprint(
                "[dim]Dollar-sign variables will become install-time"
                " dependencies — users will be prompted for these values.[/dim]\n"
            )
            for var in dollar_vars:
                rprint(f"  [cyan]$[/cyan]{var}")
            rprint()

        # Interactive env var configuration — developer reviews, edits,
        # or provides env vars instead of blindly including auto-detected ones.
        env_vars = _configure_env_vars_interactive(detected_env_vars)

    submit_payload = {
        "git_url": git_url,
        "name": _name,
        "version": _version,
        "category": _category,
        "description": _desc,
        "owner": _owner,
        "supported_ides": supported_ides,
        "environment_variables": env_vars,
        "setup_instructions": _setup,
        "changelog": _changelog,
    }
    if _framework:
        submit_payload["framework"] = _framework
    if _docker_image:
        submit_payload["docker_image"] = _docker_image
    if _command:
        submit_payload["command"] = _command
    if _args is not None:
        submit_payload["args"] = _args

    if analyzed_locally:
        submit_payload["client_analysis"] = {
            "tools": prefill.get("tools", []),
            "issues": prefill.get("issues", []),
            "framework": prefill.get("framework", ""),
            "entry_point": prefill.get("entry_point", ""),
            "command": prefill.get("command"),
            "args": prefill.get("args"),
            "docker_image": prefill.get("docker_image"),
        }

    endpoint = "/api/v1/mcps/draft" if draft else "/api/v1/mcps/submit"
    label = "Saving draft..." if draft else "Submitting..."
    with spinner(label):
        result = client.post(endpoint, submit_payload)
    msg = "Draft saved!" if draft else "Submitted!"
    rprint(f"\n[green]{msg}[/green] ID: [bold]{result['id']}[/bold]")
    if _framework:
        rprint(f"  Framework: [cyan]{_framework}[/cyan]")
    rprint(f"  Status: {status_badge(result.get('status', 'pending'))}")


def _list_impl(category, search, limit, sort, output, interactive=False):
    params = {}
    if category:
        params["category"] = category
    if search:
        params["search"] = search

    with spinner("Fetching MCP servers..."):
        data = client.get("/api/v1/mcps", params=params)

    if not data:
        rprint("[dim]No MCP servers found.[/dim]")
        return

    if interactive:

        def _display(item: dict) -> str:
            return f"{item['name']}  v{item.get('version', '?')}  [{item.get('category', '')}]  {item.get('owner', '')}"

        selected = fuzzy_select(data, _display, label="Select MCP server")
        if selected:
            _show_impl(str(selected["id"]), "table")
        return

    # Sort
    key_map = {"name": "name", "category": "category", "version": "version"}
    sk = key_map.get(sort, "name")
    data = sorted(data, key=lambda x: x.get(sk, ""))[:limit]

    # Cache IDs for numeric shorthand
    config.save_last_results(data)

    if output == "json":
        output_json(data)
        return

    if output == "plain":
        for item in data:
            rprint(f"{item['id']}  {item['name']}  v{item.get('version', '?')}  [{item.get('category', '')}]")
        return

    table = Table(title=f"MCP Servers ({len(data)})", show_lines=False, padding=(0, 1))
    table.add_column("#", style="dim", width=3)
    table.add_column("Name", style="bold cyan", no_wrap=True)
    table.add_column("Version", style="green")
    table.add_column("Category")
    table.add_column("Owner", style="dim")
    table.add_column("IDEs")
    table.add_column("ID", style="dim", max_width=12)
    for i, item in enumerate(data, 1):
        table.add_row(
            str(i),
            item["name"],
            item.get("version", ""),
            item.get("category", ""),
            item.get("owner", ""),
            ide_tags(item.get("supported_ides", [])),
            str(item["id"])[:8] + "…",
        )
    console.print(table)


def _show_impl(mcp_id, output):
    resolved = config.resolve_alias(mcp_id)
    with spinner():
        item = client.get(f"/api/v1/mcps/{resolved}")

    if output == "json":
        output_json(item)
        return

    console.print(
        kv_panel(
            f"{item['name']} v{item.get('version', '?')}",
            [
                ("Status", status_badge(item.get("status", ""))),
                ("Category", item.get("category", "N/A")),
                ("Owner", item.get("owner", "N/A")),
                ("Description", item.get("description", "")),
                ("IDEs", ide_tags(item.get("supported_ides", []))),
                ("Git", f"[link={item.get('git_url', '')}]{item.get('git_url', 'N/A')}[/link]"),
                ("Setup", item.get("setup_instructions") or "[dim]none[/dim]"),
                ("Changelog", item.get("changelog") or "[dim]none[/dim]"),
                ("Created", relative_time(item.get("created_at"))),
                ("ID", f"[dim]{item['id']}[/dim]"),
            ],
            border_style="cyan",
        )
    )

    if item.get("validation_results"):
        rprint("\n[bold]Validation:[/bold]")
        for v in item["validation_results"]:
            icon = "[green]✓[/green]" if v["passed"] else "[red]✗[/red]"
            rprint(f"  {icon} {v['stage']}: {v.get('details', '') or 'passed'}")


def _install_impl(mcp_id, ide, raw):
    import json as _json

    resolved = config.resolve_alias(mcp_id)

    # Fetch listing details to check for required env vars
    with spinner("Fetching server details..."):
        listing = client.get(f"/api/v1/mcps/{resolved}")

    env_values: dict[str, str] = {}
    env_var_list = listing.get("environment_variables") or []
    if env_var_list and not raw:
        required = [ev for ev in env_var_list if ev.get("required", True)]
        optional = [ev for ev in env_var_list if not ev.get("required", True)]

        if required:
            rprint(f"\n[bold]This server requires {len(required)} environment variable(s):[/bold]")
            for ev in required:
                desc = f" [dim]({ev['description']})[/dim]" if ev.get("description") else ""
                val = typer.prompt(f"  {ev['name']}{desc}")
                env_values[ev["name"]] = val

        if optional:
            rprint(f"\n[dim]{len(optional)} optional env var(s) available:[/dim]")
            for ev in optional:
                desc = f" [dim]({ev['description']})[/dim]" if ev.get("description") else ""
                val = typer.prompt(f"  {ev['name']}{desc} (press Enter to skip)", default="")
                if val:
                    env_values[ev["name"]] = val
    elif env_var_list and raw:
        # In raw mode, include placeholders so the user knows what's needed
        for ev in env_var_list:
            env_values[ev["name"]] = f"<{ev['name']}>"

    # Prompt for headers (SSE/HTTP servers with auth)
    header_values: dict[str, str] = {}
    header_list = listing.get("headers") or []
    if header_list and not raw:
        required_headers = [h for h in header_list if h.get("required", True)]
        optional_headers = [h for h in header_list if not h.get("required", True)]
        if required_headers:
            rprint(f"\n[bold]This server requires {len(required_headers)} header(s):[/bold]")
            for h in required_headers:
                desc = f" [dim]({h['description']})[/dim]" if h.get("description") else ""
                val = typer.prompt(f"  {h['name']}{desc}")
                header_values[h["name"]] = val
        if optional_headers:
            rprint(f"\n[dim]{len(optional_headers)} optional header(s) available:[/dim]")
            for h in optional_headers:
                desc = f" [dim]({h['description']})[/dim]" if h.get("description") else ""
                val = typer.prompt(f"  {h['name']}{desc} (press Enter to skip)", default="")
                if val:
                    header_values[h["name"]] = val
    elif header_list and raw:
        for h in header_list:
            header_values[h["name"]] = f"<{h['name']}>"

    with spinner(f"Generating {ide} config..."):
        result = client.post(
            f"/api/v1/mcps/{resolved}/install",
            {"ide": ide, "env_values": env_values, "header_values": header_values},
        )

    snippet = result.get("config_snippet", {})
    if raw:
        print(_json.dumps(snippet, indent=2))
        return

    ide_config_paths = {
        "kiro": ".kiro/settings/mcp.json",
        "cursor": ".cursor/mcp.json",
        "vscode": ".vscode/mcp.json",
        "claude-code": "(run the command below)",
        "claude_code": "(run the command below)",
        "gemini-cli": ".gemini/settings.json",
        "gemini_cli": ".gemini/settings.json",
    }

    rprint(f"\n[bold]Config for {ide}:[/bold]\n")
    console.print_json(_json.dumps(snippet, indent=2))
    config_path = ide_config_paths.get(ide, "")
    if config_path and not config_path.startswith("("):
        rprint(f"\n[dim]Add to:[/dim] [bold]{config_path}[/bold]")
        rprint(f"[dim]Or pipe:[/dim] observal install {mcp_id} --ide {ide} --raw > {config_path}")

    # Warn about any empty env vars the user skipped
    missing = [k for k, v in env_values.items() if not v or v.startswith("<")]
    if missing:
        rprint(f"\n[yellow]Warning: {len(missing)} env var(s) still need values:[/yellow]")
        for m in missing:
            rprint(f"  [yellow]![/yellow] {m}")
        rprint("[dim]Set these in your IDE config or shell environment before running the server.[/dim]")


def _delete_impl(mcp_id, yes):
    resolved = config.resolve_alias(mcp_id)
    if not yes:
        with spinner():
            item = client.get(f"/api/v1/mcps/{resolved}")
        if not typer.confirm(f"Delete [bold]{item['name']}[/bold] ({resolved})?"):
            raise typer.Abort()
    with spinner("Deleting..."):
        client.delete(f"/api/v1/mcps/{resolved}")
    rprint(f"[green]✓ Deleted {resolved}[/green]")


# ── Canonical commands (on mcp_app) ─────────────────────────


@mcp_app.command()
def submit(
    git_url: str = typer.Argument(None, help="Git repository URL (optional if --config used)"),
    name: str = typer.Option(None, "--name", "-n", help="Skip name prompt"),
    category: str = typer.Option(None, "--category", "-c", help="Skip category prompt"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Accept defaults from repo analysis"),
    config: bool = typer.Option(False, "--config", help="Submit via direct JSON config (paste mode)"),
    draft: bool = typer.Option(False, "--draft", help="Save as draft instead of submitting for review"),
    submit_draft: str | None = typer.Option(None, "--submit", help="Submit a draft for review (MCP ID)"),
):
    """Submit an MCP server for review."""
    if draft and submit_draft:
        rprint(
            "[red]Cannot use --draft and --submit together.[/red] Use --draft to save a new draft, or --submit to submit an existing draft."
        )
        raise typer.Exit(code=1)
    if submit_draft:
        from observal_cli import config as cfg

        resolved = cfg.resolve_alias(submit_draft)
        with spinner("Submitting draft for review..."):
            result = client.post(f"/api/v1/mcps/{resolved}/submit")
        rprint(f"[green]✓ Draft submitted for review![/green] ID: [bold]{result['id']}[/bold]")
        return
    if not git_url and not config:
        rprint("[red]Provide a git URL or use --config[/red]")
        raise typer.Exit(1)
    _submit_impl(git_url, name, category, yes, config, draft=draft)


@mcp_app.command(name="list")
def list_mcps(
    category: str | None = typer.Option(None, "--category", "-c", help="Filter by category"),
    search: str | None = typer.Option(None, "--search", "-s", help="Search by name/description"),
    interactive: bool = typer.Option(False, "--interactive", "-i", help="Interactive search mode"),
    limit: int = typer.Option(50, "--limit", "-n", help="Max results"),
    sort: str = typer.Option("name", "--sort", help="Sort by: name, category, version"),
    output: str = typer.Option("table", "--output", "-o", help="Output: table, json, plain"),
):
    """List approved MCP servers."""
    _list_impl(category, search, limit, sort, output, interactive=interactive)


@mcp_app.command()
def show(
    mcp_id: str = typer.Argument(..., help="ID, name, row number, or @alias"),
    output: str = typer.Option("table", "--output", "-o", help="Output: table, json"),
):
    """Show full details of an MCP server."""
    _show_impl(mcp_id, output)


@mcp_app.command()
def install(
    mcp_id: str = typer.Argument(..., help="ID, name, row number, or @alias"),
    ide: str = typer.Option(..., "--ide", "-i", help="Target IDE"),
    raw: bool = typer.Option(False, "--raw", help="Output raw JSON only (for piping)"),
):
    """Get install config snippet for an MCP server."""
    _install_impl(mcp_id, ide, raw)


@mcp_app.command(name="delete")
def delete_mcp(
    mcp_id: str = typer.Argument(..., help="ID, name, row number, or @alias"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Delete an MCP server."""
    _delete_impl(mcp_id, yes)
