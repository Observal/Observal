"""Shared display formatting for model catalog rows.

Returns the (primary, secondary, is_rolling) tuple used by every UI surface.
Mirrored at:
  - ``web/src/lib/model-display.ts`` (frontend)
  - ``observal_cli/render.py`` (``format_model`` helper)

Behavioural rules (kept in sync with ``tests/fixtures/model_display_cases.json``):

1. The **primary label** is ``display_name`` from models.dev with any trailing
   date stripped (``-YYYYMMDD``, ``-YYYY-MM-DD``, ``(YYYY-MM-DD)``,
   `` (latest)``).  If ``display_name`` is empty we fall back to
   ``humanize(model_id)``.
2. The **secondary label** is only emitted when the caller passes
   ``disambiguate=True`` (i.e. another row produces the same primary), or when
   the model_id ends in ``-latest`` so the user can tell the rolling pointer
   apart from a dated snapshot.
3. ``is_rolling`` is True when the model_id has no trailing date suffix.
"""

from __future__ import annotations

import re
from datetime import date, datetime

# A trailing -YYYYMMDD (claude-3-5-sonnet-20241022) is the most common shape.
_DATE_SUFFIX_DASH_COMPACT = re.compile(r"[-_\s](\d{8})$")
# Sometimes models use -YYYY-MM-DD; not in our seed but tolerated.
_DATE_SUFFIX_DASH_HYPHEN = re.compile(r"[-_\s](\d{4}-\d{2}-\d{2})$")
# `Claude 3.5 Sonnet (2024-10-22)` — date in parens at the end of display_name.
_DATE_SUFFIX_PAREN = re.compile(r"\s*\((\d{4}-\d{2}-\d{2})\)\s*$")
# `Claude Sonnet 4.5 (latest)` style suffix.
_LATEST_PAREN = re.compile(r"\s*\(latest\)\s*$", re.IGNORECASE)
# `gemini-1.5-pro-latest` — only used when display_name is empty and we fall through to model_id.
_LATEST_DASH = re.compile(r"[-_]latest$", re.IGNORECASE)

_MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _strip_trailing_date(text: str) -> str:
    if not text:
        return text
    out = text
    out = _LATEST_PAREN.sub("", out).strip()
    out = _DATE_SUFFIX_PAREN.sub("", out).strip()
    out = _DATE_SUFFIX_DASH_HYPHEN.sub("", out).strip()
    out = _DATE_SUFFIX_DASH_COMPACT.sub("", out).strip()
    out = _LATEST_DASH.sub("", out).strip()
    return out


def _has_trailing_date(model_id: str) -> tuple[bool, date | None]:
    """Return (has_date_suffix, parsed_date_or_None) for ``model_id``."""
    m = _DATE_SUFFIX_DASH_COMPACT.search(model_id)
    if m:
        try:
            return True, datetime.strptime(m.group(1), "%Y%m%d").date()
        except ValueError:
            return True, None
    m = _DATE_SUFFIX_DASH_HYPHEN.search(model_id)
    if m:
        try:
            return True, datetime.strptime(m.group(1), "%Y-%m-%d").date()
        except ValueError:
            return True, None
    return False, None


def _format_date(d: date) -> str:
    return f"{_MONTH_NAMES[d.month - 1]} {d.day}, {d.year}"


def format_display(
    display_name: str | None,
    model_id: str,
    release_date: date | None = None,
    *,
    disambiguate: bool = False,
) -> tuple[str, str | None, bool]:
    """Compute (primary, secondary, is_rolling) for a model row.

    Args:
        display_name: ``CatalogModel.display_name`` (``models.dev`` curated name).
        model_id: ``CatalogModel.model_id`` (canonical id).
        release_date: ``CatalogModel.release_date`` if known.
        disambiguate: True when another row produces the same primary label.
            When True, dated rows render their date as secondary text and
            rolling rows render ``"latest"``.
    """
    raw = (display_name or model_id).strip()
    primary = _strip_trailing_date(raw) or raw

    has_date_suffix, parsed_date = _has_trailing_date(model_id)
    is_rolling = not has_date_suffix
    is_explicit_latest = bool(_LATEST_PAREN.search(raw)) or model_id.endswith("-latest")

    if not disambiguate and not is_explicit_latest:
        return primary, None, is_rolling

    secondary: str | None = None
    if is_rolling or is_explicit_latest:
        secondary = "latest"
    else:
        d = parsed_date or release_date
        if d is not None:
            secondary = _format_date(d)
    return primary, secondary, is_rolling
