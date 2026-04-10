"""Shared rendering helpers for the Observal CLI."""

from __future__ import annotations

import json as _json
from datetime import UTC, datetime
from typing import Any

from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.table import Table  # noqa: TC002 - used at runtime

console = Console()

# ── Status badges ────────────────────────────────────────

_STATUS_STYLES = {
    "approved": ("✓ approved", "green"),
    "active": ("✓ active", "green"),
    "pending": ("● pending", "yellow"),
    "rejected": ("✗ rejected", "red"),
    "error": ("✗ error", "red"),
    "success": ("✓ success", "green"),
    "inactive": ("○ inactive", "dim"),
}


def status_badge(status: str) -> str:
    label, color = _STATUS_STYLES.get(status, (status, "white"))
    return f"[{color}]{label}[/{color}]"


# ── Relative time ────────────────────────────────────────


def relative_time(iso: str | None) -> str:
    if not iso:
        return "--"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        now = datetime.now(UTC)
        delta = now - dt
        secs = int(delta.total_seconds())
        if secs < 60:
            return "just now"
        if secs < 3600:
            m = secs // 60
            return f"{m}m ago"
        if secs < 86400:
            h = secs // 3600
            return f"{h}h ago"
        d = secs // 86400
        return f"{d}d ago"
    except Exception:
        return iso[:19] if iso else "--"


# ── Stars ────────────────────────────────────────────────


def star_rating(n: int, max_stars: int = 5) -> str:
    return "[yellow]" + "★" * n + "[/yellow][dim]" + "☆" * (max_stars - n) + "[/dim]"


# ── Output format dispatch ───────────────────────────────


def output_json(data: Any):
    console.print_json(_json.dumps(data, default=str))


def output_table(table: Table):
    console.print(table)


def output_plain(lines: list[str]):
    for line in lines:
        rprint(line)


# ── Detail panels ────────────────────────────────────────


def kv_panel(title: str, fields: list[tuple[str, str]], border_style: str = "blue") -> Panel:
    lines = []
    for k, v in fields:
        lines.append(f"[bold]{k}:[/bold] {v}")
    return Panel("\n".join(lines), title=f"[bold]{title}[/bold]", border_style=border_style, expand=False)


# ── IDE tag rendering ────────────────────────────────────

_IDE_COLORS = {
    "cursor": "cyan",
    "vscode": "blue",
    "kiro": "magenta",
    "claude_code": "yellow",
    "claude-code": "yellow",
    "gemini_cli": "red",
    "gemini-cli": "red",
    "codex": "bright_blue",
    "copilot": "bright_magenta",
}


def ide_tags(ides: list[str]) -> str:
    parts = []
    for ide in ides:
        color = _IDE_COLORS.get(ide, "white")
        parts.append(f"[{color}]{ide}[/{color}]")
    return " ".join(parts) if parts else "[dim]none[/dim]"


# ── Progress spinner context ─────────────────────────────


def spinner(msg: str = "Loading..."):
    return console.status(f"[dim]{msg}[/dim]", spinner="dots")
