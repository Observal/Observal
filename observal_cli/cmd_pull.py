"""observal pull: fetch agent config from the server and write IDE files to disk."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich import print as rprint

from observal_cli import client, config
from observal_cli.render import console, spinner


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


def _resolve_path(raw_path: str, target_dir: Path) -> Path:
    """Resolve a path from the config snippet relative to *target_dir*.

    Handles ``~/`` prefixes by mapping them under *target_dir* (not the real
    home directory) so that the pull command always writes inside the project.
    Raises typer.Exit if the resolved path escapes *target_dir*.
    """
    if raw_path.startswith("~/") or raw_path.startswith("~\\"):
        resolved = (target_dir / raw_path[2:]).resolve()
    else:
        resolved = (target_dir / raw_path).resolve()

    if not resolved.is_relative_to(target_dir):
        rprint(f"[red]Error:[/red] path '{raw_path}' escapes target directory")
        raise typer.Exit(1)

    return resolved


def register_pull(app: typer.Typer):

    @app.command("pull")
    def pull(
        agent_id: str = typer.Argument(..., help="Agent ID, name, row number, or @alias"),
        ide: str = typer.Option(..., "--ide", "-i", help="Target IDE (cursor, vscode, claude-code, gemini-cli, kiro, codex, copilot)"),
        directory: str = typer.Option(".", "--dir", "-d", help="Target directory for written files"),
        dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Preview files without writing"),
    ):
        """Fetch agent config and write IDE files to disk.

        Calls the server to generate an install config for the specified IDE,
        then writes rules files, MCP configs, and agent files into the target
        directory.  Use --dry-run to preview without writing.
        """
        resolved = config.resolve_alias(agent_id)
        target_dir = Path(directory).resolve()

        with spinner(f"Pulling {ide} config for agent {resolved[:8]}..."):
            result = client.post(f"/api/v1/agents/{resolved}/install", {"ide": ide})

        snippet = result.get("config_snippet", {})
        if not snippet:
            rprint("[yellow]Server returned an empty config snippet.[/yellow]")
            raise typer.Exit(1)

        written: list[tuple[str, str]] = []  # (path, status)

        # ── rules_file ──────────────────────────────────────
        rules = snippet.get("rules_file")
        if rules:
            p = _resolve_path(rules["path"], target_dir)
            if dry_run:
                written.append((str(p), "would write"))
            else:
                status = _write_file(p, rules["content"])
                written.append((str(p), status))

        # ── mcp_config with path key (Cursor/VSCode/Gemini) ─
        mcp_cfg = snippet.get("mcp_config")
        if mcp_cfg and isinstance(mcp_cfg, dict) and "path" in mcp_cfg:
            p = _resolve_path(mcp_cfg["path"], target_dir)
            if dry_run:
                written.append((str(p), "would write"))
            else:
                status = _write_file(p, mcp_cfg["content"], merge_mcp=True)
                written.append((str(p), status))

        # ── agent_file (Kiro) ───────────────────────────────
        agent_file = snippet.get("agent_file")
        if agent_file:
            p = _resolve_path(agent_file["path"], target_dir)
            if dry_run:
                written.append((str(p), "would write"))
            else:
                status = _write_file(p, agent_file["content"])
                written.append((str(p), status))

        # ── Output summary ──────────────────────────────────
        if not written:
            rprint("[yellow]No files to write from the config snippet.[/yellow]")
            raise typer.Exit(1)

        if dry_run:
            rprint("\n[bold yellow]Dry run[/bold yellow] — no files written:\n")
        else:
            rprint(f"\n[bold green]Pulled {ide} config[/bold green] ({len(written)} file{'s' if len(written) != 1 else ''}):\n")

        for path, status in written:
            style = "dim" if dry_run else "green"
            rprint(f"  [{style}]{status}[/{style}]  {path}")

        # ── Setup commands (Claude Code) ────────────────────
        setup_cmds = snippet.get("mcp_setup_commands")
        if setup_cmds:
            rprint("\n[bold]Run these commands to finish setup:[/bold]")
            for cmd in setup_cmds:
                rprint(f"  [cyan]$ {' '.join(cmd)}[/cyan]")

        # ── OTLP env vars (Claude Code) ─────────────────────
        otlp_env = snippet.get("otlp_env")
        if otlp_env:
            rprint("\n[bold]Set these environment variables:[/bold]")
            for k, v in otlp_env.items():
                rprint(f"  [cyan]{k}[/cyan]={v}")
