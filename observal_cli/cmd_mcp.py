"""MCP server CLI commands."""

from __future__ import annotations

import typer
from rich import print as rprint
from rich.table import Table

from observal_cli import client, config
from observal_cli.render import (
    console,
    ide_tags,
    kv_panel,
    output_json,
    relative_time,
    spinner,
    status_badge,
)

_DEPRECATION_TPL = (
    "[yellow]Warning:[/yellow] [dim]`observal {old}` is deprecated. Use `observal {new}` instead.[/dim]\n"
)

mcp_app = typer.Typer(help="MCP server registry commands")


# ── Implementation functions (shared by canonical + deprecated) ──


def _submit_impl(git_url, name, category, yes):
    with spinner("Analyzing repository..."):
        try:
            prefill = client.post("/api/v1/mcps/analyze", {"git_url": git_url})
        except (Exception, SystemExit):
            rprint("[yellow]Could not analyze repo: fill in details manually.[/yellow]")
            prefill = {}

    if prefill.get("tools"):
        rprint(f"\n[bold]Detected {len(prefill['tools'])} tools:[/bold]")
        for t in prefill["tools"][:10]:
            rprint(f"  [cyan]•[/cyan] {t.get('name', '?')}: {t.get('description', '')[:60]}")
        if len(prefill["tools"]) > 10:
            rprint(f"  [dim]...and {len(prefill['tools']) - 10} more[/dim]")
        rprint()

    _name = name or (prefill.get("name", "") if yes else typer.prompt("Name", default=prefill.get("name", "")))
    _version = (
        prefill.get("version", "0.1.0") if yes else typer.prompt("Version", default=prefill.get("version", "0.1.0"))
    )
    _category = category or ("general" if yes else typer.prompt("Category"))
    _desc = (
        prefill.get("description", "") if yes else typer.prompt("Description", default=prefill.get("description", ""))
    )
    _owner = typer.prompt("Owner / Team") if not yes else "default"

    ide_choices = ["vscode", "cursor", "kiro", "claude_code", "gemini_cli"]
    if not yes:
        rprint(f"[dim]IDEs: {', '.join(ide_choices)}[/dim]")
        ides_input = typer.prompt("Supported IDEs (comma-separated)", default=",".join(ide_choices))
    else:
        ides_input = ",".join(ide_choices)
    supported_ides = [i.strip() for i in ides_input.split(",") if i.strip()]

    _setup = "" if yes else typer.prompt("Setup instructions", default="")
    _changelog = "Initial release" if yes else typer.prompt("Changelog", default="Initial release")

    with spinner("Submitting..."):
        result = client.post(
            "/api/v1/mcps/submit",
            {
                "git_url": git_url,
                "name": _name,
                "version": _version,
                "category": _category,
                "description": _desc,
                "owner": _owner,
                "supported_ides": supported_ides,
                "setup_instructions": _setup,
                "changelog": _changelog,
            },
        )
    rprint(f"\n[green]✓ Submitted![/green] ID: [bold]{result['id']}[/bold]")
    rprint(f"  Status: {status_badge(result.get('status', 'pending'))}")


def _list_impl(category, search, limit, sort, output):
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
    with spinner(f"Generating {ide} config..."):
        result = client.post(f"/api/v1/mcps/{resolved}/install", {"ide": ide})

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
    git_url: str = typer.Argument(..., help="Git repository URL"),
    name: str = typer.Option(None, "--name", "-n", help="Skip name prompt"),
    category: str = typer.Option(None, "--category", "-c", help="Skip category prompt"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Accept defaults from repo analysis"),
):
    """Submit an MCP server for review."""
    _submit_impl(git_url, name, category, yes)


@mcp_app.command(name="list")
def list_mcps(
    category: str | None = typer.Option(None, "--category", "-c", help="Filter by category"),
    search: str | None = typer.Option(None, "--search", "-s", help="Search by name/description"),
    limit: int = typer.Option(50, "--limit", "-n", help="Max results"),
    sort: str = typer.Option("name", "--sort", help="Sort by: name, category, version"),
    output: str = typer.Option("table", "--output", "-o", help="Output: table, json, plain"),
):
    """List approved MCP servers."""
    _list_impl(category, search, limit, sort, output)


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


# ── Deprecated root-level aliases ────────────────────────────


def register_deprecated_mcp(app: typer.Typer):
    """Register deprecated bare root-level MCP commands (submit, list, show, install, delete)."""

    @app.command(name="submit", hidden=True)
    def deprecated_submit(
        git_url: str = typer.Argument(..., help="Git repository URL"),
        name: str = typer.Option(None, "--name", "-n", help="Skip name prompt"),
        category: str = typer.Option(None, "--category", "-c", help="Skip category prompt"),
        yes: bool = typer.Option(False, "--yes", "-y", help="Accept defaults from repo analysis"),
    ):
        """(Deprecated) Use `observal registry mcp submit` instead."""
        rprint(_DEPRECATION_TPL.format(old="submit", new="registry mcp submit"))
        _submit_impl(git_url, name, category, yes)

    @app.command(name="list", hidden=True)
    def deprecated_list(
        category: str | None = typer.Option(None, "--category", "-c", help="Filter by category"),
        search: str | None = typer.Option(None, "--search", "-s", help="Search by name/description"),
        limit: int = typer.Option(50, "--limit", "-n", help="Max results"),
        sort: str = typer.Option("name", "--sort", help="Sort by: name, category, version"),
        output: str = typer.Option("table", "--output", "-o", help="Output: table, json, plain"),
    ):
        """(Deprecated) Use `observal registry mcp list` instead."""
        rprint(_DEPRECATION_TPL.format(old="list", new="registry mcp list"))
        _list_impl(category, search, limit, sort, output)

    @app.command(name="show", hidden=True)
    def deprecated_show(
        mcp_id: str = typer.Argument(..., help="ID, name, row number, or @alias"),
        output: str = typer.Option("table", "--output", "-o", help="Output: table, json"),
    ):
        """(Deprecated) Use `observal registry mcp show` instead."""
        rprint(_DEPRECATION_TPL.format(old="show", new="registry mcp show"))
        _show_impl(mcp_id, output)

    @app.command(name="install", hidden=True)
    def deprecated_install(
        mcp_id: str = typer.Argument(..., help="ID, name, row number, or @alias"),
        ide: str = typer.Option(..., "--ide", "-i", help="Target IDE"),
        raw: bool = typer.Option(False, "--raw", help="Output raw JSON only (for piping)"),
    ):
        """(Deprecated) Use `observal registry mcp install` instead."""
        rprint(_DEPRECATION_TPL.format(old="install", new="registry mcp install"))
        _install_impl(mcp_id, ide, raw)

    @app.command(name="delete", hidden=True)
    def deprecated_delete(
        mcp_id: str = typer.Argument(..., help="ID, name, row number, or @alias"),
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    ):
        """(Deprecated) Use `observal registry mcp delete` instead."""
        rprint(_DEPRECATION_TPL.format(old="delete", new="registry mcp delete"))
        _delete_impl(mcp_id, yes)
