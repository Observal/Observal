"""Hook registry CLI commands."""

from __future__ import annotations

import json as _json
import sys

import typer
from rich import print as rprint
from rich.table import Table

from observal_cli import client, config, settings_reconciler
from observal_cli.constants import VALID_HOOK_EVENTS, VALID_HOOK_HANDLER_TYPES
from observal_cli.hooks_spec import get_desired_env, get_desired_hooks
from observal_cli.prompts import select_one
from observal_cli.render import console, kv_panel, output_json, relative_time, spinner, status_badge

hook_app = typer.Typer(help="Hook registry commands")


def register_hook(app: typer.Typer):
    app.add_typer(hook_app, name="hook")


@hook_app.command(name="submit")
def hook_submit(
    from_file: str | None = typer.Option(None, "--from-file", "-f", help="Create from JSON file"),
):
    """Submit a new hook for review."""
    if from_file:
        with open(from_file) as f:
            payload = _json.load(f)
    else:
        payload = {
            "name": typer.prompt("Hook name"),
            "version": typer.prompt("Version", default="1.0.0"),
            "description": typer.prompt("Description"),
            "owner": typer.prompt("Owner"),
            "event": select_one("Event", VALID_HOOK_EVENTS),
            "handler_type": select_one("Handler type", VALID_HOOK_HANDLER_TYPES),
            "handler_config": _json.loads(typer.prompt("Handler config (JSON)")),
        }
    with spinner("Submitting hook..."):
        result = client.post("/api/v1/hooks", payload)
    rprint(f"[green]✓ Hook submitted![/green] ID: [bold]{result['id']}[/bold]")


@hook_app.command(name="list")
def hook_list(
    event: str | None = typer.Option(None, "--event", "-e"),
    scope: str | None = typer.Option(None, "--scope"),
    search: str | None = typer.Option(None, "--search", "-s"),
    output: str = typer.Option("table", "--output", "-o", help="Output: table, json, plain"),
):
    """List approved hooks."""
    params = {}
    if event:
        params["event"] = event
    if scope:
        params["scope"] = scope
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
            rprint(f"{item['id']}  {item['name']}  v{item.get('version', '?')}")
        return
    table = Table(title=f"Hooks ({len(data)})", show_lines=False, padding=(0, 1))
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
    console.print(
        kv_panel(
            f"{item['name']} v{item.get('version', '?')}",
            [
                ("Status", status_badge(item.get("status", ""))),
                ("Event", item.get("event", "N/A")),
                ("Handler Type", item.get("handler_type", "N/A")),
                ("Owner", item.get("owner", "N/A")),
                ("Description", item.get("description", "")),
                ("Created", relative_time(item.get("created_at"))),
                ("ID", f"[dim]{item['id']}[/dim]"),
            ],
            border_style="yellow",
        )
    )


@hook_app.command(name="install")
def hook_install(
    hook_id: str = typer.Argument(..., help="Hook ID, name, row number, or @alias"),
    ide: str = typer.Option(..., "--ide", "-i", help="Target IDE"),
    raw: bool = typer.Option(False, "--raw", help="Output raw JSON only"),
):
    """Get install config for a hook."""
    resolved = config.resolve_alias(hook_id)
    with spinner(f"Generating {ide} config..."):
        result = client.post(f"/api/v1/hooks/{resolved}/install", {"ide": ide, "platform": sys.platform})
    snippet = result.get("config_snippet", result)
    if raw:
        print(_json.dumps(snippet, indent=2))
        return
    rprint(f"\n[bold]Config for {ide}:[/bold]\n")
    console.print_json(_json.dumps(snippet, indent=2))


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


def _find_hook_script(name: str) -> str | None:
    """Locate hook script by name (same search logic as cmd_auth)."""
    from pathlib import Path

    candidates = [
        Path(__file__).resolve().parent / "hooks" / name,
        Path.home() / ".observal" / "hooks" / name,
    ]
    for p in candidates:
        if p.is_file():
            return str(p.resolve())
    return None


@hook_app.command(name="sync")
def hook_sync(
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Show changes without applying"),
):
    """Sync Claude Code hooks to the latest Observal spec.

    Non-destructively updates ~/.claude/settings.json: adds missing hooks,
    upgrades stale Observal hooks, and preserves any non-Observal hooks
    you've added.
    """
    cfg = config.load()

    server_url = cfg.get("server_url")
    access_token = cfg.get("access_token")
    if not server_url or not access_token:
        rprint("[red]Not authenticated. Run [bold]observal auth login[/bold] first.[/red]")
        raise typer.Exit(1)

    hooks_url = f"{server_url.rstrip('/')}/api/v1/otel/hooks"
    hook_script = _find_hook_script("observal-hook.sh")
    stop_script = _find_hook_script("observal-stop-hook.sh")
    user_id = cfg.get("user_id", "")

    desired_hooks = get_desired_hooks(hook_script, stop_script, hooks_url, user_id)
    desired_env = get_desired_env(server_url, access_token, user_id)

    applied = settings_reconciler.get_applied_version()
    from observal_cli.hooks_spec import HOOKS_SPEC_VERSION

    if dry_run:
        changes = settings_reconciler.reconcile(desired_hooks, desired_env, dry_run=True)
        if changes:
            rprint(f"[yellow]Dry run[/yellow] — spec v{applied} → v{HOOKS_SPEC_VERSION}:")
            for change in changes:
                rprint(f"  {change}")
        else:
            rprint(f"[dim]Already at spec v{HOOKS_SPEC_VERSION}, no changes needed.[/dim]")
        return

    changes = settings_reconciler.reconcile(desired_hooks, desired_env)

    if changes:
        rprint(f"[green]✓ Synced[/green] hooks spec v{applied} → v{HOOKS_SPEC_VERSION}:")
        for change in changes:
            rprint(f"  {change}")
    else:
        rprint(f"[dim]Already at spec v{HOOKS_SPEC_VERSION}, no changes needed.[/dim]")
