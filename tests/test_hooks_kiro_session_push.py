# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for the Kiro session push hook."""

from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING

from observal_cli.hooks import kiro_session_push

if TYPE_CHECKING:
    from pathlib import Path


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_config(home: Path) -> None:
    _write_json(home / ".observal" / "config.json", {"server_url": "https://example.test", "api_key": "token"})


def test_find_kiro_jsonl_returns_present_file(tmp_path: Path):
    session_id = "session-1"
    jsonl = tmp_path / ".kiro" / "sessions" / "cli" / f"{session_id}.jsonl"
    jsonl.parent.mkdir(parents=True)
    jsonl.write_text("{}\n", encoding="utf-8")

    assert kiro_session_push.find_kiro_jsonl(session_id, home=tmp_path) == jsonl


def test_find_kiro_jsonl_returns_none_for_missing_file(tmp_path: Path):
    assert kiro_session_push.find_kiro_jsonl("missing", home=tmp_path) is None


def test_find_kiro_jsonl_returns_none_for_empty_session_id(tmp_path: Path):
    assert kiro_session_push.find_kiro_jsonl("", home=tmp_path) is None


def test_resolve_session_id_prefers_event_value(tmp_path: Path):
    assert kiro_session_push._resolve_session_id({"session_id": "from-event"}, home=tmp_path) == "from-event"


def test_resolve_session_id_uses_cached_session_for_stop_event(tmp_path: Path):
    _write_json(tmp_path / ".observal" / ".kiro-session", {"session_id": "cached-session"})

    assert kiro_session_push._resolve_session_id({"hook_event_name": "Stop"}, home=tmp_path) == "cached-session"


def test_read_kiro_credits_returns_none_when_absent(tmp_path: Path):
    assert kiro_session_push._read_kiro_credits("session-1", home=tmp_path) is None


def test_read_kiro_credits_sums_credit_turns(tmp_path: Path):
    _write_json(
        tmp_path / ".kiro" / "sessions" / "cli" / "session-1.json",
        {
            "session_state": {
                "conversation_metadata": {
                    "user_turn_metadatas": [
                        {"metering_usage": [{"unit": "credit", "value": 1.25}, {"unit": "token", "value": 20}]},
                        {"metering_usage": [{"unit": "credit", "value": 2.75}]},
                    ]
                }
            }
        },
    )

    assert kiro_session_push._read_kiro_credits("session-1", home=tmp_path) == 4.0


def test_read_kiro_credits_returns_none_for_malformed_json(tmp_path: Path):
    path = tmp_path / ".kiro" / "sessions" / "cli" / "session-1.json"
    path.parent.mkdir(parents=True)
    path.write_text("{broken", encoding="utf-8")

    assert kiro_session_push._read_kiro_credits("session-1", home=tmp_path) is None


def test_run_posts_new_lines_and_writes_cursor(monkeypatch, tmp_path: Path):
    session_id = "session-1"
    jsonl = tmp_path / ".kiro" / "sessions" / "cli" / f"{session_id}.jsonl"
    jsonl.parent.mkdir(parents=True)
    jsonl.write_text('{"type":"message"}\n', encoding="utf-8")
    _write_config(tmp_path)
    posted: list[dict] = []

    monkeypatch.setattr(kiro_session_push.sys, "stdin", io.StringIO(json.dumps({"session_id": session_id, "cwd": "/repo"})))
    monkeypatch.setattr(kiro_session_push, "post_to_server", lambda **kwargs: posted.append(kwargs["payload"]) or True)
    monkeypatch.setattr(kiro_session_push, "_spawn_crash_recovery", lambda: None)

    kiro_session_push._run(home=tmp_path)

    assert posted[0]["session_id"] == session_id
    assert posted[0]["ide"] == "kiro"
    state = json.loads((tmp_path / ".observal" / "sync_state.json").read_text())
    assert state[session_id]["line_count"] == 1


def test_run_stop_finalizes_and_posts_credits_without_new_lines(monkeypatch, tmp_path: Path):
    session_id = "session-1"
    jsonl = tmp_path / ".kiro" / "sessions" / "cli" / f"{session_id}.jsonl"
    jsonl.parent.mkdir(parents=True)
    jsonl.write_text("", encoding="utf-8")
    _write_config(tmp_path)
    _write_json(
        tmp_path / ".kiro" / "sessions" / "cli" / f"{session_id}.json",
        {
            "session_state": {
                "conversation_metadata": {
                    "user_turn_metadatas": [{"metering_usage": [{"unit": "credit", "value": 3.5}]}]
                }
            }
        },
    )
    posted: list[dict] = []

    monkeypatch.setattr(
        kiro_session_push.sys,
        "stdin",
        io.StringIO(json.dumps({"session_id": session_id, "hook_event_name": "Stop"})),
    )
    monkeypatch.setattr(kiro_session_push, "post_to_server", lambda **kwargs: posted.append(kwargs["payload"]) or True)

    kiro_session_push._run(home=tmp_path)

    assert posted[0]["final"] is True
    assert posted[0]["total_credits"] == 3.5
    state = json.loads((tmp_path / ".observal" / "sync_state.json").read_text())
    assert state[session_id]["finalized"] is True
