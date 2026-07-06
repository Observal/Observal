# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""CLI commands for transferring registry ownership."""

from __future__ import annotations

import typer
from rich import print as rprint

from observal_cli import client, config

_ENTITY_LABELS = {
    "agents": "agent",
    "mcps": "mcp",
    "skills": "skill",
    "hooks": "hook",
    "prompts": "prompt",
    "sandboxes": "sandbox",
}


def add_transfer_owner_command(app: typer.Typer, entity_type: str) -> None:
    @app.command(name="transfer-owner")
    def transfer_owner(
        entity_id: str = typer.Argument(help="Entity UUID or name"),
        username: str = typer.Argument(help="New owner's username"),
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    ):
        """Transfer ownership to another username."""
        target = username.strip().lstrip("@")
        if not target:
            rprint("[red]Error:[/red] username is required")
            raise typer.Exit(1)

        label = _ENTITY_LABELS.get(entity_type, entity_type)
        if not yes and not typer.confirm(
            f"Transfer {label} '{entity_id}' to @{target}? You will no longer be the owner."
        ):
            raise typer.Exit(1)

        resolved = config.resolve_alias(entity_id)
        resp = client.post(f"/api/v1/{entity_type}/{resolved}/transfer-ownership", json_data={"username": target})
        rprint(f"[green]Ownership transferred to:[/green] @{resp.get('owner', target)}")
