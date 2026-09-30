# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""DeepSeek physical session discovery and shared delivery reader tests."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

import pytest
import zstandard

from observal_cli import telemetry_buffer
from observal_cli.sessions import base, deepseek
from observal_cli.sessions.source_reader import source_size

if TYPE_CHECKING:
    from pathlib import Path


def _line(value: dict) -> bytes:
    return (json.dumps(value, separators=(",", ":")) + "\n").encode()


def _session(
    home: Path,
    session_id: str = "session-1",
    *,
    cwd: str = "/work/tree",
    parent: str | None = None,
    compressed: bool = True,
    version: int = 4,
    records: tuple[bytes, ...] = (),
) -> Path:
    root = deepseek.resolve_dsh_home(home) / "sessions"
    project = deepseek._project_key(cwd)
    directory = root / project / deepseek._encode_segment(session_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"session.v{version}.jsonl{'.zstd' if compressed else ''}"
    header = {
        "type": "session",
        "version": version,
        "id": session_id,
        "createdAt": 1780000000000,
        "cwd": cwd,
        "isSeeded": bool(parent),
        "delegationDepth": int(bool(parent)),
    }
    if parent:
        header["parentSession"] = parent
    frames = [_line(header), *records]
    if compressed:
        compressor = zstandard.ZstdCompressor(write_checksum=True)
        path.write_bytes(b"".join(compressor.compress(frame) for frame in frames))
    else:
        path.write_bytes(b"".join(frames))
    return path


def _config() -> dict:
    return {"server_url": "http://server", "access_token": "token", "user_id": "user"}


@pytest.mark.parametrize("compressed", [True, False])
def test_current_generations_and_hook_resolution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, compressed: bool):
    monkeypatch.delenv("DSH_HOME", raising=False)
    record = _line({"type": "turn/start", "seq": 0})
    path = _session(tmp_path, compressed=compressed, records=(record,))
    source = deepseek.resolve_session_source(
        {"session_id": "session-1", "cwd": "/work/tree", "transcript_path": ""}, tmp_path
    )
    assert source is not None
    assert (source.harness, source.session_id, source.path, source.cwd) == ("deepseek", "session-1", path, "/work/tree")
    assert [s.session_id for s in deepseek.discover_session_sources(tmp_path)] == ["session-1"]
    lines, offsets, consumed = base.read_new_records(path, 0)
    assert json.loads(lines[0])["id"] == "session-1"
    assert lines[1] == record.decode().strip()
    assert consumed == offsets[-1] == sum(len(line.encode()) + 1 for line in lines)
    assert base.read_new_records(path, offsets[0]) == ([lines[1]], [offsets[1]], len(record))
    assert source_size(path) == (consumed, True)
    assert base._first_line_timestamp(path).year == 2026


def test_compressed_multiple_frames_torn_then_completed(tmp_path: Path):
    first = _line({"type": "a"})
    second = _line({"type": "b"})
    path = _session(tmp_path, records=(first,))
    compressor = zstandard.ZstdCompressor(write_checksum=True)
    frame = compressor.compress(second)
    with path.open("ab") as file:
        file.write(frame[:-2])
    lines, offsets, consumed = base.read_new_records(path, 0)
    assert len(lines) == 2
    assert consumed == offsets[-1]
    assert source_size(path) == (consumed, False)
    assert base.read_new_records(path, consumed) == ([], [], 0)
    with path.open("ab") as file:
        file.write(frame[-2:])
    assert base.read_new_records(path, consumed) == ([second.decode().strip()], [consumed + len(second)], len(second))
    assert source_size(path) == (consumed + len(second), True)


def test_large_frame_crosses_read_chunks(tmp_path: Path):
    record = _line({"content": os.urandom(70000).hex()})
    path = _session(tmp_path, records=(record,))
    assert base.read_new_records(path, 0)[0][-1] == record.decode().strip()


@pytest.mark.parametrize("bad_frame", [b"not a zstd frame", zstandard.ZstdCompressor().compress(b"{}\n")])
def test_invalid_magic_or_unchecked_frame_is_rejected(tmp_path: Path, bad_frame: bytes):
    path = _session(tmp_path)
    with path.open("ab") as file:
        file.write(bad_frame)
    with pytest.raises(ValueError, match="corrupt Zstandard"):
        base.read_new_records(path, 0)


def test_corrupt_complete_frame_is_not_delivered(tmp_path: Path):
    path = _session(tmp_path, records=(_line({"type": "a"}), _line({"type": "b"})))
    damaged = bytearray(path.read_bytes())
    damaged[-1] ^= 3
    path.write_bytes(damaged)
    with pytest.raises(ValueError, match="corrupt Zstandard"):
        base.read_new_records(path, 0)
    with pytest.raises(ValueError, match="corrupt Zstandard"):
        source_size(path)


def test_plain_jsonl_incomplete_tail_then_completion(tmp_path: Path):
    path = _session(tmp_path, compressed=False)
    complete = path.stat().st_size
    with path.open("ab") as file:
        file.write(b'{"type":"new"')
    assert base.read_new_records(path, complete) == ([], [], 0)
    assert source_size(path) == (complete, False)
    with path.open("ab") as file:
        file.write(b"}\n")
    assert base.read_new_records(path, complete) == (['{"type":"new"}'], [complete + 15], 15)


def test_plain_reader_seeks_to_offset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "plain.jsonl"
    path.write_bytes(b'{"old":1}\n' * 1000 + b'{"new":1}\n')
    offset = len(b'{"old":1}\n') * 1000
    from observal_cli.sessions import source_reader

    original = source_reader.source_chunks
    requested: list[int] = []

    def tracked(path, *, offset=0, complete=None):
        requested.append(offset)
        yield from original(path, offset=offset, complete=complete)

    monkeypatch.setattr(base, "source_chunks", tracked)
    assert base.read_new_records(path, offset) == (['{"new":1}'], [path.stat().st_size], 10)
    assert requested == [offset]


def test_checkpoint_and_hash_use_logical_offsets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DSH_HOME", raising=False)
    monkeypatch.setattr(base, "_resolve_agent", lambda *_args, **_kwargs: (None, None))
    monkeypatch.setattr(base, "_get_cached_layer_hash", lambda *_args, **_kwargs: None)
    record = _line({"type": "turn/start", "seq": 0})
    path = _session(tmp_path, records=(record,))
    source = deepseek.resolve_session_source({"session_id": "session-1"}, tmp_path)
    assert source is not None
    all_lines, offsets, total = base.read_new_records(path, 0)
    assert total != path.stat().st_size
    assert base._checkpoint_byte_offset(path, 1, offsets[0]) == offsets[0]
    assert base._checkpoint_byte_offset(path, 1, offsets[0] - 1) is None
    assert base._checkpoint_byte_offset(path, 2, offsets[0]) is None
    assert base._checkpoint_byte_offset(path, 1, 0) == offsets[0]
    recovered = base.recover_cursor_from_server(
        source,
        _config(),
        home=tmp_path,
        fetch=lambda *_args: {"acknowledged_line": 0, "acknowledged_offset": offsets[0]},
    )
    assert recovered == (offsets[0], 1)
    db = tmp_path / "outbox.db"
    assert base.drain_session_source(
        source, _config(), hook_event="Reconcile", final=True, spool_only=True, home=tmp_path, db_path=db
    )
    pending = telemetry_buffer.pending(destination="http://server", user_id="user", db_path=db)
    assert len(pending) == 1
    payload = pending[0].payload
    assert payload["lines"] == [all_lines[1]]
    assert payload["end_byte_offsets"] == [offsets[1]]
    assert payload["total_offset"] == total
    assert (payload["session_hash"], payload["hashed_line_count"]) == base.hash_session_source(path)


def test_final_deferred_for_torn_frame_and_jsonl_tail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DSH_HOME", raising=False)
    monkeypatch.setattr(base, "_resolve_agent", lambda *_args, **_kwargs: (None, None))
    monkeypatch.setattr(base, "_get_cached_layer_hash", lambda *_args, **_kwargs: None)
    for compressed in (True, False):
        session_id = f"test-{compressed}"
        path = _session(tmp_path, session_id=session_id, compressed=compressed)
        fragment = zstandard.ZstdCompressor(write_checksum=True).compress(_line({"type": "more"}))
        with path.open("ab") as file:
            file.write(fragment[:-1] if compressed else b'{"type":"more"')
        source = deepseek.resolve_session_source({"session_id": session_id}, tmp_path)
        assert source is not None
        db = tmp_path / f"{session_id}.db"
        assert base.drain_session_source(
            source, _config(), hook_event="Stop", final=True, spool_only=True, home=tmp_path, db_path=db
        )
        pending = telemetry_buffer.pending(destination="http://server", user_id="user", db_path=db)
        assert len(pending) == 1
        assert pending[0].final is False
        assert pending[0].payload["lines"] == [base.read_new_records(path, 0)[0][0]]
        with path.open("ab") as file:
            file.write(fragment[-1:] if compressed else b"}\n")
        assert base.drain_session_source(
            source, _config(), hook_event="Stop", final=True, spool_only=True, home=tmp_path, db_path=db
        )
        pending = telemetry_buffer.pending(destination="http://server", user_id="user", db_path=db)
        assert pending[-1].final
        assert pending[-1].payload["hashed_line_count"] == 2


def test_incomplete_metadata_only_stop_never_inherits_build_payload_final(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("DSH_HOME", raising=False)
    monkeypatch.setattr(base, "_resolve_agent", lambda *_args, **_kwargs: (None, None))
    monkeypatch.setattr(base, "_get_cached_layer_hash", lambda *_args, **_kwargs: None)
    path = _session(tmp_path)
    source = deepseek.resolve_session_source({"session_id": "session-1"}, tmp_path)
    assert source is not None
    end = base.read_new_records(path, 0)[2]
    base.write_cursor(source.checkpoint_key, end, 1, home=tmp_path)
    with path.open("ab") as file:
        file.write(zstandard.ZstdCompressor(write_checksum=True).compress(b'{"type":"event"}\n')[:-1])
    db = tmp_path / "outbox.db"
    assert base.drain_session_source(
        source,
        _config(),
        hook_event="Stop",
        final=True,
        extra_fields={"total_credits": 1},
        spool_only=True,
        home=tmp_path,
        db_path=db,
    )
    payload = telemetry_buffer.pending(destination="http://server", user_id="user", db_path=db)[0].payload
    assert "final" not in payload
    assert "session_hash" not in payload


def test_arbitrary_metadata_and_final_fields_are_owned_by_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DSH_HOME", raising=False)
    monkeypatch.setattr(base, "_resolve_agent", lambda *_args, **_kwargs: (None, None))
    monkeypatch.setattr(base, "_get_cached_layer_hash", lambda *_args, **_kwargs: None)
    path = _session(tmp_path)
    source = deepseek.resolve_session_source({"session_id": "session-1"}, tmp_path)
    assert source is not None
    end = base.read_new_records(path, 0)[2]
    extras = {
        "context": "present",
        "final": True,
        "total_offset": 999,
        "total_line_count": 999,
        "session_hash": "invented",
        "hashed_line_count": 999,
    }
    db = tmp_path / "outbox.db"
    frame = zstandard.ZstdCompressor(write_checksum=True).compress(b'{"type":"later"}\n')
    with path.open("ab") as file:
        file.write(frame[:-1])
    assert base.drain_session_source(
        source,
        _config(),
        hook_event="Stop",
        final=True,
        extra_fields=extras,
        spool_only=True,
        home=tmp_path,
        db_path=db,
    )
    payload = telemetry_buffer.pending(destination="http://server", user_id="user", db_path=db)[0].payload
    assert payload["context"] == "present"
    assert all(
        field not in payload
        for field in ("final", "total_offset", "total_line_count", "session_hash", "hashed_line_count")
    )
    base.write_cursor(source.checkpoint_key, end, 1, home=tmp_path)
    empty_db = tmp_path / "metadata.db"
    assert base.drain_session_source(
        source,
        _config(),
        hook_event="Stop",
        final=True,
        extra_fields=extras,
        spool_only=True,
        home=tmp_path,
        db_path=empty_db,
    )
    assert telemetry_buffer.pending(destination="http://server", user_id="user", db_path=empty_db) == []
    with path.open("ab") as file:
        file.write(frame[-1:])
    assert base.drain_session_source(
        source,
        _config(),
        hook_event="Stop",
        final=True,
        extra_fields=extras,
        spool_only=True,
        home=tmp_path,
        db_path=empty_db,
    )
    payload = telemetry_buffer.pending(destination="http://server", user_id="user", db_path=empty_db)[0].payload
    assert payload["context"] == "present"
    assert payload["final"] is True
    assert payload["total_line_count"] == 2
    assert payload["total_offset"] == source_size(path)[0]
    assert payload["session_hash"] != "invented"
    assert payload["hashed_line_count"] == 2
    base.write_cursor(source.checkpoint_key, source_size(path)[0], 2, home=tmp_path)
    metadata_db = tmp_path / "complete-metadata.db"
    assert base.drain_session_source(
        source,
        _config(),
        hook_event="Stop",
        final=True,
        extra_fields={**extras, "context": "kept", "final": False},
        spool_only=True,
        home=tmp_path,
        db_path=metadata_db,
    )
    metadata = telemetry_buffer.pending(destination="http://server", user_id="user", db_path=metadata_db)[0].payload
    assert metadata["lines"] == []
    assert metadata["context"] == "kept"
    assert metadata["final"] is True
    assert metadata["total_offset"] == source_size(path)[0]
    assert metadata["total_line_count"] == 2
    assert metadata["session_hash"] != "invented"
    assert metadata["hashed_line_count"] == 2


def test_override_missing_generation_and_parent_child(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    external = tmp_path / "external"
    monkeypatch.setenv("DSH_HOME", str(external))
    assert deepseek.resolve_dsh_home(tmp_path) == external
    assert deepseek.discover_session_sources(tmp_path) == []
    _session(tmp_path, "parent")
    child = _session(tmp_path, "child", parent="parent", cwd="/child")
    parent = deepseek.resolve_session_source({"session_id": "parent"}, tmp_path)
    assert parent is not None
    assert [
        (s.session_id, s.path, s.parent_session_id) for s in deepseek.related_session_sources(parent, tmp_path)
    ] == [("child", child, "parent")]
    assert deepseek.resolve_session_source({"session_id": "missing"}, tmp_path) is None
    _session(tmp_path, "parent", version=5)
    assert deepseek.resolve_session_source({"session_id": "parent"}, tmp_path) is None
    assert [s.session_id for s in deepseek.discover_session_sources(tmp_path)] == ["child"]
    assert deepseek.resolve_session_source({"session_id": "../../escape"}, tmp_path) is None
    encoded = _session(tmp_path, "../../safe")
    assert encoded.is_relative_to(external / "sessions")
    assert deepseek.resolve_session_source({"session_id": "../../safe", "cwd": "/work/tree"}, tmp_path).path == encoded


def test_default_home_and_nested_children(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DSH_HOME", raising=False)
    monkeypatch.setenv("DSH_HOME", "  \t")
    assert deepseek.resolve_dsh_home(tmp_path) == tmp_path / ".dsh"
    monkeypatch.setenv("DSH_HOME", "~/private")
    assert deepseek.resolve_dsh_home(tmp_path) == tmp_path / "private"
    monkeypatch.setenv("DSH_HOME", "~")
    assert deepseek.resolve_dsh_home(tmp_path) == tmp_path
    monkeypatch.delenv("DSH_HOME")
    _session(tmp_path, "parent")
    _session(tmp_path, "child", parent="parent")
    grandchild = _session(tmp_path, "grandchild", parent="child")
    child = deepseek.resolve_session_source({"session_id": "child"}, tmp_path)
    assert child is not None
    assert [source.path for source in deepseek.related_session_sources(child, tmp_path)] == [grandchild]


def test_zero_materialization_and_symlink_traversal_are_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DSH_HOME", raising=False)
    path = _session(tmp_path, "empty")
    path.write_bytes(b"")
    assert deepseek.resolve_session_source({"session_id": "empty"}, tmp_path) is None
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = deepseek.resolve_dsh_home(tmp_path) / "sessions" / "--linked--"
    linked.symlink_to(outside, target_is_directory=True)
    assert deepseek.discover_session_sources(tmp_path) == []


def test_reconcile_dry_run_defers_torn_compressed_tail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from observal_cli import cmd_reconcile_cli

    monkeypatch.delenv("DSH_HOME", raising=False)
    path = _session(tmp_path, records=(_line({"type": "turn/start"}),))
    logical, _ = source_size(path)
    with path.open("ab") as file:
        file.write(zstandard.ZstdCompressor(write_checksum=True).compress(b"x" * 10000)[:-1])
    source = deepseek.resolve_session_source({"session_id": "session-1"}, tmp_path)
    assert source is not None

    class Adapter:
        def discover_session_sources(self, since_hours):
            return [source]

    monkeypatch.setattr(cmd_reconcile_cli, "get_adapter", lambda _harness: Adapter())
    monkeypatch.setattr(cmd_reconcile_cli, "read_cursor_state", lambda _key: (logical, 2, True))
    result = cmd_reconcile_cli._reconcile_harness("deepseek", _config(), 24, True)
    assert result["up_to_date"] == 0
    assert result["skipped"] == 1
    assert result["sessions"][0]["reason"] == "incomplete source tail"


@pytest.mark.parametrize("compressed", [True, False])
def test_reconcile_dry_run_ignores_only_incomplete_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, compressed: bool
):
    from observal_cli import cmd_reconcile_cli

    monkeypatch.delenv("DSH_HOME", raising=False)
    path = _session(tmp_path, compressed=compressed)
    committed, _ = source_size(path)
    incomplete = b'{"type":"unfinished"'
    with path.open("ab") as file:
        file.write(zstandard.ZstdCompressor(write_checksum=True).compress(incomplete) if compressed else incomplete)
    assert source_size(path) == (committed, False)
    source = deepseek.resolve_session_source({"session_id": "session-1"}, tmp_path)
    assert source is not None

    class Adapter:
        def discover_session_sources(self, since_hours):
            return [source]

    monkeypatch.setattr(cmd_reconcile_cli, "get_adapter", lambda _harness: Adapter())
    monkeypatch.setattr(cmd_reconcile_cli, "read_cursor_state", lambda _key: (committed, 1, False))
    result = cmd_reconcile_cli._reconcile_harness("deepseek", _config(), 24, True)
    assert result["would_push"] == result["would_finalize"] == result["up_to_date"] == 0
    assert result["skipped"] == 1
    assert result["sessions"][0]["bytes_new"] == 0


def test_unreadable_project_and_negative_created_at_do_not_hide_other_sessions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("DSH_HOME", raising=False)
    _session(tmp_path, "unreadable", cwd="/unreadable")
    bad_header = _session(tmp_path, "negative", cwd="/negative", compressed=False)
    text = bad_header.read_text().replace('"createdAt":1780000000000', '"createdAt":-1')
    bad_header.write_text(text)
    _session(tmp_path, "good", cwd="/good")
    original = type(tmp_path).iterdir

    def isolated(directory):
        if directory.name == "--unreadable--":
            raise PermissionError("unreadable")
        return original(directory)

    monkeypatch.setattr(type(tmp_path), "iterdir", isolated)
    assert [source.session_id for source in deepseek.discover_session_sources(tmp_path)] == ["good"]


def test_configured_tilde_root_is_user_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DSH_HOME", raising=False)
    original = _session(tmp_path, "tilde")
    target = tmp_path / original.parent.parent.name / original.parent.name / original.name
    target.parent.mkdir(parents=True)
    original.replace(target)
    patch = tmp_path / ".dsh" / "cordis.patch.yml"
    patch.write_text(
        "- insert:\n    - name: '@deepseek-ai/dsh-session-persistence-jsonl'\n      config:\n        root: '~'\n"
    )
    assert [source.path for source in deepseek.discover_session_sources(tmp_path)] == [target]


def test_static_profile_root_and_dynamic_root_are_scanned_safely(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DSH_HOME", raising=False)
    root = tmp_path / "elsewhere"
    original = _session(tmp_path, "profile-session")
    target = root / original.parent.parent.name / original.parent.name / original.name
    target.parent.mkdir(parents=True)
    original.replace(target)
    patch = tmp_path / ".dsh" / "profiles" / "custom" / "cordis.patch.yml"
    patch.parent.mkdir(parents=True)
    patch.write_text(
        "- insert:\n"
        "    - name: '@deepseek-ai/dsh-session-persistence-jsonl'\n"
        f"      config:\n        root: {root}\n"
        "    - name: '@deepseek-ai/dsh-session-persistence-jsonl'\n"
        "      config:\n        root: !!js 'throw new Error()'\n"
    )
    assert [source.path for source in deepseek.discover_session_sources(tmp_path)] == [target]
    assert deepseek.resolve_session_source({"session_id": "profile-session"}, tmp_path).path == target


def test_literal_extra_root_is_scanned_without_evaluating_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("DSH_HOME", raising=False)
    root = tmp_path / "custom" / "sessions"
    path = _session(tmp_path, "custom")
    target = root / path.parent.parent.name / path.parent.name / path.name
    target.parent.mkdir(parents=True)
    path.replace(target)
    assert deepseek.discover_session_sources(tmp_path) == []
    assert [source.path for source in deepseek.discover_session_sources(tmp_path, roots=(root,))] == [target]
    assert deepseek.resolve_session_source({"session_id": "custom"}, tmp_path, roots=(root,)).path == target


def test_native_collector_delivers_flushed_session_and_recovers_only_old_sessions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from observal_cli.sessions import deepseek_collector

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("DSH_HOME", raising=False)
    current = _session(tmp_path, "live", records=(_line({"type": "turn/end"}),))
    stale = _session(tmp_path, "stale", records=(_line({"type": "turn/end"}),))
    os.utime(stale, (stale.stat().st_atime - 300, stale.stat().st_mtime - 300))
    delivered = []
    monkeypatch.setattr(deepseek_collector, "load_config", lambda: _config())
    monkeypatch.setattr(
        deepseek_collector,
        "drain_session_source",
        lambda source, config, **kwargs: delivered.append((source.session_id, kwargs)) or True,
    )
    assert deepseek_collector.main(["--session-id", "live", "--cwd", "/work/tree"]) == 0
    assert delivered[0] == (
        "live",
        {"hook_event": "DeepSeekSessionFlush", "final": False, "spool_only": False, "recover_from_server": False},
    )
    assert deepseek_collector.main(["--recover"]) == 0
    assert [session_id for session_id, _ in delivered] == ["live", "stale"]
    assert current.exists()
    assert deepseek_collector.main(["--session-id", "nonexistent"]) == 1


def _skill_call(name: str) -> bytes:
    return _line({"type": "tool/call", "data": {"name": "skill", "arguments": {"name": name}}})


def _lockfile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, agents: list[dict]) -> None:
    from observal_cli import lockfile as lockfile_mod

    # CONFIG_DIR is resolved at import time, so point the module at a fixture
    # lockfile instead of relying on HOME.
    lock_path = tmp_path / ".observal" / "lockfile.json"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps(
            {"lock_version": 2, "registries": {"http://server": {"harnesses": {"deepseek": {"agents": agents}}}}}
        )
    )
    monkeypatch.setattr(lockfile_mod, "LOCKFILE_PATH", lock_path)
    monkeypatch.setattr(lockfile_mod, "_LOCKFILE_LOCK", lock_path.with_suffix(".lock"))


class TestSessionAgentAttribution:
    """Sessions attribute to the pulled agent whose skill the model invoked."""

    def test_skill_call_attributes_to_lockfile_agent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("DSH_HOME", raising=False)
        records = (_line({"type": "turn/start"}), _skill_call("observal-my-agent"), _line({"type": "turn/end"}))
        path = _session(tmp_path, "attributed", records=records)
        _lockfile(tmp_path, monkeypatch, [{"name": "my-agent", "id": "uuid-1", "version": "1.2.0"}])

        assert deepseek.resolve_session_agent_identity(path, "/work/tree") == ("uuid-1", "1.2.0")

        from observal_cli.harness import ensure_loaded, get_adapter

        ensure_loaded()
        assert get_adapter("deepseek").resolve_session_agent_identity(path, "/work/tree") == ("uuid-1", "1.2.0")

    def test_string_arguments_are_parsed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("DSH_HOME", raising=False)
        call = _line({"type": "tool/call", "data": {"name": "skill", "arguments": '{"name": "observal-my-agent"}'}})
        path = _session(tmp_path, "string-args", records=(call,))
        _lockfile(tmp_path, monkeypatch, [{"name": "my-agent", "id": "uuid-1", "version": None}])

        assert deepseek.resolve_session_agent_identity(path, "/work/tree") == ("uuid-1", None)

    def test_session_without_agent_skill_defers_to_shared_resolution(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.delenv("DSH_HOME", raising=False)
        records = (_line({"type": "turn/start"}), _line({"type": "user/message", "data": {"content": []}}))
        path = _session(tmp_path, "unattributed", records=records)
        _lockfile(tmp_path, monkeypatch, [{"name": "my-agent", "id": "uuid-1", "version": "1.2.0"}])

        assert deepseek.resolve_session_agent_identity(path, "/work/tree") is None

    def test_bundled_skill_call_is_not_attribution(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("DSH_HOME", raising=False)
        path = _session(tmp_path, "bundled", records=(_skill_call("observal-ops"),))
        _lockfile(tmp_path, monkeypatch, [{"name": "my-agent", "id": "uuid-1", "version": "1.2.0"}])

        assert deepseek.resolve_session_agent_identity(path, "/work/tree") is None

    def test_unknown_agent_skill_defers_without_reruns(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("DSH_HOME", raising=False)
        path = _session(tmp_path, "unknown", records=(_skill_call("observal-other-agent"),))
        _lockfile(tmp_path, monkeypatch, [{"name": "my-agent", "id": "uuid-1", "version": "1.2.0"}])

        assert deepseek.resolve_session_agent_identity(path, "/work/tree") is None

    def test_growing_session_is_rescanned_until_the_skill_call_arrives(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.delenv("DSH_HOME", raising=False)
        path = _session(tmp_path, "growing", records=(_line({"type": "turn/start"}),))
        _lockfile(tmp_path, monkeypatch, [{"name": "my-agent", "id": "uuid-1", "version": "1.2.0"}])

        assert deepseek.resolve_session_agent_identity(path, "/work/tree") is None
        frame = _skill_call("observal-my-agent")
        if path.name.endswith(".zstd"):
            frame = zstandard.ZstdCompressor(write_checksum=True).compress(frame)
        with path.open("ab") as handle:
            handle.write(frame)
        os.utime(path, None)

        assert deepseek.resolve_session_agent_identity(path, "/work/tree") == ("uuid-1", "1.2.0")

    def test_identity_is_cached_per_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("DSH_HOME", raising=False)
        path = _session(tmp_path, "cached", records=(_skill_call("observal-my-agent"),))
        _lockfile(tmp_path, monkeypatch, [{"name": "my-agent", "id": "uuid-1", "version": "1.2.0"}])

        first = deepseek.resolve_session_agent_identity(path, "/work/tree")
        calls = []
        original = deepseek._first_agent_skill
        monkeypatch.setattr(deepseek, "_first_agent_skill", lambda p: calls.append(p) or original(p))
        assert deepseek.resolve_session_agent_identity(path, "/work/tree") == first
        assert calls == []

    def test_null_and_missing_paths_defer(self, tmp_path: Path):
        assert deepseek.resolve_session_agent_identity(None, "/work/tree") is None
        assert deepseek.resolve_session_agent_identity(tmp_path / "missing.jsonl", "/work/tree") is None
