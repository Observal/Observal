# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""observal registry recommend: components picked for the signed-in user.

Recommendations are derived from the user's own session history, so this
command is deliberately self-only — there is no flag to read someone else's
profile, matching the server, which exposes no such route either.
"""

from __future__ import annotations

from contextlib import nullcontext

import typer
from rich import print as rprint
from rich.table import Table

from observal_cli import client
from observal_cli.errors import ErrorCategory, fail
from observal_cli.render import OutputMode, console, esc, output_json, spinner

recommend_app = typer.Typer(
    name="recommend",
    help=(
        "Components recommended for you, based on your own sessions\n\n"
        "Examples:\n"
        "  observal registry recommend\n"
        "  observal registry recommend --type mcp\n"
        "  observal registry recommend list --output json"
    ),
    no_args_is_help=False,
    invoke_without_command=True,
)

# Singular is what the API accepts; the plural forms are what registry
# commands and URLs use, so both are taken here to avoid a pointless error.
_TYPES = {
    "mcp": "mcps",
    "skill": "skills",
    "hook": "hooks",
    "prompt": "prompts",
    "sandbox": "sandboxes",
}
_TYPE_ALIASES = {**{t: t for t in _TYPES}, **{plural: t for t, plural in _TYPES.items()}}

_VALID_ACTIONS = ("dismissed", "not_relevant", "installed")


def _normalize_type(raw: str, operation: str = "List registry recommendations") -> str:
    normalized = _TYPE_ALIASES.get(raw.strip().lower())
    if normalized is None:
        fail(
            ErrorCategory.VALIDATION,
            f"Unknown component type: {raw}.",
            operation=operation,
            resource="component type",
            remediation=f"Choose one of: {', '.join(sorted(_TYPES))}.",
        )
    return normalized


def _emit(limit: int, type_: str | None, refresh: bool, output: OutputMode) -> None:
    params: dict[str, object] = {"limit": limit}
    if type_:
        params["type"] = _normalize_type(type_)
    if refresh:
        params["refresh"] = True

    fetch_ctx = nullcontext() if output == "json" else spinner("Fetching recommendations...")
    with fetch_ctx:
        data = client.get("/api/v1/recommendations/me", params=params)

    if output == "json":
        output_json(data)
        return

    items = data.get("items") or []
    personalized = bool(data.get("personalized"))
    sessions = data.get("profile_sessions") or 0
    topics = [t for t in (data.get("topics") or []) if t]

    if not items:
        # Silence here would be indistinguishable from a broken feature, so
        # say what the empty result actually means.
        rprint("[dim]Nothing to recommend right now.[/dim]")
        rprint(
            "[dim]Either the registry has no components visible to you, or you have already "
            "installed or dismissed them all.[/dim]"
        )
        return

    if personalized:
        heading = "Recommended for you"
        plural = "" if sessions == 1 else "s"
        subtitle = f"Based on {sessions} session{plural}"
        if topics:
            subtitle += f" — mostly {', '.join(topics[:3])}"
    else:
        # Never imply personalisation that did not happen.
        heading = "Popular in your registry"
        subtitle = "No session history yet, so these are simply the most-used components"

    table = Table(title=f"{heading} ({len(items)})", show_lines=False, padding=(0, 1))
    table.add_column("#", style="dim", width=3)
    table.add_column("Type")
    table.add_column("Component", style="bold", overflow="fold")
    table.add_column("Version")
    table.add_column("Installs", justify="right")
    table.add_column("Why")
    # Descriptions and reasons are free text; Rich would read a stray "[...]"
    # in them as a style tag and either swallow it or raise MarkupError.
    for i, item in enumerate(items, 1):
        table.add_row(
            str(i),
            esc(item.get("type", "")),
            esc(item.get("qualified_name") or item.get("name", "")),
            esc(item.get("latest_version") or "-"),
            esc(item.get("download_count", 0)),
            esc(item.get("reason", "")),
        )
    console.print(table)
    rprint(f"[dim]{esc(subtitle)}.[/dim]")
    rprint()

    first = items[0]
    first_type = esc(first.get("type", "skill"))
    first_name = esc(first.get("qualified_name") or first.get("name", ""))
    rprint(f"[dim]Inspect: [cyan]observal registry {first_type} show {first_name} --output json[/cyan][/dim]")
    rprint(f"[dim]Hide one: [cyan]observal registry recommend dismiss {first_type} {first_name}[/cyan][/dim]")


@recommend_app.callback(invoke_without_command=True)
def recommend(
    ctx: typer.Context,
    limit: int = typer.Option(8, "--limit", "-n", min=1, max=24, help="How many to return"),
    type_: str | None = typer.Option(None, "--type", "-t", help="Restrict to one component type"),
    refresh: bool = typer.Option(False, "--refresh", help="Recompute your profile instead of using the cache"),
    output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table or json"),
):
    """Show components recommended for you.

    Examples:

        observal registry recommend

        observal registry recommend --limit 12 --type mcp

        observal registry recommend --refresh --output json
    """
    if ctx.invoked_subcommand is None:
        _emit(limit, type_, refresh, output)


@recommend_app.command(name="list")
def recommend_list(
    limit: int = typer.Option(8, "--limit", "-n", min=1, max=24, help="How many to return"),
    type_: str | None = typer.Option(None, "--type", "-t", help="Restrict to one component type"),
    refresh: bool = typer.Option(False, "--refresh", help="Recompute your profile instead of using the cache"),
    output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table or json"),
):
    """Show components recommended for you.

    Examples:

        observal registry recommend list --output json
    """
    _emit(limit, type_, refresh, output)


@recommend_app.command(name="dismiss")
def recommend_dismiss(
    component_type: str = typer.Argument(..., help="Component type: mcp, skill, hook, prompt, sandbox"),
    reference: str = typer.Argument(..., help="Component ID, namespace/slug, or @alias"),
    action: str = typer.Option(
        "dismissed",
        "--action",
        "-a",
        help=f"Feedback to record: {', '.join(_VALID_ACTIONS)}",
    ),
    output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table or json"),
):
    """Stop recommending a component to you.

    Examples:

        observal registry recommend dismiss skill super/terraform-plan-review

        observal registry recommend dismiss mcp 0f2b... --action installed --output json
    """
    normalized = _normalize_type(component_type, "Update recommendation feedback")
    if action not in _VALID_ACTIONS:
        fail(
            ErrorCategory.VALIDATION,
            f"Unknown recommendation action: {action}.",
            operation="Update recommendation feedback",
            resource="action",
            remediation=f"Choose one of: {', '.join(_VALID_ACTIONS)}.",
        )

    feedback_context = nullcontext() if output == "json" else spinner("Recording feedback...")
    with feedback_context:
        component_id = client.resolve_registry_reference(_TYPES[normalized], reference)
        client.post(
            "/api/v1/recommendations/feedback",
            {"component_type": normalized, "component_id": component_id, "action": action},
        )

    result = {"component_type": normalized, "component_id": component_id, "action": action}
    if output == "json":
        output_json(result)
        return
    if action == "installed":
        rprint(f"[green]✓ Marked {normalized} {esc(reference)} as installed.[/green]")
    else:
        rprint(f"[green]✓ {normalized} {esc(reference)} will no longer be recommended to you.[/green]")
