# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Claude Code session file helpers.

Handles JSONL file discovery, subagent detection, agent marker reading,
and subagent session pushing for Claude Code sessions.
"""

from __future__ import annotations

import json
from datetime import UTC
from pathlib import Path


def project_key_from_cwd(cwd: str) -> str:
    """Convert a filesystem path to the Claude Code project key format.

    e.g. "/home/user/code/proj" -> "-home-user-code-proj"
    """
    return cwd.replace("/", "-")


def find_jsonl_file(session_id: str, project_key: str, home: Path | None = None) -> Path | None:
    """Return the Path to the Claude Code session JSONL file, or None if not found."""
    if home is None:
        home = Path.home()
    primary = home / ".claude" / "projects" / project_key / f"{session_id}.jsonl"
    if primary.exists():
        return primary
    projects_root = home / ".claude" / "projects"
    if projects_root.exists():
        for match in projects_root.glob(f"**/{session_id}.jsonl"):
            return match
    return None


def get_parent_session_id(jsonl_path: Path) -> str | None:
    """Return the parent session ID if *jsonl_path* is a Claude Code subagent file.

    Subagent JSONL files live at:
      ~/.claude/projects/<project>/<parent_session_id>/subagents/<subagent_session_id>.jsonl
    """
    parts = jsonl_path.parts
    if len(parts) >= 3 and parts[-2] == "subagents":
        return parts[-3]
    return None


def read_agent_marker(cwd: str, session_jsonl: Path | None = None) -> tuple[str | None, str | None]:
    """Return (agent_id, agent_version) from <cwd>/.observal/agent, or (None, None).

    Written by ``observal pull`` so hooks can attribute sessions to the
    pulled agent.  Only applies the pulled_at guard for brand-new sessions
    (cursor offset == 0).
    """
    try:
        from observal_cli.sessions.base import read_cursor

        marker = Path(cwd) / ".observal" / "agent"
        data = json.loads(marker.read_text())

        pulled_at = data.get("pulled_at")
        if pulled_at and session_jsonl and session_jsonl.exists():
            from datetime import datetime

            session_id = session_jsonl.stem
            offset, _ = read_cursor(session_id)
            if offset == 0:
                pull_time = datetime.fromisoformat(pulled_at)
                stat = session_jsonl.stat()
                ctime = getattr(stat, "st_birthtime", None) or stat.st_ctime
                session_ctime = datetime.fromtimestamp(ctime, tz=UTC)
                if session_ctime < pull_time:
                    return None, None

        return data.get("agent_id"), data.get("agent_version")
    except Exception:
        return None, None


def find_sessions_dir(home: Path | None = None) -> Path:
    """Return ~/.claude/projects/ (the root of all Claude Code session JSONL files)."""
    if home is None:
        home = Path.home()
    return home / ".claude" / "projects"


def push_subagent_sessions(
    parent_session_id: str,
    jsonl_path: Path,
    config: dict,
    cwd: str = "",
    home: Path | None = None,
) -> None:
    """Push incremental lines from any subagent JSONL files under the parent session dir.

    Claude Code writes subagent transcripts to:
        <project_dir>/<parent_session_id>/subagents/agent-<agent_id>.jsonl
    """
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

        success = post_to_server(
            server_url=config["server_url"],
            access_token=config["access_token"],
            payload=payload,
            config=config,
        )
        if success:
            write_cursor(cursor_key, new_offset, line_count + len(lines), home=home)
