"""Sandbox registry CLI commands."""

from __future__ import annotations

import json as _json

import typer
from rich import print as rprint
from rich.table import Table

from observal_cli import client, config
from observal_cli.render import console, kv_panel, output_json, relative_time, spinner, status_badge

sandbox_app = typer.Typer(help="Sandbox registry commands")


def register_sandbox(app: typer.Typer):
    app.add_typer(sandbox_app, name="sandbox")


@sandbox_app.command(name="submit")
def sandbox_submit(
    from_file: str | None = typer.Option(None, "--from-file", "-f", help="Create from JSON file"),
):
    """Submit a new sandbox for review."""
    if from_file:
        with open(from_file) as f:
            payload = _json.load(f)
    else:
        payload = {
            "name": typer.prompt("Sandbox name"),
            "version": typer.prompt("Version", default="1.0.0"),
            "description": typer.prompt("Description"),
            "owner": typer.prompt("Owner"),
            "runtime_type": typer.prompt("Runtime type (docker/lxc)"),
            "image": typer.prompt("Image"),
            "resource_limits": _json.loads(typer.prompt("Resource limits (JSON)")),
        }
    with spinner("Submitting sandbox..."):
        result = client.post("/api/v1/sandboxes", payload)
    rprint(f"[green]✓ Sandbox submitted![/green] ID: [bold]{result['id']}[/bold]")


@sandbox_app.command(name="list")
def sandbox_list(
    runtime: str | None = typer.Option(None, "--runtime", "-r"),
    search: str | None = typer.Option(None, "--search", "-s"),
    output: str = typer.Option("table", "--output", "-o", help="Output: table, json, plain"),
):
    """List approved sandboxes."""
    params = {}
    if runtime:
        params["runtime"] = runtime
    if search:
        params["search"] = search
    with spinner("Fetching sandboxes..."):
        data = client.get("/api/v1/sandboxes", params=params)
    if not data:
        rprint("[dim]No sandboxes found.[/dim]")
        return
    config.save_last_results(data)
    if output == "json":
        output_json(data)
        return
    if output == "plain":
        for item in data:
            rprint(f"{item['id']}  {item['name']}  v{item.get('version', '?')}")
        return
    table = Table(title=f"Sandboxes ({len(data)})", show_lines=False, padding=(0, 1))
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


@sandbox_app.command(name="show")
def sandbox_show(
    sandbox_id: str = typer.Argument(..., help="ID, name, row number, or @alias"),
    output: str = typer.Option("table", "--output", "-o"),
):
    """Show sandbox details."""
    resolved = config.resolve_alias(sandbox_id)
    with spinner():
        item = client.get(f"/api/v1/sandboxes/{resolved}")
    if output == "json":
        output_json(item)
        return
    console.print(
        kv_panel(
            f"{item['name']} v{item.get('version', '?')}",
            [
                ("Status", status_badge(item.get("status", ""))),
                ("Runtime", item.get("runtime_type", "N/A")),
                ("Image", item.get("image", "N/A")),
                ("Owner", item.get("owner", "N/A")),
                ("Description", item.get("description", "")),
                ("Created", relative_time(item.get("created_at"))),
                ("ID", f"[dim]{item['id']}[/dim]"),
            ],
            border_style="red",
        )
    )


@sandbox_app.command(name="install")
def sandbox_install(
    sandbox_id: str = typer.Argument(..., help="Sandbox ID, name, row number, or @alias"),
    ide: str = typer.Option(..., "--ide", "-i", help="Target IDE"),
    raw: bool = typer.Option(False, "--raw", help="Output raw JSON only"),
):
    """Get install config for a sandbox."""
    resolved = config.resolve_alias(sandbox_id)
    with spinner(f"Generating {ide} config..."):
        result = client.post(f"/api/v1/sandboxes/{resolved}/install", {"ide": ide})
    snippet = result.get("config_snippet", result)
    if raw:
        print(_json.dumps(snippet, indent=2))
        return
    rprint(f"\n[bold]Config for {ide}:[/bold]\n")
    console.print_json(_json.dumps(snippet, indent=2))


@sandbox_app.command(name="delete")
def sandbox_delete(
    sandbox_id: str = typer.Argument(..., help="ID, name, row number, or @alias"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Delete a sandbox."""
    resolved = config.resolve_alias(sandbox_id)
    if not yes:
        with spinner():
            item = client.get(f"/api/v1/sandboxes/{resolved}")
        if not typer.confirm(f"Delete [bold]{item['name']}[/bold] ({resolved})?"):
            raise typer.Abort()
    with spinner("Deleting..."):
        client.delete(f"/api/v1/sandboxes/{resolved}")
    rprint(f"[green]✓ Deleted {resolved}[/green]")
