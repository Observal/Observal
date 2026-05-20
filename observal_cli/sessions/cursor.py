# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Cursor session file helpers.

Handles JSONL file discovery, project key computation, usage line
synthesis, and subagent pushing for Cursor sessions.
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


def push_subagent_sessions(
    parent_session_id: str,
    jsonl_path: Path,
    config: dict,
    cwd: str = "",
    home: Path | None = None,
) -> None:
    """Push incremental lines from any Cursor subagent JSONL files."""
    from observal_cli.sessions.base import (
        build_payload,
        post_to_server,
        read_cursor,
        read_new_lines,
        write_cursor,
    )

    subagents_dir = jsonl_path.parent / parent_session_id / "subagents"
    if not subagents_dir.is_dir():
        return

    for sub_file in subagents_dir.glob("agent-*.jsonl"):
        agent_id = sub_file.stem[len("agent-") :]
        cursor_key = f"{parent_session_id}__sub__{agent_id}"

        offset, line_count = read_cursor(cursor_key, home=home)
        lines, bytes_read = read_new_lines(sub_file, offset=offset)
        if not lines:
            continue

        new_offset = offset + bytes_read
        payload = build_payload(
            session_id=agent_id,
            lines=lines,
            start_offset=line_count,
            hook_event="UserPromptSubmit",
            line_count_before=line_count,
            new_offset=new_offset,
            cwd=cwd,
            parent_session_id=parent_session_id,
        )
        payload["ide"] = "cursor"

        success = post_to_server(
            server_url=config["server_url"],
            access_token=config["access_token"],
            payload=payload,
            config=config,
        )
        if success:
            write_cursor(cursor_key, new_offset, line_count + len(lines), home=home)
