# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""CLI commands for archiving registry components."""

from __future__ import annotations

import typer
from rich import print as rprint

from observal_cli import client, config

_ENTITY_LABELS = {
    "mcps": "MCP server",
    "skills": "skill",
    "hooks": "hook",
    "prompts": "prompt",
    "sandboxes": "sandbox",
}


def _archive_component(entity_type: str, entity_id: str, yes: bool) -> None:
    resolved = config.resolve_alias(entity_id)
    label = _ENTITY_LABELS.get(entity_type, entity_type)
    if not yes:
        item = client.get(f"/api/v1/{entity_type}/{resolved}")
        if not typer.confirm(f"Archive {label} [bold]{item['name']}[/bold] ({resolved})?"):
            raise typer.Abort()
    client.patch(f"/api/v1/{entity_type}/{resolved}/archive")
    rprint(f"[green]✓ {label.title()} archived[/green]")


def _unarchive_component(entity_type: str, entity_id: str, yes: bool) -> None:
    resolved = config.resolve_alias(entity_id)
    label = _ENTITY_LABELS.get(entity_type, entity_type)
    if not yes:
        item = client.get(f"/api/v1/{entity_type}/{resolved}")
        if not typer.confirm(f"Restore {label} [bold]{item['name']}[/bold] ({resolved})?"):
            raise typer.Abort()
    client.patch(f"/api/v1/{entity_type}/{resolved}/unarchive")
    rprint(f"[green]✓ {label.title()} restored[/green]")


def add_archive_commands(app: typer.Typer, entity_type: str) -> None:
    @app.command(name="archive")
    def archive(
        entity_id: str = typer.Argument(help="Entity UUID or name"),
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    ):
        """Archive this component."""
        _archive_component(entity_type, entity_id, yes)

    @app.command(name="unarchive")
    def unarchive(
        entity_id: str = typer.Argument(help="Entity UUID or name"),
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    ):
        """Restore an archived component."""
        _unarchive_component(entity_type, entity_id, yes)
