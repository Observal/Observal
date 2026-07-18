# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
import time
from pathlib import Path

from observal_cli.harness import SessionSource


def test_public_reconcile_drains_outbox_then_all_detected_adapters(monkeypatch):
    from observal_cli import cmd_reconcile_cli

    calls: list[str] = []

    class Adapter:
        def __init__(self, installed: bool):
            self.installed = installed

        def is_installed(self):
            return self.installed

    monkeypatch.setattr(cmd_reconcile_cli, "load_config", lambda: {"user_id": "user"})
    monkeypatch.setattr(cmd_reconcile_cli, "ensure_loaded", lambda: None)
    monkeypatch.setattr(
        cmd_reconcile_cli,
        "drain_outbox",
        lambda _config: calls.append("outbox") or True,
    )
    monkeypatch.setattr(
        cmd_reconcile_cli,
        "get_all_adapters",
        lambda: {"claude-code": Adapter(True), "kiro": Adapter(True), "pi": Adapter(False)},
    )
    monkeypatch.setattr(
        cmd_reconcile_cli,
        "_reconcile_harness",
        lambda harness, *_args: calls.append(harness) or 1,
    )

    cmd_reconcile_cli.reconcile(harness="", since_hours=24, dry_run=False)

    assert calls == ["outbox", "claude-code", "kiro"]


def test_public_reconcile_discovers_claude_and_kiro_fixtures(tmp_path: Path, monkeypatch):
    from observal_cli import cmd_reconcile_cli

    claude = tmp_path / ".claude" / "projects" / "-work" / "claude-session.jsonl"
    kiro = tmp_path / ".kiro" / "sessions" / "cli" / "kiro-session.jsonl"
    claude.parent.mkdir(parents=True)
    kiro.parent.mkdir(parents=True)
    claude.write_text("{}\n")
    kiro.write_text("{}\n")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(cmd_reconcile_cli, "load_config", lambda: {"user_id": "user"})
    monkeypatch.setattr(cmd_reconcile_cli, "drain_outbox", lambda _config: True)
    delivered: list[str] = []
    monkeypatch.setattr(
        cmd_reconcile_cli,
        "drain_session_source",
        lambda source, *_args, **_kwargs: delivered.append(source.harness) or True,
    )

    cmd_reconcile_cli.reconcile(harness="", since_hours=24, dry_run=False)

    assert sorted(delivered) == ["claude-code", "kiro"]


def test_background_recovery_uses_adapter_sources_and_shared_drain(tmp_path: Path, monkeypatch):
    from observal_cli.hooks import session_push

    old_source = tmp_path / "old.jsonl"
    old_source.write_text("{}\n")
    os.utime(old_source, (time.time() - 300, time.time() - 300))
    finished_source = tmp_path / "finished.jsonl"
    finished_source.write_text("{}\n")
    os.utime(finished_source, (time.time() - 300, time.time() - 300))
    sources = [
        SessionSource("claude-code", "unfinished", old_source),
        SessionSource("claude-code", "finished", finished_source),
    ]

    class Adapter:
        def discover_session_sources(self, home=None):
            assert home == tmp_path
            return sources

        def session_extra_fields(self, source, event, final, home=None):
            return {"source": source.session_id}

    calls: list[str] = []
    monkeypatch.setattr(session_push, "ensure_loaded", lambda: None)
    monkeypatch.setattr(session_push, "get_adapter", lambda _harness: Adapter())
    monkeypatch.setattr(session_push, "load_config", lambda home=None: {"user_id": "user"})
    monkeypatch.setattr(session_push, "drain_outbox", lambda *_args, **_kwargs: calls.append("outbox") or True)
    monkeypatch.setattr(
        session_push,
        "read_cursor_state",
        lambda key, home=None: (finished_source.stat().st_size, 1, True) if key == "finished" else (0, 0, False),
    )
    monkeypatch.setattr(
        session_push,
        "drain_session_source",
        lambda source, *_args, **_kwargs: calls.append(source.session_id) or True,
    )

    session_push._recover_sessions("claude-code", home=tmp_path)

    assert calls == ["outbox", "unfinished"]
