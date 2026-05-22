# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Hook registry CLI commands."""

from __future__ import annotations

import json as _json
import os
from pathlib import Path

import typer
from rich import print as rprint
from rich.table import Table

from observal_cli import client, config
from observal_cli.constants import VALID_HOOK_EVENTS, VALID_HOOK_EXECUTION_MODES, VALID_HOOK_HANDLER_TYPES
from observal_cli.prompts import select_one
from observal_cli.render import console, kv_panel, output_json, relative_time, spinner, status_badge

hook_app = typer.Typer(help="Hook registry commands")


def register_hook(app: typer.Typer):
    app.add_typer(hook_app, name="hook")


# ── Timeout caps (client-side fail-fast) ──────────────────────────────────

HOOK_TIMEOUT_CAPS: dict[str, int] = {
    "blocking": 30,
    "sync": 10,
    "async": 60,
}


def _validate_timeout(execution_mode: str, handler_config: dict) -> None:
    """Fail-fast timeout validation before sending to server."""
    timeout = handler_config.get("timeout")
    if timeout is None:
        return
    cap = HOOK_TIMEOUT_CAPS.get(execution_mode)
    if cap and int(timeout) > cap:
        rprint(
            f"[red]Timeout {timeout}s exceeds maximum {cap}s for {execution_mode} hooks.[/red]\n"
            f"Either reduce the timeout or change execution_mode (async max: 60s)."
        )
        raise typer.Exit(code=1)


@hook_app.command(name="submit")
def hook_submit(
    from_file: str | None = typer.Option(None, "--from-file", "-f", help="Create from JSON file"),
    draft: bool = typer.Option(False, "--draft", help="Save as draft instead of submitting for review"),
    submit_draft: str | None = typer.Option(None, "--submit", help="Submit a draft for review (hook ID)"),
    script: str | None = typer.Option(None, "--script", help="Path to hook script file (content stored in registry)"),
    source_url: str | None = typer.Option(None, "--source-url", help="Git repo containing hook scripts"),
    source_ref: str | None = typer.Option(None, "--source-ref", help="Branch/tag to track (default: main)"),
    source_path: str | None = typer.Option(None, "--source-path", help="Directory within repo containing hook files"),
    requires: list[str] | None = typer.Option(None, "--requires", help="Install prerequisites (repeatable)"),
):
    """Submit a new hook for review.

    Only submit hooks you created or are the point-of-contact for.

    Examples:
      observal registry hook submit
      observal registry hook submit --script ./protect-files.sh
      observal registry hook submit --source-url https://github.com/org/hooks --source-path hooks/guard/
      observal registry hook submit --from-file hook.json
    """
    rprint("[dim]Note: Only submit components you created (private) or are the point-of-contact for (external).[/dim]")
    if draft and submit_draft:
        rprint(
            "[red]Cannot use --draft and --submit together.[/red] "
            "Use --draft to save a new draft, or --submit to submit an existing draft."
        )
        raise typer.Exit(code=1)
    if submit_draft:
        resolved = config.resolve_alias(submit_draft)
        with spinner("Submitting draft for review..."):
            result = client.post(f"/api/v1/hooks/{resolved}/submit")
        rprint(f"[green]✓ Draft submitted for review![/green] ID: [bold]{result['id']}[/bold]")
        return

    if from_file:
        try:
            with open(from_file) as f:
                payload = _json.load(f)
        except _json.JSONDecodeError as e:
            rprint(f"[red]Invalid JSON in {from_file}:[/red] {e}")
            raise typer.Exit(code=1)
        except FileNotFoundError:
            rprint(f"[red]File not found:[/red] {from_file}")
            raise typer.Exit(code=1)
    else:
        # Read script content if --script provided
        script_content: str | None = None
        script_filename: str | None = None
        if script:
            script_path = Path(script)
            if not script_path.exists():
                rprint(f"[red]Script file not found:[/red] {script}")
                raise typer.Exit(code=1)
            script_content = script_path.read_text()
            script_filename = script_path.name

        # Prompt for essential fields
        name = typer.prompt("Hook name")
        version = typer.prompt("Version", default="1.0.0")
        description = typer.prompt("Description")
        owner = typer.prompt("Owner", default=config.load().get("user_name", ""))
        event = select_one("Event", VALID_HOOK_EVENTS)
        handler_type = select_one("Handler type", VALID_HOOK_HANDLER_TYPES)

        # Build handler_config
        if script_filename and handler_type == "command":
            # Auto-populate command from script filename
            timeout = int(typer.prompt("Timeout (seconds)", default="10"))
            handler_config = {"command": script_filename, "timeout": timeout}
            rprint(f"[dim]Command auto-set to '{script_filename}' from --script[/dim]")
        elif handler_type == "command":
            command = typer.prompt("Command")
            timeout = int(typer.prompt("Timeout (seconds)", default="10"))
            handler_config = {"command": command, "timeout": timeout}
        else:
            # HTTP handler
            url = typer.prompt("Hook URL")
            timeout = int(typer.prompt("Timeout (seconds)", default="10"))
            handler_config = {"url": url, "timeout": timeout}

        execution_mode = select_one("Execution mode", VALID_HOOK_EXECUTION_MODES)

        # Validate timeout before sending
        _validate_timeout(execution_mode, handler_config)

        payload: dict = {
            "name": name,
            "version": version,
            "description": description,
            "owner": owner,
            "event": event,
            "handler_type": handler_type,
            "handler_config": handler_config,
            "execution_mode": execution_mode,
        }

        # Add optional script/source fields
        if script_content:
            payload["script_content"] = script_content
            payload["script_filename"] = script_filename
        if source_url:
            payload["source_url"] = source_url
            payload["source_ref"] = source_ref or "main"
        if source_path:
            payload["source_path"] = source_path
        if requires:
            payload["requirements"] = requires

    if draft:
        with spinner("Saving draft..."):
            result = client.post("/api/v1/hooks/draft", payload)
        rprint(f"[green]✓ Draft saved![/green] ID: [bold]{result['id']}[/bold]")
    else:
        with spinner("Submitting hook..."):
            result = client.post("/api/v1/hooks/submit", payload)
        rprint(f"[green]✓ Hook submitted![/green] ID: [bold]{result['id']}[/bold]")


@hook_app.command(name="list")
def hook_list(
    event: str | None = typer.Option(None, "--event", "-e", help="Filter by event type"),
    search: str | None = typer.Option(None, "--search", "-s"),
    output: str = typer.Option("table", "--output", "-o", help="Output: table, json, plain"),
):
    """List approved hooks."""
    params = {}
    if event:
        params["event"] = event
    if search:
        params["search"] = search
    with spinner("Fetching hooks..."):
        data = client.get("/api/v1/hooks", params=params)
    if not data:
        rprint("[dim]No hooks found.[/dim]")
        return
    config.save_last_results(data)
    if output == "json":
        output_json(data)
        return
    if output == "plain":
        for item in data:
            rprint(f"{item['id']}  {item['name']}  {item.get('event', '?')}")
        return
    table = Table(title=f"Hooks ({len(data)})", show_lines=False, padding=(0, 1))
    table.add_column("#", style="dim", width=3)
    table.add_column("Name", style="bold cyan", no_wrap=True)
    table.add_column("Event", style="magenta")
    table.add_column("Mode", style="green")
    table.add_column("Owner", style="dim")
    table.add_column("Status")
    table.add_column("ID", style="dim", max_width=12)
    for i, item in enumerate(data, 1):
        table.add_row(
            str(i),
            item["name"],
            item.get("event", ""),
            item.get("execution_mode", ""),
            item.get("owner", ""),
            status_badge(item.get("status", "")),
            str(item["id"])[:8] + "…",
        )
    console.print(table)


@hook_app.command(name="show")
def hook_show(
    hook_id: str = typer.Argument(..., help="ID, name, row number, or @alias"),
    output: str = typer.Option("table", "--output", "-o"),
):
    """Show hook details."""
    resolved = config.resolve_alias(hook_id)
    with spinner():
        item = client.get(f"/api/v1/hooks/{resolved}")
    if output == "json":
        output_json(item)
        return
    rows = [
        ("Status", status_badge(item.get("status", ""))),
        ("Event", item.get("event", "N/A")),
        ("Handler Type", item.get("handler_type", "N/A")),
        ("Handler Config", _json.dumps(item.get("handler_config", {}), indent=2)),
        ("Execution Mode", item.get("execution_mode", "N/A")),
        ("Scope", item.get("scope", "N/A")),
        ("Owner", item.get("owner", "N/A")),
        ("Description", item.get("description", "")),
        ("Created", relative_time(item.get("created_at"))),
        ("ID", f"[dim]{item['id']}[/dim]"),
    ]
    if item.get("script_filename"):
        rows.insert(5, ("Script", item["script_filename"]))
    if item.get("source_url"):
        rows.insert(5, ("Source", f"{item['source_url']}@{item.get('source_ref', 'main')}"))
    if item.get("requirements"):
        rows.insert(5, ("Requires", ", ".join(item["requirements"])))
    console.print(
        kv_panel(
            f"{item['name']} v{item.get('version', '?')}",
            rows,
            border_style="magenta",
        )
    )


@hook_app.command(name="install")
def hook_install(
    hook_id: str = typer.Argument(..., help="Hook ID, name, row number, or @alias"),
    ide: str = typer.Option(..., "--ide", "-i", help="Target IDE"),
    platform: str = typer.Option("", "--platform", "-p", help="Platform (win32, darwin, linux)"),
    raw: bool = typer.Option(False, "--raw", help="Output raw JSON only (no file writes)"),
    directory: str | None = typer.Option(None, "--dir", "-d", help="Project directory for file writes"),
):
    """Install a hook for a specific IDE.

    Writes script files and merges hook config into the IDE's settings.
    Use --raw to just output JSON without writing anything.
    """
    resolved = config.resolve_alias(hook_id)
    with spinner(f"Generating {ide} config..."):
        result = client.post(f"/api/v1/hooks/{resolved}/install", {"ide": ide, "platform": platform})

    config_snippet = result.get("config_snippet", {})
    files = result.get("files", [])
    requirements = result.get("requirements", [])
    notes = result.get("notes", [])
    config_path = result.get("config_path", "")

    if raw:
        print(_json.dumps(result, indent=2))
        return

    project_dir = Path(directory) if directory else Path.cwd()

    # Write script files to disk
    if files:
        for file_entry in files:
            file_path = (project_dir / file_entry["path"]).resolve()
            # Guard against path traversal
            if not file_path.is_relative_to(project_dir.resolve()):
                rprint(f"  [red]✗[/red] Skipped {file_entry['path']} (path traversal blocked)")
                continue
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(file_entry["content"])
            if file_entry.get("executable"):
                os.chmod(file_path, 0o755)
            rprint(f"  [green]✓[/green] Wrote {file_entry['path']}")

    # Write/merge config into the IDE's hooks config file
    if config_path and config_snippet:
        if config_path.startswith("~/"):
            cfg_file = Path(config_path).expanduser()
        else:
            cfg_file = project_dir / config_path
        cfg_file.parent.mkdir(parents=True, exist_ok=True)

        if cfg_file.exists():
            try:
                existing = _json.loads(cfg_file.read_text())
            except (_json.JSONDecodeError, OSError):
                existing = {}
            # Merge hooks: append to existing event arrays
            incoming_hooks = config_snippet.get("hooks", {})
            existing_hooks = existing.setdefault("hooks", {})
            for event, entries in incoming_hooks.items():
                existing_hooks.setdefault(event, []).extend(entries)
            if "version" in config_snippet:
                existing["version"] = config_snippet["version"]
            cfg_file.write_text(_json.dumps(existing, indent=2) + "\n")
            rprint(f"  [green]✓[/green] Merged hook into {config_path}")
        else:
            cfg_file.write_text(_json.dumps(config_snippet, indent=2) + "\n")
            rprint(f"  [green]✓[/green] Created {config_path}")

    # Print requirements warning
    if requirements:
        rprint("\n[yellow]⚠ Prerequisites required:[/yellow]")
        for req in requirements:
            rprint(f"  [dim]$[/dim] {req}")

    # Print notes
    for note in notes:
        rprint(f"[dim]ℹ {note}[/dim]")

    rprint(f"\n[green]✓ Hook installed for {ide}![/green]")


@hook_app.command(name="edit")
def hook_edit(
    hook_id: str = typer.Argument(..., help="ID, name, row number, or @alias"),
    from_file: str | None = typer.Option(None, "--from-file", "-f", help="Load updates from JSON file"),
    name: str | None = typer.Option(None, "--name", "-n", help="New listing name"),
    description: str | None = typer.Option(None, "--description", "-d", help="New description"),
    version: str | None = typer.Option(None, "--version", "-v", help="New version string"),
    event: str | None = typer.Option(None, "--event", "-e", help="New event type"),
):
    """Edit a draft, rejected, or pending hook submission."""
    resolved = config.resolve_alias(hook_id)
    if from_file:
        try:
            with open(from_file) as f:
                updates = _json.load(f)
        except _json.JSONDecodeError as e:
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
        if version is not None:
            updates["version"] = version
        if event is not None:
            updates["event"] = event

    if not updates:
        rprint("[yellow]No changes specified.[/yellow] Use --from-file or field options (--name, --description, etc.)")
        raise typer.Exit(code=1)

    try:
        client.post(f"/api/v1/hooks/{resolved}/start-edit")
    except Exception as exc:
        if "409" in str(exc) or "currently being edited" in str(exc):
            rprint(f"[red]✗ Cannot edit:[/red] {exc}")
            raise typer.Exit(code=1)
    try:
        with spinner("Saving changes..."):
            result = client.put(f"/api/v1/hooks/{resolved}/draft", updates)
        rprint(f"[green]✓ Updated {result['name']}[/green] (status: {result.get('status', 'unknown')})")
    except Exception as exc:
        try:
            client.post(f"/api/v1/hooks/{resolved}/cancel-edit")
        except Exception:
            pass
        rprint(f"[red]Failed to update:[/red] {exc}")
        raise typer.Exit(code=1)


@hook_app.command(name="delete")
def hook_delete(
    hook_id: str = typer.Argument(..., help="ID, name, row number, or @alias"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Delete a hook."""
    resolved = config.resolve_alias(hook_id)
    if not yes:
        with spinner():
            item = client.get(f"/api/v1/hooks/{resolved}")
        if not typer.confirm(f"Delete [bold]{item['name']}[/bold] ({resolved})?"):
            raise typer.Abort()
    with spinner("Deleting..."):
        client.delete(f"/api/v1/hooks/{resolved}")
    rprint(f"[green]✓ Deleted {resolved}[/green]")
