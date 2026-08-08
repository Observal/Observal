# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Kiro session file helpers.

Handles JSONL file discovery, session ID resolution, and credit reading
for Kiro sessions.
"""

from __future__ import annotations

import json
from pathlib import Path


def find_sessions_dir(home: Path | None = None) -> Path:
    """Return ~/.kiro/sessions/cli/ (the root of all Kiro session JSONL files)."""
    if home is None:
        home = Path.home()
    return home / ".kiro" / "sessions" / "cli"


def find_kiro_jsonl(session_id: str, home: Path | None = None) -> Path | None:
    """Return the Path to a Kiro session JSONL file, or None if not found.

    Kiro stores transcripts at ~/.kiro/sessions/cli/<session_id>.jsonl.
    """
    if not session_id:
        return None
    if home is None:
        home = Path.home()
    path = home / ".kiro" / "sessions" / "cli" / f"{session_id}.jsonl"
    return path if path.exists() else None


def _read_kiro_session(session_jsonl: Path | None) -> dict | None:
    """Read a Kiro companion session object, returning None on any invalid shape."""
    if session_jsonl is None:
        return None
    try:
        session = json.loads(session_jsonl.with_suffix(".json").read_text())
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return session if isinstance(session, dict) else None


def read_kiro_agent_name(session_jsonl: Path | None) -> str | None:
    """Return the active Kiro agent recorded in a session companion file.

    Kiro stores session metadata next to the transcript as ``<session_id>.json``.
    Current versions expose the active agent directly as
    ``session_state.agent_name``. Older-compatible metadata also records the
    agent on each user turn, so the latest turn is a safe fallback when the
    direct field is absent. Missing or malformed metadata is left unattributed.
    """
    session = _read_kiro_session(session_jsonl)
    if session is None:
        return None

    state = session.get("session_state")
    if not isinstance(state, dict):
        return None
    agent_name = state.get("agent_name")
    if isinstance(agent_name, str) and agent_name.strip():
        return agent_name.strip()

    conversation = state.get("conversation_metadata")
    if not isinstance(conversation, dict):
        return None
    turns = conversation.get("user_turn_metadatas")
    if not isinstance(turns, list):
        return None
    for turn in reversed(turns):
        if not isinstance(turn, dict):
            continue
        loop_id = turn.get("loop_id")
        agent_id = loop_id.get("agent_id") if isinstance(loop_id, dict) else None
        name = agent_id.get("name") if isinstance(agent_id, dict) else None
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


def read_kiro_session_cwd(session_jsonl: Path | None) -> str:
    """Return the working directory persisted in a Kiro companion session."""
    session = _read_kiro_session(session_jsonl)
    if session is None:
        return ""
    cwd = session.get("cwd")
    return cwd.strip() if isinstance(cwd, str) else ""


def resolve_session_id(event: dict, home: Path | None = None) -> str:
    """Return a non-empty session ID supplied explicitly by a Kiro hook event.

    Identity-less events are intentionally left unresolved because a shared
    fallback cannot safely correlate concurrent Kiro sessions.
    """
    del home  # Kept for call-site compatibility.
    session_id = event.get("session_id")
    return session_id.strip() if isinstance(session_id, str) else ""


def read_kiro_credits(session_id: str, home: Path | None = None) -> float | None:
    """Read total credit usage from the Kiro session companion .json file.

    Sums all turns so the sessions page shows lifetime credit spend.
    Returns None if the file is absent or has no metering_usage yet.
    """
    if not session_id:
        return None
    if home is None:
        home = Path.home()
    json_path = home / ".kiro" / "sessions" / "cli" / f"{session_id}.json"
    if not json_path.exists():
        return None
    try:
        session = json.loads(json_path.read_text())
        turns = session.get("session_state", {}).get("conversation_metadata", {}).get("user_turn_metadatas", [])
        total = sum(
            u.get("value", 0.0) for turn in turns for u in turn.get("metering_usage", []) if u.get("unit") == "credit"
        )
        return total if total > 0 else None
    except Exception:
        return None
