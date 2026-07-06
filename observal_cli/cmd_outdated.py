# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""observal outdated: compare lock file version pins against registry latest."""

from __future__ import annotations

import typer
from rich import print as rprint
from rich.table import Table

from observal_cli import client
from observal_cli.render import console, spinner

outdated_app = typer.Typer(
    name="outdated",
    help="Check for newer versions of installed agents and components",
    no_args_is_help=False,
    invoke_without_command=True,
)


def register_outdated(app: typer.Typer):
    @app.command("outdated")
    def outdated(
        harness: str | None = typer.Option(None, "--harness", "-i", help="Filter by harness"),
        output: str = typer.Option("table", "--output", "-o", help="Output format: table or json"),
    ):
        """Show installed components that have newer versions available.

        Reads ~/.observal/lockfile.json and checks the registry for each
        pinned agent/component to see if a newer version exists.

        Examples:
          observal outdated
          observal outdated --harness claude-code
          observal outdated --output json
        """
        from observal_cli.lockfile import get_all_entries

        entries = get_all_entries(harness=harness)
        if not entries:
            rprint("[dim]No installed agents or components found in lock file.[/dim]")
            rprint("[dim]Run `observal agent pull` or `observal registry mcp install` first.[/dim]")
            raise typer.Exit(0)

        rprint(f"\n[bold]Checking {len(entries)} installed item(s)...[/bold]\n")

        results: list[dict] = []

        with spinner("Fetching latest versions from registry..."):
            for entry in entries:
                entry_type = entry.get("entry_type", "")
                component_type = entry.get("type", "")
                entry_id = entry.get("id", "")
                current_version = entry.get("version")
                name = entry.get("name", entry_id[:8])

                if not entry_id or not current_version:
                    continue

                try:
                    if entry_type == "agent":
                        data = client.get(f"/api/v1/agents/{entry_id}")
                        latest = data.get("latest_approved_version") or data.get("version")
                    elif component_type == "mcp":
                        data = client.get(f"/api/v1/mcps/{entry_id}")
                        latest = data.get("version")
                    elif component_type == "skill":
                        data = client.get(f"/api/v1/skills/{entry_id}")
                        latest = data.get("version")
                    elif component_type == "hook":
                        data = client.get(f"/api/v1/hooks/{entry_id}")
                        latest = data.get("version")
                    else:
                        continue
                except (Exception, SystemExit):
                    results.append(
                        {
                            "name": name,
                            "type": entry_type if entry_type == "agent" else component_type,
                            "harness": entry.get("harness", ""),
                            "current": current_version,
                            "latest": "?",
                            "outdated": False,
                            "error": True,
                        }
                    )
                    continue

                is_outdated = latest and latest != current_version and _version_newer(latest, current_version)
                results.append(
                    {
                        "name": name,
                        "type": entry_type if entry_type == "agent" else component_type,
                        "harness": entry.get("harness", ""),
                        "current": current_version,
                        "latest": latest or current_version,
                        "outdated": is_outdated,
                        "error": False,
                    }
                )

        if output == "json":
            import json

            print(json.dumps(results, indent=2))
            return

        outdated_items = [r for r in results if r["outdated"]]
        up_to_date = [r for r in results if not r["outdated"] and not r["error"]]
        errors = [r for r in results if r["error"]]

        if outdated_items:
            table = Table(title="Outdated", show_header=True, header_style="bold")
            table.add_column("Name", style="cyan")
            table.add_column("Type", style="dim")
            table.add_column("harness", style="dim")
            table.add_column("Pinned", style="yellow")
            table.add_column("Latest", style="green")

            for item in outdated_items:
                table.add_row(
                    item["name"],
                    item["type"],
                    item["harness"],
                    item["current"],
                    item["latest"],
                )

            console.print(table)
            rprint(f"\n[yellow]{len(outdated_items)} item(s) have newer versions available.[/yellow]")
            rprint("[dim]Run `observal agent pull <name> --harness <harness>` to upgrade.[/dim]")
        else:
            rprint("[green]✓ All installed items are up to date.[/green]")

        if up_to_date:
            rprint(f"[dim]{len(up_to_date)} item(s) up to date.[/dim]")

        if errors:
            rprint(f"[dim]{len(errors)} item(s) could not be checked (registry unreachable or item deleted).[/dim]")


def _version_newer(latest: str, current: str) -> bool:
    """Check if latest is newer than current using simple semver comparison."""
    try:

        def _parse(v: str) -> tuple[int, ...]:
            return tuple(int(x) for x in v.split("."))

        return _parse(latest) > _parse(current)
    except (ValueError, AttributeError):
        return latest != current
