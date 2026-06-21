# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""observal logs - live log viewer.

observal logs                  # follow local dev.log
observal logs --remote         # stream from hosted server via SSE
observal logs --level WARNING  # only warnings and above
observal logs --filter ingest  # grep for 'ingest'
observal logs --no-color       # disable ANSI colors

"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.text import Text

logs_app = typer.Typer(name="logs", help="Live log viewer (open in a separate tab)")

LOG_PATH = Path.home() / ".observal" / "logs" / "dev.log"

LEVEL_STYLES = {
    "TRACE": "dim blue",
    "DEBUG": "dim",
    "INFO": "green",
    "WARNING": "yellow",
    "ERROR": "red bold",
    "CRITICAL": "red bold reverse",
}

_LEVEL_RANK = {"TRACE": 0, "DEBUG": 1, "INFO": 2, "WARNING": 3, "ERROR": 4, "CRITICAL": 5}


def _level_rank(level: str) -> int:
    return _LEVEL_RANK.get(level.upper(), 0)


def _parse_level(line: str) -> str | None:
    for level in LEVEL_STYLES:
        if f"| {level} " in line or f"| {level}" in line:
            return level
    return None


def _print_line(console: Console, line: str, *, no_color: bool) -> None:
    """Print a raw log line (from file) with optional color."""
    if no_color:
        console.print(line.rstrip(), highlight=False)
        return
    level = _parse_level(line)
    if level:
        text = Text(line.rstrip())
        text.stylize(LEVEL_STYLES.get(level, ""))
        console.print(text)
    else:
        console.print(line.rstrip())


def _print_entry(console: Console, entry: dict, *, no_color: bool) -> None:
    """Print a structured SSE entry with optional color."""
    level = entry.get("level", "INFO")
    ts = entry.get("timestamp", "")
    ts_short = ts[11:23] if len(ts) >= 23 else ts
    msg = entry.get("event", "")
    source = "{}:{}:{}".format(
        entry.get("logger_name", ""),
        entry.get("function", ""),
        entry.get("line", ""),
    )
    formatted = f"{ts_short} | {level:<7} | {source} - {msg}"

    if no_color:
        console.print(formatted, highlight=False)
        return
    text = Text(formatted)
    text.stylize(LEVEL_STYLES.get(level, ""))
    console.print(text)


# ---------------------------------------------------------------------------
# Remote streaming (SSE)
# ---------------------------------------------------------------------------


def _stream_remote(console: Console, *, level: str, filter_text: str, no_color: bool) -> None:
    """Connect to the server's SSE log stream and print entries."""
    import httpx

    from observal_cli import config
    from observal_cli.client import _get_cli_version

    cfg = config.get_or_exit()
    base_url = cfg["server_url"].rstrip("/")
    token = cfg["access_token"]

    url = f"{base_url}/api/v1/admin/logs/stream"
    params: dict = {"level": level}
    if filter_text:
        params["filter"] = filter_text

    console.print(f"[dim]Connecting to {base_url} …[/dim]")

    try:
        with httpx.stream(
            "GET",
            url,
            params=params,
            headers={
                "Authorization": f"Bearer {token}",
                "X-Observal-CLI-Version": _get_cli_version(),
            },
            timeout=None,
        ) as resp:
            if resp.status_code == 401:
                console.print("[red]Authentication failed.[/red] Run `observal auth login`.")
                raise typer.Exit(1)
            if resp.status_code == 403:
                console.print("[red]Admin access required.[/red] Only admins can stream server logs.")
                raise typer.Exit(1)
            if resp.status_code != 200:
                console.print(f"[red]Server returned {resp.status_code}[/red]")
                raise typer.Exit(1)

            console.print("[dim]- Streaming (Ctrl+C to stop) -[/dim]\n")

            for line in resp.iter_lines():
                if not line:
                    continue
                if line.startswith(": "):
                    continue  # SSE keepalive comment
                if line.startswith("data: "):
                    try:
                        entry = json.loads(line[6:])
                        _print_entry(console, entry, no_color=no_color)
                    except (json.JSONDecodeError, ValueError):
                        console.print(line[6:])
    except httpx.ConnectError:
        console.print("[red]Cannot connect.[/red] Is the server running?")
        raise typer.Exit(1)
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped.[/dim]")
        sys.exit(0)


# ---------------------------------------------------------------------------
# Main command
# ---------------------------------------------------------------------------


@logs_app.callback(invoke_without_command=True)
def logs(
    level: str = typer.Option("DEBUG", "--level", "-l", help="Minimum level (TRACE, DEBUG, INFO, WARNING, ERROR)"),
    filter_text: str = typer.Option("", "--filter", "-f", help="Only show lines containing this text"),
    lines: int = typer.Option(20, "--lines", "-n", help="Recent lines to show before following"),
    no_follow: bool = typer.Option(False, "--no-follow", help="Print recent lines and exit"),
    remote: bool = typer.Option(False, "--remote", "-r", help="Stream from the connected server via SSE"),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output"),
):
    """Live-follow Observal logs.

    By default reads the local dev.log file.  Use --remote to stream from
    a hosted server (requires admin access).

    For Docker deployments, local mode won't work because the log file
    is inside the container.  Always use --remote for hosted instances.
    """
    console = Console(stderr=True, no_color=no_color)

    if remote:
        _stream_remote(console, level=level, filter_text=filter_text, no_color=no_color)
        return

    # Local file mode
    if not LOG_PATH.exists():
        console.print(
            f"[yellow]No log file at {LOG_PATH}[/yellow]\n"
            + "[dim]Try [bold]observal logs --remote[/bold] to stream from a hosted server.[/dim]"
        )
        raise typer.Exit(1)

    min_rank = _level_rank(level)

    def _should_show(line: str) -> bool:
        line_level = _parse_level(line)
        if line_level and _level_rank(line_level) < min_rank:
            return False
        return not (filter_text and filter_text.lower() not in line.lower())

    # Show last N lines
    try:
        from collections import deque

        with open(LOG_PATH) as f:
            all_lines = list(deque(f, maxlen=lines)) if lines > 0 else []
    except OSError:
        all_lines = []

    for line in all_lines:
        if _should_show(line):
            _print_line(console, line.rstrip("\n"), no_color=no_color)

    if no_follow:
        return

    console.print(f"\n[dim]- Following {LOG_PATH} (Ctrl+C to stop) -[/dim]\n")

    try:
        with open(LOG_PATH) as f:
            f.seek(0, 2)
            while True:
                line = f.readline()
                if line:
                    if _should_show(line):
                        _print_line(console, line.rstrip("\n"), no_color=no_color)
                else:
                    time.sleep(0.1)
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped.[/dim]")
        sys.exit(0)
