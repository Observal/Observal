# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""CLI commands for managing co-authors on agents and components."""

from __future__ import annotations

from uuid import UUID

import typer
from rich import print as rprint
from rich.table import Table

from observal_cli import client
from observal_cli.errors import ErrorCategory, fail
from observal_cli.render import OutputMode, esc, output_json


def _entity_id(entity_type: str, reference: str) -> str:
    return client.resolve_registry_reference(entity_type, reference)


def _list_co_authors(entity_type: str, entity_id: str, output: OutputMode) -> None:
    resolved = _entity_id(entity_type, entity_id)
    response = client.get(f"/api/v1/{entity_type}/{resolved}/co-authors")
    if output == "json":
        output_json(response)
        return
    if not response:
        rprint("[dim]No co-authors.[/dim]")
        return

    table = Table(title="Co-Authors")
    table.add_column("Email", style="cyan")
    table.add_column("Username", style="green")
    table.add_column("Active", style="dim")
    for author in response:
        table.add_row(
            esc(author.get("email", "")),
            esc(author.get("username") or ""),
            "yes" if author.get("is_active", True) else "no",
        )
    rprint(table)


def _add_co_author(entity_type: str, entity_id: str, user: str, output: OutputMode) -> None:
    user = user.strip()
    identity = user.lstrip("@")
    if not identity:
        fail(
            ErrorCategory.VALIDATION,
            "Co-author email or username is required.",
            operation="Add co-author",
            resource=f"{entity_type} co-authors",
            remediation="Provide an email address or username.",
        )
    resolved = _entity_id(entity_type, entity_id)
    body = {"email": user.lower()} if "@" in user and not user.startswith("@") else {"username": identity}
    response = client.post(f"/api/v1/{entity_type}/{resolved}/co-authors", json_data=body)
    if output == "json":
        output_json(response)
        return
    rprint(f"[green]Added co-author:[/green] {esc(response.get('email', user))} ({esc(response.get('username', ''))})")


def _remove_co_author(entity_type: str, entity_id: str, user_id: str, output: OutputMode) -> None:
    try:
        user_id = str(UUID(user_id))
    except ValueError:
        fail(
            ErrorCategory.VALIDATION,
            "Co-author user ID must be a UUID.",
            operation="Remove co-author",
            resource=f"{entity_type} co-authors",
            remediation="Copy the user ID from the co-author list JSON result.",
        )
    resolved = _entity_id(entity_type, entity_id)
    response = client.delete(f"/api/v1/{entity_type}/{resolved}/co-authors/{user_id}")
    if output == "json":
        output_json(response)
        return
    rprint("[green]Co-author removed.[/green]")


def make_co_authors_typer(entity_type: str) -> typer.Typer:
    """Create a co-author command group for one registry entity type."""
    command = {
        "agents": "agent",
        "mcps": "registry mcp",
        "skills": "registry skill",
        "hooks": "registry hook",
        "prompts": "registry prompt",
        "sandboxes": "registry sandbox",
    }[entity_type]
    prefix = f"observal {command} co-authors"
    example = "alice/my-agent" if entity_type == "agents" else "alice/my-component"
    co_app = typer.Typer(help=f"Manage co-authors for {entity_type}\n\nExamples:\n  {prefix} list {example}")

    def list_cmd(
        entity_id: str = typer.Argument(help="Entity UUID or canonical name"),
        output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table or json"),
    ):
        _list_co_authors(entity_type, entity_id, output)

    list_cmd.__doc__ = f"""List co-authors.

    Examples:
      {prefix} list {example}
      {prefix} list {example} --output json
    """
    co_app.command(name="list")(list_cmd)

    def add_cmd(
        entity_id: str = typer.Argument(help="Entity UUID or canonical name"),
        user: str = typer.Argument(help="Email or username of the user to add"),
        output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table or json"),
    ):
        _add_co_author(entity_type, entity_id, user, output)

    add_cmd.__doc__ = f"""Add a co-author.

    Examples:
      {prefix} add {example} alice@example.com
      {prefix} add {example} @alice --output json
    """
    co_app.command(name="add")(add_cmd)

    def remove_cmd(
        entity_id: str = typer.Argument(help="Entity UUID or canonical name"),
        user_id: str = typer.Argument(help="UUID of the co-author to remove"),
        output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table or json"),
    ):
        _remove_co_author(entity_type, entity_id, user_id, output)

    remove_cmd.__doc__ = f"""Remove a co-author.

    Examples:
      {prefix} remove {example} 550e8400-e29b-41d4-a716-446655440000
      {prefix} remove {example} 550e8400-e29b-41d4-a716-446655440000 --output json
    """
    co_app.command(name="remove")(remove_cmd)

    return co_app
