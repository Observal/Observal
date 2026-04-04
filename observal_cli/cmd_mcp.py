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


def register_mcp(app: typer.Typer):

    @app.command()
    def submit(
        git_url: str = typer.Argument(..., help="Git repository URL"),
        name: str = typer.Option(None, "--name", "-n", help="Skip name prompt"),
        category: str = typer.Option(None, "--category", "-c", help="Skip category prompt"),
        yes: bool = typer.Option(False, "--yes", "-y", help="Accept defaults from repo analysis"),
    ):
        """Submit an MCP server for review."""
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
            prefill.get("description", "")
            if yes
            else typer.prompt("Description (min 100 chars)", default=prefill.get("description", ""))
        )
        _owner = typer.prompt("Owner / Team") if not yes else "default"

        ide_choices = ["vscode", "cursor", "windsurf", "kiro", "claude_code", "gemini_cli"]
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

    @app.command(name="list")
    def list_mcps(
        category: str | None = typer.Option(None, "--category", "-c", help="Filter by category"),
        search: str | None = typer.Option(None, "--search", "-s", help="Search by name/description"),
        limit: int = typer.Option(50, "--limit", "-n", help="Max results"),
        sort: str = typer.Option("name", "--sort", help="Sort by: name, category, version"),
        output: str = typer.Option("table", "--output", "-o", help="Output: table, json, plain"),
    ):
        """List approved MCP servers."""
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

        # Cache IDs for numeric shorthand (observal show 1, observal install 2 --ide kiro)
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

    @app.command()
    def show(
        mcp_id: str = typer.Argument(..., help="ID, name, row number, or @alias"),
        output: str = typer.Option("table", "--output", "-o", help="Output: table, json"),
    ):
        """Show full details of an MCP server."""
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

    @app.command()
    def install(
        mcp_id: str = typer.Argument(..., help="ID, name, row number, or @alias"),
        ide: str = typer.Option(..., "--ide", "-i", help="Target IDE"),
        raw: bool = typer.Option(False, "--raw", help="Output raw JSON only (for piping)"),
    ):
        """Get install config snippet for an MCP server."""
        import json as _json

        resolved = config.resolve_alias(mcp_id)
        with spinner(f"Generating {ide} config..."):
            result = client.post(f"/api/v1/mcps/{resolved}/install", {"ide": ide})

        snippet = result.get("config_snippet", {})
        if raw:
            print(_json.dumps(snippet, indent=2))
            return

        _IDE_CONFIG_PATHS = {
            "kiro": ".kiro/settings/mcp.json",
            "cursor": ".cursor/mcp.json",
            "vscode": ".vscode/mcp.json",
            "windsurf": ".windsurf/mcp.json",
            "claude-code": "(run the command below)",
            "claude_code": "(run the command below)",
            "gemini-cli": ".gemini/settings.json",
            "gemini_cli": ".gemini/settings.json",
        }

        rprint(f"\n[bold]Config for {ide}:[/bold]\n")
        console.print_json(_json.dumps(snippet, indent=2))
        config_path = _IDE_CONFIG_PATHS.get(ide, "")
        if config_path and not config_path.startswith("("):
            rprint(f"\n[dim]Add to:[/dim] [bold]{config_path}[/bold]")
            rprint(f"[dim]Or pipe:[/dim] observal install {mcp_id} --ide {ide} --raw > {config_path}")

    @app.command(name="delete")
    def delete_mcp(
        mcp_id: str = typer.Argument(..., help="ID, name, row number, or @alias"),
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    ):
        """Delete an MCP server."""
        resolved = config.resolve_alias(mcp_id)
        if not yes:
            with spinner():
                item = client.get(f"/api/v1/mcps/{resolved}")
            if not typer.confirm(f"Delete [bold]{item['name']}[/bold] ({resolved})?"):
                raise typer.Abort()
        with spinner("Deleting..."):
            client.delete(f"/api/v1/mcps/{resolved}")
        rprint(f"[green]✓ Deleted {resolved}[/green]")
