# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Claude Code session file helpers.

Handles JSONL file discovery, subagent detection, and agent marker reading
for the Claude Code adapter.
"""

from __future__ import annotations

from pathlib import Path

from observal_cli.sessions.agent_marker import read_agent_marker  # noqa: F401


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


def find_sessions_dir(home: Path | None = None) -> Path:
    """Return ~/.claude/projects/ (the root of all Claude Code session JSONL files)."""
    if home is None:
        home = Path.home()
    return home / ".claude" / "projects"
