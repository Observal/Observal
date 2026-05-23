# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Component version CLI commands.

Provides:
  observal component version publish <type> <listing-name-or-id> [flags]
  observal component version list    <type> <listing-name-or-id> [flags]
"""

from __future__ import annotations

import json as _json

import typer
from loguru import logger
from rich import print as rprint
from rich.table import Table

from observal_cli import client, config
from observal_cli.prompts import text_input
from observal_cli.render import console, output_json, relative_time, spinner, status_badge

# ── Constants ──────────────────────────────────────────────────

_VALID_TYPES = {"mcp", "skill", "hook", "prompt", "sandbox"}

_PLURAL = {
    "mcp": "mcps",
    "skill": "skills",
    "hook": "hooks",
    "prompt": "prompts",
    "sandbox": "sandboxes",
}

# ── App hierarchy ──────────────────────────────────────────────

component_app = typer.Typer(
    help="Component version commands",
    no_args_is_help=True,
)

version_app = typer.Typer(
    help="Manage component versions",
    no_args_is_help=True,
)

component_app.add_typer(version_app, name="version")


# ── Helpers ────────────────────────────────────────────────────


def _require_valid_type(component_type: str) -> None:
    if component_type not in _VALID_TYPES:
        rprint(
            f"[red]Error:[/red] Invalid component type '{component_type}'. "
            f"Must be one of: {', '.join(sorted(_VALID_TYPES))}"
        )
        raise typer.Exit(code=1)


# ── version publish ────────────────────────────────────────────


@version_app.command(name="publish")
def version_publish(
    component_type: str = typer.Argument(..., help="Component type: hook, skill, prompt, mcp, sandbox"),
    listing: str = typer.Argument(..., help="Listing name or ID"),
    version: str | None = typer.Option(None, "--version", "-v", help="Version to publish (e.g. 1.2.0)"),
    description: str = typer.Option(..., "--description", "-d", help="Short description of this version"),
    changelog: str | None = typer.Option(None, "--changelog", help="Changelog notes"),
    supported_ides: list[str] | None = typer.Option(None, "--ide", help="Supported IDEs (repeat for multiple)"),
    extra: str | None = typer.Option(None, "--extra", help="Extra JSON for type-specific fields"),
):
    """Publish a new version for a registry component.

    Creates a versioned release for any component type (mcp, skill, hook,
    prompt, sandbox). If --version is omitted, fetches version suggestions
    from the server and prompts interactively.

    The --extra flag accepts a JSON string for type-specific metadata
    (e.g. supported transports for MCP servers).

    \b
    Examples:
      observal component version publish mcp my-server -v 2.0.0 -d "Breaking change"
      observal component version publish hook guard-hook -v 1.1.0 -d "Add timeout" --changelog "Fixed race"
      observal component version publish skill my-skill -v 1.0.0 -d "Initial" --ide claude-code --ide cursor
      observal component version publish mcp analyzer --extra '{"transport": "http"}' -d "HTTP support"
    """
    logger.debug("version_publish: component_type={}", component_type)
    _require_valid_type(component_type)

    # Validate --extra JSON early
    extra_data: dict | None = None
    if extra is not None:
        try:
            extra_data = _json.loads(extra)
        except _json.JSONDecodeError as exc:
            rprint(f"[red]Error:[/red] --extra is not valid JSON: {exc}")
            raise typer.Exit(code=1)

    resolved = config.resolve_alias(listing)
    plural = _PLURAL[component_type]

    # If --version omitted, fetch suggestions and prompt
    if version is None:
        try:
            with spinner("Fetching version suggestions..."):
                suggestions = client.get(f"/api/v1/{plural}/{resolved}/version-suggestions")
            current = suggestions.get("current", "?")
            sugs = suggestions.get("suggestions", {})
            hint = (
                f"  Current: {current}  "
                f"patch→{sugs.get('patch', '?')}  "
                f"minor→{sugs.get('minor', '?')}  "
                f"major→{sugs.get('major', '?')}"
            )
            rprint(f"[dim]{hint}[/dim]")
        except (Exception, SystemExit):
            pass
        version = text_input("Version")

    # Build payload (only include optional keys when provided)
    payload: dict = {
        "version": version,
        "description": description,
    }
    if changelog is not None:
        payload["changelog"] = changelog
    if supported_ides:
        payload["supported_ides"] = supported_ides
    if extra_data is not None:
        payload["extra"] = extra_data

    with spinner(f"Publishing {component_type} version {version}..."):
        result = client.post(f"/api/v1/{plural}/{resolved}/versions", payload)

    status = result.get("status", "pending")
    rprint(
        f"[green]✓ Version [bold]{result.get('version', version)}[/bold] submitted for review![/green]"
        f"  Status: {status_badge(status)}"
    )


# ── version list ───────────────────────────────────────────────


@version_app.command(name="list")
def version_list(
    component_type: str = typer.Argument(..., help="Component type: hook, skill, prompt, mcp, sandbox"),
    listing: str = typer.Argument(..., help="Listing name or ID"),
    output: str = typer.Option("table", "--output", "-o", help="Output format: table or json"),
):
    """List version history for a registry component.

    Shows all published versions for a component, including status,
    release date, and who published each version. Supports table and
    JSON output formats.

    \b
    Examples:
      observal component version list mcp my-server
      observal component version list hook guard-hook --output json
      observal component version list skill @my-skill-alias
    """
    _require_valid_type(component_type)

    resolved = config.resolve_alias(listing)
    plural = _PLURAL[component_type]

    with spinner("Fetching versions..."):
        data = client.get(f"/api/v1/{plural}/{resolved}/versions", params={"page": 1, "page_size": 50})

    items = data.get("items", [])

    if output == "json":
        output_json(data)
        return

    if not items:
        rprint("[dim]No versions found.[/dim]")
        return

    table = Table(show_lines=False, padding=(0, 1))
    table.add_column("VERSION", style="bold cyan", no_wrap=True)
    table.add_column("STATUS")
    table.add_column("DATE")
    table.add_column("RELEASED BY", style="dim")

    for item in items:
        table.add_row(
            item.get("version", ""),
            status_badge(item.get("status", "")),
            relative_time(item.get("created_at")),
            item.get("created_by_email", "") or item.get("created_by_username", ""),
        )

    console.print(table)
