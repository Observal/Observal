# SPDX-FileCopyrightText: 2026 RAWx18 <rawx18.dev@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Goose session helpers: read ``sessions.db`` and mirror it as JSONL.

Goose 1.10+ keeps every CLI and Desktop session in a single SQLite database at
``<data-dir>/sessions/sessions.db``.  Observal's delivery engine
(``observal_cli.sessions.base``) is byte-offset based, so this module projects
each Goose session onto an append-only JSONL mirror under
``~/.observal/sessions/goose/<session_id>.jsonl``.  The mirror is what the
shared spool, acknowledgement, checkpoint-recovery and final-hash protocol
operate on, so Goose needs no bespoke transport.

Reads are strictly non-mutating: the database is opened through a
``file:...?mode=ro`` URI so SQLite never creates, migrates or checkpoints
Goose's WAL, and a busy timeout keeps a concurrently writing Goose from
turning a read into an error.

Mirror records (one JSON object per line):

``{"type": "session", ...}``      session metadata, always the first record
``{"type": "message", ...}``      one row of the ``messages`` table
``{"type": "session_end", ...}``  final boundary with the session's usage totals
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple

from loguru import logger as optic

from observal_cli.shared.utils import resolve_goose_data_dir

# Goose stores message timestamps in seconds, but rows imported from other
# formats can carry milliseconds. This is the same threshold Goose itself uses.
_MILLISECOND_TIMESTAMP_THRESHOLD = 10_000_000_000

# Bounded tail read used to recover the mirror's export cursor.
_CURSOR_TAIL_BYTES = 64 * 1024

_SESSION_COLUMNS = (
    "id",
    "name",
    "description",
    "session_type",
    "working_dir",
    "created_at",
    "updated_at",
    "total_tokens",
    "input_tokens",
    "output_tokens",
    "accumulated_total_tokens",
    "accumulated_input_tokens",
    "accumulated_output_tokens",
    "accumulated_cost",
    "provider_name",
    "model_config_json",
    "goose_mode",
    "parent_session_id",
    "schedule_id",
)

_REQUIRED_MESSAGE_COLUMNS = frozenset({"id", "role", "content_json", "created_timestamp"})


class MirroredSession(NamedTuple):
    """A session's JSONL mirror plus the working directory Goose recorded for it."""

    path: Path
    working_dir: str


class GooseSession(NamedTuple):
    """One row of Goose's ``sessions`` table, as needed for discovery."""

    session_id: str
    working_dir: str
    parent_session_id: str | None
    updated_epoch: float


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------


def find_sessions_db(home: Path | None = None) -> Path:
    """Return the path to Goose's session database (which may not exist)."""
    return resolve_goose_data_dir(home) / "sessions" / "sessions.db"


def mirror_dir(home: Path | None = None) -> Path:
    """Return the directory holding Observal's Goose session mirrors."""
    return (home or Path.home()) / ".observal" / "sessions" / "goose"


def mirror_path(session_id: str, home: Path | None = None) -> Path:
    """Return the mirror file for one Goose session."""
    return mirror_dir(home) / f"{_safe_session_id(session_id)}.jsonl"


def _safe_session_id(session_id: str) -> str:
    """Keep a Goose session id usable as a filename on every platform."""
    return "".join(char if char.isalnum() or char in "-_." else "_" for char in session_id)[:128]


# ---------------------------------------------------------------------------
# Read-only database access
# ---------------------------------------------------------------------------


def _connect(db_path: Path) -> sqlite3.Connection:
    """Open ``sessions.db`` read-only so Goose's own writes are never blocked."""
    connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


def _read_session_row(connection: sqlite3.Connection, session_id: str) -> dict[str, Any] | None:
    available = _table_columns(connection, "sessions")
    if "id" not in available:
        return None
    columns = [name for name in _SESSION_COLUMNS if name in available]
    query = f"SELECT {', '.join(columns)} FROM sessions WHERE id = ?"
    row = connection.execute(query, (session_id,)).fetchone()
    return dict(row) if row is not None else None


def _read_message_rows(connection: sqlite3.Connection, session_id: str, after_row_id: int) -> list[sqlite3.Row]:
    available = _table_columns(connection, "messages")
    if not available >= _REQUIRED_MESSAGE_COLUMNS:
        return []
    optional = [name for name in ("message_id", "metadata_json") if name in available]
    columns = ["id", "role", "content_json", "created_timestamp", *optional]
    query = (
        f"SELECT {', '.join(columns)} FROM messages "
        "WHERE session_id = ? AND id > ? ORDER BY id"
    )
    return connection.execute(query, (session_id, after_row_id)).fetchall()


def list_recent_sessions(cutoff_epoch: float, home: Path | None = None) -> list[GooseSession]:
    """Return sessions updated since *cutoff*, most recently updated first.

    Returns an empty list when Goose is not installed or its database cannot
    be read.
    """
    db_path = find_sessions_db(home)
    if not db_path.is_file():
        return []
    try:
        with closing(_connect(db_path)) as connection:
            available = _table_columns(connection, "sessions")
            if "id" not in available:
                return []
            parent = "parent_session_id" if "parent_session_id" in available else "NULL AS parent_session_id"
            query = (
                f"SELECT id, working_dir, {parent}, "
                "CAST(strftime('%s', updated_at) AS INTEGER) AS updated_epoch FROM sessions "
                "WHERE updated_at >= datetime(?, 'unixepoch') ORDER BY updated_at DESC"
            )
            rows = connection.execute(query, (int(cutoff_epoch),)).fetchall()
    except (sqlite3.Error, OSError) as exc:
        optic.debug("could not list goose sessions from {}: {}", db_path, exc)
        return []
    return [
        GooseSession(row["id"], row["working_dir"] or "", row["parent_session_id"], row["updated_epoch"] or 0)
        for row in rows
    ]


def read_child_session_ids(session_id: str, home: Path | None = None) -> list[tuple[str, str]]:
    """Return ``(session_id, working_dir)`` for delegated/subagent children."""
    db_path = find_sessions_db(home)
    if not session_id or not db_path.is_file():
        return []
    try:
        with closing(_connect(db_path)) as connection:
            if "parent_session_id" not in _table_columns(connection, "sessions"):
                return []
            rows = connection.execute(
                "SELECT id, working_dir FROM sessions WHERE parent_session_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()
    except (sqlite3.Error, OSError) as exc:
        optic.debug("could not read goose child sessions for {}: {}", session_id, exc)
        return []
    return [(row["id"], row["working_dir"] or "") for row in rows]


# ---------------------------------------------------------------------------
# Mirror state
# ---------------------------------------------------------------------------


def _loads(raw: Any, fallback: Any) -> Any:
    if not isinstance(raw, str) or not raw:
        return fallback
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return fallback


def _scan_state(blob: bytes) -> tuple[int, bool]:
    """Return the highest ``row_id`` and whether ``session_end`` appears in *blob*."""
    row_id = 0
    has_end = False
    for line in blob.split(b"\n"):
        record = _loads(line.decode("utf-8", errors="replace"), None)
        if not isinstance(record, dict):
            continue
        if isinstance(record.get("row_id"), int):
            row_id = max(row_id, record["row_id"])
        elif record.get("type") == "session_end":
            has_end = True
    return row_id, has_end


def _mirror_state(path: Path) -> tuple[int, bool]:
    """Return the export cursor and finalisation flag recorded in a mirror.

    Reads a bounded tail first; only an inconclusive tail (a single record
    larger than the window) escalates to reading the whole mirror.
    """
    if not path.is_file():
        return 0, False
    try:
        size = path.stat().st_size
        with path.open("rb") as mirror:
            mirror.seek(max(0, size - _CURSOR_TAIL_BYTES))
            state = _scan_state(mirror.read())
            if state[0] or size <= _CURSOR_TAIL_BYTES:
                return state
            mirror.seek(0)
            return _scan_state(mirror.read())
    except OSError as exc:
        optic.warning("could not read goose session mirror {}: {}", path, exc)
        return 0, False


# ---------------------------------------------------------------------------
# Record building
# ---------------------------------------------------------------------------


def _iso_timestamp(created: Any) -> str:
    """Convert a Goose ``created_timestamp`` to an ISO-8601 UTC string."""
    try:
        epoch = float(created)
    except (TypeError, ValueError):
        return ""
    if epoch > _MILLISECOND_TIMESTAMP_THRESHOLD:
        epoch /= 1000.0
    try:
        return datetime.fromtimestamp(epoch, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    except (OverflowError, OSError, ValueError):
        return ""


def _sql_timestamp(value: Any) -> str:
    """Normalise a SQLite ``TIMESTAMP`` column to an ISO-8601 UTC string."""
    if not value:
        return ""
    text = str(value).strip().replace(" ", "T")
    return text if text.endswith("Z") or "+" in text else f"{text}Z"


def _session_record(session: dict[str, Any]) -> dict[str, Any]:
    model_config = _loads(session.get("model_config_json"), {})
    if not isinstance(model_config, dict):
        model_config = {}
    return {
        "type": "session",
        "session_id": session.get("id", ""),
        "name": session.get("name") or session.get("description") or "",
        "session_type": session.get("session_type") or "user",
        "working_dir": session.get("working_dir") or "",
        "parent_session_id": session.get("parent_session_id"),
        "schedule_id": session.get("schedule_id"),
        "goose_mode": session.get("goose_mode") or "",
        "provider": session.get("provider_name") or "",
        "model": model_config.get("model_name") or model_config.get("model") or "",
        "timestamp": _sql_timestamp(session.get("created_at")),
    }


def _session_end_record(session: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "session_end",
        "session_id": session.get("id", ""),
        "timestamp": _sql_timestamp(session.get("updated_at")),
        "usage": {
            "inputTokens": session.get("accumulated_input_tokens") or session.get("input_tokens") or 0,
            "outputTokens": session.get("accumulated_output_tokens") or session.get("output_tokens") or 0,
            "totalTokens": session.get("accumulated_total_tokens") or session.get("total_tokens") or 0,
            "cost": session.get("accumulated_cost"),
        },
    }


def _message_record(row: sqlite3.Row, session_id: str) -> dict[str, Any]:
    keys = row.keys()
    return {
        "type": "message",
        "row_id": row["id"],
        "session_id": session_id,
        "message_id": row["message_id"] if "message_id" in keys else None,
        "role": row["role"],
        "timestamp": _iso_timestamp(row["created_timestamp"]),
        "content": _loads(row["content_json"], []),
        "metadata": _loads(row["metadata_json"], {}) if "metadata_json" in keys else {},
    }


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def export_session(session_id: str, home: Path | None = None, *, finalize: bool = False) -> MirroredSession | None:
    """Append new Goose rows for *session_id* to its JSONL mirror.

    Returns the mirror and the working directory Goose recorded for the
    session, or None when nothing is readable yet.  The mirror only ever
    grows, which is what keeps the shared engine's byte offsets and
    acknowledged checkpoints valid across calls.
    """
    if not session_id:
        return None
    db_path = find_sessions_db(home)
    path = mirror_path(session_id, home)
    existing = MirroredSession(path, "") if path.is_file() else None
    if not db_path.is_file():
        optic.debug("goose session database not found at {}", db_path)
        return existing

    exported_row_id, already_final = _mirror_state(path)
    try:
        with closing(_connect(db_path)) as connection:
            session = _read_session_row(connection, session_id)
            if session is None:
                optic.debug("goose session {} is not in {}", session_id, db_path)
                return existing
            new_rows = _read_message_rows(connection, session_id, exported_row_id)
            records = [_message_record(row, session_id) for row in new_rows]
    except (sqlite3.Error, OSError) as exc:
        optic.warning("could not read goose session {}: {}", session_id, exc)
        return existing

    mirrored = MirroredSession(path, str(session.get("working_dir") or ""))
    if not path.is_file():
        records.insert(0, _session_record(session))
    if finalize and not already_final:
        records.append(_session_end_record(session))
    if not records:
        return mirrored

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as mirror:
            for record in records:
                mirror.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        optic.error("could not write goose session mirror {}: {}", path, exc)
        return existing
    return mirrored


def resolve_session_id(event: dict[str, Any], home: Path | None = None) -> str:
    """Return the session id for a Goose hook payload.

    Goose sends ``session_id`` on every hook event.  The last seen id is cached
    so an out-of-band finalize or a payload that omits it still resolves.
    """
    session_id = str(event.get("session_id") or event.get("sessionId") or "")
    state_file = (home or Path.home()) / ".observal" / ".goose-session"
    if session_id:
        try:
            state_file.parent.mkdir(parents=True, exist_ok=True)
            state_file.write_text(json.dumps({"session_id": session_id}))
        except OSError:
            pass
        return session_id
    try:
        cached = _loads(state_file.read_text(), {})
    except OSError:
        return ""
    return str(cached.get("session_id", "")) if isinstance(cached, dict) else ""
