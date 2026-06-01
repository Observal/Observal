# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Antigravity CLI session file helpers.

Session transcripts live at:
  ~/.gemini/antigravity-cli/brain/<conversation-id>/.system_generated/logs/transcript.jsonl

On WSL, agy (Windows binary) writes to the Windows user profile, so we use
resolve_antigravity_dir() to find the correct base directory.
"""

from __future__ import annotations

import json
from pathlib import Path


def _get_ag_dir(home: Path | None = None) -> Path | None:
    """Return the antigravity-cli config dir with WSL fallback."""
    from observal_cli.shared.utils import resolve_antigravity_dir

    return resolve_antigravity_dir(home)


def find_antigravity_jsonl(session_id: str, home: Path | None = None) -> Path | None:
    """Return the Path to an Antigravity session transcript JSONL, or None.

    Transcripts live at:
      <ag_dir>/brain/<session_id>/.system_generated/logs/transcript.jsonl
    """
    if not session_id:
        return None
    ag_dir = _get_ag_dir(home)
    if ag_dir is None:
        return None
    path = ag_dir / "brain" / session_id / ".system_generated" / "logs" / "transcript.jsonl"
    return path if path.exists() else None


def find_sessions_dir(home: Path | None = None) -> Path | None:
    """Return the brain/ directory containing all session subdirs."""
    ag_dir = _get_ag_dir(home)
    if ag_dir is None:
        return None
    return ag_dir / "brain"


def resolve_session_id(event: dict, home: Path | None = None) -> str:
    """Return the session_id (conversation ID) for an Antigravity hook event.

    Antigravity sends conversationId on pre_turn events but not on session_end.
    Falls back to the value persisted by a previous hook in ~/.observal/.antigravity-session.
    """
    session_id = event.get("conversationId", "") or event.get("conversation_id", "") or event.get("session_id", "")
    if session_id:
        return session_id
    if home is None:
        home = Path.home()
    session_file = home / ".observal" / ".antigravity-session"
    try:
        if session_file.exists():
            cached = json.loads(session_file.read_text())
            session_id = cached.get("session_id", "")
    except Exception:
        pass
    return session_id
