# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Copilot CLI session file helpers.

Handles events.jsonl file discovery, parsing, and edge case handling for
Copilot CLI sessions stored at:
    ~/.copilot/session-state/<uuid>/events.jsonl

Envelope format:
    {"agentId": "...", "ts": "ISO-8601", "event": {"type": "...", ...fields}}
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from urllib.parse import quote, unquote


def find_sessions_dir(home: Path | None = None) -> Path:
    """Return ~/.copilot/session-state/ (root of all Copilot CLI session files)."""
    if home is None:
        home = Path.home()
    return home / ".copilot" / "session-state"


def discover_sessions(home: Path | None = None) -> list[Path]:
    """Discover events.jsonl files for all Copilot CLI sessions.

    Tries the SQLite index at ~/.copilot/session-store.db first for faster
    discovery. Falls back to globbing ~/.copilot/session-state/*/events.jsonl.
    """
    if home is None:
        home = Path.home()

    # Try SQLite index for faster discovery
    db_path = home / ".copilot" / "session-store.db"
    if db_path.exists():
        try:
            sessions = _discover_via_sqlite(db_path, home)
            if sessions:
                return sessions
        except Exception:
            pass

    # Fallback: glob
    sessions_dir = find_sessions_dir(home)
    if not sessions_dir.is_dir():
        return []
    return sorted(sessions_dir.glob("*/events.jsonl"))


def _discover_via_sqlite(db_path: Path, home: Path) -> list[Path]:
    """Query session-store.db for session UUIDs and resolve to events.jsonl paths."""
    sessions_dir = find_sessions_dir(home)
    results: list[Path] = []
    conn = sqlite3.connect(str(db_path), timeout=2)
    try:
        cursor = conn.execute("SELECT id FROM sessions ORDER BY id")
        for (session_id,) in cursor.fetchall():
            jsonl = sessions_dir / str(session_id) / "events.jsonl"
            if jsonl.exists():
                results.append(jsonl)
    except Exception:
        pass
    finally:
        conn.close()
    return results


def _sanitize_line(line: str) -> str:
    """Sanitize a raw JSONL line before JSON parsing.

    Handles known edge cases:
    - Trailing NUL bytes (from crash-interrupted writes)
    - U+2028 (LINE SEPARATOR) and U+2029 (PARAGRAPH SEPARATOR)
    """
    line = line.rstrip("\x00")
    line = line.replace("\u2028", "\\n").replace("\u2029", "\\n")
    return line


def parse_event_line(line: str) -> dict | None:
    """Parse a single events.jsonl line.

    Copilot CLI envelope format:
        {"agentId": "...", "ts": "ISO-8601", "event": {"type": "...", ...fields}}

    Returns a normalized dict with keys:
        - agent_id: str (the agentId from the envelope)
        - timestamp: str (ISO-8601, from the ts field)
        - event_type: str (e.g. "session.start", "tool.call")
        - payload: dict (the event dict minus the "type" key)

    Returns None for malformed or empty lines.
    """
    if not line or not line.strip():
        return None

    sanitized = _sanitize_line(line.strip())
    if not sanitized:
        return None

    try:
        data = json.loads(sanitized)
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(data, dict):
        return None

    # Unwrap envelope: {agentId, ts, event: {type, ...}}
    event = data.get("event")
    if not isinstance(event, dict):
        return None

    event_type = event.get("type", "")
    if not event_type:
        return None

    # Payload is everything in the event dict except "type"
    payload = {k: v for k, v in event.items() if k != "type"}

    return {
        "agent_id": data.get("agentId", ""),
        "timestamp": data.get("ts", ""),
        "event_type": event_type,
        "payload": payload,
    }


def find_session_jsonl(session_id: str, home: Path | None = None) -> Path | None:
    """Return the Path to a Copilot CLI session events.jsonl, or None if not found."""
    if not session_id:
        return None
    if home is None:
        home = Path.home()
    primary = find_sessions_dir(home) / session_id / "events.jsonl"
    if primary.exists():
        return primary
    return None


def resolve_hook_event(event: dict) -> str:
    """Resolve Copilot/VS Code hook payloads to canonical event names."""
    explicit = event.get("hookEventName") or event.get("hook_event_name")
    if explicit:
        return str(explicit)
    if "source" in event or "initialPrompt" in event or "initial_prompt" in event:
        return "SessionStart"
    if "reason" in event:
        return "Stop"
    if "prompt" in event:
        return "UserPromptSubmit"
    if "toolResult" in event or "tool_result" in event or "tool_response" in event:
        return "PostToolUse"
    if "toolName" in event or "tool_name" in event:
        return "PreToolUse"
    return "UserPromptSubmit"


_EVENT_TYPE_MAP = {
    "SessionStart": "session.start",
    "UserPromptSubmit": "user.message",
    "PreToolUse": "tool.call",
    "PostToolUse": "tool.result",
    "Stop": "session.end",
    "SessionEnd": "session.end",
}


def hook_event_to_line(event: dict, session_id: str) -> str:
    """Convert a native hook payload into one stable Copilot envelope record."""
    hook_event = resolve_hook_event(event)
    body: dict = {"type": _EVENT_TYPE_MAP.get(hook_event, "session.start")}
    if hook_event == "UserPromptSubmit":
        body["content"] = event.get("prompt", "")
    elif hook_event == "PreToolUse":
        body["name"] = event.get("tool_name") or event.get("toolName") or ""
        tool_input = event.get("tool_input", event.get("toolArgs", {}))
        if isinstance(tool_input, str):
            try:
                tool_input = json.loads(tool_input)
            except (json.JSONDecodeError, ValueError):
                tool_input = {"raw": tool_input}
        body["input"] = tool_input
    elif hook_event == "PostToolUse":
        body["name"] = event.get("tool_name") or event.get("toolName") or ""
        result = event.get("tool_response", event.get("tool_result", event.get("toolResult", "")))
        if isinstance(result, dict):
            body["output"] = result.get("text_result_for_llm", result.get("textResultForLlm", json.dumps(result)))
        else:
            body["output"] = str(result or "")
    elif hook_event == "SessionStart":
        body["source"] = event.get("source", "new")
    elif hook_event in ("Stop", "SessionEnd"):
        body["reason"] = event.get("reason", event.get("stop_reason", event.get("stopReason", "session_end")))
    return json.dumps(
        {
            "agentId": session_id,
            "ts": event.get("timestamp", ""),
            "event": body,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def vscode_hook_source_path(session_id: str, home: Path | None = None) -> Path:
    """Return the durable local source path for a VS Code Copilot session."""
    home = home or Path.home()
    return home / ".observal" / "session_sources" / "copilot" / f"{quote(session_id, safe='')}.jsonl"


def append_vscode_hook_event(event: dict, session_id: str, home: Path | None = None) -> Path:
    """Durably append a VS Code hook event to its local JSONL source."""
    path = vscode_hook_source_path(session_id, home=home)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as source:
        source.write(hook_event_to_line(event, session_id) + "\n")
        source.flush()
        os.fsync(source.fileno())
    return path


def discover_vscode_hook_sources(home: Path | None = None) -> list[tuple[str, Path]]:
    """Return materialized VS Code hook sources and their original session IDs."""
    home = home or Path.home()
    root = home / ".observal" / "session_sources" / "copilot"
    if not root.is_dir():
        return []
    return [(unquote(path.stem), path) for path in root.glob("*.jsonl")]


def find_active_session(cwd: str, home: Path | None = None) -> Path | None:
    """Find the most recently modified events.jsonl.

    Used by the session push hook to locate the current session's file.
    """
    if home is None:
        home = Path.home()
    sessions_dir = find_sessions_dir(home)
    if not sessions_dir.is_dir():
        return None

    candidates = list(sessions_dir.glob("*/events.jsonl"))
    if not candidates:
        return None

    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]
