"""observal pull: fetch agent config from the server and write IDE files to disk."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import typer
from rich import print as rprint

from observal_cli import client, config
from observal_cli.render import spinner


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


def _write_file(path: Path, content: str | dict, *, merge_mcp: bool = False) -> str:
    """Write content to a file path, creating parent dirs as needed.

    If *merge_mcp* is True and the file already exists, merge the incoming
    ``mcpServers`` dict into the existing one rather than overwriting.

    Returns a human-readable status string ("created", "updated", "merged").
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()

    if isinstance(content, dict):
        if merge_mcp and existed and isinstance(content, dict):
            try:
                existing = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                existing = {}
            incoming_servers = content.get("mcpServers", {})
            existing.setdefault("mcpServers", {}).update(incoming_servers)
            path.write_text(json.dumps(existing, indent=2) + "\n")
            return "merged"
        path.write_text(json.dumps(content, indent=2) + "\n")
    else:
        path.write_text(content)

    return "updated" if existed else "created"


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


# IDEs that support a project vs user install scope
_SCOPE_AWARE_IDES = {
    "claude-code": ("project (.claude/agents/)", "user (~/.claude/agents/)"),
    "kiro": ("project (.kiro/agents/)", "user (~/.kiro/agents/)"),
    "gemini-cli": ("project (GEMINI.md)", "user (~/.gemini/GEMINI.md)"),
    "cursor": ("project (.cursor/rules/)", "user (~/.cursor/rules/)"),
}


def _collect_install_options(
    ide: str,
    *,
    scope: str | None,
    model: str | None,
    tools: str | None,
    no_prompt: bool,
) -> dict:
    """Interactively collect IDE-specific install options.

    Honors explicit --scope/--model/--tools flags; only prompts for what's
    missing when running in an interactive terminal and --no-prompt isn't set.
    """
    import sys

    from observal_cli.prompts import select_one

    opts: dict = {}
    interactive = sys.stdin.isatty() and not no_prompt

    # Scope (Claude Code, Kiro, Gemini CLI, Cursor)
    if ide in _SCOPE_AWARE_IDES:
        if scope:
            opts["scope"] = scope
        elif interactive:
            project_label, user_label = _SCOPE_AWARE_IDES[ide]
            choice = select_one("  Scope", [project_label, user_label], default=project_label)
            opts["scope"] = "user" if choice.startswith("user") else "project"
        else:
            opts["scope"] = "project"

    # Claude Code only: model and tools
    if ide in ("claude-code", "claude_code"):
        if model:
            opts["model"] = model
        elif interactive:
            choice = select_one(
                "  Model",
                ["inherit (use main session model)", "sonnet", "opus", "haiku"],
                default="inherit (use main session model)",
            )
            opts["model"] = "inherit" if choice.startswith("inherit") else choice

        if tools:
            opts["tools"] = tools

    return opts


def register_pull(app: typer.Typer):
    @app.command("pull")
    def pull(
        agent_id: str = typer.Argument(..., help="Agent ID, name, row number, or @alias"),
        ide: str = typer.Option(
            ..., "--ide", "-i", help="Target IDE (cursor, vscode, claude-code, gemini-cli, kiro, codex, copilot)"
        ),
        directory: str = typer.Option(".", "--dir", "-d", help="Target directory for written files"),
        dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Preview files without writing"),
        scope: str | None = typer.Option(
            None, "--scope", help="Install scope: 'project' or 'user' (Claude Code/Kiro/Gemini only)"
        ),
        model: str | None = typer.Option(
            None, "--model", help="Sub-agent model: inherit, sonnet, opus, haiku (Claude Code only)"
        ),
        tools: str | None = typer.Option(None, "--tools", help="Comma-separated tool whitelist (Claude Code only)"),
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

        # Collect IDE-specific install options (scope, model, tools)
        rprint(f"\n[bold]Install options for [cyan]{ide}[/cyan]:[/bold]")
        options = _collect_install_options(ide, scope=scope, model=model, tools=tools, no_prompt=no_prompt)
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
            if dry_run:
                written.append((str(p), "would write"))
            else:
                status = _write_file(p, rules["content"])
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

        # ── agent_file (Kiro) ───────────────────────────────
        agent_file = snippet.get("agent_file")
        if agent_file:
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
