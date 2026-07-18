# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from observal_cli import telemetry_buffer
from observal_cli.harness import SessionSource
from observal_cli.sessions import base

if TYPE_CHECKING:
    from pathlib import Path


def config() -> dict:
    return {
        "server_url": "http://server",
        "access_token": "token",
        "user_id": "user",
    }


def disable_payload_metadata(monkeypatch):
    monkeypatch.setattr(base, "_resolve_agent", lambda *_args, **_kwargs: (None, None))
    monkeypatch.setattr(base, "_get_cached_layer_hash", lambda *_args, **_kwargs: None)


def test_read_new_records_excludes_partial_line_and_tracks_bytes(tmp_path: Path):
    source = tmp_path / "session.jsonl"
    source.write_bytes(b'{"a":1}\n\n{"b":2}')

    lines, end_offsets, consumed = base.read_new_records(source, 0)

    assert lines == ['{"a":1}']
    assert end_offsets == [8]
    assert consumed == 9


@pytest.mark.parametrize("local_state", ["missing", "corrupt", "stale"])
def test_server_checkpoint_recovers_local_cursor(tmp_path: Path, monkeypatch, local_state: str):
    disable_payload_metadata(monkeypatch)
    source_path = tmp_path / "session.jsonl"
    records = ['{"n":0}\n', '{"n":1}\n', '{"n":2}\n']
    source_path.write_text("".join(records))
    if local_state == "corrupt":
        state = tmp_path / ".observal" / "sync_state.json"
        state.parent.mkdir()
        state.write_text("not-json")
    elif local_state == "stale":
        base.write_cursor("session", source_path.stat().st_size, 3, finalized=True, home=tmp_path)
    db = tmp_path / "outbox.db"
    source = SessionSource("claude-code", "session", source_path)
    acknowledged_offset = len(records[0].encode()) + len(records[1].encode())

    assert base.drain_session_source(
        source,
        config(),
        hook_event="Reconcile",
        spool_only=True,
        recover_from_server=True,
        checkpoint_fetch=lambda _source, _config: {
            "acknowledged_line": 1,
            "acknowledged_offset": acknowledged_offset,
        },
        home=tmp_path,
        db_path=db,
    )

    item = telemetry_buffer.pending(destination="http://server", user_id="user", db_path=db)[0]
    assert item.start_line == item.end_line == 2
    assert item.payload["lines"] == ['{"n":2}']
    assert base.read_cursor("session", home=tmp_path) == (acknowledged_offset, 2)
    assert base.read_cursor_state("session", home=tmp_path)[2] is False


def test_server_checkpoint_without_byte_offset_maps_source_line(tmp_path: Path):
    source_path = tmp_path / "session.jsonl"
    source_path.write_text('{"n":0}\n\n{"n":1}\n')
    source = SessionSource("claude-code", "session", source_path)

    recovered = base.recover_cursor_from_server(
        source,
        config(),
        home=tmp_path,
        fetch=lambda _source, _config: {"acknowledged_line": 0, "acknowledged_offset": 0},
    )

    assert recovered == (8, 1)


def test_invalid_server_byte_checkpoint_does_not_skip_local_source(tmp_path: Path):
    source_path = tmp_path / "session.jsonl"
    source_path.write_text('{"n":0}\n')
    source = SessionSource("claude-code", "session", source_path)

    recovered = base.recover_cursor_from_server(
        source,
        config(),
        home=tmp_path,
        fetch=lambda _source, _config: {"acknowledged_line": 4, "acknowledged_offset": 999},
    )

    assert recovered is None
    assert base.read_cursor("session", home=tmp_path) == (0, 0)


def test_offline_delivery_spools_before_post_and_keeps_cursor(tmp_path: Path, monkeypatch):
    disable_payload_metadata(monkeypatch)
    source_path = tmp_path / "session.jsonl"
    source_path.write_text('{"type":"system","content":"one"}\n')
    db = tmp_path / "outbox.db"
    source = SessionSource("claude-code", "session", source_path)
    observed_pending: list[int] = []

    def offline(_payload, _config):
        observed_pending.append(telemetry_buffer.stats(db_path=db)["pending"])
        return None

    assert not base.drain_session_source(
        source,
        config(),
        hook_event="UserPromptSubmit",
        home=tmp_path,
        db_path=db,
        post=offline,
    )

    assert observed_pending == [1]
    assert base.read_cursor("session", home=tmp_path) == (0, 0)
    assert telemetry_buffer.pending(destination="http://server", user_id="user", db_path=db)[0].attempts == 1


def test_spool_only_never_blocks_hook_on_network(tmp_path: Path, monkeypatch):
    disable_payload_metadata(monkeypatch)
    source_path = tmp_path / "session.jsonl"
    source_path.write_text('{"role":"user","message":{"content":[]}}\n')
    db = tmp_path / "outbox.db"
    posts: list[dict] = []

    assert base.drain_session_source(
        SessionSource("cursor", "session", source_path),
        config(),
        hook_event="stop",
        extra_records=(json.dumps({"role": "assistant", "message": {"usage": {"input_tokens": 1}}}),),
        spool_only=True,
        home=tmp_path,
        db_path=db,
        post=lambda payload, _config: posts.append(payload),
    )

    assert posts == []
    assert base.read_cursor("session", home=tmp_path) == (0, 0)
    item = telemetry_buffer.pending(destination="http://server", user_id="user", db_path=db)[0]
    assert item.start_line == 0
    assert item.end_line == 1


def test_offline_growth_spools_only_records_after_pending_checkpoint(tmp_path: Path, monkeypatch):
    disable_payload_metadata(monkeypatch)
    source_path = tmp_path / "session.jsonl"
    source_path.write_text('{"type":"system","content":"one"}\n')
    db = tmp_path / "outbox.db"
    source = SessionSource("claude-code", "session", source_path)

    def offline(_payload, _config):
        return None

    base.drain_session_source(
        source,
        config(),
        hook_event="UserPromptSubmit",
        home=tmp_path,
        db_path=db,
        post=offline,
    )
    with source_path.open("a") as file:
        file.write('{"type":"system","content":"two"}\n')
    base.drain_session_source(
        source,
        config(),
        hook_event="Stop",
        final=True,
        home=tmp_path,
        db_path=db,
        post=offline,
    )

    items = telemetry_buffer.pending(destination="http://server", user_id="user", db_path=db)
    assert [(item.start_line, item.end_line) for item in items] == [(0, 0), (1, 1)]
    assert items[-1].final
    assert base.read_cursor("session", home=tmp_path) == (0, 0)


def test_restart_drains_acknowledged_records_and_finalizes_cursor(tmp_path: Path, monkeypatch):
    disable_payload_metadata(monkeypatch)
    source_path = tmp_path / "session.jsonl"
    source_path.write_text('{"type":"system","content":"one"}\n\n')
    db = tmp_path / "outbox.db"
    source = SessionSource("claude-code", "session", source_path)

    base.drain_session_source(
        source,
        config(),
        hook_event="Stop",
        final=True,
        home=tmp_path,
        db_path=db,
        post=lambda _payload, _config: None,
    )

    def acknowledge(payload, _config):
        return {
            "acknowledged_line": payload["start_offset"] + len(payload["lines"]) - 1,
            "acknowledged_offset": payload["end_byte_offsets"][-1],
        }

    assert base.drain_outbox(config(), home=tmp_path, db_path=db, post=acknowledge)
    assert telemetry_buffer.stats(db_path=db)["pending"] == 0
    assert base.read_cursor("session", home=tmp_path) == (source_path.stat().st_size, 1)
    state = json.loads((tmp_path / ".observal" / "sync_state.json").read_text())
    assert state["session"]["finalized"] is True


def test_metadata_only_final_batch_is_spooled_and_acknowledged(tmp_path: Path, monkeypatch):
    disable_payload_metadata(monkeypatch)
    source_path = tmp_path / "session.jsonl"
    source_path.write_text("")
    db = tmp_path / "outbox.db"
    captured: list[dict] = []

    def acknowledge(payload, _config):
        captured.append(payload)
        return {"acknowledged_line": -1, "acknowledged_offset": 0}

    assert base.drain_session_source(
        SessionSource("kiro", "session", source_path),
        config(),
        hook_event="Stop",
        final=True,
        extra_fields={"total_credits": 2.0},
        home=tmp_path,
        db_path=db,
        post=acknowledge,
    )
    assert captured[0]["lines"] == []
    assert captured[0]["total_credits"] == 2.0
    assert telemetry_buffer.stats(db_path=db)["pending"] == 0


def test_final_drain_with_no_new_records_marks_acknowledged_cursor_final(tmp_path: Path, monkeypatch):
    disable_payload_metadata(monkeypatch)
    source_path = tmp_path / "session.jsonl"
    source_path.write_text('{"type":"system","content":"one"}\n')
    db = tmp_path / "outbox.db"
    source = SessionSource("claude-code", "session", source_path)

    def acknowledge(payload, _config):
        return {
            "acknowledged_line": payload["start_offset"] + len(payload["lines"]) - 1,
            "acknowledged_offset": payload.get("end_byte_offsets", [])[-1]
            if payload.get("end_byte_offsets")
            else payload["total_offset"],
        }

    assert base.drain_session_source(
        source,
        config(),
        hook_event="UserPromptSubmit",
        home=tmp_path,
        db_path=db,
        post=acknowledge,
    )
    assert base.drain_session_source(
        source,
        config(),
        hook_event="Stop",
        final=True,
        home=tmp_path,
        db_path=db,
        post=acknowledge,
    )
    state = json.loads((tmp_path / ".observal" / "sync_state.json").read_text())
    assert state["session"]["finalized"] is True


def test_final_hash_mismatch_rewinds_and_repairs_source_range(tmp_path: Path, monkeypatch):
    disable_payload_metadata(monkeypatch)
    source_path = tmp_path / "session.jsonl"
    source_path.write_text('{"n":0}\n{"n":1}\n{"n":2}\n')
    source = SessionSource("claude-code", "session", source_path)
    db = tmp_path / "outbox.db"
    starts: list[int] = []

    def audit(payload, _config):
        starts.append(payload["start_offset"])
        if len(starts) == 1:
            return {
                "acknowledged_line": 0,
                "acknowledged_offset": 8,
                "integrity_ok": False,
                "repair_from_line": 1,
            }
        return {
            "acknowledged_line": 2,
            "acknowledged_offset": source_path.stat().st_size,
            "integrity_ok": True,
        }

    assert not base.drain_session_source(
        source,
        config(),
        hook_event="Stop",
        final=True,
        home=tmp_path,
        db_path=db,
        post=audit,
    )
    assert base.read_cursor("session", home=tmp_path) == (8, 1)

    assert base.drain_session_source(
        source,
        config(),
        hook_event="Stop",
        final=True,
        home=tmp_path,
        db_path=db,
        post=audit,
    )
    assert starts == [0, 1]
    assert telemetry_buffer.stats(db_path=db)["pending"] == 0
    assert base.read_cursor("session", home=tmp_path) == (source_path.stat().st_size, 3)


def test_server_commit_before_local_delete_is_safe_to_retry(tmp_path: Path, monkeypatch):
    disable_payload_metadata(monkeypatch)
    source_path = tmp_path / "session.jsonl"
    source_path.write_text('{"type":"system","content":"one"}\n')
    db = tmp_path / "outbox.db"
    source = SessionSource("claude-code", "session", source_path)
    posts = 0

    base.drain_session_source(
        source,
        config(),
        hook_event="UserPromptSubmit",
        home=tmp_path,
        db_path=db,
        post=lambda _payload, _config: None,
    )

    real_acknowledge = telemetry_buffer.acknowledge

    def crash_after_server_ack(**_kwargs):
        raise RuntimeError("process died before local delete")

    monkeypatch.setattr(telemetry_buffer, "acknowledge", crash_after_server_ack)

    def server_ack(payload, _config):
        nonlocal posts
        posts += 1
        return {
            "acknowledged_line": payload["start_offset"] + len(payload["lines"]) - 1,
            "acknowledged_offset": payload["end_byte_offsets"][-1],
        }

    with pytest.raises(RuntimeError):
        base.drain_outbox(config(), home=tmp_path, db_path=db, post=server_ack)

    assert telemetry_buffer.stats(db_path=db)["pending"] == 1
    monkeypatch.setattr(telemetry_buffer, "acknowledge", real_acknowledge)
    assert base.drain_outbox(config(), home=tmp_path, db_path=db, post=server_ack)
    assert posts == 2
    assert telemetry_buffer.stats(db_path=db)["pending"] == 0


def test_outbox_is_drained_before_new_source_batch(tmp_path: Path, monkeypatch):
    disable_payload_metadata(monkeypatch)
    db = tmp_path / "outbox.db"
    telemetry_buffer.enqueue(
        {
            "session_id": "older",
            "harness": "claude-code",
            "lines": ['{"type":"system","content":"old"}'],
            "start_offset": 0,
            "end_byte_offsets": [10],
        },
        destination="http://server",
        user_id="user",
        db_path=db,
    )
    source_path = tmp_path / "new.jsonl"
    source_path.write_text('{"type":"system","content":"new"}\n')
    order: list[str] = []

    def acknowledge(payload, _config):
        order.append(payload["session_id"])
        return {
            "acknowledged_line": payload["start_offset"] + len(payload["lines"]) - 1,
            "acknowledged_offset": payload["end_byte_offsets"][-1],
        }

    assert base.drain_session_source(
        SessionSource("claude-code", "new", source_path),
        config(),
        hook_event="UserPromptSubmit",
        home=tmp_path,
        db_path=db,
        post=acknowledge,
    )
    assert order == ["older", "new"]
