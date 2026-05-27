# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""CLI commands for managing co-authors on agents and components."""

from __future__ import annotations

import typer
from rich import print as rprint
from rich.table import Table

from observal_cli import client

co_authors_app = typer.Typer(help="Manage co-authors for agents and components")

VALID_ENTITY_TYPES = ("agents", "mcps", "skills", "hooks", "prompts", "sandboxes")


def _resolve_entity_type(entity_type: str) -> str:
    """Normalize entity type input."""
    t = entity_type.lower().strip()
    # Allow singular forms
    if t == "agent":
        return "agents"
    if t == "mcp":
        return "mcps"
    if t == "skill":
        return "skills"
    if t == "hook":
        return "hooks"
    if t == "prompt":
        return "prompts"
    if t == "sandbox":
        return "sandboxes"
    if t in VALID_ENTITY_TYPES:
        return t
    rprint(f"[red]Invalid entity type:[/red] {entity_type}")
    rprint(f"Valid types: {', '.join(VALID_ENTITY_TYPES)}")
    raise typer.Exit(code=1)


@co_authors_app.command(name="list")
def co_authors_list(
    entity_type: str = typer.Argument(help="Entity type (agent, mcp, skill, hook, prompt, sandbox)"),
    entity_id: str = typer.Argument(help="Entity UUID or name"),
):
    """List co-authors for an agent or component."""
    t = _resolve_entity_type(entity_type)
    resp = client.get(f"/{t}/{entity_id}/co-authors")
    if not resp:
        rprint("[dim]No co-authors.[/dim]")
        return

    table = Table(title="Co-Authors")
    table.add_column("Email", style="cyan")
    table.add_column("Username", style="green")
    table.add_column("Active", style="dim")

    for author in resp:
        table.add_row(
            author.get("email", ""),
            author.get("username") or "",
            "yes" if author.get("is_active", True) else "no",
        )

    rprint(table)


@co_authors_app.command(name="add")
def co_authors_add(
    entity_type: str = typer.Argument(help="Entity type (agent, mcp, skill, hook, prompt, sandbox)"),
    entity_id: str = typer.Argument(help="Entity UUID or name"),
    user: str = typer.Argument(help="Email or username of the user to add"),
):
    """Add a co-author to an agent or component."""
    t = _resolve_entity_type(entity_type)

    # Determine if email or username
    body = {"email": user.lower()} if "@" in user and not user.startswith("@") else {"username": user.lstrip("@")}

    resp = client.post(f"/{t}/{entity_id}/co-authors", json_data=body)
    rprint(f"[green]Added co-author:[/green] {resp.get('email', user)} ({resp.get('username', '')})")


@co_authors_app.command(name="remove")
def co_authors_remove(
    entity_type: str = typer.Argument(help="Entity type (agent, mcp, skill, hook, prompt, sandbox)"),
    entity_id: str = typer.Argument(help="Entity UUID or name"),
    user_id: str = typer.Argument(help="UUID of the co-author to remove"),
):
    """Remove a co-author from an agent or component."""
    t = _resolve_entity_type(entity_type)
    client.delete(f"/{t}/{entity_id}/co-authors/{user_id}")
    rprint("[green]Co-author removed.[/green]")
