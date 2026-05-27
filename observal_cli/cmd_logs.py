# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""observal logs - live dev log viewer (like Android Studio's Logcat tab).

Open in a separate terminal tab while using the app:

    observal logs                  # follow all logs
    observal logs --level WARNING  # only warnings and errors
    observal logs --filter ingest  # grep for 'ingest'
    observal logs --lines 50       # show last 50 lines then follow

"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.text import Text

logs_app = typer.Typer(name="logs", help="Live dev log viewer (open in a separate tab)")

LOG_PATH = Path.home() / ".observal" / "logs" / "dev.log"

# Level colors matching loguru's style
LEVEL_STYLES = {
    "DEBUG": "dim",
    "INFO": "green",
    "WARNING": "yellow",
    "ERROR": "red bold",
    "CRITICAL": "red bold reverse",
}


def _parse_level(line: str) -> str | None:
    """Extract the level from a formatted log line."""
    for level in LEVEL_STYLES:
        if f"| {level}" in line:
            return level
    return None


def _level_rank(level: str) -> int:
    ranks = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}
    return ranks.get(level.upper(), 0)


def _colorize_line(console: Console, line: str) -> None:
    """Print a log line with color based on its level."""
    level = _parse_level(line)
    if level:
        style = LEVEL_STYLES.get(level, "")
        text = Text(line.rstrip())
        text.stylize(style)
        console.print(text)
    else:
        console.print(line.rstrip())


@logs_app.callback(invoke_without_command=True)
def logs(
    level: str = typer.Option("DEBUG", "--level", "-l", help="Minimum log level (DEBUG, INFO, WARNING, ERROR)"),
    filter_text: str = typer.Option("", "--filter", "-f", help="Only show lines containing this text"),
    lines: int = typer.Option(20, "--lines", "-n", help="Number of recent lines to show before following"),
    no_follow: bool = typer.Option(False, "--no-follow", help="Print recent lines and exit (don't follow)"),
):
    """Live-follow the Observal dev log file.

    Open this in a separate terminal tab while using the app.
    Like Android Studio's Logcat - shows every action as it happens.
    """
    console = Console(stderr=True)

    if not LOG_PATH.exists():
        console.print(
            f"[yellow]No log file found at {LOG_PATH}[/yellow]\n"
            "[dim]Logs are written when the server runs without a license key (dev mode).[/dim]\n"
            "[dim]Set observability.log_format=console in Settings to enable file logging.[/dim]"
        )
        raise typer.Exit(1)

    min_rank = _level_rank(level)

    def _should_show(line: str) -> bool:
        """Check if a line passes the level and filter criteria."""
        line_level = _parse_level(line)
        if line_level and _level_rank(line_level) < min_rank:
            return False
        return not (filter_text and filter_text.lower() not in line.lower())

    # Show last N lines (read efficiently from end)
    try:
        from collections import deque

        with open(LOG_PATH) as f:
            all_lines = list(deque(f, maxlen=lines)) if lines > 0 else []
    except OSError:
        all_lines = []

    for line in all_lines:
        line = line.rstrip("\n")
        if _should_show(line):
            _colorize_line(console, line)

    if no_follow:
        return

    # Follow mode: tail -f style
    console.print(f"\n[dim]-- Following {LOG_PATH} (Ctrl+C to stop) --[/dim]\n")

    try:
        with open(LOG_PATH) as f:
            # Seek to end
            f.seek(0, 2)
            while True:
                line = f.readline()
                if line:
                    if _should_show(line):
                        _colorize_line(console, line)
                else:
                    time.sleep(0.1)
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped.[/dim]")
        sys.exit(0)
