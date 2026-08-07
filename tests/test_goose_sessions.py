# SPDX-FileCopyrightText: 2026 RAWx18 <rawx18.dev@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Tests for reading Goose's SQLite session store and mirroring it as JSONL."""

from __future__ import annotations

import json
import sqlite3
import time
from typing import TYPE_CHECKING

import pytest

from observal_cli.harness.goose import GooseAdapter
from observal_cli.sessions import goose as goose_sessions

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _isolated_goose_env(monkeypatch: pytest.MonkeyPatch):
    """GOOSE_PATH_ROOT overrides every other location, so keep tests hermetic."""
    monkeypatch.delenv("GOOSE_PATH_ROOT", raising=False)


_SESSIONS_DDL = """
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    session_type TEXT NOT NULL DEFAULT 'user',
    working_dir TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    total_tokens INTEGER,
    input_tokens INTEGER,
    output_tokens INTEGER,
    accumulated_total_tokens INTEGER,
    accumulated_input_tokens INTEGER,
    accumulated_output_tokens INTEGER,
    accumulated_cost REAL,
    provider_name TEXT,
    model_config_json TEXT,
    goose_mode TEXT NOT NULL DEFAULT 'auto',
    schedule_id TEXT,
    parent_session_id TEXT
)
"""

_MESSAGES_DDL = """
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content_json TEXT NOT NULL,
    created_timestamp INTEGER NOT NULL,
    metadata_json TEXT
)
"""

# Pre-v7 goose databases have neither message_id nor metadata_json.
_LEGACY_MESSAGES_DDL = """
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content_json TEXT NOT NULL,
    created_timestamp INTEGER NOT NULL
)
"""


def _db_path(home: Path) -> Path:
    path = home / ".local" / "share" / "goose" / "sessions" / "sessions.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _make_db(home: Path, *, legacy_messages: bool = False) -> Path:
    path = _db_path(home)
    with sqlite3.connect(path) as connection:
        connection.execute(_SESSIONS_DDL)
        connection.execute(_LEGACY_MESSAGES_DDL if legacy_messages else _MESSAGES_DDL)
    return path


def _add_session(
    home: Path,
    session_id: str = "20260807_1",
    *,
    working_dir: str = "/project",
    parent: str | None = None,
    updated_at: str = "2026-08-07 12:00:00",
) -> None:
    with sqlite3.connect(_db_path(home)) as connection:
        connection.execute(
            "INSERT INTO sessions (id, name, working_dir, created_at, updated_at, provider_name, "
            "model_config_json, accumulated_input_tokens, accumulated_output_tokens, "
            "accumulated_total_tokens, parent_session_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                session_id,
                "Fix the parser",
                working_dir,
                "2026-08-07 11:59:00",
                updated_at,
                "anthropic",
                json.dumps({"model_name": "claude-sonnet-4-6"}),
                120,
                45,
                165,
                parent,
            ),
        )


def _add_message(
    home: Path,
    session_id: str = "20260807_1",
    *,
    role: str = "user",
    content: list | None = None,
    created: int = 1_785_000_000,
    message_id: str | None = "msg-1",
    metadata: dict | None = None,
    legacy: bool = False,
) -> None:
    content_json = json.dumps(content if content is not None else [{"type": "text", "text": "hello"}])
    with sqlite3.connect(_db_path(home)) as connection:
        if legacy:
            connection.execute(
                "INSERT INTO messages (session_id, role, content_json, created_timestamp) VALUES (?,?,?,?)",
                (session_id, role, content_json, created),
            )
        else:
            connection.execute(
                "INSERT INTO messages (message_id, session_id, role, content_json, created_timestamp, "
                "metadata_json) VALUES (?,?,?,?,?,?)",
                (message_id, session_id, role, content_json, created, json.dumps(metadata or {})),
            )


def _records(mirrored) -> list[dict]:
    return [json.loads(line) for line in mirrored.path.read_text().splitlines() if line.strip()]


# ── Export ────────────────────────────────────────────────────────────────────


def test_export_writes_session_then_message_records(tmp_path: Path):
    _make_db(tmp_path)
    _add_session(tmp_path)
    _add_message(tmp_path)

    mirrored = goose_sessions.export_session("20260807_1", home=tmp_path)

    assert mirrored.path == goose_sessions.mirror_path("20260807_1", home=tmp_path)
    assert mirrored.working_dir == "/project"
    records = _records(mirrored)
    assert [record["type"] for record in records] == ["session", "message"]
    assert records[0]["working_dir"] == "/project"
    assert records[0]["provider"] == "anthropic"
    assert records[0]["model"] == "claude-sonnet-4-6"
    assert records[1]["role"] == "user"
    assert records[1]["content"] == [{"type": "text", "text": "hello"}]
    assert records[1]["timestamp"].endswith("Z")


def test_export_is_incremental_and_never_rewrites_history(tmp_path: Path):
    _make_db(tmp_path)
    _add_session(tmp_path)
    _add_message(tmp_path, message_id="msg-1")

    mirrored = goose_sessions.export_session("20260807_1", home=tmp_path)
    first_pass = mirrored.path.read_bytes()

    assert goose_sessions.export_session("20260807_1", home=tmp_path).path.read_bytes() == first_pass

    _add_message(tmp_path, role="assistant", message_id="msg-2")
    goose_sessions.export_session("20260807_1", home=tmp_path)

    assert mirrored.path.read_bytes().startswith(first_pass)
    assert [record["message_id"] for record in _records(mirrored) if record["type"] == "message"] == ["msg-1", "msg-2"]


def test_export_appends_session_end_exactly_once(tmp_path: Path):
    _make_db(tmp_path)
    _add_session(tmp_path)
    _add_message(tmp_path)

    mirrored = goose_sessions.export_session("20260807_1", home=tmp_path, finalize=True)
    goose_sessions.export_session("20260807_1", home=tmp_path, finalize=True)

    ends = [record for record in _records(mirrored) if record["type"] == "session_end"]
    assert len(ends) == 1
    assert ends[0]["usage"] == {"inputTokens": 120, "outputTokens": 45, "totalTokens": 165, "cost": None}


def test_export_never_modifies_the_goose_database(tmp_path: Path):
    db = _make_db(tmp_path)
    _add_session(tmp_path)
    _add_message(tmp_path)
    before = db.read_bytes()
    sidecars_before = sorted(p.name for p in db.parent.iterdir())

    goose_sessions.export_session("20260807_1", home=tmp_path, finalize=True)

    assert db.read_bytes() == before
    assert sorted(p.name for p in db.parent.iterdir()) == sidecars_before


def test_export_reads_a_database_missing_optional_columns(tmp_path: Path):
    _make_db(tmp_path, legacy_messages=True)
    _add_session(tmp_path)
    _add_message(tmp_path, legacy=True)

    records = _records(goose_sessions.export_session("20260807_1", home=tmp_path))

    assert records[1]["message_id"] is None
    assert records[1]["metadata"] == {}


def test_export_normalises_millisecond_timestamps(tmp_path: Path):
    _make_db(tmp_path)
    _add_session(tmp_path)
    _add_message(tmp_path, created=1_785_000_000_000)

    records = _records(goose_sessions.export_session("20260807_1", home=tmp_path))

    assert records[1]["timestamp"].startswith("2026-")


def test_export_tolerates_corrupt_message_content(tmp_path: Path):
    _make_db(tmp_path)
    _add_session(tmp_path)
    with sqlite3.connect(_db_path(tmp_path)) as connection:
        connection.execute(
            "INSERT INTO messages (message_id, session_id, role, content_json, created_timestamp) VALUES (?,?,?,?,?)",
            ("msg-x", "20260807_1", "assistant", "{not json", 1_785_000_000),
        )

    records = _records(goose_sessions.export_session("20260807_1", home=tmp_path))

    assert records[1]["content"] == []


@pytest.mark.parametrize("session_id", ["", "does-not-exist"])
def test_export_returns_none_for_unknown_sessions(tmp_path: Path, session_id: str):
    _make_db(tmp_path)
    assert goose_sessions.export_session(session_id, home=tmp_path) is None


def test_export_returns_none_without_a_database(tmp_path: Path):
    assert goose_sessions.export_session("20260807_1", home=tmp_path) is None


def test_export_returns_none_for_an_unreadable_database(tmp_path: Path):
    _db_path(tmp_path).write_text("this is not a sqlite database")
    assert goose_sessions.export_session("20260807_1", home=tmp_path) is None


def test_mirror_path_is_filesystem_safe(tmp_path: Path):
    path = goose_sessions.mirror_path("../../escape/me", home=tmp_path)
    assert path.parent == goose_sessions.mirror_dir(tmp_path)
    assert "/" not in path.name.removesuffix(".jsonl")


# ── Discovery ─────────────────────────────────────────────────────────────────


def test_list_recent_sessions_respects_the_cutoff(tmp_path: Path):
    _make_db(tmp_path)
    _add_session(tmp_path, "recent", updated_at="2026-08-07 12:00:00")
    _add_session(tmp_path, "stale", updated_at="2020-01-01 00:00:00")

    cutoff = time.mktime(time.strptime("2026-01-01", "%Y-%m-%d"))
    assert [row[0] for row in goose_sessions.list_recent_sessions(cutoff, home=tmp_path)] == ["recent"]


def test_list_recent_sessions_without_a_database(tmp_path: Path):
    assert goose_sessions.list_recent_sessions(0, home=tmp_path) == []


def test_read_child_session_ids(tmp_path: Path):
    _make_db(tmp_path)
    _add_session(tmp_path, "parent")
    _add_session(tmp_path, "child", working_dir="/child", parent="parent")

    assert goose_sessions.read_child_session_ids("parent", home=tmp_path) == [("child", "/child")]
    assert goose_sessions.read_child_session_ids("child", home=tmp_path) == []


def test_resolve_session_id_caches_the_last_seen_value(tmp_path: Path):
    assert goose_sessions.resolve_session_id({"session_id": "abc-123"}, home=tmp_path) == "abc-123"
    assert goose_sessions.resolve_session_id({"event": "SessionEnd"}, home=tmp_path) == "abc-123"


def test_resolve_session_id_without_history(tmp_path: Path):
    assert goose_sessions.resolve_session_id({"event": "Stop"}, home=tmp_path) == ""


def test_goose_path_root_overrides_every_other_location(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Goose relocates config, data and .agents wholesale when GOOSE_PATH_ROOT is set."""
    from observal_cli.shared.utils import (
        resolve_goose_agents_home,
        resolve_goose_config_dir,
        resolve_goose_data_dir,
    )

    root = tmp_path / "root"
    monkeypatch.setenv("GOOSE_PATH_ROOT", str(root))

    assert resolve_goose_config_dir() == root / "config"
    assert resolve_goose_data_dir() == root / "data"
    assert resolve_goose_agents_home() == root / ".agents"
    assert goose_sessions.find_sessions_db() == root / "data" / "sessions" / "sessions.db"


def test_goose_path_root_is_ignored_when_relative(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from observal_cli.shared.utils import resolve_goose_config_dir

    monkeypatch.setenv("GOOSE_PATH_ROOT", "relative/path")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    assert resolve_goose_config_dir(tmp_path) == tmp_path / ".config" / "goose"


# ── Adapter session wiring ────────────────────────────────────────────────────


def test_adapter_resolves_a_hook_payload_to_the_mirror(tmp_path: Path):
    _make_db(tmp_path)
    _add_session(tmp_path)
    _add_message(tmp_path)

    source = GooseAdapter().resolve_session_source(
        {"event": "UserPromptSubmit", "session_id": "20260807_1", "working_dir": "/project"},
        home=tmp_path,
    )

    assert source is not None
    assert source.harness == "goose"
    assert source.cwd == "/project"
    assert source.path == goose_sessions.mirror_path("20260807_1", home=tmp_path)


def test_adapter_discovers_recent_sessions_with_parent_links(tmp_path: Path):
    _make_db(tmp_path)
    _add_session(tmp_path, "parent")
    _add_session(tmp_path, "child", parent="parent")
    _add_message(tmp_path, "parent")
    _add_message(tmp_path, "child")

    sources = {source.session_id: source for source in GooseAdapter().discover_session_sources(home=tmp_path)}

    assert set(sources) == {"parent", "child"}
    assert sources["child"].parent_session_id == "parent"


def test_adapter_returns_delegated_child_sources(tmp_path: Path):
    _make_db(tmp_path)
    _add_session(tmp_path, "parent")
    _add_session(tmp_path, "child", working_dir="/child", parent="parent")
    _add_message(tmp_path, "child")

    parent = GooseAdapter().resolve_session_source({"session_id": "parent"}, home=tmp_path)
    children = GooseAdapter().related_session_sources(parent, home=tmp_path)

    assert [child.session_id for child in children] == ["child"]
    assert children[0].parent_session_id == "parent"


def test_only_session_end_finalises_a_goose_session():
    adapter = GooseAdapter()
    assert adapter.is_session_final({"event": "SessionEnd"}) is True
    assert adapter.is_session_final({"event": "Stop"}) is False
    assert adapter.is_session_final({"event": "PostToolUse"}) is False


def test_adapter_falls_back_to_the_recorded_working_dir(tmp_path: Path):
    """SessionStart, UserPromptSubmit and SessionEnd payloads omit working_dir."""
    _make_db(tmp_path)
    _add_session(tmp_path, working_dir="/repo")
    _add_message(tmp_path)

    source = GooseAdapter().resolve_session_source({"event": "SessionEnd", "session_id": "20260807_1"}, home=tmp_path)

    assert source.cwd == "/repo"


def test_discovery_skips_reading_sessions_the_mirror_already_covers(tmp_path: Path, monkeypatch):
    _make_db(tmp_path)
    _add_session(tmp_path)
    _add_message(tmp_path)
    with sqlite3.connect(_db_path(tmp_path)) as connection:
        connection.execute("UPDATE sessions SET updated_at = datetime('now', '-1 hour')")
    adapter = GooseAdapter()
    adapter.discover_session_sources(home=tmp_path)  # first pass builds the mirror

    exports: list[str] = []
    original = goose_sessions.export_session
    monkeypatch.setattr(
        goose_sessions,
        "export_session",
        lambda session_id, **kwargs: exports.append(session_id) or original(session_id, **kwargs),
    )

    sources = adapter.discover_session_sources(home=tmp_path)

    assert [source.session_id for source in sources] == ["20260807_1"]
    assert exports == []  # mirror is newer than the session row, so the database is not reopened


def test_discovery_re_exports_when_goose_wrote_after_the_last_mirror(tmp_path: Path):
    _make_db(tmp_path)
    _add_session(tmp_path)
    _add_message(tmp_path, message_id="msg-1")
    adapter = GooseAdapter()
    adapter.discover_session_sources(home=tmp_path)

    _add_message(tmp_path, message_id="msg-2", role="assistant")
    with sqlite3.connect(_db_path(tmp_path)) as connection:
        connection.execute("UPDATE sessions SET updated_at = datetime('now', '+1 hour') WHERE id = ?", ("20260807_1",))

    adapter.discover_session_sources(home=tmp_path)

    ids = [r["message_id"] for r in _records(goose_sessions.export_session("20260807_1", home=tmp_path))[1:]]
    assert ids == ["msg-1", "msg-2"]


def test_goose_defers_network_delivery_out_of_the_hook():
    assert GooseAdapter().defer_session_delivery() is True
