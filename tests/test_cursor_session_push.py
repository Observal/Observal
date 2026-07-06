# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for observal_cli.hooks.cursor_session_push."""

import json
from unittest.mock import patch

from observal_cli.hooks.cursor_session_push import (
    find_cursor_jsonl,
    main,
    project_key_from_cwd,
)


class TestProjectKeyFromCwd:
    def test_unix_path(self):
        assert project_key_from_cwd("/home/user/project") == "home-user-project"

    def test_unix_path_wsl(self):
        result = project_key_from_cwd("/mnt/c/Users/alice/projects/myapp")
        assert result == "mnt-c-Users-alice-projects-myapp"

    def test_windows_path_backslashes(self):
        result = project_key_from_cwd("C:\\Users\\alice\\project")
        assert result == "c-Users-alice-project"

    def test_windows_path_forward_slashes(self):
        result = project_key_from_cwd("C:/Users/alice/project")
        assert result == "c-Users-alice-project"

    def test_lowercase_drive_letter(self):
        result = project_key_from_cwd("D:\\Code\\repo")
        assert result == "d-Code-repo"

    def test_real_observal_path(self):
        result = project_key_from_cwd("C:\\Users\\alice\\projects\\myapp")
        assert result == "c-Users-alice-projects-myapp"


class TestFindCursorJsonl:
    def test_finds_primary_path(self, tmp_path):
        project_key = "c-Users-alice-project"
        session_dir = tmp_path / ".cursor" / "projects" / project_key / "agent-transcripts" / "abc123"
        session_dir.mkdir(parents=True)
        jsonl_file = session_dir / "abc123.jsonl"
        jsonl_file.write_text('{"type":"user"}\n')

        result = find_cursor_jsonl("abc123", project_key, home=tmp_path)
        assert result == jsonl_file

    def test_returns_none_when_not_found(self, tmp_path):
        result = find_cursor_jsonl("nonexistent", "some-project", home=tmp_path)
        assert result is None

    def test_fallback_scan(self, tmp_path):
        session_dir = tmp_path / ".cursor" / "projects" / "other-project" / "agent-transcripts" / "def456"
        session_dir.mkdir(parents=True)
        jsonl_file = session_dir / "def456.jsonl"
        jsonl_file.write_text('{"type":"user"}\n')

        result = find_cursor_jsonl("def456", "wrong-project-key", home=tmp_path)
        assert result == jsonl_file

    def test_empty_session_id_returns_none(self, tmp_path):
        assert find_cursor_jsonl("", "some-project", home=tmp_path) is None


class TestMainEntrypoint:
    def test_no_crash_on_empty_stdin(self, monkeypatch):
        monkeypatch.setattr("sys.stdin", __import__("io").StringIO(""))
        main()

    def test_no_crash_on_invalid_json(self, monkeypatch):
        monkeypatch.setattr("sys.stdin", __import__("io").StringIO("not json"))
        main()

    def test_no_crash_on_missing_config(self, tmp_path, monkeypatch):
        event = json.dumps(
            {
                "event": "beforeSubmitPrompt",
                "conversationId": "test-session",
                "workspacePath": "/home/user/project",
            }
        )
        monkeypatch.setattr("sys.stdin", __import__("io").StringIO(event))
        main(home=tmp_path)

    def test_pushes_lines_via_transcript_path(self, tmp_path, monkeypatch):
        transcript_file = tmp_path / "transcript" / "sess-1.jsonl"
        transcript_file.parent.mkdir(parents=True)
        transcript_file.write_text('{"type":"human","message":{"content":"hello"}}\n')

        config_dir = tmp_path / ".observal"
        config_dir.mkdir(parents=True)
        (config_dir / "config.json").write_text(
            json.dumps(
                {
                    "server_url": "http://localhost:8000",
                    "access_token": "test-token",
                }
            )
        )

        event = json.dumps(
            {
                "event": "beforeSubmitPrompt",
                "conversationId": "sess-1",
                "transcriptPath": str(transcript_file),
                "workspacePath": "/home/user/project",
            }
        )
        monkeypatch.setattr("sys.stdin", __import__("io").StringIO(event))

        with patch("observal_cli.hooks.cursor_session_push._spawn_post") as mock_spawn:
            main(home=tmp_path)

        mock_spawn.assert_called_once()
        payload = mock_spawn.call_args[0][0]
        assert payload["harness"] == "cursor"
        assert payload["session_id"] == "sess-1"
        assert len(payload["lines"]) == 1

    def test_fallback_to_project_search(self, tmp_path, monkeypatch):
        project_key = "home-user-project"
        session_dir = tmp_path / ".cursor" / "projects" / project_key / "agent-transcripts" / "sess-2"
        session_dir.mkdir(parents=True)
        jsonl_file = session_dir / "sess-2.jsonl"
        jsonl_file.write_text('{"type":"human","message":{"content":"hi"}}\n')

        config_dir = tmp_path / ".observal"
        config_dir.mkdir(parents=True)
        (config_dir / "config.json").write_text(
            json.dumps(
                {
                    "server_url": "http://localhost:8000",
                    "access_token": "test-token",
                }
            )
        )

        event = json.dumps(
            {
                "event": "beforeSubmitPrompt",
                "conversationId": "sess-2",
                "workspacePath": "/home/user/project",
            }
        )
        monkeypatch.setattr("sys.stdin", __import__("io").StringIO(event))

        with patch("observal_cli.hooks.cursor_session_push._spawn_post") as mock_spawn:
            main(home=tmp_path)

        mock_spawn.assert_called_once()
        payload = mock_spawn.call_args[0][0]
        assert payload["harness"] == "cursor"
        assert payload["session_id"] == "sess-2"
