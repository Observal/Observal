# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""observal ops logs: live log viewer.

observal ops logs                  # follow local dev.log
observal ops logs --remote         # stream from hosted server via SSE
observal ops logs --level WARNING  # only warnings and above
observal ops logs --filter ingest  # grep for 'ingest'
observal ops logs --no-color       # disable ANSI colors

"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.text import Text
from typer.models import OptionInfo

from observal_cli.errors import ErrorCategory, fail
from observal_cli.render import OutputMode, output_json_line

logs_app = typer.Typer(
    name="logs",
    help=(
        "Live log viewer (open in a separate tab)\n\n"
        "Examples:\n"
        "  observal ops logs\n"
        "  observal ops logs --remote\n"
        "  observal ops logs --level WARNING --no-follow"
    ),
)

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


def _recent_remote(
    console: Console,
    *,
    level: str,
    filter_text: str,
    lines: int,
    no_color: bool,
    output: OutputMode | str = "table",
) -> None:
    """Fetch and print a finite batch of recent server logs."""
    if lines == 0:
        return

    from observal_cli import client

    params: dict = {"level": level, "limit": lines}
    if filter_text:
        params["filter"] = filter_text
    result = client.get(
        "/api/v1/admin/logs",
        params,
        operation="Read recent server logs",
        resource="server logs",
    )
    entries = result.get("entries") if isinstance(result, dict) else None
    if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
        fail(
            ErrorCategory.UNAVAILABLE,
            "The server returned an invalid recent logs response.",
            operation="Read recent server logs",
            resource="server logs",
            remediation="Check server health and version compatibility, then retry.",
        )
    for entry in entries:
        if output == "json":
            output_json_line({"event": "log", "source": "remote", "log": entry})
        else:
            _print_entry(console, entry, no_color=no_color)


def _stream_remote(
    console: Console,
    *,
    level: str,
    filter_text: str,
    no_color: bool,
    output: OutputMode | str = "table",
) -> None:
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

    if output != "json":
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
                fail(
                    ErrorCategory.AUTH,
                    "Authentication failed while streaming logs.",
                    operation="Stream server logs",
                    resource="server log stream",
                    remediation="Run `observal auth login` and retry.",
                    http_status=401,
                )
            if resp.status_code == 403:
                fail(
                    ErrorCategory.PERMISSION,
                    "Administrator access is required to stream server logs.",
                    operation="Stream server logs",
                    resource="server log stream",
                    remediation="Use an administrator account or read local logs.",
                    http_status=403,
                )
            if resp.status_code != 200:
                fail(
                    ErrorCategory.UNAVAILABLE,
                    f"The server log stream returned HTTP {resp.status_code}.",
                    operation="Stream server logs",
                    resource="server log stream",
                    remediation="Check server health and retry.",
                    http_status=resp.status_code,
                )

            if output != "json":
                console.print("[dim]- Streaming (Ctrl+C to stop) -[/dim]\n")

            for line in resp.iter_lines():
                if not line:
                    continue
                if line.startswith(": "):
                    continue  # SSE keepalive comment
                if line.startswith("data:"):
                    raw = line[5:].lstrip()
                    try:
                        entry = json.loads(raw)
                    except (json.JSONDecodeError, ValueError) as error:
                        fail(
                            ErrorCategory.UNAVAILABLE,
                            "The server log stream returned malformed JSON.",
                            operation="Stream server logs",
                            resource="server log stream",
                            remediation="Check server health and version compatibility.",
                            detail=repr(error),
                        )
                    if not isinstance(entry, dict):
                        fail(
                            ErrorCategory.UNAVAILABLE,
                            "The server log stream returned an invalid record.",
                            operation="Stream server logs",
                            resource="server log stream",
                            remediation="Check server health and version compatibility.",
                        )
                    if output == "json":
                        output_json_line({"event": "log", "source": "remote", "log": entry})
                    else:
                        _print_entry(console, entry, no_color=no_color)
    except httpx.TransportError as error:
        fail(
            ErrorCategory.UNAVAILABLE,
            "Cannot connect to the server log stream.",
            operation="Stream server logs",
            resource="server log stream",
            remediation="Check server connectivity and retry.",
            detail=repr(error),
        )
    except KeyboardInterrupt:
        if output != "json":
            console.print("\n[dim]Stopped.[/dim]")
        return


# ---------------------------------------------------------------------------
# Main command
# ---------------------------------------------------------------------------


@logs_app.callback(invoke_without_command=True)
def logs(
    level: str = typer.Option(
        "DEBUG", "--level", "-l", help="Minimum level (TRACE, DEBUG, INFO, WARNING, ERROR, CRITICAL)"
    ),
    filter_text: str = typer.Option("", "--filter", "-f", help="Only show lines containing this text"),
    lines: int = typer.Option(20, "--lines", "-n", min=0, help="Recent lines to show before following"),
    no_follow: bool = typer.Option(False, "--no-follow", help="Print recent lines and exit"),
    remote: bool = typer.Option(False, "--remote", "-r", help="Stream from the connected server via SSE"),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output"),
    output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table or json"),
):
    """Live-follow Observal logs.

    By default reads the local dev.log file.  Use --remote to stream from
    a hosted server (requires admin access).

    For Docker deployments, local mode won't work because the log file
    is inside the container.  Always use --remote for hosted instances.
    """
    output = output.default if isinstance(output, OptionInfo) else output
    level = level.strip().upper()
    if level not in _LEVEL_RANK:
        fail(
            ErrorCategory.VALIDATION,
            f"Unknown log level: {level}.",
            operation="Stream logs",
            resource="log level",
            remediation=f"Choose from: {', '.join(_LEVEL_RANK)}.",
        )
    console = Console(stderr=True, no_color=no_color)

    if remote:
        if no_follow:
            _recent_remote(
                console,
                level=level,
                filter_text=filter_text,
                lines=lines,
                no_color=no_color,
                output=output,
            )
        else:
            _stream_remote(console, level=level, filter_text=filter_text, no_color=no_color, output=output)
        return

    # Local file mode
    if not LOG_PATH.is_file():
        fail(
            ErrorCategory.NOT_FOUND,
            f"Local log file not found: {LOG_PATH}.",
            operation="Read local logs",
            resource=str(LOG_PATH),
            remediation="Use `observal ops logs --remote` for a hosted server.",
        )

    min_rank = _level_rank(level)

    def _should_show(line: str) -> bool:
        line_level = _parse_level(line)
        if line_level and _level_rank(line_level) < min_rank:
            return False
        return not (filter_text and filter_text.lower() not in line.lower())

    def _emit_local(line: str) -> None:
        raw = line.rstrip("\n")
        if output == "json":
            output_json_line({"event": "log", "source": "local", "level": _parse_level(raw), "line": raw})
        else:
            _print_line(console, raw, no_color=no_color)

    # Show last N lines
    try:
        from collections import deque

        with open(LOG_PATH) as f:
            all_lines = list(deque(f, maxlen=lines)) if lines > 0 else []
    except OSError as error:
        fail(
            ErrorCategory.UNAVAILABLE,
            f"Could not read local log file: {LOG_PATH}.",
            operation="Read local logs",
            resource=str(LOG_PATH),
            remediation="Check file permissions and retry.",
            detail=repr(error),
        )

    for line in all_lines:
        if _should_show(line):
            _emit_local(line)

    if no_follow:
        return

    if output != "json":
        console.print(f"\n[dim]- Following {LOG_PATH} (Ctrl+C to stop) -[/dim]\n")

    try:
        with open(LOG_PATH) as f:
            f.seek(0, 2)
            while True:
                line = f.readline()
                if line:
                    if _should_show(line):
                        _emit_local(line)
                else:
                    time.sleep(0.1)
    except OSError as error:
        fail(
            ErrorCategory.UNAVAILABLE,
            f"Could not follow local log file: {LOG_PATH}.",
            operation="Follow local logs",
            resource=str(LOG_PATH),
            remediation="Check file permissions and retry.",
            detail=repr(error),
        )
    except KeyboardInterrupt:
        if output == "json":
            return
        console.print("\n[dim]Stopped.[/dim]")
        sys.exit(0)
