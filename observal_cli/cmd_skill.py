"""Skill registry CLI commands."""

from __future__ import annotations

import json as _json

import typer
from rich import print as rprint
from rich.table import Table

from observal_cli import client, config
from observal_cli.constants import VALID_SKILL_TASK_TYPES
from observal_cli.prompts import select_one
from observal_cli.render import console, kv_panel, output_json, relative_time, spinner, status_badge

skill_app = typer.Typer(help="Skill registry commands")


def register_skill(app: typer.Typer):
    app.add_typer(skill_app, name="skill")


@skill_app.command(name="submit")
def skill_submit(
    from_file: str | None = typer.Option(None, "--from-file", "-f", help="Create from JSON file"),
    draft: bool = typer.Option(False, "--draft", help="Save as draft instead of submitting for review"),
    submit_draft: str | None = typer.Option(None, "--submit", help="Submit a draft for review (skill ID)"),
):
    """Submit a new skill for review.

    Only submit skills you created or are the point-of-contact for.
    """
    rprint("[dim]Note: Only submit components you created (private) or are the point-of-contact for (external).[/dim]")
    if draft and submit_draft:
        rprint(
            "[red]Cannot use --draft and --submit together.[/red] Use --draft to save a new draft, or --submit to submit an existing draft."
        )
        raise typer.Exit(code=1)
    if submit_draft:
        resolved = config.resolve_alias(submit_draft)
        with spinner("Submitting draft for review..."):
            result = client.post(f"/api/v1/skills/{resolved}/submit")
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
        agents_input = typer.prompt("Target agents (comma-separated)", default="")
        payload = {
            "name": typer.prompt("Skill name"),
            "version": typer.prompt("Version", default="1.0.0"),
            "description": typer.prompt("Description"),
            "owner": typer.prompt("Owner"),
            "git_url": typer.prompt("Git URL"),
            "task_type": select_one("Task type", VALID_SKILL_TASK_TYPES),
            "target_agents": [a.strip() for a in agents_input.split(",") if a.strip()],
        }

    if draft:
        with spinner("Saving draft..."):
            result = client.post("/api/v1/skills/draft", payload)
        rprint(f"[green]✓ Draft saved![/green] ID: [bold]{result['id']}[/bold]")
    else:
        with spinner("Submitting skill..."):
            result = client.post("/api/v1/skills/submit", payload)
        rprint(f"[green]✓ Skill submitted![/green] ID: [bold]{result['id']}[/bold]")


@skill_app.command(name="list")
def skill_list(
    task_type: str | None = typer.Option(None, "--task-type", "-t"),
    target_agent: str | None = typer.Option(None, "--target-agent"),
    search: str | None = typer.Option(None, "--search", "-s"),
    output: str = typer.Option("table", "--output", "-o", help="Output: table, json, plain"),
):
    """List approved skills."""
    params = {}
    if task_type:
        params["task_type"] = task_type
    if target_agent:
        params["target_agent"] = target_agent
    if search:
        params["search"] = search
    with spinner("Fetching skills..."):
        data = client.get("/api/v1/skills", params=params)
    if not data:
        rprint("[dim]No skills found.[/dim]")
        return
    config.save_last_results(data)
    if output == "json":
        output_json(data)
        return
    if output == "plain":
        for item in data:
            rprint(f"{item['id']}  {item['name']}  v{item.get('version', '?')}")
        return
    table = Table(title=f"Skills ({len(data)})", show_lines=False, padding=(0, 1))
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


@skill_app.command(name="show")
def skill_show(
    skill_id: str = typer.Argument(..., help="ID, name, row number, or @alias"),
    output: str = typer.Option("table", "--output", "-o"),
):
    """Show skill details."""
    resolved = config.resolve_alias(skill_id)
    with spinner():
        item = client.get(f"/api/v1/skills/{resolved}")
    if output == "json":
        output_json(item)
        return
    console.print(
        kv_panel(
            f"{item['name']} v{item.get('version', '?')}",
            [
                ("Status", status_badge(item.get("status", ""))),
                ("Task Type", item.get("task_type", "N/A")),
                ("Owner", item.get("owner", "N/A")),
                ("Git URL", item.get("git_url", "N/A")),
                ("Description", item.get("description", "")),
                ("Target Agents", ", ".join(item.get("target_agents", [])) or "N/A"),
                ("Created", relative_time(item.get("created_at"))),
                ("ID", f"[dim]{item['id']}[/dim]"),
            ],
            border_style="green",
        )
    )


@skill_app.command(name="install")
def skill_install(
    skill_id: str = typer.Argument(..., help="Skill ID, name, row number, or @alias"),
    ide: str = typer.Option(..., "--ide", "-i", help="Target IDE"),
    raw: bool = typer.Option(False, "--raw", help="Output raw JSON only"),
    no_write: bool = typer.Option(False, "--no-write", help="Print config without writing files"),
):
    """Install a skill — writes the skill file to disk and shows config."""
    resolved = config.resolve_alias(skill_id)
    with spinner(f"Generating {ide} config..."):
        result = client.post(f"/api/v1/skills/{resolved}/install", {"ide": ide})
    snippet = result.get("config_snippet", result)

    if raw:
        print(_json.dumps(snippet, indent=2))
        return

    # Write the skill file to disk unless --no-write
    skill_file = snippet.get("skill_file")
    if skill_file and not no_write:
        from pathlib import Path

        file_path = skill_file["path"]
        if file_path.startswith("~/"):
            file_path = str(Path.home() / file_path[2:])

        dest = Path(file_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(skill_file["content"], encoding="utf-8")
        rprint(f"[green]✓ Wrote skill file:[/green] {dest}")
    elif skill_file:
        rprint(f"[dim]Skill file (not written):[/dim] {skill_file['path']}")

    rprint(f"\n[bold]Config for {ide}:[/bold]\n")
    console.print_json(_json.dumps(snippet, indent=2))


@skill_app.command(name="edit")
def skill_edit(
    skill_id: str = typer.Argument(..., help="ID, name, row number, or @alias"),
    from_file: str | None = typer.Option(None, "--from-file", "-f", help="Load updates from JSON file"),
    name: str | None = typer.Option(None, "--name", "-n", help="New listing name"),
    description: str | None = typer.Option(None, "--description", "-d", help="New description"),
    version: str | None = typer.Option(None, "--version", "-v", help="New version string"),
    task_type: str | None = typer.Option(None, "--task-type", "-t", help="New task type"),
):
    """Edit a draft, rejected, or pending skill submission."""
    resolved = config.resolve_alias(skill_id)
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
        if task_type is not None:
            updates["task_type"] = task_type

    if not updates:
        rprint("[yellow]No changes specified.[/yellow] Use --from-file or field options (--name, --description, etc.)")
        raise typer.Exit(code=1)

    with spinner("Saving changes..."):
        result = client.put(f"/api/v1/skills/{resolved}/draft", updates)
    rprint(f"[green]✓ Updated {result['name']}[/green] (status: {result.get('status', 'unknown')})")


@skill_app.command(name="delete")
def skill_delete(
    skill_id: str = typer.Argument(..., help="ID, name, row number, or @alias"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Delete a skill."""
    resolved = config.resolve_alias(skill_id)
    if not yes:
        with spinner():
            item = client.get(f"/api/v1/skills/{resolved}")
        if not typer.confirm(f"Delete [bold]{item['name']}[/bold] ({resolved})?"):
            raise typer.Abort()
    with spinner("Deleting..."):
        client.delete(f"/api/v1/skills/{resolved}")
    rprint(f"[green]✓ Deleted {resolved}[/green]")
