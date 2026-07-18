# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Cursor session file helpers.

Handles JSONL discovery, project keys, and usage-line synthesis for the
Cursor adapter.
"""

from __future__ import annotations

import json
from pathlib import Path


def project_key_from_cwd(cwd: str) -> str:
    """Convert a filesystem path to Cursor's project key format.

    e.g. "C:\\\\Users\\\\alice\\\\project" -> "c-Users-alice-project"
         "/home/user/project" -> "home-user-project"
         "/mnt/c/Users/alice/proj" -> "mnt-c-Users-alice-proj"
    """
    key = cwd.replace("\\", "-").replace("/", "-").replace(":", "")
    key = key.lstrip("-")
    if len(key) > 1 and key[0].isupper() and key[1] == "-":
        key = key[0].lower() + key[1:]
    return key


def find_cursor_jsonl(session_id: str, project_key: str, home: Path | None = None) -> Path | None:
    """Return the Path to a Cursor session JSONL file, or None if not found.

    Cursor stores transcripts at:
        ~/.cursor/projects/<project_key>/agent-transcripts/<session_id>/<session_id>.jsonl
    """
    if not session_id:
        return None
    if home is None:
        home = Path.home()
    primary = home / ".cursor" / "projects" / project_key / "agent-transcripts" / session_id / f"{session_id}.jsonl"
    if primary.exists():
        return primary
    projects_root = home / ".cursor" / "projects"
    if projects_root.exists():
        for match in projects_root.glob(f"**/agent-transcripts/{session_id}/{session_id}.jsonl"):
            return match
        for match in projects_root.glob(f"**/{session_id}.jsonl"):
            return match
    return None


def get_parent_session_id(jsonl_path: Path) -> str | None:
    """Return the parent session ID if this is a Cursor subagent file.

    Subagent JSONL files live at:
      ~/.cursor/projects/<project>/<parent_session_id>/subagents/<subagent_session_id>.jsonl
    """
    parts = jsonl_path.parts
    if len(parts) >= 3 and parts[-2] == "subagents":
        return parts[-3]
    return None


def build_usage_line(event: dict) -> str | None:
    """Build a synthetic JSONL line carrying token usage from a Cursor stop event payload.

    Cursor's stop event includes input_tokens, output_tokens, cache_read_tokens,
    cache_write_tokens at the top level.  We wrap them in the message.usage format
    the server's _extract_usage_tokens() expects.
    """
    input_tokens = event.get("input_tokens", 0) or 0
    output_tokens = event.get("output_tokens", 0) or 0
    cache_read = event.get("cache_read_tokens", 0) or 0
    cache_write = event.get("cache_write_tokens", 0) or 0
    if not any((input_tokens, output_tokens, cache_read, cache_write)):
        return None
    synthetic = {
        "role": "assistant",
        "message": {
            "content": [],
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": cache_write,
            },
            "model": event.get("model", ""),
        },
    }
    return json.dumps(synthetic)
