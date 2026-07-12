# SPDX-FileCopyrightText: 2026 kilqwe <shreyas0514@gmail.com>
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from observal_cli.sessions.agent_marker import read_agent_marker
from observal_cli.sessions.base import (
    build_payload,
    load_config,
    read_cursor,
    read_new_lines,
    write_cursor,
)
from observal_cli.sessions.claude_code import (
    find_jsonl_file,
    get_parent_session_id,
    project_key_from_cwd,
)

# project_key_from_cwd


class TestProjectKeyFromCwd:
    def test_basic_roundtrip(self):
        assert project_key_from_cwd("/home/user/code/proj") == "-home-user-code-proj"

    def test_trailing_slash_is_preserved_verbatim(self):
        # Edge case: no normalization happens -- every "/" becomes "-",
        # including a trailing one. Pinning current (unnormalized) behavior.
        assert project_key_from_cwd("/home/user/code/proj/") == "-home-user-code-proj-"


# find_jsonl_file


class TestFindJsonlFile:
    def test_primary_path_hit(self, tmp_path: Path):
        project_key = "-home-user-proj"
        session_id = "sess-primary"
        jsonl_dir = tmp_path / ".claude" / "projects" / project_key
        jsonl_dir.mkdir(parents=True)
        target = jsonl_dir / f"{session_id}.jsonl"
        target.write_text("{}\n")

        result = find_jsonl_file(session_id, project_key, home=tmp_path)
        assert result == target

    def test_fallback_glob_hit(self, tmp_path: Path):
        # File lives under a different project directory than the one implied
        # by project_key (e.g. cwd moved) -- fallback glob should still find it.
        session_id = "sess-fallback"
        other_dir = tmp_path / ".claude" / "projects" / "-some-other-project"
        other_dir.mkdir(parents=True)
        target = other_dir / f"{session_id}.jsonl"
        target.write_text("{}\n")

        result = find_jsonl_file(session_id, "-nonexistent-key", home=tmp_path)
        assert result == target

    def test_miss_returns_none(self, tmp_path: Path):
        result = find_jsonl_file("nope-session", "-some-key", home=tmp_path)
        assert result is None


# read_cursor / write_cursor


class TestCursorRoundtrip:
    def test_roundtrip(self, tmp_path: Path):
        write_cursor("sess-a", offset=123, line_count=5, home=tmp_path)
        offset, line_count = read_cursor("sess-a", home=tmp_path)
        assert offset == 123
        assert line_count == 5

    def test_missing_state_file_returns_zeros(self, tmp_path: Path):
        offset, line_count = read_cursor("never-written", home=tmp_path)
        assert offset == 0
        assert line_count == 0

    def test_finalized_flag_preserved_across_writes(self, tmp_path: Path):
        write_cursor("sess-b", offset=10, line_count=1, finalized=True, home=tmp_path)
        # A subsequent write that doesn't explicitly pass finalized=True
        # should still retain the finalized flag once set.
        write_cursor("sess-b", offset=20, line_count=2, finalized=False, home=tmp_path)

        state_file = tmp_path / ".observal" / "sync_state.json"
        data = json.loads(state_file.read_text())
        assert data["sess-b"]["finalized"] is True
        assert data["sess-b"]["offset"] == 20
        assert data["sess-b"]["line_count"] == 2

    def test_finalized_not_set_when_never_requested(self, tmp_path: Path):
        write_cursor("sess-c", offset=5, line_count=1, home=tmp_path)
        state_file = tmp_path / ".observal" / "sync_state.json"
        data = json.loads(state_file.read_text())
        assert "finalized" not in data["sess-c"]


# read_new_lines


class TestReadNewLines:
    def test_empty_file(self, tmp_path: Path):
        jsonl = tmp_path / "session.jsonl"
        jsonl.write_text("")
        lines, bytes_read = read_new_lines(jsonl, offset=0)
        assert lines == []
        assert bytes_read == 0

    def test_offset_past_eof(self, tmp_path: Path):
        jsonl = tmp_path / "session.jsonl"
        jsonl.write_text("line1\n")
        lines, bytes_read = read_new_lines(jsonl, offset=100)
        assert lines == []
        assert bytes_read == 0

    def test_multi_line_read(self, tmp_path: Path):
        jsonl = tmp_path / "session.jsonl"
        content = "line1\nline2\nline3\n"
        jsonl.write_bytes(content.encode("utf-8"))
        lines, bytes_read = read_new_lines(jsonl, offset=0)
        assert lines == ["line1", "line2", "line3"]
        assert bytes_read == len(content.encode("utf-8"))

    def test_incomplete_trailing_line_excluded(self, tmp_path: Path):
        # A write in progress -- last line has no trailing newline yet.
        jsonl = tmp_path / "session.jsonl"
        jsonl.write_bytes(b"line1\nline2\npartial-w")
        lines, bytes_read = read_new_lines(jsonl, offset=0)
        assert lines == ["line1", "line2"]
        assert bytes_read == len(b"line1\nline2\n")


# build_payload


class TestBuildPayload:
    def test_schema_shape(self):
        payload = build_payload(
            session_id="session-abc",
            lines=['{"type": "user"}'],
            start_offset=0,
            hook_event="UserPromptSubmit",
            line_count_before=0,
            new_offset=42,
            cwd="/tmp/project",
        )
        expected_keys = {
            "session_id",
            "harness",
            "agent_id",
            "agent_version",
            "layer_hash",
            "lines",
            "start_offset",
            "hook_event",
            "parent_session_id",
        }
        assert expected_keys.issubset(payload.keys())
        assert payload["session_id"] == "session-abc"
        assert payload["harness"] == "claude-code"
        assert payload["lines"] == ['{"type": "user"}']
        assert payload["hook_event"] == "UserPromptSubmit"
        assert payload["start_offset"] == 0
        assert payload["parent_session_id"] is None
        # Non-Stop events should not carry the "final" fields.
        assert "final" not in payload
        assert "total_line_count" not in payload
        assert "total_offset" not in payload

    def test_stop_event_adds_final_and_totals(self):
        payload = build_payload(
            session_id="session-stop",
            lines=["l1", "l2"],
            start_offset=10,
            hook_event="Stop",
            line_count_before=10,
            new_offset=999,
            cwd="/tmp/project",
        )
        assert payload["final"] is True
        assert payload["total_line_count"] == 12  # line_count_before + len(lines)
        assert payload["total_offset"] == 999

    def test_parent_session_id_passed_through(self):
        payload = build_payload(
            session_id="child-session",
            lines=["l1"],
            start_offset=0,
            hook_event="UserPromptSubmit",
            line_count_before=0,
            cwd="/tmp/project",
            parent_session_id="parent-session",
        )
        assert payload["parent_session_id"] == "parent-session"


# get_parent_session_id


class TestGetParentSessionId:
    def test_subagent_path_returns_parent(self, tmp_path: Path):
        path = tmp_path / ".claude" / "projects" / "-proj" / "parent-123" / "subagents" / "child-456.jsonl"
        assert get_parent_session_id(path) == "parent-123"

    def test_top_level_path_returns_none(self, tmp_path: Path):
        path = tmp_path / ".claude" / "projects" / "-proj" / "session-789.jsonl"
        assert get_parent_session_id(path) is None


# load_config


class TestLoadConfig:
    def test_missing_file_returns_none(self, tmp_path: Path):
        assert load_config(home=tmp_path) is None

    def test_malformed_file_returns_none(self, tmp_path: Path):
        cfg_dir = tmp_path / ".observal"
        cfg_dir.mkdir()
        (cfg_dir / "config.json").write_text("{not valid json")
        assert load_config(home=tmp_path) is None

    def test_api_key_takes_priority_over_access_token(self, tmp_path: Path):
        cfg_dir = tmp_path / ".observal"
        cfg_dir.mkdir()
        cfg_data = {
            "server_url": "https://api.observal.dev",
            "api_key": "api-key-30day",
            "access_token": "access-token-1hr",
        }
        (cfg_dir / "config.json").write_text(json.dumps(cfg_data))

        config = load_config(home=tmp_path)
        assert config is not None
        assert config["access_token"] == "api-key-30day"
        assert config["server_url"] == "https://api.observal.dev"

    def test_missing_required_fields_returns_none(self, tmp_path: Path):
        cfg_dir = tmp_path / ".observal"
        cfg_dir.mkdir()
        # server_url present but no api_key/access_token at all.
        (cfg_dir / "config.json").write_text(json.dumps({"server_url": "https://api.observal.dev"}))
        assert load_config(home=tmp_path) is None


# read_agent_marker


class TestReadAgentMarker:
    def test_no_marker_file_returns_none_none(self, tmp_path: Path):
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        agent_id, agent_version = read_agent_marker(str(project_dir))
        assert agent_id is None
        assert agent_version is None

    def test_pulled_at_guard_blocks_first_push(self, tmp_path: Path, monkeypatch):
        # read_agent_marker reads ~/.observal/sync_state.json directly via
        # Path.home(), independent of any home= parameter -- patch it here.
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

        project_dir = tmp_path / "project"
        marker_dir = project_dir / ".observal"
        marker_dir.mkdir(parents=True)

        pulled_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        marker_data = {
            "agent_id": "new-agent",
            "agent_version": "2.0",
            "pulled_at": pulled_at,
        }
        (marker_dir / "agent").write_text(json.dumps(marker_data))

        session_jsonl = tmp_path / "session.jsonl"
        session_jsonl.write_text("{}\n")

        # No sync_state.json exists -> offset defaults to 0 -> this is
        # treated as a brand-new session, and the pulled_at guard applies:
        # the session was created before the pull, so it must NOT be
        # attributed to the freshly-pulled agent.
        agent_id, agent_version = read_agent_marker(str(project_dir), session_jsonl=session_jsonl)
        assert agent_id is None
        assert agent_version is None

    def test_pulled_at_guard_ignored_on_resumed_session(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

        project_dir = tmp_path / "project"
        marker_dir = project_dir / ".observal"
        marker_dir.mkdir(parents=True)

        pulled_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        marker_data = {
            "agent_id": "resumed-agent",
            "agent_version": "3.1",
            "pulled_at": pulled_at,
        }
        (marker_dir / "agent").write_text(json.dumps(marker_data))

        session_jsonl = tmp_path / "session.jsonl"
        session_jsonl.write_text("{}\n")

        # sync_state.json shows this session already has a nonzero offset,
        # i.e. it's a resumed session, not brand new -- the pulled_at guard
        # should be skipped entirely, even though pulled_at is in the future.
        sync_dir = tmp_path / ".observal"
        sync_dir.mkdir(parents=True, exist_ok=True)
        state = {session_jsonl.stem: {"offset": 500, "line_count": 10}}
        (sync_dir / "sync_state.json").write_text(json.dumps(state))

        agent_id, agent_version = read_agent_marker(str(project_dir), session_jsonl=session_jsonl)
        assert agent_id == "resumed-agent"
        assert agent_version == "3.1"

    def test_malformed_marker_file_returns_none_none(self, tmp_path: Path):
        project_dir = tmp_path / "project"
        marker_dir = project_dir / ".observal"
        marker_dir.mkdir(parents=True)
        (marker_dir / "agent").write_text("{not valid json")

        agent_id, agent_version = read_agent_marker(str(project_dir))
        assert agent_id is None
        assert agent_version is None
