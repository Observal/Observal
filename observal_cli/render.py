"""Shared rendering helpers for the Observal CLI."""

from __future__ import annotations

import json as _json
import re
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


# ── Model display helpers (mirror of services/model_display.py) ──

_MODEL_DATE_DASH_COMPACT = re.compile(r"[-_\s](\d{8})$")
_MODEL_DATE_DASH_HYPHEN = re.compile(r"[-_\s](\d{4}-\d{2}-\d{2})$")
_MODEL_DATE_PAREN = re.compile(r"\s*\((\d{4}-\d{2}-\d{2})\)\s*$")
_MODEL_LATEST_PAREN = re.compile(r"\s*\(latest\)\s*$", re.IGNORECASE)
_MODEL_LATEST_DASH = re.compile(r"[-_]latest$", re.IGNORECASE)
_MODEL_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _strip_model_date(text: str) -> str:
    if not text:
        return text
    out = text
    out = _MODEL_LATEST_PAREN.sub("", out).strip()
    out = _MODEL_DATE_PAREN.sub("", out).strip()
    out = _MODEL_DATE_DASH_HYPHEN.sub("", out).strip()
    out = _MODEL_DATE_DASH_COMPACT.sub("", out).strip()
    out = _MODEL_LATEST_DASH.sub("", out).strip()
    return out


def _model_has_trailing_date(model_id: str) -> tuple[bool, date | None]:
    m = _MODEL_DATE_DASH_COMPACT.search(model_id)
    if m:
        try:
            return True, datetime.strptime(m.group(1), "%Y%m%d").date()
        except ValueError:
            return True, None
    m = _MODEL_DATE_DASH_HYPHEN.search(model_id)
    if m:
        try:
            return True, datetime.strptime(m.group(1), "%Y-%m-%d").date()
        except ValueError:
            return True, None
    return False, None


def format_model(row: dict, *, disambiguate: bool = False) -> tuple[str, str | None, bool]:
    """Format a model catalog row for CLI display.

    Returns ``(primary, secondary, is_rolling)``. Secondary may be ``None``.
    Mirrors ``services/model_display.format_display`` line-for-line so CLI
    output never drifts from the web UI.
    """
    display_name = row.get("display_name") or ""
    model_id = row.get("model_id", "")
    release_date_value = row.get("release_date")
    raw = (display_name or model_id).strip()
    primary = _strip_model_date(raw) or raw

    has_date, parsed = _model_has_trailing_date(model_id)
    is_rolling = not has_date
    is_explicit_latest = bool(_MODEL_LATEST_PAREN.search(raw)) or model_id.endswith("-latest")

    if not disambiguate and not is_explicit_latest:
        return primary, None, is_rolling

    secondary: str | None = None
    if is_rolling or is_explicit_latest:
        secondary = "latest"
    else:
        d = parsed
        if d is None and release_date_value:
            try:
                d = datetime.fromisoformat(str(release_date_value)).date()
            except ValueError:
                d = None
        if d is not None:
            secondary = f"{_MODEL_MONTHS[d.month - 1]} {d.day}, {d.year}"
    return primary, secondary, is_rolling


def annotate_models(rows: list[dict]) -> list[dict]:
    """Return a new list where each row gets a ``_display`` dict with primary/secondary."""
    counts: dict[str, int] = {}
    primaries: list[str] = []
    for r in rows:
        primary, _, _ = format_model(r, disambiguate=False)
        primaries.append(primary)
        counts[primary] = counts.get(primary, 0) + 1
    out: list[dict] = []
    for r, primary in zip(rows, primaries, strict=True):
        annotated = dict(r)
        p, s, rolling = format_model(r, disambiguate=counts[primary] > 1)
        annotated["_display"] = {"primary": p, "secondary": s, "is_rolling": rolling}
        out.append(annotated)
    return out
