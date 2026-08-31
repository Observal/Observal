# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""CLI commands for archiving registry components."""

from __future__ import annotations

import typer
from rich import print as rprint

from observal_cli import client
from observal_cli.errors import ErrorCategory, fail
from observal_cli.render import OutputMode, esc, output_json

_ENTITY_LABELS = {
    "mcps": "MCP server",
    "skills": "skill",
    "hooks": "hook",
    "prompts": "prompt",
    "sandboxes": "sandbox",
}
_COMMAND_NAMES = {
    "mcps": "mcp",
    "skills": "skill",
    "hooks": "hook",
    "prompts": "prompt",
    "sandboxes": "sandbox",
}


def _require_confirmation_bypass(output: OutputMode, yes: bool, operation: str) -> None:
    if output == "json" and not yes:
        fail(
            ErrorCategory.VALIDATION,
            "JSON mode cannot open a confirmation prompt.",
            operation=operation,
            resource="confirmation",
            remediation="Pass the confirmation bypass option and retry.",
        )


def _archive_component(entity_type: str, entity_id: str, yes: bool, output: OutputMode) -> None:
    _require_confirmation_bypass(output, yes, "Archive registry component")
    resolved = client.resolve_registry_reference(entity_type, entity_id)
    label = _ENTITY_LABELS[entity_type]
    if not yes:
        item = client.get(f"/api/v1/{entity_type}/{resolved}")
        if not typer.confirm(f"Archive {label} {item['name']} ({resolved})?"):
            raise typer.Abort()
    result = client.patch(f"/api/v1/{entity_type}/{resolved}/archive")
    if output == "json":
        output_json(result)
        return
    rprint(f"[green]✓ {label.title()} archived:[/green] {esc(result.get('name', entity_id))}")


def _unarchive_component(entity_type: str, entity_id: str, yes: bool, output: OutputMode) -> None:
    _require_confirmation_bypass(output, yes, "Restore registry component")
    resolved = client.resolve_registry_reference(entity_type, entity_id)
    label = _ENTITY_LABELS[entity_type]
    if not yes:
        item = client.get(f"/api/v1/{entity_type}/{resolved}")
        if not typer.confirm(f"Restore {label} {item['name']} ({resolved})?"):
            raise typer.Abort()
    result = client.patch(f"/api/v1/{entity_type}/{resolved}/unarchive")
    if output == "json":
        output_json(result)
        return
    rprint(f"[green]✓ {label.title()} restored:[/green] {esc(result.get('name', entity_id))}")


def add_archive_commands(app: typer.Typer, entity_type: str) -> None:
    command = _COMMAND_NAMES[entity_type]

    def archive(
        entity_id: str = typer.Argument(help="Entity UUID or canonical name"),
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
        output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table or json"),
    ):
        _archive_component(entity_type, entity_id, yes, output)

    archive.__doc__ = f"""Archive this component.

    Examples:
      observal registry {command} archive alice/my-component
      observal registry {command} archive alice/my-component --yes --output json
    """
    app.command(name="archive")(archive)

    def unarchive(
        entity_id: str = typer.Argument(help="Entity UUID or canonical name"),
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
        output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table or json"),
    ):
        _unarchive_component(entity_type, entity_id, yes, output)

    unarchive.__doc__ = f"""Restore an archived component.

    Examples:
      observal registry {command} unarchive alice/my-component
      observal registry {command} unarchive alice/my-component --yes --output json
    """
    app.command(name="unarchive")(unarchive)
