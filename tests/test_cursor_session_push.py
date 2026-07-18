# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Cursor adapter and shared acknowledged-delivery tests."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from observal_cli.harness import ensure_loaded, get_adapter
from observal_cli.hooks import session_push
from observal_cli.sessions.cursor import find_cursor_jsonl, project_key_from_cwd

if TYPE_CHECKING:
    from pathlib import Path


def make_session(home: Path, session_id: str = "session") -> Path:
    root = home / ".cursor" / "projects" / "home-user-project" / "agent-transcripts" / session_id
    root.mkdir(parents=True)
    path = root / f"{session_id}.jsonl"
    path.write_text('{"role":"user","message":{"content":[{"type":"text","text":"hello"}]}}\n')
    return path


def write_config(home: Path) -> None:
    root = home / ".observal"
    root.mkdir(parents=True)
    (root / "config.json").write_text(
        json.dumps({"server_url": "http://server", "access_token": "token", "user_id": "user"})
    )


def test_project_key_from_paths():
    assert project_key_from_cwd("/home/user/project") == "home-user-project"
    assert project_key_from_cwd("C:\\Users\\alice\\project") == "c-Users-alice-project"


def test_find_cursor_jsonl_primary_and_fallback(tmp_path: Path):
    path = make_session(tmp_path)
    assert find_cursor_jsonl("session", "home-user-project", home=tmp_path) == path
    assert find_cursor_jsonl("session", "wrong", home=tmp_path) == path
    assert find_cursor_jsonl("missing", "home-user-project", home=tmp_path) is None


def test_cursor_adapter_resolves_transcript_and_related_subagent(tmp_path: Path):
    path = make_session(tmp_path)
    subagents = path.parent / "subagents"
    subagents.mkdir()
    child = subagents / "agent-child.jsonl"
    child.write_text('{"role":"assistant","message":{"content":[]}}\n')
    ensure_loaded()
    adapter = get_adapter("cursor")

    source = adapter.resolve_session_source(
        {
            "conversationId": "session",
            "transcriptPath": str(path),
            "workspacePath": "/home/user/project",
        },
        home=tmp_path,
    )

    assert source is not None and source.path == path
    related = adapter.related_session_sources(source, home=tmp_path)
    assert len(related) == 1
    assert related[0].path == child
    assert related[0].checkpoint_key == "session__sub__child"
    assert related[0].parent_session_id == "session"


def test_cursor_usage_is_a_parent_only_synthetic_record(tmp_path: Path):
    path = make_session(tmp_path)
    ensure_loaded()
    adapter = get_adapter("cursor")
    source = adapter.resolve_session_source(
        {"conversationId": "session", "transcriptPath": str(path)},
        home=tmp_path,
    )
    assert source is not None
    event = {"input_tokens": 10, "output_tokens": 5, "model": "cursor-model"}

    records = adapter.session_extra_records(source, event, True, home=tmp_path)

    assert len(records) == 1
    usage = json.loads(records[0])["message"]["usage"]
    assert usage["input_tokens"] == 10
    assert usage["output_tokens"] == 5
    assert adapter.session_extra_records(source, event, False, home=tmp_path) == ()
    assert adapter.defer_session_delivery()


def test_cursor_stop_spools_in_hook_and_drains_in_worker(tmp_path: Path, monkeypatch):
    path = make_session(tmp_path)
    write_config(tmp_path)
    calls: list[dict] = []
    workers: list[tuple[tuple[str, ...], str]] = []

    monkeypatch.setattr(
        session_push,
        "drain_session_source",
        lambda _source, _config, **kwargs: calls.append(kwargs) or True,
    )
    monkeypatch.setattr(
        session_push,
        "_spawn_worker",
        lambda *args, harness: workers.append((args, harness)),
    )

    session_push._run_hook(
        {
            "event": "stop",
            "conversationId": "session",
            "transcriptPath": str(path),
            "workspacePath": "/home/user/project",
            "input_tokens": 10,
        },
        harness="cursor",
        home=tmp_path,
    )

    assert calls[0]["spool_only"] is True
    assert len(calls[0]["extra_records"]) == 1
    assert (("--drain-outbox",), "cursor") in workers
    assert (("--finalize-session", "session", "--cwd", "/home/user/project"), "cursor") in workers
