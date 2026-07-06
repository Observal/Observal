# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""OpenCode session parser (READ path).

OpenCode's telemetry plugin converts messages to a Claude-Code-compatible
JSONL format before pushing to the Observal ingest endpoint. This parser
handles the read path (ClickHouse rows -> frontend events).

The format is nearly identical to Claude Code's JSONL:
  { "type": "user"|"assistant", "timestamp": "...", "uuid": "...",
    "message": { "role": "...", "content": [...], "usage": {...} } }

We delegate to the Claude Code parser since the wire format is compatible.
"""

from __future__ import annotations

from .claude_code import parse_rows as _parse_claude_code


def parse_rows(rows: list[dict]) -> list[dict]:
    """Parse OpenCode session rows into normalised frontend events.

    OpenCode's plugin emits Claude-Code-compatible JSONL, so we delegate
    to the Claude Code parser. If OpenCode's format diverges in the future,
    this function can be extended with OpenCode-specific handling.
    """
    return _parse_claude_code(rows)
