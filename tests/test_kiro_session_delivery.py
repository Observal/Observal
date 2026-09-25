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


# ── Kiro IDE transcript layout ────────────────────────────────────
#
# The IDE stores sessions as
# ``~/.kiro/sessions/<workspaceHash>/<session_id>/messages.jsonl`` with a
# sibling ``session.json``, enveloping each record as ``{id, timestamp,
# payload}``. Nothing about that matches the CLI layout, so these pin the
# discovery and metadata paths that make IDE sessions deliverable at all.


def make_ide_session(
    home: Path,
    session_id: str = "sess_ide-1",
    workspace: str = "/work/project",
    bucket: str = "a1b2c3d4",
    credits: tuple[float, ...] = (0.25, 0.75),
    sub_agents: tuple[str, ...] = (),
) -> Path:
    session_dir = home / ".kiro" / "sessions" / bucket / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    records = [
        {"id": "r1", "payload": {"type": "session_start", "agentType": "vibe"}},
        {"id": "r2", "payload": {"type": "user", "content": "hello"}},
        {"id": "r3", "payload": {"type": "assistant", "content": "hi", "operationType": "Say"}},
    ]
    for index, name in enumerate(sub_agents):
        records.append(
            {
                "id": f"sub{index}",
                "payload": {"type": "sub_agent_start", "subAgentName": name, "prompt": "go"},
            }
        )
    for value in credits:
        records.append(
            {
                "id": f"u{value}",
                "payload": {
                    "type": "usage_summary",
                    "promptTurnSummaries": [{"unit": "credit", "usage": value}],
                },
            }
        )
    transcript = session_dir / "messages.jsonl"
    transcript.write_text("".join(json.dumps(r) + "\n" for r in records))
    (session_dir / "session.json").write_text(json.dumps({"id": session_id, "workspacePaths": [workspace]}))
    return transcript


def test_kiro_finds_ide_transcript_across_workspace_buckets(tmp_path: Path):
    """The workspace hash is not derivable from the session id, so buckets are scanned."""
    from observal_cli.sessions.kiro import find_kiro_jsonl

    make_ide_session(tmp_path, session_id="sess_a", bucket="bucket-one")
    expected = make_ide_session(tmp_path, session_id="sess_b", bucket="bucket-two")

    assert find_kiro_jsonl("sess_b", home=tmp_path) == expected
    assert find_kiro_jsonl("sess_missing", home=tmp_path) is None


def test_kiro_prefers_cli_layout_when_both_exist(tmp_path: Path):
    cli = make_session(tmp_path, session_id="dup")
    make_ide_session(tmp_path, session_id="dup")

    from observal_cli.sessions.kiro import find_kiro_jsonl

    assert find_kiro_jsonl("dup", home=tmp_path) == cli


def test_kiro_ide_cwd_comes_from_workspace_paths(tmp_path: Path):
    """The IDE records ``workspacePaths``; there is no ``cwd`` key to read."""
    from observal_cli.sessions.kiro import read_kiro_session_cwd

    transcript = make_ide_session(tmp_path, workspace="/work/project")

    assert read_kiro_session_cwd(transcript) == "/work/project"


def test_kiro_ide_credits_sum_usage_summaries(tmp_path: Path):
    """IDE credits live on per-turn ``usage_summary`` payloads, not the companion file."""
    from observal_cli.sessions.kiro import read_kiro_credits

    make_ide_session(tmp_path, session_id="sess_credits", credits=(0.25, 0.75))

    assert read_kiro_credits("sess_credits", home=tmp_path) == 1.0


def test_kiro_ide_credits_absent_before_first_turn_completes(tmp_path: Path):
    from observal_cli.sessions.kiro import read_kiro_credits

    make_ide_session(tmp_path, session_id="sess_new", credits=())

    assert read_kiro_credits("sess_new", home=tmp_path) is None


def test_kiro_resolves_ide_session_source_from_hook_event(tmp_path: Path):
    """End of the chain: a hook event for an IDE session must yield a source."""
    make_ide_session(tmp_path, session_id="sess_hooked", workspace="/work/ide")

    ensure_loaded()
    source = get_adapter("kiro").resolve_session_source({"session_id": "sess_hooked"}, home=tmp_path)

    assert source is not None
    assert source.session_id == "sess_hooked"
    assert source.path.name == "messages.jsonl"
    assert source.cwd == "/work/ide"


def test_kiro_discovers_both_layouts_for_reconcile(tmp_path: Path):
    make_session(tmp_path, session_id="cli-one")
    make_ide_session(tmp_path, session_id="sess_ide-one")

    ensure_loaded()
    found = {s.session_id for s in get_adapter("kiro").discover_session_sources(home=tmp_path)}

    assert found == {"cli-one", "sess_ide-one"}


def test_kiro_ide_partial_line_does_not_break_credit_read(tmp_path: Path):
    """A transcript being appended to can end mid-line; that must not raise."""
    from observal_cli.sessions.kiro import read_kiro_credits

    transcript = make_ide_session(tmp_path, session_id="sess_partial", credits=(0.5,))
    with transcript.open("a") as handle:
        handle.write('{"id":"trunc","payl')

    assert read_kiro_credits("sess_partial", home=tmp_path) == 0.5


# ── Kiro IDE agent attribution ────────────────────────────────────
#
# An IDE session always runs as Kiro itself. A registry agent only participates
# when Kiro delegates a turn to it, recorded as a ``sub_agent_start`` payload;
# nothing else on disk names an agent.


def test_kiro_ide_attributes_session_to_delegated_agent(tmp_path: Path):
    from observal_cli.sessions.kiro import read_kiro_agent_name

    transcript = make_ide_session(tmp_path, sub_agents=("pikachu-dude-agent",))

    assert read_kiro_agent_name(transcript) == "pikachu-dude-agent"


def test_kiro_ide_uses_most_recent_delegation(tmp_path: Path):
    """Attribution is session-level, so the latest delegation wins."""
    from observal_cli.sessions.kiro import read_kiro_agent_name

    transcript = make_ide_session(tmp_path, sub_agents=("first-agent", "second-agent", "third-agent"))

    assert read_kiro_agent_name(transcript) == "third-agent"


def test_kiro_ide_without_delegation_stays_unattributed(tmp_path: Path):
    """A bare Kiro conversation belongs to no registry agent."""
    from observal_cli.sessions.kiro import read_kiro_agent_name

    transcript = make_ide_session(tmp_path, sub_agents=())

    assert read_kiro_agent_name(transcript) is None


def test_kiro_ide_identity_resolves_through_lockfile(tmp_path: Path, monkeypatch):
    """The delegated name must resolve to a registry id, like the CLI path does."""
    import observal_cli.lockfile as lockfile

    monkeypatch.setattr(
        lockfile,
        "get_agent_by_name",
        lambda name, harness, directory=None: (
            {"id": "agent-uuid", "version": "2.0.0"} if name == "pikachu-dude-agent" else None
        ),
    )
    transcript = make_ide_session(tmp_path, sub_agents=("pikachu-dude-agent",), workspace="/work/ide")
    ensure_loaded()

    assert get_adapter("kiro").resolve_session_agent_identity(transcript, "/work/ide") == (
        "agent-uuid",
        "2.0.0",
    )


def test_kiro_ide_unknown_agent_is_left_unattributed(tmp_path: Path, monkeypatch):
    """An agent that was never pulled has no local id; do not invent one."""
    import observal_cli.lockfile as lockfile

    monkeypatch.setattr(lockfile, "get_agent_by_name", lambda name, harness, directory=None: None)
    transcript = make_ide_session(tmp_path, sub_agents=("never-pulled-agent",))
    ensure_loaded()

    assert get_adapter("kiro").resolve_session_agent_identity(transcript, "/work") == (None, None)


# ── Attribution must not outlive the registry entry ───────────────
#
# The lockfile is local and can carry agents the current registry no longer
# has. Attributing to one produces a session tagged with an id nothing can
# resolve, which surfaces as an agent id with a blank name.


def test_kiro_skips_attribution_for_an_agent_the_registry_lost(tmp_path: Path, monkeypatch):
    """Reconciliation marked it "unavailable": the server reported it not found."""
    import observal_cli.lockfile as lockfile

    monkeypatch.setattr(
        lockfile,
        "get_agent_by_name",
        lambda name, harness, directory=None: {
            "id": "stale-uuid",
            "version": "1.0.0",
            "registry_status": "unavailable",
        },
    )
    transcript = make_ide_session(tmp_path, sub_agents=("deleted-agent",))
    ensure_loaded()

    assert get_adapter("kiro").resolve_session_agent_identity(transcript, "/work") == (None, None)


def test_kiro_attributes_when_reconciliation_has_not_run(tmp_path: Path, monkeypatch):
    """No status means unknown, not disqualified - it must still attribute."""
    import observal_cli.lockfile as lockfile

    monkeypatch.setattr(
        lockfile,
        "get_agent_by_name",
        lambda name, harness, directory=None: {"id": "agent-uuid", "version": "1.0.0"},
    )
    transcript = make_ide_session(tmp_path, sub_agents=("some-agent",))
    ensure_loaded()

    assert get_adapter("kiro").resolve_session_agent_identity(transcript, "/work") == (
        "agent-uuid",
        "1.0.0",
    )


def test_registry_backed_guard_covers_every_harness(monkeypatch):
    """The same guard protects the shared OBSERVAL_AGENT_ID path, not just Kiro.

    Every other harness bakes an agent id into its hook command at pull time and
    trusts the lockfile entry it resolves to, so it is exposed to exactly the
    same staleness.
    """
    import observal_cli.sessions.base as base

    monkeypatch.setenv("OBSERVAL_AGENT_ID", "stale-uuid")
    monkeypatch.setattr(
        base,
        "_lookup_lockfile_agent_by_id",
        lambda agent_id, harness=None: {
            "id": "stale-uuid",
            "version": "1.0.0",
            "registry_status": "unavailable",
        },
    )

    assert base._resolve_agent("/work", [], None, harness="claude-code") == (None, None)
