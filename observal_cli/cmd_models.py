# SPDX-License-Identifier: AGPL-3.0-only
"""``observal registry models`` - list registry-backed harness models."""

from __future__ import annotations

import json

import typer
from rich import print as rprint
from rich.table import Table

from observal_cli import model_catalog

models_app = typer.Typer(name="models", help="Inspect registry-backed harness model data.", no_args_is_help=False)


def _emit(harness: str | None, output: str) -> None:
    rows = model_catalog.fetch_catalog(harness=harness).get("models") or []
    if output == "json":
        rprint(json.dumps(rows, indent=2))
        return
    if output == "plain":
        for row in rows:
            rprint(f"{row['harness']}\t{row['model_id']}\t{row.get('kind','exact')}\t{row.get('display_name','')}")
        return
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("harness")
    table.add_column("model_id", overflow="fold")
    table.add_column("kind")
    table.add_column("display")
    for row in rows:
        table.add_row(row["harness"], row["model_id"], row.get("kind", "exact"), row.get("display_name", ""))
    rprint(table)
    rprint(f"[dim]source: harness-registry, count: {len(rows)}[/dim]")


@models_app.callback(invoke_without_command=True)
def models(
    ctx: typer.Context,
    harness: str | None = typer.Option(None, "--harness", help="Filter to one harness."),
    output: str = typer.Option("table", "--output", "-o", help="Output format: table | json | plain"),
):
    if ctx.invoked_subcommand is None:
        _emit(harness, output)


@models_app.command("list")
def list_models(
    harness: str | None = typer.Option(None, "--harness", help="Filter to one harness."),
    output: str = typer.Option("table", "--output", "-o", help="Output format: table | json | plain"),
):
    _emit(harness, output)
