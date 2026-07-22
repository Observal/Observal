# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""``observal team`` - teamspace creation, membership, and listing."""

from __future__ import annotations

import typer
from rich import print as rprint
from rich.table import Table

from observal_cli import client
from observal_cli.render import output_json

team_app = typer.Typer(name="team", help="Manage teamspaces: creation, membership, and listing.", no_args_is_help=True)
members_app = typer.Typer(name="members", help="Manage team membership.", no_args_is_help=True)
team_app.add_typer(members_app, name="members")


def _require_teamspaces() -> None:
    """Gate team commands on server support; clean message on older servers."""
    if not client.server_supports("teamspaces"):
        rprint("[yellow]Teamspaces are not supported by this server.[/yellow]")
        rprint("[dim]Update your server to v1.11.0 or later to use team commands.[/dim]")
        raise typer.Exit(1)


def _resolve_team_id(team: str) -> str:
    """Accept a UUID or a team handle; resolve to a UUID via the all-teams list."""
    import uuid as _uuid

    try:
        _uuid.UUID(team)
        return team
    except ValueError:
        pass
    teams = client.get("/api/v1/teams/all")
    for row in teams:
        if row.get("handle") == team.lower():
            return str(row["id"])
    raise typer.BadParameter(f"No teamspace with handle '{team}'", param_hint="team")


@team_app.command("list")
def list_teams(
    output: str = typer.Option("table", "--output", "-o", help="Output format: table | json"),
    all_teams: bool = typer.Option(False, "--all", help="List all teamspaces, not only yours."),
):
    """List teamspaces you belong to (or all with --all).

    Examples:

        observal team list

        observal team list --all

        observal team list --output json
    """
    _require_teamspaces()
    path = "/api/v1/teams/all" if all_teams else "/api/v1/teams"
    rows = client.get(path)
    if output == "json":
        output_json(rows)
        return
    if not rows:
        rprint("[dim]No teamspaces.[/dim]")
        return
    table = Table(title="Teamspaces")
    table.add_column("name", style="cyan")
    table.add_column("handle", style="green")
    table.add_column("role", style="dim")
    table.add_column("members", style="dim")
    for row in rows:
        table.add_row(
            row.get("name", ""),
            row.get("handle", ""),
            row.get("role") or "-",
            str(row.get("member_count") if row.get("member_count") is not None else "-"),
        )
    rprint(table)


@team_app.command("show")
def show_team(
    team: str = typer.Argument(help="Team UUID or handle."),
    output: str = typer.Option("table", "--output", "-o", help="Output format: table | json"),
):
    """Show teamspace detail and members.

    Examples:

        observal team show platform-tools

        observal team show platform-tools --output json

        observal team show 36e0c516-7a7f-4fec-ad2c-b47eb426b8a7
    """
    _require_teamspaces()
    team_id = _resolve_team_id(team)
    detail = client.get(f"/api/v1/teams/{team_id}")
    members = client.get(f"/api/v1/teams/{team_id}/members")
    if output == "json":
        output_json({"team": detail, "members": members})
        return
    rprint(f"[cyan]{detail.get('name')}[/cyan]  [dim]{detail.get('handle')}[/dim]")
    if detail.get("description"):
        rprint(f"[dim]{detail['description']}[/dim]")
    rprint(f"your role: [green]{detail.get('role') or '-'}[/green]")
    table = Table(title="Members")
    table.add_column("user", style="cyan")
    table.add_column("role", style="green")
    for m in members:
        table.add_row((m.get("username") and f"@{m['username']}") or m.get("email", ""), m.get("role", ""))
    rprint(table)


@team_app.command("create")
def create_team(
    name: str = typer.Argument(help="Teamspace display name."),
    handle: str = typer.Option(None, "--handle", "-h", help="Namespace handle (derived from name if omitted)."),
    description: str = typer.Option(None, "--description", "-d", help="Teamspace description."),
):
    """Create a teamspace. Requires reviewer role or above. You become the owner.

    The handle is reserved across users and teams, so it must not collide with
    an existing username or team handle.

    Examples:

        observal team create 'Platform Tools' --handle platform-tools --description 'Internal tooling'

        observal team create 'SRE' -h sre -d 'Site reliability'
    """
    _require_teamspaces()
    body: dict = {"name": name}
    if handle:
        body["handle"] = handle
    if description:
        body["description"] = description
    resp = client.post("/api/v1/teams", json_data=body)
    rprint(
        f"[green]Created teamspace:[/green] {resp.get('name')} ([dim]{resp.get('handle')}[/dim]) id={resp.get('id')}"
    )


@team_app.command("delete")
def delete_team(
    team: str = typer.Argument(help="Team UUID or handle."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
):
    """Delete a teamspace. Owner or admin only. This cannot be undone.

    Examples:

        observal team delete platform-tools --yes

        observal team delete 36e0c516-7a7f-4fec-ad2c-b47eb426b8a7 -y
    """
    _require_teamspaces()
    team_id = _resolve_team_id(team)
    if not yes and not typer.confirm(f"Delete teamspace '{team}'? This cannot be undone."):
        raise typer.Abort()
    client.delete(f"/api/v1/teams/{team_id}")
    rprint("[green]Teamspace deleted.[/green]")


@team_app.command("leave")
def leave_team(
    team: str = typer.Argument(help="Team UUID or handle."),
):
    """Leave a teamspace. The last owner cannot leave; transfer ownership first.

    Examples:

        observal team leave platform-tools

        observal team leave sre
    """
    _require_teamspaces()
    team_id = _resolve_team_id(team)
    client.post(f"/api/v1/teams/{team_id}/leave")
    rprint("[green]Left teamspace.[/green]")


@members_app.command("list")
def list_members(
    team: str = typer.Argument(help="Team UUID or handle."),
    output: str = typer.Option("table", "--output", "-o", help="Output format: table | json"),
):
    """List members of a teamspace.

    Examples:

        observal team members list platform-tools

        observal team members list sre --output json
    """
    _require_teamspaces()
    team_id = _resolve_team_id(team)
    rows = client.get(f"/api/v1/teams/{team_id}/members")
    if output == "json":
        output_json(rows)
        return
    table = Table(title="Members")
    table.add_column("user", style="cyan")
    table.add_column("email", style="dim")
    table.add_column("role", style="green")
    for m in rows:
        table.add_row((m.get("username") and f"@{m['username']}") or "-", m.get("email", ""), m.get("role", ""))
    rprint(table)


@members_app.command("add")
def add_member(
    team: str = typer.Argument(help="Team UUID or handle."),
    user: str = typer.Argument(help="Email or @username of the user to add."),
    role: str = typer.Option("member", "--role", "-r", help="Role: member | reviewer | owner."),
):
    """Add or update a team member. Owner or admin only.

    If the user is already a member, their role is updated.

    Examples:

        observal team members add platform-tools alice@example.com --role reviewer

        observal team members add sre @bob -r owner
    """
    _require_teamspaces()
    team_id = _resolve_team_id(team)
    body: dict = {"role": role}
    if "@" in user and not user.startswith("@"):
        body["email"] = user.lower()
    else:
        body["username"] = user.lstrip("@")
    resp = client.post(f"/api/v1/teams/{team_id}/members", json_data=body)
    rprint(f"[green]Member saved:[/green] {resp.get('email', user)} as {resp.get('role')}")


@members_app.command("remove")
def remove_member(
    team: str = typer.Argument(help="Team UUID or handle."),
    user: str = typer.Argument(help="Email or @username of the member to remove."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
):
    """Remove a team member. Owner or admin only. The last owner cannot be removed.

    Examples:

        observal team members remove platform-tools @bob --yes

        observal team members remove sre alice@example.com -y
    """
    _require_teamspaces()
    team_id = _resolve_team_id(team)
    members = client.get(f"/api/v1/teams/{team_id}/members")
    target = None
    for m in members:
        if (m.get("username") and user.lstrip("@") == m["username"]) or user.lower() == m.get("email", "").lower():
            target = m
            break
    if not target:
        raise typer.BadParameter(f"Member '{user}' not found in this team", param_hint="user")
    if not yes and not typer.confirm(f"Remove {user} from this team?"):
        raise typer.Abort()
    client.delete(f"/api/v1/teams/{team_id}/members/{target['id']}")
    rprint("[green]Member removed.[/green]")
