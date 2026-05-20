# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

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


def resolve_session_id(event: dict, home: Path | None = None) -> str:
    """Return the session_id for a Kiro hook event.

    Kiro sends ``session_id`` on userPromptSubmit / agentSpawn, but NOT on stop.
    For stop events, falls back to the value persisted by a previous hook in
    ~/.observal/.kiro-session.
    """
    session_id = event.get("session_id", "")
    if session_id:
        return session_id
    if home is None:
        home = Path.home()
    session_file = home / ".observal" / ".kiro-session"
    try:
        if session_file.exists():
            cached = json.loads(session_file.read_text())
            session_id = cached.get("session_id", "")
    except Exception:
        pass
    return session_id


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
