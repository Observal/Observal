# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
#
# SPDX-License-Identifier: AGPL-3.0-only

"""Tool-param → file path extraction lookup table.

Maps an agent's tool name to the JSON keys in its `input` payload that
name files, classified as read, write, or both (a list of both).

A list value like ["read", "write"] means the tool's path is *causally*
both an input and an output: the same path must appear in BOTH
`files_read` and `files_written` (e.g. Edit reads-then-writes).

Population rules:
- Only entries verifiable from in-tree evidence are included. Tool names
  whose schemas aren't documented in this repo are intentionally absent;
  unknown tools fall through to ([], []), which is correct behavior.
- Pattern-based / search-based tools (Glob, Grep) get an explicit empty
  dict — they don't operate on a concrete file path.
- Lowercase / IDE-specific variants (Kiro, Gemini, Copilot CLI) require a
  payload-capture exercise before they can be added.
"""

from __future__ import annotations

import json
from typing import Literal

Mode = Literal["read", "write"]
ParamSpec = Mode | list[Mode]

# fmt: off
TOOL_FILE_PARAMS: dict[str, dict[str, ParamSpec]] = {
    # source: Claude Code Read tool schema
    "Read":         {"file_path": "read"},
    # source: Claude Code Write tool schema (creates/overwrites file at file_path)
    "Write":        {"file_path": "write"},
    # source: Claude Code Edit tool schema — reads-then-writes; path is both
    "Edit":         {"file_path": ["read", "write"]},
    # source: Claude Code NotebookEdit tool schema — reads-then-writes
    "NotebookEdit": {"notebook_path": ["read", "write"]},
    # source: Claude Code Glob tool — pattern-based, no concrete file
    "Glob":         {},
    # source: Claude Code Grep tool — search-based, no concrete file
    "Grep":         {},
    # source: Claude Code Bash tool — shell parsing deferred (see SDK Phase 1 notes)
    "Bash":         {},
    # source: Claude Code WebFetch — operates on URLs
    "WebFetch":     {},
    # source: Claude Code WebSearch — operates on queries
    "WebSearch":    {},
    # source: Claude Code Task/Agent — delegates to subagent; opaque
    "Task":         {},
    "Agent":        {},
    # source: Claude Code Skill — invokes a skill, not a direct file op
    "Skill":        {},
    # source: Claude Code TodoWrite — state, not files
    "TodoWrite":    {},
}
# fmt: on


def _resolve_tool_name(
    name: str | None,
    method: str | None,
    metadata: dict[str, str] | None,
) -> str:
    """Pick the tool name from the available carriers, in priority order.

    On the IngestBatch path callers may set `method`; on OTLP-derived rows
    `method` is empty and the tool name lives in `name`. As a last resort
    we look at metadata, since some IDEs may carry it there. The first
    non-empty value wins.
    """
    for candidate in (method, name):
        if candidate and candidate.strip():
            return candidate.strip()
    if metadata:
        meta_val = metadata.get("tool_name")
        if meta_val and meta_val.strip():
            return meta_val.strip()
    return ""


def extract_files(
    name: str | None,
    method: str | None,
    input_str: str | None,
    metadata: dict[str, str] | None = None,
) -> tuple[list[str], list[str]]:
    """Return (files_read, files_written) extracted from a span's tool input.

    Resolution order for the tool name: method → name → metadata["tool_name"].
    Unknown tools return ([], []).
    """
    tool = _resolve_tool_name(name, method, metadata)
    if not tool:
        return [], []
    spec = TOOL_FILE_PARAMS.get(tool)
    if not spec:
        return [], []
    if not input_str:
        return [], []

    try:
        params = json.loads(input_str)
    except (json.JSONDecodeError, TypeError, ValueError):
        return [], []
    if not isinstance(params, dict):
        return [], []

    reads: list[str] = []
    writes: list[str] = []
    for param_key, mode_spec in spec.items():
        val = params.get(param_key)
        if not isinstance(val, str) or not val:
            continue
        modes: list[Mode] = mode_spec if isinstance(mode_spec, list) else [mode_spec]
        if "read" in modes:
            reads.append(val)
        if "write" in modes:
            writes.append(val)
    return reads, writes
