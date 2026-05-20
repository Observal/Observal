# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Session JSONL parsers -- READ path (raw ClickHouse rows -> frontend events).

Dispatches to format-specific parsers based on the ``session_parser`` key in
``schemas/ide_registry.IDE_REGISTRY``.  Dispatch is **strict**: an unknown IDE
raises ``KeyError`` so new IDEs cannot silently fall through to a wrong parser.

When adding a new IDE:
  1. Add its entry to ``schemas/ide_registry.py`` with a ``"session_parser"`` key.
  2. If the IDE needs a new parser, add a module under ``session_parsers/`` and
     register it in ``_PARSERS`` below.
  3. If the IDE re-uses an existing format (e.g. Claude Code), point its
     ``"session_parser"`` at the existing parser ID.

Public API
----------
parse_raw_events(rows)  -- consumed by api/routes/sessions.py
"""

from __future__ import annotations

from collections.abc import Callable

from .claude_code import parse_rows as _parse_claude_code
from .cursor import parse_rows as _parse_cursor
from .kiro import parse_rows as _parse_kiro

# Maps session_parser ID -> parse_rows callable.
# Add new entries here when implementing a new JSONL format.
_ParseFn = Callable[[list[dict]], list[dict]]
_PARSERS: dict[str, _ParseFn] = {
    "claude-code": _parse_claude_code,
    "cursor": _parse_cursor,
    "kiro": _parse_kiro,
}


def parse_raw_events(rows: list[dict]) -> list[dict]:
    """Parse raw_line JSONL rows into normalised frontend events.

    Looks up the IDE from the first row, resolves the ``session_parser`` key
    from ``ide_registry``, and dispatches to the matching parser.

    Raises ``KeyError`` for unregistered IDEs or unimplemented parsers.
    """
    if not rows:
        return []
    ide = rows[0].get("ide", "")

    from schemas.ide_registry import IDE_REGISTRY

    parser_id = IDE_REGISTRY[ide]["session_parser"]  # KeyError = unknown IDE
    parser = _PARSERS[parser_id]  # KeyError = unimplemented parser
    return parser(rows)
