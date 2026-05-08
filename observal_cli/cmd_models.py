"""``observal registry models list`` — list the known model catalog."""

from __future__ import annotations

import json

import typer
from rich import print as rprint
from rich.table import Table

from observal_cli import model_catalog
from observal_cli.render import format_model

models_app = typer.Typer(
    name="models",
    help="Inspect the model catalog (live from models.dev with offline fallback).",
    no_args_is_help=True,
)


@models_app.command("list")
def list_models(
    ide: str | None = typer.Option(None, "--ide", help="Filter to models supported by this IDE."),
    output: str = typer.Option("table", "--output", "-o", help="Output format: table | json | plain"),
    refresh: bool = typer.Option(False, "--refresh", help="Bypass the local 1h file cache and re-fetch."),
):
    """Show models from the registry.

    Source order: file cache (1h TTL) → ``GET /api/v1/models`` → file cache (stale)
    → vendored offline mirror. Each output line marks where the data came from.
    """
    catalog = model_catalog.fetch_catalog(refresh=refresh)
    rows = catalog.get("models") or []
    if ide:
        rows = [m for m in rows if ide in (m.get("supported_ides") or [])]

    if output == "json":
        rprint(json.dumps(rows, indent=2, default=str))
        return

    if not rows:
        rprint("[yellow]No models found.[/yellow]")
        return

    if output == "plain":
        for m in rows:
            primary, secondary, _ = format_model(m, disambiguate=True)
            label = f"{primary} ({secondary})" if secondary else primary
            ides = ",".join(m.get("supported_ides") or [])
            rprint(f"{m.get('model_id', '')}\t{m.get('provider', '')}\t{label}\t{ides}")
        return

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("model_id", overflow="fold")
    table.add_column("provider")
    table.add_column("display")
    table.add_column("ides")
    table.add_column("released")

    for m in rows:
        primary, secondary, _ = format_model(m, disambiguate=True)
        label = f"{primary} ({secondary})" if secondary else primary
        ides = ", ".join(m.get("supported_ides") or [])
        released = str(m.get("release_date") or "—")
        deprecated = " [red](deprecated)[/red]" if m.get("deprecated") else ""
        table.add_row(
            m.get("model_id", "") + deprecated,
            m.get("provider", ""),
            label,
            ides,
            released,
        )

    rprint(table)
    src = catalog.get("_source") or catalog.get("source") or "?"
    degraded = " [yellow](degraded — using snapshot)[/yellow]" if catalog.get("degraded") else ""
    rprint(f"[dim]source: {src}{degraded}, count: {len(rows)}[/dim]")
