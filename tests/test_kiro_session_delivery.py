# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import os
import time
from typing import TYPE_CHECKING

from observal_cli.harness import ensure_loaded, get_adapter
from observal_cli.harness_specs.kiro_hooks_spec import build_kiro_hooks
from observal_cli.hooks import session_push
from observal_cli.sessions.kiro import read_kiro_agent_name

if TYPE_CHECKING:
    from pathlib import Path


def make_session(
    home: Path,
    session_id: str = "kiro-session",
    agent_name: str = "kiro_default",
    cwd: str = "/work",
) -> Path:
    root = home / ".kiro" / "sessions" / "cli"
    root.mkdir(parents=True, exist_ok=True)
    transcript = root / f"{session_id}.jsonl"
    transcript.write_text('{"kind":"Prompt","data":{"content":[{"kind":"text","data":"hello"}]}}\n')
    (root / f"{session_id}.json").write_text(
        json.dumps(
            {
                "cwd": cwd,
                "session_state": {
                    "agent_name": agent_name,
                    "conversation_metadata": {
                        "user_turn_metadatas": [
                            {
                                "loop_id": {"agent_id": {"name": agent_name}},
                                "metering_usage": [{"unit": "credit", "value": 1.25}],
                            },
                            {
                                "loop_id": {"agent_id": {"name": agent_name}},
                                "metering_usage": [{"unit": "credit", "value": 0.75}],
                            },
                        ]
                    },
                },
            }
        )
    )
    return transcript


def write_config(home: Path) -> None:
    root = home / ".observal"
    root.mkdir(parents=True, exist_ok=True)
    (root / "config.json").write_text(
        json.dumps({"server_url": "http://server", "access_token": "token", "user_id": "user"})
    )


def test_kiro_adapter_resolves_explicit_session_without_singleton(tmp_path: Path):
    transcript = make_session(tmp_path)
    ensure_loaded()
    adapter = get_adapter("kiro")

    source = adapter.resolve_session_source(
        {"session_id": "kiro-session", "cwd": "/hook-work"},
        home=tmp_path,
    )

    assert source is not None and source.path == transcript
    assert source.cwd == "/work"
    assert not (tmp_path / ".observal" / ".kiro-session").exists()


def test_kiro_adapter_ignores_missing_id_and_stale_singleton(tmp_path: Path):
    make_session(tmp_path, "stale-session")
    state_file = tmp_path / ".observal" / ".kiro-session"
    state_file.parent.mkdir(parents=True)
    state_file.write_text(json.dumps({"session_id": "stale-session"}))
    ensure_loaded()
    adapter = get_adapter("kiro")

    assert adapter.resolve_session_source({"event": "stop"}, home=tmp_path) is None
    assert json.loads(state_file.read_text()) == {"session_id": "stale-session"}


def test_uncorrelated_stop_does_not_select_concurrent_kiro_session(tmp_path: Path):
    make_session(tmp_path, "session-a")
    make_session(tmp_path, "session-b")
    ensure_loaded()
    adapter = get_adapter("kiro")

    source_a = adapter.resolve_session_source({"session_id": "session-a"}, home=tmp_path)
    source_b = adapter.resolve_session_source({"session_id": "session-b"}, home=tmp_path)

    assert source_a is not None and source_a.session_id == "session-a"
    assert source_b is not None and source_b.session_id == "session-b"
    assert adapter.resolve_session_source({"event": "stop"}, home=tmp_path) is None


def test_kiro_adapter_discovers_recent_sessions_and_credits(tmp_path: Path):
    recent = make_session(tmp_path)
    old = make_session(tmp_path, "old")
    old_time = time.time() - 10 * 24 * 3600
    os.utime(old, (old_time, old_time))
    ensure_loaded()
    adapter = get_adapter("kiro")

    sources = adapter.discover_session_sources(home=tmp_path, since_hours=24)

    assert [source.path for source in sources] == [recent]
    assert sources[0].cwd == "/work"
    assert adapter.session_extra_fields(sources[0], {}, True, home=tmp_path) == {"total_credits": 2.0}


def test_kiro_reads_active_agent_with_latest_turn_fallback(tmp_path: Path):
    transcript = make_session(tmp_path, agent_name="top-level-agent")
    assert read_kiro_agent_name(transcript) == "top-level-agent"

    companion = transcript.with_suffix(".json")
    companion.write_text(
        json.dumps(
            {
                "session_state": {
                    "conversation_metadata": {
                        "user_turn_metadatas": [
                            {"loop_id": {"agent_id": {"name": "old-agent"}}},
                            {"loop_id": {"agent_id": {"name": "latest-agent"}}},
                        ]
                    }
                }
            }
        )
    )
    assert read_kiro_agent_name(transcript) == "latest-agent"


def test_kiro_agent_metadata_fails_safely(tmp_path: Path):
    transcript = make_session(tmp_path)
    transcript.with_suffix(".json").write_text("not json")
    assert read_kiro_agent_name(transcript) is None
    transcript.with_suffix(".json").write_text("[]")
    assert read_kiro_agent_name(transcript) is None
    transcript.with_suffix(".json").write_text("null")
    assert read_kiro_agent_name(transcript) is None
    assert read_kiro_agent_name(tmp_path / "missing.jsonl") is None
    assert read_kiro_agent_name(None) is None


def test_kiro_recovery_attributes_each_session_from_its_metadata(tmp_path: Path, monkeypatch):
    pulled = make_session(tmp_path, "agent-session", agent_name="pulled-agent")
    default = make_session(tmp_path, "default-session", agent_name="kiro_default")
    old_time = time.time() - 180
    os.utime(pulled, (old_time, old_time))
    os.utime(default, (old_time, old_time))
    write_config(tmp_path)
    recovered: dict[str, tuple[str | None, str | None, bool]] = {}

    def lookup(name, harness, directory=None):
        assert name == "pulled-agent"
        assert directory == "/work"
        assert harness == "kiro"
        return {"id": "pulled-uuid", "version": "1.2.0"}

    def capture(source, _config, **_kwargs):
        from observal_cli.sessions.base import _resolve_agent

        assert source.session_id not in recovered
        identity = _resolve_agent(source.cwd, [], source.path, harness="kiro")
        recovered[source.session_id] = (*identity, _kwargs["final"])
        return True

    monkeypatch.setenv("OBSERVAL_AGENT_ID", "triggering-hook-uuid")
    monkeypatch.setattr("observal_cli.lockfile.get_agent_by_name", lookup)
    monkeypatch.setattr(session_push, "drain_outbox", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(session_push, "read_cursor_state", lambda *_args, **_kwargs: (0, 0, False))
    monkeypatch.setattr(session_push, "drain_session_source", capture)

    session_push._recover_sessions("kiro", home=tmp_path)

    assert recovered == {
        "agent-session": ("pulled-uuid", "1.2.0", False),
        "default-session": (None, None, False),
    }


def test_kiro_recovery_skips_acknowledged_eof(tmp_path: Path, monkeypatch):
    transcript = make_session(tmp_path)
    old_time = time.time() - 180
    os.utime(transcript, (old_time, old_time))
    write_config(tmp_path)
    recovered: list[str] = []

    monkeypatch.setattr(session_push, "drain_outbox", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        session_push,
        "read_cursor_state",
        lambda *_args, **_kwargs: (transcript.stat().st_size, 1, False),
    )
    monkeypatch.setattr(
        session_push,
        "drain_session_source",
        lambda source, *_args, **_kwargs: recovered.append(source.session_id) or True,
    )

    session_push._recover_sessions("kiro", home=tmp_path)

    assert recovered == []


def test_kiro_recovery_delivers_growth_non_finally(tmp_path: Path, monkeypatch):
    transcript = make_session(tmp_path)
    acknowledged_offset = transcript.stat().st_size
    with transcript.open("a") as file:
        file.write('{"kind":"Response","data":{"content":"later"}}\n')
    old_time = time.time() - 180
    os.utime(transcript, (old_time, old_time))
    write_config(tmp_path)
    recovered: list[tuple[str, bool]] = []

    monkeypatch.setattr(session_push, "drain_outbox", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        session_push,
        "read_cursor_state",
        lambda *_args, **_kwargs: (acknowledged_offset, 1, False),
    )
    monkeypatch.setattr(
        session_push,
        "drain_session_source",
        lambda source, *_args, **kwargs: recovered.append((source.session_id, kwargs["final"])) or True,
    )

    session_push._recover_sessions("kiro", home=tmp_path)

    assert recovered == [("kiro-session", False)]


def test_kiro_stop_routes_credits_through_shared_engine(tmp_path: Path, monkeypatch):
    make_session(tmp_path)
    write_config(tmp_path)
    drained: list[dict] = []
    spawned: list[tuple[tuple[str, ...], str]] = []

    def capture(_source, _config, **kwargs):
        drained.append(kwargs)
        return True

    monkeypatch.setattr(session_push, "drain_session_source", capture)
    monkeypatch.setattr(
        session_push,
        "_spawn_worker",
        lambda *args, harness: spawned.append((args, harness)),
    )

    session_push._run_hook(
        {"session_id": "kiro-session", "cwd": "/work", "event": "stop"},
        harness="kiro",
        home=tmp_path,
    )

    assert drained[0]["extra_fields"] == {"total_credits": 2.0}
    assert spawned == [(("--finalize-session", "kiro-session", "--cwd", "/work"), "kiro")]


def test_kiro_hook_spec_uses_shared_engine_with_uuid_attribution():
    hooks = build_kiro_hooks(agent_id="agent-uuid")
    command = hooks["userPromptSubmit"][0]["command"]

    assert "OBSERVAL_AGENT_ID=agent-uuid" in command or 'set "OBSERVAL_AGENT_ID=agent-uuid"' in command
    assert "observal_cli.hooks.session_push --harness kiro" in command
    assert hooks["stop"][0]["command"] == command
