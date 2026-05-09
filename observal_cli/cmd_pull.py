"""observal pull: fetch agent config from the server and write IDE files to disk."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import typer
from rich import print as rprint

from observal_cli import client, config
from observal_cli.ide_registry import get_scope_aware_ides
from observal_cli.render import spinner

# Hook script names used as placeholders in server-generated agent configs.
# Resolved to absolute paths client-side before writing to disk.
_HOOK_SCRIPT_NAMES = ("observal-hook.sh", "observal-stop-hook.sh")


def _resolve_hook_paths(content: str) -> str:
    """Replace hook script names with absolute paths in agent file content.

    Server-side config generator emits bare script names (observal-hook.sh)
    since it doesn't know the client's install path. This resolves them to
    the actual paths inside the installed package.

    Uses regex anchored to quoted command context so matches like
    ``"observal-hook.sh --agent-name foo"`` are resolved correctly,
    but comments or prose mentioning the script name are not affected.
    """
    import shutil

    hooks_dir = Path(__file__).parent / "hooks"
    for name in _HOOK_SCRIPT_NAMES:
        local = hooks_dir / name
        path = local.resolve().as_posix()
        if not local.is_file():
            # Fallback: check if it's on PATH
            found = shutil.which(name)
            if not found:
                continue
            path = Path(found).resolve().as_posix()
        # Match script name inside quotes with optional trailing args, replace only the script name
        pattern = rf'"{re.escape(name)}(?:\s+[^"]*)?'
        replacement = f'"{path}'
        content = re.sub(pattern, replacement, content)
    return content


def _collect_mcp_env_vars(agent_detail: dict) -> dict[str, dict[str, str]]:
    """Discover MCP env vars from agent components and prompt the user for values.

    Returns {mcp_listing_id: {VAR_NAME: value}} for all MCPs that have env vars.
    """
    env_values: dict[str, dict[str, str]] = {}

    # Collect MCP component IDs from both mcp_links and component_links
    mcp_ids: list[tuple[str, str]] = []  # (listing_id, display_name)
    for link in agent_detail.get("mcp_links", []):
        mcp_ids.append((str(link["mcp_listing_id"]), link.get("mcp_name", "")))
    for link in agent_detail.get("component_links", []):
        if link.get("component_type") == "mcp":
            cid = str(link["component_id"])
            # Avoid duplicates if already in mcp_links
            if not any(mid == cid for mid, _ in mcp_ids):
                mcp_ids.append((cid, link.get("component_name", "")))

    if not mcp_ids:
        return env_values

    # Fetch each MCP listing to get its environment_variables
    for listing_id, display_name in mcp_ids:
        try:
            listing = client.get(f"/api/v1/mcps/{listing_id}")
        except (Exception, SystemExit):
            continue

        ev_list = listing.get("environment_variables") or []
        if not ev_list:
            continue

        required = [ev for ev in ev_list if ev.get("required", True)]
        optional = [ev for ev in ev_list if not ev.get("required", True)]
        mcp_name = display_name or listing.get("name", listing_id[:8])
        mcp_env: dict[str, str] = {}

        if required:
            rprint(f"\n[bold]{mcp_name}[/bold] requires {len(required)} environment variable(s):")
            for ev in required:
                desc = f" [dim]({ev['description']})[/dim]" if ev.get("description") else ""
                val = typer.prompt(f"  {ev['name']}{desc}")
                mcp_env[ev["name"]] = val

        if optional:
            rprint(f"\n[dim]{mcp_name}: {len(optional)} optional env var(s):[/dim]")
            for ev in optional:
                desc = f" [dim]({ev['description']})[/dim]" if ev.get("description") else ""
                val = typer.prompt(f"  {ev['name']}{desc} (press Enter to skip)", default="")
                if val:
                    mcp_env[ev["name"]] = val

        if mcp_env:
            env_values[listing_id] = mcp_env

    # Warn about MCPs that had env vars but user skipped all of them
    return env_values


def _dict_to_toml(d: dict) -> str:
    """Very basic TOML serializer for MCP configs."""
    lines = []
    for section, servers in d.items():
        for name, srv in servers.items():
            lines.append(f"[{section}.{name}]")
            for k, v in srv.items():
                if isinstance(v, list):
                    arr = ", ".join(json.dumps(s) for s in v)
                    lines.append(f"{k} = [{arr}]")
                elif isinstance(v, dict):
                    for subk, subv in v.items():
                        lines.append(f"{k}.{subk} = {json.dumps(subv)}")
                elif isinstance(v, bool):
                    lines.append(f"{k} = {'true' if v else 'false'}")
                elif isinstance(v, str):
                    lines.append(f"{k} = {json.dumps(v)}")
                else:
                    lines.append(f"{k} = {v}")
            lines.append("")
    return "\n".join(lines)


def _write_file(path: Path, content: str | dict, *, merge_mcp: bool = False) -> str:
    """Write content to a file path, creating parent dirs as needed.

    If *merge_mcp* is True and the file already exists, merge the incoming
    dict into the existing one rather than overwriting.

    Returns a human-readable status string ("created", "updated", "merged").
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()

    if isinstance(content, dict):
        root_key = next(iter(content.keys())) if content else "mcpServers"
        if path.suffix == ".toml":
            incoming_servers = content.get(root_key, {})
            toml_str = _dict_to_toml({root_key: incoming_servers})
            if existed and merge_mcp:
                path.write_text(path.read_text() + "\n" + toml_str)
                return "merged"
            else:
                path.write_text(toml_str)
        else:
            if merge_mcp and existed:
                try:
                    existing = json.loads(path.read_text())
                except (json.JSONDecodeError, OSError):
                    existing = {}
                incoming_servers = content.get(root_key, {})
                existing.setdefault(root_key, {}).update(incoming_servers)
                path.write_text(json.dumps(existing, indent=2) + "\n")
                return "merged"
            path.write_text(json.dumps(content, indent=2) + "\n")
    else:
        path.write_text(content)

    return "updated" if existed else "created"


def _rewrite_kiro_hooks(content: dict) -> dict:
    """Rewrite Kiro hook commands to use the current Python interpreter.

    The server generates commands with bare 'python3' which won't find
    observal_cli when installed in a project-local virtual environment.
    """
    hooks = content.get("hooks")
    agent_name = content.get("name")
    if not hooks or not agent_name:
        return content

    from observal_cli.ide_specs.kiro_hooks_spec import build_kiro_hooks

    cfg = config.get_or_exit()
    hooks_url = f"{cfg['server_url'].rstrip('/')}/api/v1/telemetry/hooks"
    desired_hooks = build_kiro_hooks(hooks_url, agent_name)

    # Replace only Observal hooks, preserve any user-added hooks
    for event, desired_entries in desired_hooks.items():
        existing = hooks.get(event, [])
        cleaned = [h for h in existing if "observal_cli" not in h.get("command", "")]
        hooks[event] = cleaned + desired_entries

    content["hooks"] = hooks
    return content


def _resolve_path(raw_path: str, target_dir: Path, *, allow_home: bool = False) -> Path:
    """Resolve a path from the config snippet relative to *target_dir*.

    By default, ``~/`` prefixes are mapped under *target_dir* (not the real
    home directory) so that the pull command always writes inside the project.
    When *allow_home* is True (e.g. user explicitly chose --scope user), real
    ``$HOME`` expansion is allowed.

    Raises typer.Exit if the resolved path escapes *target_dir* (and home
    expansion is not permitted).
    """
    if raw_path.startswith("~/") or raw_path.startswith("~\\"):
        if allow_home:
            return Path(raw_path).expanduser().resolve()
        resolved = (target_dir / raw_path[2:]).resolve()
    else:
        resolved = (target_dir / raw_path).resolve()

    if not resolved.is_relative_to(target_dir):
        rprint(f"[red]Error:[/red] path '{raw_path}' escapes target directory")
        raise typer.Exit(1)

    return resolved


# IDEs that support a project vs user install scope (derived from registry)
_SCOPE_AWARE_IDES = get_scope_aware_ides()


def _parse_model_overrides(values: list[str]) -> tuple[str | None, dict[str, str]]:
    """Parse one or more ``--model`` flags.

    Two grammars are accepted:

    * ``--model <value>`` — applies to the IDE selected for this pull.
    * ``--model <ide>=<value>`` — explicit per-IDE override (advanced; lets
      a single command target a specific IDE without ambiguity).

    Returns ``(default_value, per_ide_overrides)``.
    """
    default: str | None = None
    overrides: dict[str, str] = {}
    for raw in values or []:
        if "=" in raw:
            ide_key, _, val = raw.partition("=")
            ide_key = ide_key.strip()
            val = val.strip()
            if ide_key and val:
                overrides[ide_key] = val
        elif raw.strip():
            default = raw.strip()
    return default, overrides


def _agent_saved_model(agent_detail: dict | None, ide: str) -> str | None:
    """Return the model the *agent* has saved for *ide*, if any.

    Per-IDE override wins; otherwise the legacy ``model_name`` is used as
    the implicit default for Claude Code only. Mirrors the server-side
    ``services.model_resolver._candidate_for_ide`` rules so the CLI never
    re-prompts when the author has already chosen a model.
    """
    if not agent_detail:
        return None
    raw = agent_detail.get("models_by_ide") if isinstance(agent_detail, dict) else None
    if isinstance(raw, dict):
        candidate = raw.get(ide)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    if ide in ("claude-code", "claude_code"):
        legacy = agent_detail.get("model_name") if isinstance(agent_detail, dict) else None
        if isinstance(legacy, str) and legacy.strip():
            return legacy.strip()
    return None


def _collect_install_options(
    ide: str,
    *,
    scope: str | None,
    model_default: str | None,
    model_overrides: dict[str, str],
    tools: str | None,
    no_prompt: bool,
    refresh_models: bool = False,
    agent_detail: dict | None = None,
) -> dict:
    """Interactively collect IDE-specific install options.

    Honors explicit ``--scope``/``--model``/``--tools`` flags; only prompts for
    what's missing when running in an interactive terminal and ``--no-prompt``
    isn't set. The model picker now consults the live catalog (``GET /api/v1/models``)
    instead of a hardcoded list.

    When the agent already has a saved model for the target IDE (set in the
    builder) and the user didn't pass ``--model``, the saved value is used
    silently — the picker is skipped so authoring decisions aren't undone
    by a stray Enter at the prompt.
    """
    import sys

    from observal_cli.ide_registry import accepts_model_choice
    from observal_cli.prompts import select_one
    from observal_cli.render import format_model as _format_model

    opts: dict = {}
    interactive = sys.stdin.isatty() and not no_prompt

    if ide in _SCOPE_AWARE_IDES:
        if scope:
            opts["scope"] = scope
        elif interactive:
            project_label, user_label = _SCOPE_AWARE_IDES[ide]
            choice = select_one("  Scope", [project_label, user_label], default=project_label)
            opts["scope"] = "user" if choice.startswith("user") else "project"
        else:
            opts["scope"] = "project"

    if accepts_model_choice(ide):
        explicit = model_overrides.get(ide) or model_default
        saved = _agent_saved_model(agent_detail, ide)
        if explicit:
            opts["model"] = explicit
        elif saved:
            try:
                primary, _secondary, _ = _format_model({"model_id": saved})
                pretty = primary or saved
            except Exception:
                pretty = saved
            rprint(f"  [dim]Model:[/dim] {pretty} [dim](from agent)[/dim]")
            # Pass through the saved value so the server records the same
            # choice on the install download record. The resolver still
            # validates the candidate against the live catalog and falls
            # back gracefully if needed.
            opts["model"] = saved
        elif interactive:
            from observal_cli import model_catalog as _catalog

            try:
                catalog = _catalog.fetch_catalog(refresh=refresh_models)
            except Exception:
                catalog = {"models": []}
            choices = _catalog.model_choices_for_picker(catalog, ide)
            choice_labels = [c[0] for c in choices] if choices else []
            choice_labels = ["auto (let the IDE decide)", *choice_labels]
            picked = select_one("  Model", choice_labels, default="auto (let the IDE decide)")
            if picked.startswith("auto"):
                opts["model"] = ""
            else:
                for label, model_id in choices:
                    if label == picked:
                        opts["model"] = model_id
                        break

    if ide in ("claude-code", "claude_code") and tools:
        opts["tools"] = tools

    return opts


def register_pull(app: typer.Typer):
    @app.command("pull")
    def pull(
        agent_id: str = typer.Argument(..., help="Agent ID, name, row number, or @alias"),
        ide: str = typer.Option(
            ...,
            "--ide",
            "-i",
            help="Target IDE (cursor, vscode, claude-code, gemini-cli, kiro, codex, copilot, opencode)",
        ),
        directory: str = typer.Option(".", "--dir", "-d", help="Target directory for written files"),
        dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Preview files without writing"),
        scope: str | None = typer.Option(
            None, "--scope", help="Install scope: 'project' or 'user' (Claude Code/Kiro/Gemini only)"
        ),
        model: list[str] | None = typer.Option(
            None,
            "--model",
            help=(
                "Model override. Accepts '<value>' (applies to the selected --ide) or "
                "'<ide>=<value>' for explicit per-IDE overrides. May be repeated."
            ),
        ),
        tools: str | None = typer.Option(None, "--tools", help="Comma-separated tool whitelist (Claude Code only)"),
        refresh_models: bool = typer.Option(
            False, "--refresh-models", help="Bust the local model catalog cache before showing the model picker"
        ),
        no_prompt: bool = typer.Option(False, "--no-prompt", "-y", help="Skip interactive prompts"),
    ):
        """Fetch agent config and write IDE files to disk.

        Calls the server to generate an install config for the specified IDE,
        then writes rules files, MCP configs, and agent files into the target
        directory.  Use --dry-run to preview without writing.
        """
        resolved = config.resolve_alias(agent_id)
        target_dir = Path(directory).resolve()

        # Fetch agent details to discover MCP env vars
        with spinner("Fetching agent details..."):
            agent_detail = client.get(f"/api/v1/agents/{resolved}")

        env_values = _collect_mcp_env_vars(agent_detail)

        rprint(f"\n[bold]Install options for [cyan]{ide}[/cyan]:[/bold]")
        if refresh_models:
            from observal_cli import model_catalog as _catalog

            _catalog.invalidate_cache()
        model_default, model_overrides = _parse_model_overrides(model or [])
        options = _collect_install_options(
            ide,
            scope=scope,
            model_default=model_default,
            model_overrides=model_overrides,
            tools=tools,
            no_prompt=no_prompt,
            refresh_models=refresh_models,
            agent_detail=agent_detail,
        )
        is_user_scope = options.get("scope") == "user"
        if is_user_scope:
            rprint("  [dim]Files will be written to your home directory (user scope).[/dim]")

        with spinner(f"Pulling {ide} config for agent {resolved[:8]}..."):
            result = client.post(
                f"/api/v1/agents/{resolved}/install",
                {"ide": ide, "env_values": env_values, "options": options, "platform": sys.platform},
            )

        snippet = result.get("config_snippet", {})
        if not snippet:
            rprint("[yellow]Server returned an empty config snippet.[/yellow]")
            raise typer.Exit(1)

        written: list[tuple[str, str]] = []  # (path, status)

        # ── rules_file ──────────────────────────────────────
        rules = snippet.get("rules_file")
        if rules:
            p = _resolve_path(rules["path"], target_dir, allow_home=is_user_scope)
            content = rules["content"]
            # Resolve hook script placeholders to absolute paths
            if isinstance(content, str):
                content = _resolve_hook_paths(content)
            if dry_run:
                written.append((str(p), "would write"))
            else:
                status = _write_file(p, content)
                written.append((str(p), status))

        # ── mcp_config with path key (Cursor/VSCode/Gemini) ─
        mcp_cfg = snippet.get("mcp_config")
        if mcp_cfg and isinstance(mcp_cfg, dict) and "path" in mcp_cfg:
            p = _resolve_path(mcp_cfg["path"], target_dir, allow_home=is_user_scope)
            if dry_run:
                written.append((str(p), "would write"))
            else:
                status = _write_file(p, mcp_cfg["content"], merge_mcp=True)
                written.append((str(p), status))

        # ── hooks_config (Cursor/VSCode/Copilot/OpenCode/Gemini) ─
        hooks_cfg = snippet.get("hooks_config")
        if hooks_cfg and isinstance(hooks_cfg, dict) and "path" in hooks_cfg:
            p = _resolve_path(hooks_cfg["path"], target_dir, allow_home=is_user_scope)
            content = hooks_cfg["content"]
            if isinstance(content, str):
                content = _resolve_hook_paths(content)
            elif isinstance(content, dict):
                # Resolve hook paths inside JSON content (command fields)
                raw = json.dumps(content)
                raw = _resolve_hook_paths(raw)
                content = json.loads(raw)
            if dry_run:
                written.append((str(p), "would write"))
            else:
                status = _write_file(p, content, merge_mcp=hooks_cfg.get("merge", False))
                written.append((str(p), status))

        # ── agent_file (Kiro) ───────────────────────────────
        agent_file = snippet.get("agent_file")
        if agent_file:
            # Rewrite hook commands to use the current Python interpreter
            # so they work regardless of which directory Kiro is launched from.
            if isinstance(agent_file.get("content"), dict):
                agent_file["content"] = _rewrite_kiro_hooks(agent_file["content"])
            p = _resolve_path(agent_file["path"], target_dir, allow_home=is_user_scope)
            if dry_run:
                written.append((str(p), "would write"))
            else:
                status = _write_file(p, agent_file["content"])
                written.append((str(p), status))

        # ── steering_file (Kiro) ───────────────────────────
        steering_file = snippet.get("steering_file")
        if steering_file:
            p = _resolve_path(steering_file["path"], target_dir, allow_home=is_user_scope)
            if dry_run:
                written.append((str(p), "would write"))
            else:
                status = _write_file(p, steering_file["content"])
                written.append((str(p), status))

        # ── skill_files (Claude Code, Kiro, Cursor) ──────────
        for sf in snippet.get("skill_files") or []:
            p = _resolve_path(sf["path"], target_dir, allow_home=is_user_scope)
            if dry_run:
                written.append((str(p), "would write"))
            else:
                status = _write_file(p, sf["content"])
                written.append((str(p), status))

        # ── Agent marker (all IDEs) ─────────────────────────
        # Write <target_dir>/.observal/agent so session_push hooks can attribute
        # telemetry to this agent without needing OBSERVAL_AGENT_ID in the shell.
        # Both Claude Code and Kiro pass cwd in their hook events, so one marker
        # file covers all JSONL-based IDEs.
        if not dry_run:
            agent_uuid = agent_detail.get("id", resolved)
            agent_version = agent_detail.get("version") or agent_detail.get("latest_version")
            marker_dir = target_dir / ".observal"
            marker_dir.mkdir(parents=True, exist_ok=True)
            import datetime as _dt
            (marker_dir / "agent").write_text(json.dumps({
                "agent_id": agent_uuid,
                "agent_version": agent_version,
                "pulled_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            }))

        # ── Output summary ──────────────────────────────────
        if not written:
            rprint("[yellow]No files to write from the config snippet.[/yellow]")
            raise typer.Exit(1)

        if dry_run:
            rprint("\n[bold yellow]Dry run[/bold yellow] — no files written:\n")
        else:
            rprint(
                f"\n[bold green]Pulled {ide} config[/bold green] ({len(written)} file{'s' if len(written) != 1 else ''}):\n"
            )

        for path, status in written:
            style = "dim" if dry_run else "green"
            rprint(f"  [{style}]{status}[/{style}]  {path}")

        warnings_list = snippet.get("_warnings") or []
        if warnings_list:
            rprint("")
            for w in warnings_list:
                rprint(f"  [yellow]⚠[/yellow]  {w}")

        # ── Setup commands (Claude Code) ────────────────────
        setup_cmds = snippet.get("mcp_setup_commands")
        if setup_cmds and not dry_run:
            rprint("\n[bold]Registering MCP servers...[/bold]")
            for cmd in setup_cmds:
                try:
                    proc = subprocess.run(cmd, capture_output=True, text=True)
                except FileNotFoundError:
                    rprint(f"  [yellow]⚠[/yellow]  {cmd[0]} not found — run manually: [cyan]{' '.join(cmd)}[/cyan]")
                    continue
                if proc.returncode == 0:
                    rprint(f"  [green]✓[/green]  {' '.join(cmd[:4])}...")
                else:
                    stderr = (proc.stderr or "").strip()
                    rprint(f"  [red]✗[/red]  {' '.join(cmd)}")
                    if stderr:
                        rprint(f"      [dim]{stderr}[/dim]")
        elif setup_cmds and dry_run:
            rprint("\n[bold]Would run these setup commands:[/bold]")
            for cmd in setup_cmds:
                rprint(f"  [cyan]$ {' '.join(cmd)}[/cyan]")

        # ── OTLP env vars (Observal telemetry — optional) ──
        otlp_env = snippet.get("otlp_env")
        if otlp_env:
            rprint("\n[bold dim]Observal telemetry (optional):[/bold dim]")
            rprint("[dim]These enable usage tracking via Observal — not required by the MCP server itself.[/dim]")
            for k, v in otlp_env.items():
                rprint(f"  [dim]{k}={v}[/dim]")
