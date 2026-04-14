"""MCP server CLI commands."""

from __future__ import annotations

import typer
from rich import print as rprint
from rich.table import Table

from observal_cli import client, config
from observal_cli.analyzer import analyze_local
from observal_cli.constants import VALID_IDES, VALID_MCP_CATEGORIES
from observal_cli.prompts import select_many, select_one
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


# ── Implementation functions (shared by canonical + deprecated) ──


def _submit_impl(git_url, name, category, yes):
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

    rprint("\n[bold]--- Analysis Results ---[/bold]")

    if error:
        rprint(f"  [bold red]Error:[/bold red] {error}")
        rprint("  [dim]You can still submit manually, but the server could not be analyzed.[/dim]")
        if not yes and not typer.confirm("Continue with manual submission?", default=False):
            raise typer.Abort()
    else:
        if detected_name:
            rprint(f"  Server name:  [cyan]{detected_name}[/cyan]")
        if detected_framework:
            rprint(f"  Framework:    [cyan]{detected_framework}[/cyan]")
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
    if yes:
        _name = name or detected_name
        _version = detected_ver
        _desc = detected_desc
        _owner = "default"
        _category = category or "general"
        supported_ides = list(VALID_IDES)
        _setup = ""
        _changelog = "Initial release"
        env_vars = detected_env_vars
    else:
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
        supported_ides = select_many("Supported IDEs", VALID_IDES, defaults=VALID_IDES)
        _setup = typer.prompt("Setup instructions (optional, press Enter to skip)", default="")
        _changelog = typer.prompt("Changelog", default="Initial release")

        # Env vars are auto-included from analysis — users are prompted
        # for actual values during `install`, not here.
        env_vars = list(detected_env_vars)

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
    if analyzed_locally:
        submit_payload["client_analysis"] = {
            "tools": prefill.get("tools", []),
            "issues": prefill.get("issues", []),
            "framework": prefill.get("framework", ""),
            "entry_point": prefill.get("entry_point", ""),
        }

    with spinner("Submitting..."):
        result = client.post("/api/v1/mcps/submit", submit_payload)
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

    with spinner(f"Generating {ide} config..."):
        result = client.post(f"/api/v1/mcps/{resolved}/install", {"ide": ide, "env_values": env_values})

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
