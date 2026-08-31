# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""CLI commands for transferring registry ownership."""

from __future__ import annotations

import typer
from rich import print as rprint

from observal_cli import client
from observal_cli.errors import ErrorCategory, fail
from observal_cli.render import OutputMode, esc, output_json

_ENTITY_LABELS = {
    "agents": "agent",
    "mcps": "mcp",
    "skills": "skill",
    "hooks": "hook",
    "prompts": "prompt",
    "sandboxes": "sandbox",
}


def add_transfer_owner_command(app: typer.Typer, entity_type: str) -> None:
    label = _ENTITY_LABELS[entity_type]
    command = "agent" if entity_type == "agents" else f"registry {label}"

    def transfer_owner(
        entity_id: str = typer.Argument(help="Entity UUID or canonical name"),
        username: str = typer.Argument(help="New owner's username"),
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
        output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table or json"),
    ):
        target = username.strip().lstrip("@")
        if not target:
            fail(
                ErrorCategory.VALIDATION,
                "The new owner's username is required.",
                operation="Transfer registry ownership",
                resource=entity_id,
                remediation="Provide a username and retry.",
            )
        if output == "json" and not yes:
            fail(
                ErrorCategory.VALIDATION,
                "JSON mode cannot open a confirmation prompt.",
                operation="Transfer registry ownership",
                resource=entity_id,
                remediation="Pass the confirmation bypass option and retry.",
            )
        if not yes and not typer.confirm(
            f"Transfer {label} '{entity_id}' to @{target}? You will no longer be the owner."
        ):
            raise typer.Abort()

        resolved = client.resolve_registry_reference(entity_type, entity_id)
        response = client.post(
            f"/api/v1/{entity_type}/{resolved}/transfer-ownership",
            json_data={"username": target},
        )
        if output == "json":
            output_json(response)
            return
        rprint(f"[green]Ownership transferred to:[/green] @{esc(response.get('owner', target))}")

    transfer_owner.__doc__ = f"""Transfer ownership to another username.

    Examples:
      observal {command} transfer-owner alice/my-component bob
      observal {command} transfer-owner alice/my-component bob --yes --output json
    """
    app.command(name="transfer-owner")(transfer_owner)
