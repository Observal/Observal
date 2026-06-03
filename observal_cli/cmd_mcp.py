# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""MCP server CLI commands."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import typer
from loguru import logger as optic
from rich import print as rprint
from rich.table import Table

from observal_cli import client, config
from observal_cli.analyzer import analyze_local
from observal_cli.constants import VALID_IDES, VALID_MCP_CATEGORIES
from observal_cli.prompts import fuzzy_select, select_one, text_input
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
    optic.trace("file_path={}", file_path)
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
    optic.trace("detected={}", detected)
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
            raw = text_input("Choose", default="1")
        else:
            rprint("  1. Load from .env file")
            rprint("  2. Enter manually")
            rprint("  3. Skip (no env vars)")
            raw = text_input("Choose", default="3")
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
        file_path = text_input("Path to .env file (e.g. .env.example)")
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
    optic.trace("env_vars={}", env_vars)
    reviewed: list[dict] = []

    rprint("\n[bold]Review each variable[/bold]\n")

    for ev in env_vars:
        action = text_input(
            f"  {ev['name']} - keep? [Enter=keep / r=remove / o=optional]",
            default="",
        )
        action = action.strip().lower()

        if action == "r":
            rprint("    [dim]removed[/dim]")
            continue

        required = action != "o"
        desc = ev.get("description", "")
        if not desc:
            desc = text_input(f"    Description for {ev['name']} (optional)", default="")

        reviewed.append({"name": ev["name"], "description": desc, "required": required})
        status = "[green]required[/green]" if required else "[yellow]optional[/yellow]"
        rprint(f"    {status}")

    # Offer to add more
    while True:
        add_more = text_input("\n  Add another env var? (name or Enter to finish)", default="")
        if not add_more:
            break
        desc = text_input(f"    Description for {add_more} (optional)", default="")
        req = typer.confirm("    Required?", default=True)
        reviewed.append({"name": add_more.strip().upper(), "description": desc, "required": req})

    return reviewed


def _enter_env_vars_manually() -> list[dict]:
    """Prompt the developer to enter env vars one by one."""
    env_vars: list[dict] = []
    rprint("\n[bold]Enter env vars one at a time[/bold] [dim](empty name to finish)[/dim]\n")

    while True:
        name = text_input("  Variable name (or Enter to finish)", default="")
        if not name:
            break
        name = name.strip().upper()
        desc = text_input(f"    Description for {name} (optional)", default="")
        req = typer.confirm("    Required?", default=True)
        env_vars.append({"name": name, "description": desc, "required": req})

    return env_vars


# ── Dollar-sign variable detection ──────────────────────────

_DOLLAR_VAR_RE = re.compile(r"\$\{?([A-Z][A-Z0-9_]+)\}?")


def _dollar_to_placeholder(value: str) -> str:
    """Replace $VAR / ${VAR} references with <VAR> placeholders.

    Examples:
        "Bearer $TOKEN"           → "Bearer <TOKEN>"
        "Bearer $TOKEN1 $TOKEN2"  → "Bearer <TOKEN1> <TOKEN2>"
        "$API_KEY"                → "<API_KEY>"
    """
    optic.trace("value={}", value)
    return _DOLLAR_VAR_RE.sub(lambda m: f"<{m.group(1)}>", value)


def _extract_dollar_vars(args: list[str], env: dict[str, str]) -> list[str]:
    """Extract unique $VAR / ${VAR} references from args and env values.

    Returns a sorted list of uppercase variable names found in the args list
    and the *values* (not keys) of the env dict, filtered to exclude
    system/infrastructure vars (PATH, HOME, CI_*, etc.).
    """
    optic.trace("args={}, env={}", args, env)
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
    optic.trace("cfg={}", cfg)
    if "mcpServers" in cfg and isinstance(cfg["mcpServers"], dict):
        servers = cfg["mcpServers"]
        if len(servers) == 1:
            server_name, inner = next(iter(servers.items()))
            if isinstance(inner, dict):
                return inner, server_name
        return cfg, None

    # Shape 3: bare config - has a direct config key
    if cfg.get("command") or cfg.get("url") or cfg.get("type"):
        return cfg, None

    # Shape 2: single named key wrapping a config dict
    if len(cfg) == 1:
        server_name, inner = next(iter(cfg.items()))
        if isinstance(inner, dict) and (inner.get("command") or inner.get("url") or inner.get("type")):
            return inner, server_name

    return cfg, None


def _parse_server_json_manifest(cfg: dict) -> dict | None:
    """Parse a server.json manifest format (packages[]/remotes[] arrays).

    Also handles the MCP registry format where data is nested under a "server" key:
      {"server": {"name": "...", "remotes": [...]}, "_meta": {...}}

    Returns parsed dict if this looks like a server.json manifest, None otherwise.
    """
    # Handle registry format: unwrap "server" envelope
    optic.trace("cfg={}", cfg)
    manifest = cfg
    server_meta = cfg.get("server")
    if isinstance(server_meta, dict) and ("remotes" in server_meta or "packages" in server_meta):
        manifest = server_meta

    if "packages" not in manifest and "remotes" not in manifest:
        return None

    parsed: dict = {}
    env_vars: list[dict] = []

    # Extract server name/description from registry metadata
    if server_meta and isinstance(server_meta, dict):
        reg_name = server_meta.get("title") or server_meta.get("name")
        if reg_name:
            parsed["_server_name"] = reg_name
        reg_desc = server_meta.get("description")
        if reg_desc:
            parsed["_description"] = reg_desc

    # packages[].runtimeArguments - Docker -e flags
    for pkg in manifest.get("packages", []):
        for arg in pkg.get("runtimeArguments", []):
            value = arg.get("value", "")
            # Pattern: "ENV_VAR={placeholder}" - extract the var name before '='
            if "=" in value:
                var_name = value.split("=", 1)[0]
                if var_name and var_name == var_name.upper():
                    desc = arg.get("description", "")
                    env_vars.append({"name": var_name, "description": desc, "required": True})

    # remotes[].variables - URL-interpolated secrets
    for remote in manifest.get("remotes", []):
        url = remote.get("url", "")
        if url and not parsed.get("url"):
            parsed["url"] = url
            parsed["transport"] = remote.get("type", "sse")
        for var_key, var_meta in (remote.get("variables") or {}).items():
            desc = var_meta.get("description", "") if isinstance(var_meta, dict) else ""
            env_vars.append({"name": var_key, "description": desc, "required": True})

    if env_vars:
        parsed["environment_variables"] = env_vars

    # Determine transport: URL means SSE/HTTP, packages-only means stdio/docker
    if not parsed.get("url"):
        has_remotes = bool(manifest.get("remotes"))
        if not has_remotes:
            # Packages-only manifest implies stdio (Docker typically)
            parsed["transport"] = "stdio"
            parsed["framework"] = "docker"
        # else: remotes without a URL - don't assume transport

    return parsed


def _parse_direct_config(cfg: dict) -> dict:
    """Normalize a JSON config dict into submit-ready fields.

    Accepts:
    - IDE config: wrapped (mcpServers) or bare {command, args} / {url, type}
    - server.json manifest: {packages: [...]} / {remotes: [...]}

    Handles two transport shapes:
    - stdio: {command, args, env}
    - SSE/HTTP: {url, type, headers, autoApprove}
    """
    # Try server.json manifest format first
    optic.trace("cfg={}", cfg)
    manifest_result = _parse_server_json_manifest(cfg)
    if manifest_result is not None:
        return manifest_result

    inner, server_name = _unwrap_mcp_config(cfg)
    parsed: dict = {}
    if server_name:
        parsed["_server_name"] = server_name

    if inner.get("url") and not inner.get("command"):
        # SSE / streamable-http transport
        transport = inner.get("type", "sse")
        parsed["transport"] = transport
        parsed["url"] = inner["url"]

        # Convert headers dict {name: value} → list of {name, value, description, required}
        raw_headers = inner.get("headers") or {}
        if isinstance(raw_headers, dict):
            parsed["headers"] = [
                {"name": k, "value": v, "description": "", "required": True} for k, v in raw_headers.items()
            ]
        elif isinstance(raw_headers, list):
            parsed["headers"] = raw_headers

        if inner.get("autoApprove"):
            parsed["auto_approve"] = inner["autoApprove"]

        # env as environment_variables
        raw_env = inner.get("env") or {}
        if isinstance(raw_env, dict):
            parsed["environment_variables"] = [{"name": k, "description": "", "required": True} for k in raw_env]

        # Detect $VAR references in header values and env values
        dollar_vars = _extract_dollar_vars([], {**raw_headers, **raw_env})
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
    optic.trace("server_name={}, parsed={}", server_name, parsed)
    preview: dict = {}

    if parsed.get("url"):
        # SSE / streamable-http preview
        preview["type"] = parsed.get("transport", "sse")
        preview["url"] = parsed["url"]
        if parsed.get("headers"):
            preview["headers"] = {
                h["name"]: _dollar_to_placeholder(h["value"])
                if _DOLLAR_VAR_RE.search(h.get("value", ""))
                else h.get("value", f"<{h['name']}>")
                for h in parsed["headers"]
            }
        env_vars = parsed.get("environment_variables") or []
        if env_vars:
            preview["env"] = {ev["name"]: f"<{ev['name']}>" for ev in env_vars}
        if parsed.get("auto_approve"):
            preview["autoApprove"] = parsed["auto_approve"]
        preview["disabled"] = False
    else:
        # stdio preview
        command = parsed.get("command", "")
        args = [_dollar_to_placeholder(a) if _DOLLAR_VAR_RE.search(a) else a for a in (parsed.get("args") or [])]

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
    optic.trace("git_url={}, name={}", git_url, name)
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
            # Long single-line pastes can get split by the terminal - retry without newlines
            try:
                cfg = json.loads("".join(part.strip() for part in lines))
            except json.JSONDecodeError as e:
                rprint(f"[red]Invalid JSON:[/red] {e}")
                raise typer.Exit(1)

        parsed = _parse_direct_config(cfg)
        _name = name or parsed.pop("_server_name", None) or "my-mcp-server"
        _parsed_desc = parsed.pop("_description", None)

        # Extract dollar-sign input variables before preview
        dollar_vars = parsed.pop("_dollar_vars_detected", None)

        rprint("\n[bold]Config preview:[/bold]")
        console.print_json(json.dumps(_build_config_preview(_name, parsed), indent=2))

        if dollar_vars:
            placeholders = " ".join(f"<{v}>" for v in dollar_vars)
            rprint(f"\n[bold]The user variables are:[/bold] [cyan]{placeholders}[/cyan]")
            rprint(
                "[dim]These will become install-time prompts - users must supply"
                " values before the server can run.[/dim]"
            )

        if not yes:
            if not typer.confirm("\nSubmit this config?", default=True):
                raise typer.Abort()

            # Let creator review/confirm input dependencies
            if dollar_vars:
                rprint("\n[bold]Confirm input dependencies:[/bold]")
                parsed["environment_variables"] = _review_env_vars(parsed.get("environment_variables", []))

            _name = name or text_input("Server name", default=_name)
            _desc_default = _parsed_desc or ""
            _desc = text_input("Description (what does this server do?)", default=_desc_default or "")
            while not _desc.strip():
                rprint("[yellow]Description is required.[/yellow]")
                _desc = text_input("Description (what does this server do?)")
            _desc = _desc.strip()
            _owner = text_input(
                "Owner / Team (e.g. your GitHub username)", default=config.load().get("user_name", "default")
            )
            _category = category or select_one("Category", VALID_MCP_CATEGORIES, default="general")
        else:
            if dollar_vars:
                rprint(f"\n[dim]Auto-detected {len(dollar_vars)} input variable(s) from $VAR patterns.[/dim]")
            _desc = _parsed_desc or _name
            _owner = config.load().get("user_name", "") or "default"
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
    rprint(
        "\n[yellow]Note:[/yellow] Git analysis is best-effort and not a long-term supported feature."
        "\n      Environment variable detection may not cover all cases - please review"
        "\n      and add any missing variables manually.\n"
    )
    analyzed_locally = False
    with spinner("Analyzing repository..."):
        try:
            prefill = analyze_local(git_url)
            if prefill.get("error"):
                rprint(f"[yellow]Local analysis issue:[/yellow] {prefill['error']}")
                rprint("[dim]Falling back to server-side analysis...[/dim]")
                try:
                    prefill = client.post("/api/v1/mcps/analyze", {"git_url": git_url})
                except SystemExit:
                    rprint("[yellow]Server analysis also failed. Fill in details manually.[/yellow]")
                    prefill = {}
            else:
                analyzed_locally = True
        except (OSError, ValueError, RuntimeError):
            # Local analysis can fail with filesystem/git/parsing errors
            try:
                prefill = client.post("/api/v1/mcps/analyze", {"git_url": git_url})
            except SystemExit:
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
    # MCP servers are IDE-agnostic - config generation handles all IDEs.
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
        _owner = config.load().get("user_name", "") or "default"
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
                    " was inferred from the GitHub URL - verify it exists)[/dim]"
                )
            choice = (
                text_input(
                    "Startup config looks correct? [Y/n/edit]",
                    default="Y",
                )
                .strip()
                .lower()
            )
            if choice == "n":
                raise typer.Abort()
            elif choice == "edit":
                _command = text_input("Command", default=detected_command or "")
                raw_args = text_input(
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
            custom_cmd = text_input("Command (e.g. docker, python, npx - Enter to skip)", default="")
            if custom_cmd:
                _command = custom_cmd
                raw_args = text_input("Args (space-separated)", default="")
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
            _name = text_input("Server name")

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
            _desc = text_input("Description (what does this server do?)")

        _owner = text_input("\nOwner / Team (e.g. your GitHub username)", default=config.load().get("user_name", ""))
        rprint()

        _category = category or select_one("Category", VALID_MCP_CATEGORIES, default="general")

        _setup = text_input("Setup instructions (optional, press Enter to skip)", default="")
        _changelog = text_input("Changelog", default="Initial release")

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
                " dependencies - users will be prompted for these values.[/dim]\n"
            )
            for var in dollar_vars:
                rprint(f"  [cyan]$[/cyan]{var}")
            rprint()

        # Interactive env var configuration - developer reviews, edits,
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
    optic.trace("category={}, search={}", category, search)
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
            optic.trace("item={}", item)
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
    optic.trace("mcp_id={}, output={}", mcp_id, output)
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


def _install_impl(mcp_id, ide, raw, version=None):
    optic.trace("mcp_id={}, ide={}, version={}", mcp_id, ide, version)
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
                val = text_input(f"  {ev['name']}{desc}")
                env_values[ev["name"]] = val

        if optional:
            rprint(f"\n[dim]{len(optional)} optional env var(s) available:[/dim]")
            for ev in optional:
                desc = f" [dim]({ev['description']})[/dim]" if ev.get("description") else ""
                val = text_input(f"  {ev['name']}{desc} (press Enter to skip)", default="")
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
                val = text_input(f"  {h['name']}{desc}")
                header_values[h["name"]] = val
        if optional_headers:
            rprint(f"\n[dim]{len(optional_headers)} optional header(s) available:[/dim]")
            for h in optional_headers:
                desc = f" [dim]({h['description']})[/dim]" if h.get("description") else ""
                val = text_input(f"  {h['name']}{desc} (press Enter to skip)", default="")
                if val:
                    header_values[h["name"]] = val
    elif header_list and raw:
        for h in header_list:
            header_values[h["name"]] = f"<{h['name']}>"

    with spinner(f"Generating {ide} config..."):
        install_body = {"ide": ide, "env_values": env_values, "header_values": header_values}
        if version:
            install_body["version"] = version
        result = client.post(
            f"/api/v1/mcps/{resolved}/install",
            install_body,
        )

    snippet = result.get("config_snippet", {})
    if raw:
        print(_json.dumps(snippet, indent=2))
        return

    # Write to lock file (track the install regardless of how user applies config)
    try:
        from observal_cli.lockfile import upsert_standalone

        upsert_standalone(
            ide,
            component_type="mcp",
            name=listing.get("name", resolved),
            component_id=str(listing.get("id", resolved)),
            version=version or listing.get("version") or listing.get("latest_version"),
            scope="user",
        )
    except Exception:
        pass  # Never block install on lockfile failure

    ide_config_paths = {
        "kiro": ".kiro/settings/mcp.json",
        "cursor": ".cursor/mcp.json",
        "claude-code": "(run the command below)",
        "claude_code": "(run the command below)",
        "gemini-cli": ".gemini/settings.json",
        "gemini_cli": ".gemini/settings.json",
        "opencode": ".config/opencode/opencode.json",
        "codex": "~/.codex/config.toml",
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
    optic.trace("mcp_id={}, yes={}", mcp_id, yes)
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
    git_url: str = typer.Option(None, "--git", "-g", help="Analyze a git repository instead of pasting config"),
    name: str = typer.Option(None, "--name", "-n", help="Skip name prompt"),
    category: str = typer.Option(None, "--category", "-c", help="Skip category prompt"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Accept defaults from repo analysis"),
    config: bool = typer.Option(False, "--config", hidden=True, help="(deprecated) JSON paste is now the default"),
    draft: bool = typer.Option(False, "--draft", help="Save as draft instead of submitting for review"),
    submit_draft: str | None = typer.Option(None, "--submit", help="Submit a draft for review (MCP ID)"),
):
    """Submit an MCP server to the registry.

    By default, opens an interactive JSON paste prompt where you provide
    the same config format used in your IDE (e.g. mcpServers block). Use
    --git to analyze a git repository instead, which auto-detects tools,
    env vars, and startup commands.

    Only submit servers you created or are the point-of-contact for.
    Submissions go into a pending review queue unless saved as a draft.
    You can install your own submissions immediately without approval.

    Environment variables containing $VAR or ${VAR} patterns in args or
    header values are auto-detected and become install-time prompts.

    Examples:
        # Interactive JSON paste (default)
        observal registry mcp submit

        # Analyze a git repo with all defaults accepted
        observal registry mcp submit --git https://github.com/org/mcp-server --yes

        # Submit with name and category pre-filled
        observal registry mcp submit --git https://github.com/org/server -n my-server -c ai

        # Save as draft for later editing
        observal registry mcp submit --draft

        # Submit an existing draft for review
        observal registry mcp submit --submit my-server
    """
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
    if config:
        rprint("[dim]Note: --config is now the default. You can just run `observal mcp submit`.[/dim]")
    rprint("[dim]Note: Only submit components you created (private) or are the point-of-contact for (external).[/dim]")
    # Default is JSON paste (direct_config=True), unless --git is provided
    direct_config = not git_url
    _submit_impl(git_url, name, category, yes, direct_config, draft=draft)


@mcp_app.command(name="list")
def list_mcps(
    category: str | None = typer.Option(None, "--category", "-c", help="Filter by category"),
    search: str | None = typer.Option(None, "--search", "-s", help="Search by name/description"),
    interactive: bool = typer.Option(False, "--interactive", "-i", help="Interactive search mode"),
    limit: int = typer.Option(50, "--limit", "-n", help="Max results"),
    sort: str = typer.Option("name", "--sort", help="Sort by: name, category, version"),
    output: str = typer.Option("table", "--output", "-o", help="Output: table, json, plain"),
):
    """List approved MCP servers in the registry.

    Shows publicly approved servers by default. Use --search for keyword
    filtering, --category to narrow by type, and --sort to change ordering.
    Results are cached locally so you can reference them by row number in
    subsequent show/install/delete commands.

    Interactive mode (--interactive) opens a fuzzy-search picker and
    displays full details of the selected server.

    Examples:
        # List all approved servers
        observal registry mcp list

        # Search for database-related servers
        observal registry mcp list --search postgres

        # Filter by category, output as JSON
        observal registry mcp list --category ai --output json

        # Interactive fuzzy picker
        observal registry mcp list --interactive

        # Sort by category, limit to 10 results
        observal registry mcp list --sort category --limit 10
    """
    _list_impl(category, search, limit, sort, output, interactive=interactive)


@mcp_app.command(name="my")
def mcp_my(
    output: str = typer.Option("table", "--output", "-o", help="Output: table, json, plain"),
):
    """List your own MCP servers across all statuses.

    Shows servers you submitted regardless of approval state (pending,
    approved, rejected, draft). Useful for checking submission status
    or finding draft IDs to resume editing.

    Examples:
        # List your servers in a table
        observal registry mcp my

        # JSON output for scripting
        observal registry mcp my --output json

        # Plain output (one per line)
        observal registry mcp my --output plain
    """
    optic.trace("output={}", output)
    with spinner("Fetching your MCPs..."):
        data = client.get("/api/v1/mcps/my")
    if not data:
        rprint("[dim]You have no MCP servers.[/dim]")
        return
    config.save_last_results(data)
    if output == "json":
        output_json(data)
        return
    if output == "plain":
        for item in data:
            rprint(f"{item['name']}  v{item.get('version', '?')}  {item.get('status', '')}")
        return
    table = Table(title=f"My MCPs ({len(data)})", show_lines=False, padding=(0, 1))
    table.add_column("#", style="dim", width=3)
    table.add_column("Name", style="bold cyan", no_wrap=True)
    table.add_column("Version", style="green")
    table.add_column("Owner", style="dim")
    table.add_column("Status")
    table.add_column("ID", style="dim", max_width=12)
    for i, item in enumerate(data, 1):
        table.add_row(
            str(i),
            item["name"],
            item.get("version", ""),
            item.get("owner", ""),
            status_badge(item.get("status", "")),
            str(item["id"])[:8] + "…",
        )
    console.print(table)


@mcp_app.command()
def show(
    mcp_id: str = typer.Argument(..., help="ID, name, row number, or @alias"),
    output: str = typer.Option("table", "--output", "-o", help="Output: table, json"),
):
    """Show full details of an MCP server.

    Displays metadata, validation results, supported IDEs, env vars,
    and timestamps for a given server. Accepts a UUID, server name,
    row number from the last list command, or an @alias.

    Examples:
        # Show by name
        observal registry mcp show my-server

        # Show by row number from last list
        observal registry mcp show 3

        # Show by alias
        observal registry mcp show @fav

        # JSON output
        observal registry mcp show my-server --output json
    """
    optic.trace("mcp_id={}, output={}", mcp_id, output)
    _show_impl(mcp_id, output)


@mcp_app.command()
def install(
    mcp_id: str = typer.Argument(..., help="ID, name, row number, or @alias"),
    ide: str = typer.Option(..., "--ide", "-i", help="Target IDE"),
    raw: bool = typer.Option(False, "--raw", help="Output raw JSON only (for piping)"),
    version: str | None = typer.Option(
        None, "--version", "-V", help="Install a specific version (e.g. '2.1.0'). Defaults to latest."
    ),
):
    """Generate an install config snippet for an MCP server.

    Produces IDE-specific configuration that you paste into your editor's
    MCP settings file. Prompts for required environment variables and
    headers interactively (unless --raw is used).

    The --raw flag outputs bare JSON suitable for piping directly into
    config files, with placeholder values for env vars.

    Examples:
        # Generate config for Claude Code
        observal registry mcp install my-server --ide claude-code

        # Generate for Cursor and pipe to config file
        observal registry mcp install my-server --ide cursor --raw > .cursor/mcp.json

        # Install by row number for VS Code
        observal registry mcp install 2 --ide vscode

        # Install using an alias
        observal registry mcp install @db --ide kiro
    """
    optic.trace("mcp_id={}, ide={}", mcp_id, ide)
    _install_impl(mcp_id, ide, raw, version=version)


@mcp_app.command(name="edit")
def edit_mcp(
    mcp_id: str = typer.Argument(..., help="ID, name, row number, or @alias"),
    from_file: str | None = typer.Option(None, "--from-file", "-f", help="Load updates from JSON file"),
    name: str | None = typer.Option(None, "--name", "-n", help="New listing name"),
    description: str | None = typer.Option(None, "--description", "-d", help="New description"),
    category: str | None = typer.Option(None, "--category", "-c", help="New category"),
    version: str | None = typer.Option(None, "--version", "-v", help="New version string"),
    git_url: str | None = typer.Option(None, "--git-url", help="New git URL"),
    command: str | None = typer.Option(None, "--command", help="New command"),
    url: str | None = typer.Option(None, "--url", help="New URL"),
):
    """Edit an MCP server submission.

    For draft, pending, or rejected listings: edits the submission in place.
    For approved listings: publishes a new version with a semver bump
    (you will be prompted to choose patch, minor, or major).

    Without flags, opens an interactive JSON paste prompt (same format as
    submit). You can also pass individual fields via options, or load a
    complete update from a JSON file with --from-file.

    Examples:
        # Interactive JSON paste edit
        observal registry mcp edit my-server

        # Update description and category
        observal registry mcp edit my-server -d "New description" -c databases

        # Load updates from a file
        observal registry mcp edit my-server --from-file updates.json

        # Bump version on an approved listing
        observal registry mcp edit my-server --version 1.2.0

        # Change the git URL
        observal registry mcp edit my-server --git-url https://github.com/org/new-repo
    """
    optic.trace("mcp_id={}, from_file={}", mcp_id, from_file)
    resolved = config.resolve_alias(mcp_id)
    if from_file:
        try:
            with open(from_file) as f:
                updates = json.load(f)
        except json.JSONDecodeError as e:
            rprint(f"[red]Invalid JSON in {from_file}:[/red] {e}")
            raise typer.Exit(code=1)
        except FileNotFoundError:
            rprint(f"[red]File not found:[/red] {from_file}")
            raise typer.Exit(code=1)
    else:
        updates = {}
        if name is not None:
            updates["name"] = name
        if description is not None:
            updates["description"] = description
        if category is not None:
            updates["category"] = category
        if version is not None:
            updates["version"] = version
        if git_url is not None:
            updates["git_url"] = git_url
        if command is not None:
            updates["command"] = command
        if url is not None:
            updates["url"] = url

    if not updates:
        # Interactive JSON paste mode (like submit)
        rprint("[bold]Paste your updated MCP server JSON config below.[/bold]")
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
            rprint("[yellow]No input received.[/yellow]")
            raise typer.Exit(code=1)
        try:
            cfg = json.loads(raw_text)
        except json.JSONDecodeError:
            try:
                cfg = json.loads("".join(part.strip() for part in lines))
            except json.JSONDecodeError as e:
                rprint(f"[red]Invalid JSON:[/red] {e}")
                raise typer.Exit(1)

        parsed = _parse_direct_config(cfg)
        _name = parsed.pop("_server_name", None)
        _desc = parsed.pop("_description", None)
        parsed.pop("_dollar_vars_detected", None)

        # Build updates from parsed config
        if _name:
            updates["name"] = _name
        if _desc:
            updates["description"] = _desc
        if parsed.get("command"):
            updates["command"] = parsed["command"]
        if parsed.get("args") is not None:
            updates["args"] = parsed["args"]
        if parsed.get("url"):
            updates["url"] = parsed["url"]
        if parsed.get("transport"):
            updates["transport"] = parsed["transport"]
        if parsed.get("framework"):
            updates["framework"] = parsed["framework"]
        if parsed.get("environment_variables"):
            updates["environment_variables"] = parsed["environment_variables"]

        rprint("\n[bold]Config preview:[/bold]")
        preview_name = _name or mcp_id
        console.print_json(json.dumps(_build_config_preview(preview_name, parsed), indent=2))

        if not typer.confirm("\nApply these changes?", default=True):
            raise typer.Abort()

    if not updates:
        rprint("[yellow]No changes could be parsed from input.[/yellow]")
        raise typer.Exit(code=1)

    # Check listing status - approved listings need a new version, drafts can be edited directly
    is_approved = False
    listing = None
    try:
        with spinner("Checking listing status..."):
            listing = client.get(f"/api/v1/mcps/{resolved}")
        if listing.get("status") == "approved":
            is_approved = True
    except SystemExit:
        # client raises typer.Exit on API failure - fall through to draft edit flow
        pass

    if is_approved:
        # Approved listing → publish a new version with semver bump
        current_ver = listing.get("version", "0.1.0") if listing else "0.1.0"
        rprint(f"[dim]Current version: {current_ver}[/dim]")
        bump_type = select_one("Version bump", ["patch", "minor", "major"], default="patch")

        parts = current_ver.split(".")
        if len(parts) == 3 and all(p.isdigit() for p in parts):
            major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
            if bump_type == "major":
                _new_version = f"{major + 1}.0.0"
            elif bump_type == "minor":
                _new_version = f"{major}.{minor + 1}.0"
            else:
                _new_version = f"{major}.{minor}.{patch + 1}"
        else:
            _new_version = "0.2.0"

        rprint(f"[bold]New version:[/bold] {_new_version}")
        _changelog = text_input("Changelog (what changed?)", default="")

        # Separate top-level fields from extra (version-specific) fields
        version_description = updates.pop("description", None) or (listing.get("description", "") if listing else "")
        updates.pop("name", None)  # name is a listing field, not a version field

        version_body: dict = {
            "version": _new_version.strip(),
            "description": version_description,
        }
        if updates:
            version_body["extra"] = updates
        if _changelog.strip():
            version_body["changelog"] = _changelog.strip()

        # client.post prints its own error message and raises typer.Exit on failure - let it propagate
        with spinner("Publishing new version..."):
            result = client.post(f"/api/v1/mcps/{resolved}/versions", version_body)
        rprint(f"[green]✓ Published v{_new_version.strip()}[/green] for [bold]{result.get('name', mcp_id)}[/bold]")
    else:
        # Draft/pending/rejected → edit in place
        try:
            client.post(f"/api/v1/mcps/{resolved}/start-edit")
        except SystemExit:
            # start-edit may 409 if already locked - client prints the error, proceed anyway
            pass
        try:
            with spinner("Saving changes..."):
                result = client.put(f"/api/v1/mcps/{resolved}/draft", updates)
            rprint(f"[green]✓ Updated {result['name']}[/green] (status: {result.get('status', 'unknown')})")
        except SystemExit:
            # Save failed - attempt to release the edit lock before exiting
            try:
                client.post(f"/api/v1/mcps/{resolved}/cancel-edit")
            except SystemExit:
                pass
            raise typer.Exit(code=1)


@mcp_app.command(name="delete")
def delete_mcp(
    mcp_id: str = typer.Argument(..., help="ID, name, row number, or @alias"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Delete an MCP server from the registry.

    Permanently removes the server listing and all associated data.
    Prompts for confirmation unless --yes is passed. You can only
    delete servers you own (or any server if you are an admin).

    Examples:
        # Delete with confirmation prompt
        observal registry mcp delete my-server

        # Delete by ID without confirmation
        observal registry mcp delete abc123 --yes

        # Delete by row number from last list
        observal registry mcp delete 3 --yes

        # Delete by alias
        observal registry mcp delete @old-server
    """
    optic.trace("mcp_id={}, yes={}", mcp_id, yes)
    _delete_impl(mcp_id, yes)
