# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""observal reconcile: push local session transcripts to the Observal server.

Scans IDE session directories for transcripts not yet pushed and uploads them.
Currently supports Antigravity CLI (brain/<id>/.system_generated/logs/transcript.jsonl).
"""

from __future__ import annotations

import time

import typer
from loguru import logger as optic
from rich import print as rprint

from observal_cli.sessions.base import (
    build_payload,
    load_config,
    post_to_server,
    read_cursor,
    read_new_lines,
    write_cursor,
)

reconcile_app = typer.Typer(name="reconcile", help="Push local session transcripts to the server")


@reconcile_app.callback(invoke_without_command=True)
def reconcile(
    ide: str = typer.Option("", "--ide", "-i", help="Target specific IDE (e.g. antigravity)"),
    since_hours: int = typer.Option(168, "--since", help="Only process sessions modified within N hours"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Show what would be pushed without sending"),
):
    """Push local session transcripts to the Observal server.

    Scans for session JSONL files that haven't been fully pushed yet and
    uploads them. Useful when hooks can't fire (e.g. agy on WSL).

    Examples:
        observal reconcile --ide antigravity
        observal reconcile --since 24
        observal reconcile --dry-run
    """
    optic.debug("reconcile: ide={}, since_hours={}", ide, since_hours)

    cfg = load_config()
    if cfg is None:
        rprint("[red]Not configured. Run [bold]observal auth login[/bold] first.[/red]")
        raise typer.Exit(1)

    targets = [ide] if ide else ["antigravity"]
    total_pushed = 0

    for target in targets:
        if target == "antigravity":
            pushed = _reconcile_antigravity(cfg, since_hours, dry_run)
            total_pushed += pushed

    if dry_run:
        rprint(f"\n[yellow]Dry run:[/yellow] {total_pushed} session(s) would be pushed.")
    elif total_pushed:
        rprint(f"\n[green]✓ Pushed {total_pushed} session(s) to Observal.[/green]")
    else:
        rprint("[dim]No new sessions to push.[/dim]")


def _reconcile_antigravity(cfg: dict, since_hours: int, dry_run: bool) -> int:
    """Scan antigravity brain/ for non-empty transcripts and push them."""
    from observal_cli.shared.utils import resolve_antigravity_dir

    ag_dir = resolve_antigravity_dir()
    if ag_dir is None:
        rprint("[dim]Antigravity not found — skipping[/dim]")
        return 0

    brain_dir = ag_dir / "brain"
    if not brain_dir.is_dir():
        rprint("[dim]No antigravity sessions found[/dim]")
        return 0

    cutoff = time.time() - since_hours * 3600
    pushed = 0

    rprint("[cyan]Antigravity - scanning sessions...[/cyan]")

    for session_dir in brain_dir.iterdir():
        if not session_dir.is_dir():
            continue

        transcript = session_dir / ".system_generated" / "logs" / "transcript.jsonl"
        if not transcript.exists():
            continue

        try:
            stat = transcript.stat()
            if stat.st_size == 0:
                continue
            if stat.st_mtime < cutoff:
                continue
        except OSError:
            continue

        session_id = session_dir.name

        # Check cursor — skip if already fully pushed
        offset, line_count = read_cursor(session_id)
        if offset >= stat.st_size:
            continue

        if dry_run:
            rprint(f"  [dim]Would push:[/dim] {session_id} ({stat.st_size - offset} bytes new)")
            pushed += 1
            continue

        # Read new lines from where we left off
        lines, bytes_read = read_new_lines(transcript, offset=offset)
        if not lines:
            continue

        new_offset = offset + bytes_read
        payload = build_payload(
            session_id=session_id,
            lines=lines,
            start_offset=line_count,
            hook_event="Stop",
            line_count_before=line_count,
            new_offset=new_offset,
            cwd="",
        )
        payload["ide"] = "antigravity"

        success = post_to_server(
            server_url=cfg["server_url"],
            access_token=cfg["access_token"],
            payload=payload,
        )

        if success:
            write_cursor(session_id, new_offset, line_count + len(lines), finalized=True)
            rprint(f"  [green]✓[/green] {session_id} ({len(lines)} lines)")
            pushed += 1
        else:
            rprint(f"  [red]✗[/red] {session_id} (push failed)")

    return pushed
