# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""``observal team`` - teamspace creation, membership, and listing."""

from __future__ import annotations

from uuid import UUID

import typer
from rich import print as rprint
from rich.table import Table
from typer.models import OptionInfo

from observal_cli import client
from observal_cli.errors import ErrorCategory, fail
from observal_cli.render import OutputMode, esc, output_json

team_app = typer.Typer(
    name="team",
    help=(
        "Manage teamspaces: creation, membership, access, and visibility.\n\n"
        "Examples:\n"
        "  observal team list\n"
        "  observal team show platform-tools\n"
        "  observal team members list platform-tools"
    ),
    no_args_is_help=True,
)
members_app = typer.Typer(
    name="members",
    help=(
        "Manage team membership.\n\n"
        "Examples:\n"
        "  observal team members list platform-tools\n"
        "  observal team members add platform-tools alice@example.com\n"
        "  observal team members remove platform-tools @alice"
    ),
    no_args_is_help=True,
)
invite_app = typer.Typer(
    name="invite",
    help=(
        "Manage private-team invitation links.\n\n"
        "Examples:\n"
        "  observal team invite list platform-tools\n"
        "  observal team invite create platform-tools\n"
        "  observal team invite preview INVITE_TOKEN"
    ),
    no_args_is_help=True,
)
visibility_app = typer.Typer(
    name="visibility",
    help=(
        "Manage and review teamspace visibility.\n\n"
        "Examples:\n"
        "  observal team visibility set platform-tools private\n"
        "  observal team visibility list-requests\n"
        "  observal team visibility approve platform-tools"
    ),
    no_args_is_help=True,
)
request_app = typer.Typer(
    name="request",
    help=(
        "Manage teamspace join requests.\n\n"
        "Examples:\n"
        "  observal team request join platform-tools\n"
        "  observal team request mine platform-tools\n"
        "  observal team request list platform-tools"
    ),
    no_args_is_help=True,
)
team_app.add_typer(members_app, name="members")
team_app.add_typer(invite_app, name="invite")
team_app.add_typer(visibility_app, name="visibility")
team_app.add_typer(request_app, name="request")

_VISIBILITIES = ("public", "private")
_ROLES = ("member", "reviewer", "owner")
_REQUEST_STATUSES = ("pending", "approved", "rejected", "cancelled")


def _option_value(value):
    return value.default if isinstance(value, OptionInfo) else value


def _validate_choice(value: str, allowed: tuple[str, ...], label: str, operation: str) -> str:
    normalized = value.strip().lower()
    if normalized not in allowed:
        fail(
            ErrorCategory.VALIDATION,
            f"Unknown {label}: {value}.",
            operation=operation,
            resource=label,
            remediation=f"Choose from: {', '.join(allowed)}.",
        )
    return normalized


def _validate_text(value: str | None, label: str, max_length: int, operation: str) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > max_length:
        fail(
            ErrorCategory.VALIDATION,
            f"{label.capitalize()} must contain 1 to {max_length} characters.",
            operation=operation,
            resource=label,
            remediation=f"Provide a non-empty {label} within the server limit.",
        )
    return normalized


def _validate_uuid(value: str, label: str, operation: str) -> str:
    try:
        return str(UUID(value))
    except ValueError:
        fail(
            ErrorCategory.VALIDATION,
            f"{label.capitalize()} must be a UUID.",
            operation=operation,
            resource=label,
            remediation=f"Copy the {label} from a JSON list result.",
        )


def _resolve_team_id(team: str) -> str:
    """Accept a UUID or a team handle; resolve through the shared client helper."""
    try:
        return client.resolve_team_id(team)
    except typer.BadParameter as error:
        fail(
            ErrorCategory.NOT_FOUND,
            f"Teamspace not found: {team}.",
            operation="Resolve teamspace",
            resource="teamspace",
            remediation="Check the handle or list available teamspaces.",
            detail=str(error),
        )


def _require_confirmation(output: OutputMode | str, yes: bool, operation: str) -> bool:
    output = _option_value(output)
    yes = _option_value(yes)
    if output == "json" and not yes:
        fail(
            ErrorCategory.VALIDATION,
            "JSON mode cannot prompt for this teamspace change.",
            operation=operation,
            resource="teamspace",
            remediation="Add --yes to confirm the operation.",
        )
    return yes


def _render_team(response: dict, title: str) -> None:
    table = Table(title=title)
    table.add_column("name", style="cyan")
    table.add_column("handle", style="green")
    table.add_column("visibility")
    table.add_column("review status")
    table.add_row(
        esc(response.get("name", "")),
        esc(response.get("handle", "")),
        esc(response.get("visibility", "")),
        esc(response.get("visibility_request_status") or "-"),
    )
    rprint(table)


def _render_join_requests(rows: list[dict], title: str) -> None:
    table = Table(title=title)
    table.add_column("user", style="cyan")
    table.add_column("status", style="green")
    table.add_column("message", style="dim")
    table.add_column("decided by", style="dim")
    table.add_column("reason", style="dim")
    for row in rows:
        table.add_row(
            esc((row.get("username") and f"@{row['username']}") or row.get("email", "") or "-"),
            esc(row.get("status", "")),
            esc(row.get("message") or "-"),
            esc((row.get("decided_by_username") and f"@{row['decided_by_username']}") or "-"),
            esc(row.get("decision_reason") or "-"),
        )
    rprint(table)


@team_app.command("list")
def list_teams(
    output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table | json"),
    all_teams: bool = typer.Option(False, "--all", help="List all teamspaces, not only yours."),
):
    """List teamspaces you belong to (or all with --all).

    Examples:

        observal team list

        observal team list --all

        observal team list --output json
    """
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
            esc(row.get("name", "")),
            esc(row.get("handle", "")),
            esc(row.get("role") or "-"),
            str(row.get("member_count") if row.get("member_count") is not None else "-"),
        )
    rprint(table)


@team_app.command("show")
def show_team(
    team: str = typer.Argument(help="Team UUID or handle."),
    output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table | json"),
):
    """Show teamspace detail and members.

    Examples:

        observal team show platform-tools

        observal team show platform-tools --output json

        observal team show 36e0c516-7a7f-4fec-ad2c-b47eb426b8a7
    """
    team_id = _resolve_team_id(team)
    detail = client.get(f"/api/v1/teams/{team_id}")
    members = client.get(f"/api/v1/teams/{team_id}/members")
    if output == "json":
        output_json({"team": detail, "members": members})
        return
    rprint(f"[cyan]{esc(detail.get('name'))}[/cyan]  [dim]{esc(detail.get('handle'))}[/dim]")
    if detail.get("description"):
        rprint(f"[dim]{esc(detail['description'])}[/dim]")
    rprint(f"your role: [green]{esc(detail.get('role') or '-')}[/green]")
    table = Table(title="Members")
    table.add_column("user", style="cyan")
    table.add_column("role", style="green")
    for m in members:
        table.add_row(
            esc((m.get("username") and f"@{m['username']}") or m.get("email", "")),
            esc(m.get("role", "")),
        )
    rprint(table)


@team_app.command("create")
def create_team(
    name: str = typer.Argument(help="Teamspace display name."),
    handle: str = typer.Option(None, "--handle", "-h", help="Namespace handle (derived from name if omitted)."),
    description: str = typer.Option(None, "--description", "-d", help="Teamspace description."),
    visibility: str = typer.Option("public", "--visibility", "-v", help="Visibility: public | private."),
    output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table | json"),
):
    """Create a teamspace. Any signed-in user can; you become the owner.

    The handle is reserved across users and teams, so it must not collide with
    an existing username or team handle. A private teamspace is hidden from
    users who are not members. Deployment admins retain operational access.

    Examples:

        observal team create 'Platform Tools' --handle platform-tools --description 'Internal tooling'

        observal team create 'SRE' -h sre -d 'Site reliability' --visibility private
    """
    name = _validate_text(name, "teamspace name", 255, "Create teamspace")
    visibility = _validate_choice(visibility, _VISIBILITIES, "teamspace visibility", "Create teamspace")
    handle = _option_value(handle)
    if handle is not None:
        handle = _validate_text(handle.lstrip("@"), "teamspace handle", 32, "Create teamspace")
    body: dict = {"name": name, "visibility": visibility}
    if handle:
        body["handle"] = handle.lower()
    if description:
        body["description"] = description
    resp = client.post("/api/v1/teams", json_data=body)
    if output == "json":
        output_json(resp)
        return
    rprint(
        f"[green]Created teamspace:[/green] {esc(resp.get('name'))} "
        f"([dim]{esc(resp.get('handle'))}[/dim]) {esc(resp.get('visibility', 'public'))} "
        f"id={esc(resp.get('id'))}"
    )


@team_app.command("claim-personal")
def claim_personal_teamspace(
    output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table | json"),
):
    """Claim or return your private personal teamspace.

    Examples:

        observal team claim-personal

        observal team claim-personal --output json
    """
    response = client.post("/api/v1/teams/claim-personal")
    if output == "json":
        output_json(response)
        return
    _render_team(response, "Personal teamspace")


@visibility_app.command("set")
def set_visibility(
    team: str = typer.Argument(help="Team UUID or handle."),
    visibility: str = typer.Argument(help="public | private"),
    output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table | json"),
):
    """Change visibility or request public review. Owners and admins only.

    Examples:

        observal team visibility set platform-tools private

        observal team visibility set sre public --output json
    """
    visibility = _validate_choice(visibility, _VISIBILITIES, "teamspace visibility", "Update teamspace visibility")
    team_id = _resolve_team_id(team)
    response = client.patch(f"/api/v1/teams/{team_id}/visibility", json_data={"visibility": visibility})
    if output == "json":
        output_json(response)
        return
    _render_team(response, "Teamspace visibility")


@visibility_app.command("list-requests")
def list_visibility_requests(
    output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table | json"),
):
    """List pending public visibility requests. Reviewer or admin only.

    Examples:

        observal team visibility list-requests

        observal team visibility list-requests --output json
    """
    rows = client.get("/api/v1/teams/visibility-requests")
    if output == "json":
        output_json(rows)
        return
    if not rows:
        rprint("[dim]No pending visibility requests.[/dim]")
        return
    table = Table(title="Pending public visibility requests")
    table.add_column("name", style="cyan")
    table.add_column("handle", style="green")
    table.add_column("requested by")
    table.add_column("requested at", style="dim")
    for row in rows:
        table.add_row(
            esc(row.get("name", "")),
            esc(row.get("handle", "")),
            esc((row.get("requested_by_username") and f"@{row['requested_by_username']}") or "-"),
            esc(row.get("requested_at", "")),
        )
    rprint(table)


@visibility_app.command("approve")
def approve_visibility_request(
    team: str = typer.Argument(help="Team UUID or handle."),
    output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table | json"),
):
    """Approve pending public visibility. Reviewer or admin only.

    Examples:

        observal team visibility approve platform-tools

        observal team visibility approve platform-tools --output json
    """
    team_id = _resolve_team_id(team)
    response = client.post(f"/api/v1/teams/{team_id}/visibility-request/approve")
    if output == "json":
        output_json(response)
        return
    _render_team(response, "Visibility request approved")


@visibility_app.command("reject")
def reject_visibility_request(
    team: str = typer.Argument(help="Team UUID or handle."),
    reason: str | None = typer.Option(None, "--reason", "-r", help="Optional reason shown to the owner."),
    output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table | json"),
):
    """Reject pending public visibility. Reviewer or admin only.

    Examples:

        observal team visibility reject platform-tools

        observal team visibility reject platform-tools --reason 'Needs a public description' --output json
    """
    reason = _option_value(reason)
    reason = (
        _validate_text(reason, "visibility rejection reason", 500, "Reject teamspace visibility")
        if reason is not None
        else None
    )
    team_id = _resolve_team_id(team)
    response = client.post(
        f"/api/v1/teams/{team_id}/visibility-request/reject",
        json_data={"reason": reason} if reason else {},
    )
    if output == "json":
        output_json(response)
        return
    _render_team(response, "Visibility request rejected")


@team_app.command("delete")
def delete_team(
    team: str = typer.Argument(help="Team UUID or handle."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
    output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table | json"),
):
    """Delete a teamspace. Owner or admin only. This cannot be undone.

    Examples:

        observal team delete platform-tools --yes

        observal team delete 36e0c516-7a7f-4fec-ad2c-b47eb426b8a7 -y
    """
    yes = _require_confirmation(output, yes, "Delete teamspace")
    team_id = _resolve_team_id(team)
    if not yes and not typer.confirm(f"Delete teamspace '{team}'? This cannot be undone."):
        raise typer.Abort()
    response = client.delete(f"/api/v1/teams/{team_id}")
    if output == "json":
        output_json(response)
        return
    rprint("[green]Teamspace deleted.[/green]")


@team_app.command("leave")
def leave_team(
    team: str = typer.Argument(help="Team UUID or handle."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
    output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table | json"),
):
    """Leave a teamspace. The last owner cannot leave; transfer ownership first.

    Examples:

        observal team leave platform-tools

        observal team leave sre
    """
    yes = _require_confirmation(output, yes, "Leave teamspace")
    team_id = _resolve_team_id(team)
    if not yes and not typer.confirm(f"Leave teamspace '{team}'?"):
        raise typer.Abort()
    response = client.post(f"/api/v1/teams/{team_id}/leave")
    if output == "json":
        output_json(response)
        return
    rprint("[green]Left teamspace.[/green]")


@members_app.command("list")
def list_members(
    team: str = typer.Argument(help="Team UUID or handle."),
    output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table | json"),
):
    """List members of a teamspace.

    Examples:

        observal team members list platform-tools

        observal team members list sre --output json
    """
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
        table.add_row(
            esc((m.get("username") and f"@{m['username']}") or "-"),
            esc(m.get("email", "")),
            esc(m.get("role", "")),
        )
    rprint(table)


@invite_app.command("create")
def create_invite(
    team: str = typer.Argument(help="Private team UUID or handle."),
    name: str | None = typer.Option(None, help="Readable invite name."),
    expires_days: int = typer.Option(7, min=1, max=365, help="Days until the link expires."),
    max_uses: int | None = typer.Option(
        None, min=1, max=10000, help="Maximum access requests; unlimited when omitted."
    ),
    output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table | json"),
):
    """Create a private-team invitation link. Owner or global admin only.

    Examples:
      observal team invite create platform-tools
      observal team invite create platform-tools --name onboarding --expires-days 30
    """
    invite_name = _validate_text(name, "invite name", 100, "Create team invite") if name is not None else None
    team_id = _resolve_team_id(team)
    body: dict = {"expires_in_days": expires_days}
    if invite_name is not None:
        body["name"] = invite_name
    if max_uses is not None:
        body["max_uses"] = max_uses
    response = client.post(f"/api/v1/teams/{team_id}/invites", json_data=body)
    if output == "json":
        output_json(response)
        return
    rprint(esc(response["url"]))


@invite_app.command("list")
def list_invites(
    team: str = typer.Argument(help="Private team UUID or handle."),
    output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table | json"),
):
    """List invitation links for a private teamspace.

    Examples:
      observal team invite list platform-tools
      observal team invite list platform-tools --output json
    """
    team_id = _resolve_team_id(team)
    rows = client.get(f"/api/v1/teams/{team_id}/invites")
    if output == "json":
        output_json(rows)
        return
    if not rows:
        rprint("[dim]No invite links.[/dim]")
        return
    table = Table(title="Private-team invite links")
    table.add_column("id", style="dim")
    table.add_column("name")
    table.add_column("state", style="green")
    table.add_column("uses")
    table.add_column("expires")
    table.add_column("created by")
    for row in rows:
        uses = str(row.get("use_count", 0))
        if row.get("max_uses") is not None:
            uses += f" / {row['max_uses']}"
        table.add_row(
            esc(row.get("id", "")),
            esc(row.get("name", "")),
            esc(row.get("state", "")),
            uses,
            esc(row.get("expires_at", "")),
            esc(row.get("invited_by_username") or "-"),
        )
    rprint(table)


@invite_app.command("revoke")
def revoke_invite(
    team: str = typer.Argument(help="Private team UUID or handle."),
    invite_id: str = typer.Argument(help="Invitation UUID."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
    output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table | json"),
):
    """Revoke a private-team invitation link. Owner or global admin only.

    Examples:
      observal team invite revoke platform-tools 550e8400-e29b-41d4-a716-446655440000
    """
    invite_id = _validate_uuid(invite_id, "invite ID", "Revoke team invite")
    yes = _require_confirmation(output, yes, "Revoke team invite")
    team_id = _resolve_team_id(team)
    if not yes and not typer.confirm(f"Revoke invite '{invite_id}'?"):
        raise typer.Abort()
    response = client.post(f"/api/v1/teams/{team_id}/invites/{invite_id}/revoke")
    if output == "json":
        output_json(response)
        return
    rprint(f"[green]Invite {esc(response.get('state'))}.[/green]")


@invite_app.command("preview")
def preview_invite(
    token: str = typer.Argument(help="Invitation token."),
    output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table | json"),
):
    """Preview an invitation without requesting access.

    Examples:

        observal team invite preview INVITE_TOKEN

        observal team invite preview INVITE_TOKEN --output json
    """
    token = _validate_text(token, "invite token", 128, "Preview team invite")
    response = client.post(
        "/api/v1/teams/invites/preview",
        json_data={"token": token},
        operation="Preview teamspace invite",
        resource="teamspace invitation",
    )
    if output == "json":
        output_json(response)
        return
    table = Table(title="Team invitation")
    table.add_column("team", style="cyan")
    table.add_column("handle", style="green")
    table.add_column("state")
    table.add_column("member")
    table.add_column("request")
    table.add_column("invited by")
    table.add_row(
        esc(response.get("team_name") or "-"),
        esc(response.get("team_handle") or "-"),
        esc(response.get("invite_state") or ("active" if response.get("valid") else "invalid")),
        "yes" if response.get("is_member") else "no",
        esc((response.get("request") or {}).get("status") or "-"),
        esc(response.get("invited_by") or "-"),
    )
    rprint(table)


@invite_app.command("request")
def request_via_invite(
    token: str = typer.Argument(help="Invitation token."),
    message: str | None = typer.Option(None, "--message", "-m", help="Optional note shown to the owners."),
    output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table | json"),
):
    """Use an invitation to request access. An owner must still approve.

    Examples:

        observal team invite request INVITE_TOKEN

        observal team invite request INVITE_TOKEN --message 'I maintain deployments' --output json
    """
    token = _validate_text(token, "invite token", 128, "Request teamspace access via invite")
    message = _option_value(message)
    message = (
        _validate_text(message, "join request message", 500, "Request teamspace access via invite")
        if message is not None
        else None
    )
    preview = client.post(
        "/api/v1/teams/invites/preview",
        json_data={"token": token},
        operation="Preview teamspace invite",
        resource="teamspace invitation",
    )
    team_id = preview.get("team_id")
    if not preview.get("valid") or not team_id:
        fail(
            ErrorCategory.NOT_FOUND,
            "Invitation is invalid or unavailable.",
            operation="Request teamspace access via invite",
            resource="teamspace invitation",
            remediation="Ask a team owner for a new invitation link.",
        )
    body: dict = {"invite_token": token}
    if message:
        body["message"] = message
    response = client.post(
        f"/api/v1/teams/{team_id}/join-requests",
        json_data=body,
        operation="Request teamspace access via invite",
        resource="teamspace invitation",
    )
    if output == "json":
        output_json(response)
        return
    _render_join_requests([response], "Join request")


@invite_app.command("delete")
def delete_invite(
    team: str = typer.Argument(help="Private team UUID or handle."),
    invite_id: str = typer.Argument(help="Unused invitation UUID."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
    output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table | json"),
):
    """Delete an unused invitation. Owner or global admin only.

    Examples:

        observal team invite delete platform-tools 550e8400-e29b-41d4-a716-446655440000

        observal team invite delete platform-tools 550e8400-e29b-41d4-a716-446655440000 --yes --output json
    """
    invite_id = _validate_uuid(invite_id, "invite ID", "Delete team invite")
    yes = _require_confirmation(output, yes, "Delete team invite")
    team_id = _resolve_team_id(team)
    if not yes and not typer.confirm(f"Delete unused invite '{invite_id}'?"):
        raise typer.Abort()
    response = client.delete(f"/api/v1/teams/{team_id}/invites/{invite_id}")
    if output == "json":
        output_json(response)
        return
    rprint("[green]Unused invite deleted.[/green]")


@invite_app.command("requests")
def list_invite_requests(
    team: str = typer.Argument(help="Private team UUID or handle."),
    invite_id: str = typer.Argument(help="Invitation UUID."),
    output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table | json"),
):
    """List access requests associated with an invitation.

    Examples:

        observal team invite requests platform-tools 550e8400-e29b-41d4-a716-446655440000

        observal team invite requests platform-tools 550e8400-e29b-41d4-a716-446655440000 --output json
    """
    invite_id = _validate_uuid(invite_id, "invite ID", "List team invite requests")
    team_id = _resolve_team_id(team)
    rows = client.get(f"/api/v1/teams/{team_id}/invites/{invite_id}/requests")
    if output == "json":
        output_json(rows)
        return
    if not rows:
        rprint("[dim]No requests for this invite.[/dim]")
        return
    _render_join_requests(rows, "Invite access requests")


@request_app.command("join")
def request_join(
    team: str = typer.Argument(help="Team UUID or handle."),
    message: str = typer.Option(None, "--message", "-m", help="Optional note shown to the owners."),
    output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table | json"),
):
    """Request member access to a teamspace. An owner must approve.

    Examples:

        observal team request join platform-tools

        observal team request join sre --message 'I maintain the pager rotation' --output json
    """
    message = _option_value(message)
    message = (
        _validate_text(message, "join request message", 500, "Request teamspace access")
        if message is not None
        else None
    )
    team_id = _resolve_team_id(team)
    body: dict = {}
    if message:
        body["message"] = message
    response = client.post(f"/api/v1/teams/{team_id}/join-requests", json_data=body)
    if output == "json":
        output_json(response)
        return
    _render_join_requests([response], "Join request")


@request_app.command("list")
def list_join_requests(
    team: str = typer.Argument(help="Team UUID or handle."),
    status: str = typer.Option(None, "--status", "-s", help="Filter: pending | approved | rejected | cancelled."),
    output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table | json"),
):
    """List a teamspace's join requests and decisions. Owner or admin only.

    Examples:

        observal team request list platform-tools

        observal team request list sre --status pending --output json
    """
    status = _option_value(status)
    status = (
        _validate_choice(status, _REQUEST_STATUSES, "join request status", "List join requests") if status else None
    )
    team_id = _resolve_team_id(team)
    params = {"status": status} if status else None
    rows = client.get(f"/api/v1/teams/{team_id}/join-requests", params=params)
    if output == "json":
        output_json(rows)
        return
    if not rows:
        rprint("[dim]No join requests.[/dim]")
        return
    _render_join_requests(rows, "Join requests")


@request_app.command("mine")
def list_my_join_requests(
    team: str = typer.Argument(help="Team UUID or handle."),
    output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table | json"),
):
    """Show your join-request status for a teamspace.

    Examples:

        observal team request mine platform-tools

        observal team request mine platform-tools --output json
    """
    team_id = _resolve_team_id(team)
    rows = client.get(f"/api/v1/teams/{team_id}/join-requests/mine")
    if output == "json":
        output_json(rows)
        return
    if not rows:
        rprint("[dim]You have no join requests for this teamspace.[/dim]")
        return
    _render_join_requests(rows, "Your join requests")


@request_app.command("withdraw")
def withdraw_join_request(
    team: str = typer.Argument(help="Team UUID or handle."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
    output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table | json"),
):
    """Withdraw your pending join request for a teamspace.

    Examples:

        observal team request withdraw platform-tools

        observal team request withdraw platform-tools --yes --output json
    """
    yes = _require_confirmation(output, yes, "Withdraw teamspace join request")
    team_id = _resolve_team_id(team)
    rows = client.get(f"/api/v1/teams/{team_id}/join-requests/mine")
    pending = next((row for row in rows if row.get("status") == "pending"), None)
    if pending is None:
        fail(
            ErrorCategory.NOT_FOUND,
            "You have no pending join request for this teamspace.",
            operation="Withdraw teamspace join request",
            resource="team join request",
            remediation="Check your request status before retrying.",
        )
    if not yes and not typer.confirm(f"Withdraw your pending request to join '{team}'?"):
        raise typer.Abort()
    response = client.delete(f"/api/v1/teams/{team_id}/join-requests/{pending['id']}")
    if output == "json":
        output_json(response)
        return
    rprint("[green]Join request withdrawn.[/green]")


def _find_pending_request(team_id: str, user: str, *, operation: str) -> dict:
    user = _validate_text(user, "requester identity", 320, operation)
    rows = client.get(f"/api/v1/teams/{team_id}/join-requests", params={"status": "pending"})
    needle = user.lstrip("@").lower()
    for r in rows:
        if (r.get("username") or "").lower() == needle or (r.get("email") or "").lower() == needle:
            return r
    fail(
        ErrorCategory.NOT_FOUND,
        f"No pending join request from {user}.",
        operation=operation,
        resource="team join request",
        remediation="List pending requests and choose an exact email or username.",
    )


@request_app.command("approve")
def approve_join_request(
    team: str = typer.Argument(help="Team UUID or handle."),
    user: str = typer.Argument(help="Email or @username of the requester."),
    output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table | json"),
):
    """Approve a pending join request. Owner or admin only. Grants member role.

    Examples:

        observal team request approve platform-tools @alice

        observal team request approve sre bob@example.com --output json
    """
    user = _validate_text(user, "requester identity", 320, "Approve team join request")
    team_id = _resolve_team_id(team)
    req = _find_pending_request(team_id, user, operation="Approve team join request")
    response = client.post(f"/api/v1/teams/{team_id}/join-requests/{req['id']}/approve")
    if output == "json":
        output_json(response)
        return
    _render_join_requests([response], "Approved join request")


@request_app.command("reject")
def reject_join_request(
    team: str = typer.Argument(help="Team UUID or handle."),
    user: str = typer.Argument(help="Email or @username of the requester."),
    reason: str = typer.Option(None, "--reason", "-r", help="Optional reason shown to the requester."),
    output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table | json"),
):
    """Reject a pending join request. Owner or admin only.

    Examples:

        observal team request reject platform-tools @alice --reason 'Use the sre teamspace instead'

        observal team request reject sre bob@example.com --output json
    """
    user = _validate_text(user, "requester identity", 320, "Reject team join request")
    reason = _option_value(reason)
    reason = _validate_text(reason, "rejection reason", 500, "Reject team join request") if reason is not None else None
    team_id = _resolve_team_id(team)
    req = _find_pending_request(team_id, user, operation="Reject team join request")
    body: dict = {}
    if reason:
        body["reason"] = reason
    response = client.post(f"/api/v1/teams/{team_id}/join-requests/{req['id']}/reject", json_data=body)
    if output == "json":
        output_json(response)
        return
    _render_join_requests([response], "Rejected join request")


@members_app.command("add")
def add_member(
    team: str = typer.Argument(help="Team UUID or handle."),
    user: str = typer.Argument(help="Email or @username of the user to add."),
    role: str = typer.Option("member", "--role", "-r", help="Role: member | reviewer | owner."),
    output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table | json"),
):
    """Add or update a team member. Owner or admin only.

    If the user is already a member, their role is updated.

    Examples:

        observal team members add platform-tools alice@example.com --role reviewer

        observal team members add sre @bob -r owner
    """
    user = _validate_text(user, "member identity", 320, "Add team member")
    role = _validate_choice(role, _ROLES, "team member role", "Add team member")
    team_id = _resolve_team_id(team)
    body: dict = {"role": role}
    if "@" in user and not user.startswith("@"):
        body["email"] = user.lower()
    else:
        body["username"] = user.lstrip("@")
    resp = client.post(f"/api/v1/teams/{team_id}/members", json_data=body)
    if output == "json":
        output_json(resp)
        return
    rprint(f"[green]Member saved:[/green] {esc(resp.get('email', user))} as {esc(resp.get('role'))}")


@members_app.command("remove")
def remove_member(
    team: str = typer.Argument(help="Team UUID or handle."),
    user: str = typer.Argument(help="Email or @username of the member to remove."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
    output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table | json"),
):
    """Remove a team member. Owner or admin only. The last owner cannot be removed.

    Examples:

        observal team members remove platform-tools @bob --yes

        observal team members remove sre alice@example.com -y
    """
    user = _validate_text(user, "member identity", 320, "Remove team member")
    yes = _require_confirmation(output, yes, "Remove team member")
    team_id = _resolve_team_id(team)
    members = client.get(f"/api/v1/teams/{team_id}/members")
    target = None
    needle = user.lstrip("@").lower()
    for member in members:
        if (member.get("username") or "").lower() == needle or (member.get("email") or "").lower() == needle:
            target = member
            break
    if not target:
        fail(
            ErrorCategory.NOT_FOUND,
            f"Team member not found: {user}.",
            operation="Remove team member",
            resource="team membership",
            remediation="List team members and choose an exact email or username.",
        )
    if not yes and not typer.confirm(f"Remove {user} from this team?"):
        raise typer.Abort()
    response = client.delete(f"/api/v1/teams/{team_id}/members/{target['id']}")
    if output == "json":
        output_json(response)
        return
    rprint("[green]Member removed.[/green]")
