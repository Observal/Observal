# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Public reconciliation command backed by harness adapters and the shared outbox."""

from __future__ import annotations

import typer
from loguru import logger as optic
from rich import print as rprint

from observal_cli.harness import ensure_loaded, get_adapter, get_all_adapters
from observal_cli.sessions.base import drain_outbox, drain_session_source, load_config, read_cursor

reconcile_app = typer.Typer(name="reconcile", help="Push local session transcripts to the server")


@reconcile_app.callback(invoke_without_command=True)
def reconcile(
    harness: str = typer.Option("", "--harness", "-i", help="Target specific harness (e.g. antigravity)"),
    since_hours: int = typer.Option(168, "--since", help="Only process sessions modified within N hours"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Show what would be pushed without sending"),
):
    """Push local session transcripts through durable acknowledged delivery."""
    optic.debug("reconcile: harness={}, since_hours={}", harness, since_hours)
    cfg = load_config()
    if cfg is None:
        rprint("[red]Not configured. Run [bold]observal auth login[/bold] first.[/red]")
        raise typer.Exit(1)

    ensure_loaded()
    if not dry_run:
        drain_outbox(cfg)
    targets = (
        [harness]
        if harness
        else [name for name, adapter in get_all_adapters().items() if adapter.is_installed()]
    )
    total = sum(_reconcile_harness(target, cfg, since_hours, dry_run) for target in targets)
    if dry_run:
        rprint(f"\n[yellow]Dry run:[/yellow] {total} session(s) would be pushed.")
    elif total:
        rprint(f"\n[green]✓ Pushed {total} session(s) to Observal.[/green]")
    else:
        rprint("[dim]No new sessions to push.[/dim]")


def _reconcile_harness(harness: str, cfg: dict, since_hours: int, dry_run: bool) -> int:
    """Drain one adapter's recent sources through the shared delivery engine."""
    try:
        adapter = get_adapter(harness)
    except KeyError:
        rprint(f"[red]Unknown harness:[/red] {harness}")
        return 0

    sources = adapter.discover_session_sources(since_hours=since_hours)
    if not sources:
        rprint(f"[dim]No {harness} sessions found[/dim]")
        return 0

    pushed = 0
    rprint(f"[cyan]{harness} - scanning sessions...[/cyan]")
    for source in sources:
        if source.path is None:
            continue
        try:
            size = source.path.stat().st_size
        except OSError:
            continue
        offset, _line_count = read_cursor(source.checkpoint_key)
        if offset >= size:
            continue
        if dry_run:
            rprint(f"  [dim]Would push:[/dim] {source.session_id} ({size - offset} bytes new)")
            pushed += 1
            continue
        if drain_session_source(source, cfg, hook_event="Reconcile", final=True):
            rprint(f"  [green]✓[/green] {source.session_id}")
            pushed += 1
        else:
            rprint(f"  [yellow]↻[/yellow] {source.session_id} queued for retry")
    return pushed
