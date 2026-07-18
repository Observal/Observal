# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import os
import time
from typing import TYPE_CHECKING

from observal_cli.harness import ensure_loaded, get_adapter
from observal_cli.harness_specs.kiro_hooks_spec import build_kiro_hooks
from observal_cli.hooks import session_push

if TYPE_CHECKING:
    from pathlib import Path


def make_session(home: Path, session_id: str = "kiro-session") -> Path:
    root = home / ".kiro" / "sessions" / "cli"
    root.mkdir(parents=True, exist_ok=True)
    transcript = root / f"{session_id}.jsonl"
    transcript.write_text('{"kind":"Prompt","data":{"content":[{"kind":"text","data":"hello"}]}}\n')
    (root / f"{session_id}.json").write_text(
        json.dumps(
            {
                "session_state": {
                    "conversation_metadata": {
                        "user_turn_metadatas": [
                            {"metering_usage": [{"unit": "credit", "value": 1.25}]},
                            {"metering_usage": [{"unit": "credit", "value": 0.75}]},
                        ]
                    }
                }
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


def test_kiro_adapter_resolves_and_persists_session_for_stop(tmp_path: Path):
    transcript = make_session(tmp_path)
    ensure_loaded()
    adapter = get_adapter("kiro")

    source = adapter.resolve_session_source(
        {"session_id": "kiro-session", "cwd": "/work"},
        home=tmp_path,
    )
    stop_source = adapter.resolve_session_source({"event": "stop"}, home=tmp_path)

    assert source is not None and source.path == transcript
    assert stop_source is not None and stop_source.session_id == "kiro-session"
    assert json.loads((tmp_path / ".observal" / ".kiro-session").read_text())["session_id"] == "kiro-session"


def test_kiro_adapter_discovers_recent_sessions_and_credits(tmp_path: Path):
    recent = make_session(tmp_path)
    old = make_session(tmp_path, "old")
    old_time = time.time() - 10 * 24 * 3600
    os.utime(old, (old_time, old_time))
    ensure_loaded()
    adapter = get_adapter("kiro")

    sources = adapter.discover_session_sources(home=tmp_path, since_hours=24)

    assert [source.path for source in sources] == [recent]
    assert adapter.session_extra_fields(sources[0], {}, True, home=tmp_path) == {"total_credits": 2.0}


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
    assert spawned == [(('--finalize-session', 'kiro-session', '--cwd', '/work'), "kiro")]


def test_kiro_hook_spec_uses_shared_engine_with_uuid_attribution():
    hooks = build_kiro_hooks(agent_id="agent-uuid")
    command = hooks["userPromptSubmit"][0]["command"]

    assert "OBSERVAL_AGENT_ID=agent-uuid" in command or 'set "OBSERVAL_AGENT_ID=agent-uuid"' in command
    assert "observal_cli.hooks.session_push --harness kiro" in command
    assert hooks["stop"][0]["command"] == command
