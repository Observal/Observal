"""Shared rendering helpers for the Observal CLI."""

from __future__ import annotations

import json as _json
from datetime import UTC, date, datetime
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


# ── Message helpers ─────────────────────────────────────────


def error(msg: str, *, hint: str | None = None):
    """Print an error message with optional hint."""
    rprint(f"[bold red]Error:[/bold red] {msg}")
    if hint:
        rprint(f"[dim]  Hint: {hint}[/dim]")


def warning(msg: str):
    """Print a warning message."""
    rprint(f"[yellow]Warning:[/yellow] {msg}")


def success(msg: str):
    """Print a success message."""
    rprint(f"[green]Success:[/green] {msg}")


# ── Model display helpers ──
# Reads the pre-computed ``display`` field from the server API response
# (computed by ``services/model_display.py``). Falls back to raw model_id
# when display data isn't available (e.g. offline mirror, bare model_id lookup).

_MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _format_date_short(d: date) -> str:
    return f"{_MONTH_NAMES[d.month - 1]} {d.day}, {d.year}"


def _force_secondary(row: dict, is_rolling: bool) -> str | None:
    """Derive a secondary label when the caller wants forced disambiguation."""
    if is_rolling:
        return "latest"
    rd = row.get("release_date")
    if rd:
        try:
            d = datetime.fromisoformat(str(rd)).date() if not isinstance(rd, date) else rd
            return _format_date_short(d)
        except (ValueError, TypeError):
            pass
    return None


def format_model(row: dict, *, disambiguate: bool = False) -> tuple[str, str | None, bool]:
    """Format a model catalog row for CLI display.

    Returns ``(primary, secondary, is_rolling)``. Reads the server-computed
    ``display`` field when available; falls back to the model_id.
    """
    display = row.get("display")
    if isinstance(display, dict):
        primary = display.get("primary") or row.get("model_id", "")
        secondary = display.get("secondary")
        is_rolling = bool(display.get("is_rolling"))
        if disambiguate and not secondary:
            secondary = _force_secondary(row, is_rolling)
        return primary, secondary, is_rolling

    # Fallback: no pre-computed display (offline mirror or bare model_id lookup)
    primary = (row.get("display_name") or row.get("model_id") or "").strip()
    is_rolling = not primary[-8:].isdigit() if primary else False
    secondary = _force_secondary(row, is_rolling) if disambiguate else None
    return primary, secondary, is_rolling


def annotate_models(rows: list[dict]) -> list[dict]:
    """Return a new list where each row gets a ``_display`` dict with primary/secondary."""
    out: list[dict] = []
    for r in rows:
        annotated = dict(r)
        p, s, rolling = format_model(r, disambiguate=True)
        annotated["_display"] = {"primary": p, "secondary": s, "is_rolling": rolling}
        out.append(annotated)
    return out
