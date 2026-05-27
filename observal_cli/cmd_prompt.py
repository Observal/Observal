# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Prompt registry CLI commands."""

from __future__ import annotations

import json as _json

import typer
from loguru import logger
from rich import print as rprint
from rich.table import Table

from observal_cli import client, config
from observal_cli.constants import VALID_PROMPT_CATEGORIES
from observal_cli.prompts import select_one, text_input
from observal_cli.render import console, kv_panel, output_json, relative_time, spinner, status_badge

prompt_app = typer.Typer(help="Prompt registry commands")


def register_prompt(app: typer.Typer):
    logger.debug("register_prompt called")
    app.add_typer(prompt_app, name="prompt")


@prompt_app.command(name="submit")
def prompt_submit(
    from_file: str | None = typer.Option(
        None, "--from-file", "-f", help="Create from JSON file or read template from file"
    ),
    draft: bool = typer.Option(False, "--draft", help="Save as draft instead of submitting for review"),
    submit_draft: str | None = typer.Option(None, "--submit", help="Submit a draft for review (prompt ID)"),
):
    """Submit a new prompt template for review.

    Prompts are reusable templates with variable placeholders that agents can
    render at runtime. You can submit interactively, from a JSON file, or save
    as a draft first and submit later with --submit.

    Only submit prompts you created or are the point-of-contact for.

    Examples:
        observal registry prompt submit
        observal registry prompt submit --from-file prompt.json
        observal registry prompt submit --draft
        observal registry prompt submit --submit abc123
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
            result = client.post(f"/api/v1/prompts/{resolved}/submit")
        rprint(f"[green]✓ Draft submitted for review![/green] ID: [bold]{result['id']}[/bold]")
        return

    if from_file:
        with open(from_file) as f:
            content = f.read()
        try:
            payload = _json.loads(content)
        except _json.JSONDecodeError:
            payload = {
                "name": text_input("Prompt name"),
                "version": text_input("Version", default="1.0.0"),
                "description": text_input("Description"),
                "owner": text_input("Owner", default=config.load().get("user_name", "")),
                "category": select_one("Category", VALID_PROMPT_CATEGORIES),
                "template": content,
            }
    else:
        payload = {
            "name": text_input("Prompt name"),
            "version": text_input("Version", default="1.0.0"),
            "description": text_input("Description"),
            "owner": text_input("Owner", default=config.load().get("user_name", "")),
            "category": select_one("Category", VALID_PROMPT_CATEGORIES),
            "template": text_input("Template"),
        }

    if draft:
        with spinner("Saving draft..."):
            result = client.post("/api/v1/prompts/draft", payload)
        rprint(f"[green]✓ Draft saved![/green] ID: [bold]{result['id']}[/bold]")
    else:
        with spinner("Submitting prompt..."):
            result = client.post("/api/v1/prompts/submit", payload)
        rprint(f"[green]✓ Prompt submitted![/green] ID: [bold]{result['id']}[/bold]")


@prompt_app.command(name="list")
def prompt_list(
    category: str | None = typer.Option(None, "--category", "-c"),
    search: str | None = typer.Option(None, "--search", "-s"),
    output: str = typer.Option("table", "--output", "-o", help="Output: table, json, plain"),
):
    """List approved prompts in the registry.

    Shows only prompts with approved status. Use --category or --search to
    filter results. Row numbers from the output can be used as references
    in subsequent commands.

    Examples:
        observal registry prompt list
        observal registry prompt list --category coding
        observal registry prompt list --search "refactor" --output json
    """
    params = {}
    if category:
        params["category"] = category
    if search:
        params["search"] = search
    with spinner("Fetching prompts..."):
        data = client.get("/api/v1/prompts", params=params)
    if not data:
        rprint("[dim]No prompts found.[/dim]")
        return
    config.save_last_results(data)
    if output == "json":
        output_json(data)
        return
    if output == "plain":
        for item in data:
            rprint(f"{item['id']}  {item['name']}  v{item.get('version', '?')}")
        return
    table = Table(title=f"Prompts ({len(data)})", show_lines=False, padding=(0, 1))
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


@prompt_app.command(name="my")
def prompt_my(
    output: str = typer.Option("table", "--output", "-o", help="Output: table, json, plain"),
):
    """List your own prompts across all statuses.

    Shows drafts, pending, approved, and rejected prompts you submitted.
    Useful for tracking the review status of your submissions.

    Examples:
        observal registry prompt my
        observal registry prompt my --output json
    """
    with spinner("Fetching your prompts..."):
        data = client.get("/api/v1/prompts/my")
    if not data:
        rprint("[dim]You have no prompts.[/dim]")
        return
    config.save_last_results(data)
    if output == "json":
        output_json(data)
        return
    if output == "plain":
        for item in data:
            rprint(f"{item['name']}  v{item.get('version', '?')}  {item.get('status', '')}")
        return
    table = Table(title=f"My Prompts ({len(data)})", show_lines=False, padding=(0, 1))
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


@prompt_app.command(name="show")
def prompt_show(
    prompt_id: str = typer.Argument(..., help="ID, name, row number, or @alias"),
    output: str = typer.Option("table", "--output", "-o"),
):
    """Show detailed information about a prompt.

    Displays metadata, status, category, template content, and timestamps.
    Accepts a UUID, name, row number from a previous list, or @alias.

    Examples:
        observal registry prompt show my-prompt
        observal registry prompt show 1
        observal registry prompt show @refactor-prompt
        observal registry prompt show abc123 --output json
    """
    resolved = config.resolve_alias(prompt_id)
    with spinner():
        item = client.get(f"/api/v1/prompts/{resolved}")
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
                ("Created", relative_time(item.get("created_at"))),
                ("ID", f"[dim]{item['id']}[/dim]"),
            ],
            border_style="cyan",
        )
    )
    if item.get("template"):
        rprint(f"\n[bold]Template:[/bold]\n[dim]{item['template']}[/dim]")


@prompt_app.command(name="render")
def prompt_render(
    prompt_id: str = typer.Argument(..., help="Prompt ID, name, row number, or @alias"),
    var: list[str] = typer.Option([], "--var", "-v", help="Variable as key=value"),
):
    """Render a prompt template with variable substitution.

    Sends variable key=value pairs to the server, which substitutes them
    into the prompt template and returns the rendered output. Also emits
    a prompt_render telemetry span.

    Examples:
        observal registry prompt render my-prompt --var lang=python
        observal registry prompt render @tpl --var file=main.py --var task=refactor
    """
    resolved = config.resolve_alias(prompt_id)
    variables = {}
    for v in var:
        k, _, val = v.partition("=")
        variables[k] = val
    with spinner("Rendering prompt..."):
        result = client.post(f"/api/v1/prompts/{resolved}/render", {"variables": variables})
    rprint(result.get("rendered", result))


@prompt_app.command(name="install")
def prompt_install(
    prompt_id: str = typer.Argument(..., help="Prompt ID, name, row number, or @alias"),
    ide: str = typer.Option(..., "--ide", "-i", help="Target IDE"),
    raw: bool = typer.Option(False, "--raw", help="Output raw JSON only"),
):
    """Generate IDE install configuration for a prompt.

    Produces the config snippet needed to make this prompt available in
    the specified IDE. Use --raw to pipe the JSON directly to a file.

    Examples:
        observal registry prompt install my-prompt --ide claude-code
        observal registry prompt install @tpl --ide cursor --raw > prompt.json
    """
    resolved = config.resolve_alias(prompt_id)
    with spinner(f"Generating {ide} config..."):
        result = client.post(f"/api/v1/prompts/{resolved}/install", {"ide": ide})
    snippet = result.get("config_snippet", result)
    if raw:
        print(_json.dumps(snippet, indent=2))
        return
    rprint(f"\n[bold]Config for {ide}:[/bold]\n")
    console.print_json(_json.dumps(snippet, indent=2))


@prompt_app.command(name="edit")
def prompt_edit(
    prompt_id: str = typer.Argument(..., help="ID, name, row number, or @alias"),
    from_file: str | None = typer.Option(None, "--from-file", "-f", help="Load updates from JSON file"),
    name: str | None = typer.Option(None, "--name", "-n", help="New listing name"),
    description: str | None = typer.Option(None, "--description", "-d", help="New description"),
    version: str | None = typer.Option(None, "--version", "-v", help="New version string"),
    category: str | None = typer.Option(None, "--category", "-c", help="New category"),
    template: str | None = typer.Option(None, "--template", "-t", help="New template text"),
):
    """Edit a draft, rejected, or pending prompt submission.

    Updates fields on a prompt that has not yet been approved. You can
    provide individual field options or load all updates from a JSON file.
    Acquires an edit lock to prevent concurrent modifications.

    Examples:
        observal registry prompt edit my-prompt --description "Updated desc"
        observal registry prompt edit abc123 --from-file updates.json
        observal registry prompt edit @tpl --template "New template: {{var}}"
        observal registry prompt edit 2 --version 2.0.0 --category debugging
    """
    resolved = config.resolve_alias(prompt_id)
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
        if category is not None:
            updates["category"] = category
        if template is not None:
            updates["template"] = template

    if not updates:
        rprint("[yellow]No changes specified.[/yellow] Use --from-file or field options (--name, --description, etc.)")
        raise typer.Exit(code=1)

    try:
        client.post(f"/api/v1/prompts/{resolved}/start-edit")
    except Exception as exc:
        if "409" in str(exc) or "currently being edited" in str(exc):
            rprint(f"[red]✗ Cannot edit:[/red] {exc}")
            raise typer.Exit(code=1)
    try:
        with spinner("Saving changes..."):
            result = client.put(f"/api/v1/prompts/{resolved}/draft", updates)
        rprint(f"[green]✓ Updated {result['name']}[/green] (status: {result.get('status', 'unknown')})")
    except Exception as exc:
        try:
            client.post(f"/api/v1/prompts/{resolved}/cancel-edit")
        except Exception:
            pass
        rprint(f"[red]Failed to update:[/red] {exc}")
        raise typer.Exit(code=1)


@prompt_app.command(name="delete")
def prompt_delete(
    prompt_id: str = typer.Argument(..., help="ID, name, row number, or @alias"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Delete a prompt from the registry.

    Permanently removes the prompt. Prompts you own can be deleted regardless
    of status. Requires confirmation unless --yes is passed.

    Examples:
        observal registry prompt delete my-prompt
        observal registry prompt delete abc123 --yes
        observal registry prompt delete @old-template -y
    """
    resolved = config.resolve_alias(prompt_id)
    if not yes:
        with spinner():
            item = client.get(f"/api/v1/prompts/{resolved}")
        if not typer.confirm(f"Delete [bold]{item['name']}[/bold] ({resolved})?"):
            raise typer.Abort()
    with spinner("Deleting..."):
        client.delete(f"/api/v1/prompts/{resolved}")
    rprint(f"[green]✓ Deleted {resolved}[/green]")
