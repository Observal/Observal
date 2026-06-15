# SPDX-FileCopyrightText: 2026 Piyush <pranyasharma55555@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for `cmd_tail_flush`."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from observal_cli.cmd_tail_flush import _MAX_RETRIES, main, tail_flush

SESSION_ID = "sandbox-123"
_SESSIONS = "observal_cli.sessions.base"
_CMD_RECONCILE = "observal_cli.cmd_reconcile"
_SESSION_SUBAGENT = "observal_cli.sessions.claude_code"


def _home() -> Path:
    return Path("/path/to/test")


def _payload() -> dict[str, str]:
    return {"server_url": "https://api.observal.dev", "access_token": "secret-token"}


def _file_path() -> Path:
    return Path("/path/to/file.jsonl")


def _changes() -> list[str]:
    return ["lines that have been added to the file"]


def _cursor_values() -> tuple[int, int]:
    return 1024, 42


class TestTailFlush:
    """Tests for delayed session tail flushing."""

    def test_returns_when_config_missing(self) -> None:
        home = _home()

        with patch(f"{_SESSIONS}.load_config") as mock_config:
            mock_config.return_value = None

            result = tail_flush(SESSION_ID, home=home)

        assert result is None
        mock_config.assert_called_once_with(home=home)

    def test_returns_when_session_file_missing(self) -> None:
        home = _home()
        payload = _payload()

        with (
            patch(f"{_SESSIONS}.load_config") as mock_config,
            patch(f"{_CMD_RECONCILE}._find_session_file") as mock_session_file,
            patch("time.sleep") as mock_sleep,
        ):
            mock_config.return_value = payload
            mock_session_file.return_value = None

            result = tail_flush(SESSION_ID, home=home)

        assert result is None
        mock_sleep.assert_called_once()
        mock_config.assert_called_once_with(home=home)
        mock_session_file.assert_called_once_with(SESSION_ID, home=home)

    def test_finalizes_when_no_new_lines(self) -> None:
        home = _home()
        payload = _payload()
        file_path = _file_path()
        offset, line_count = _cursor_values()

        with (
            patch(f"{_SESSIONS}.load_config") as mock_config,
            patch(f"{_CMD_RECONCILE}._find_session_file") as mock_session_file,
            patch(f"{_SESSIONS}.read_cursor") as mock_read,
            patch(f"{_SESSIONS}.read_new_lines") as mock_read_new_lines,
            patch(f"{_SESSIONS}.write_cursor") as mock_write_cursor,
            patch("time.sleep") as mock_sleep,
        ):
            mock_config.return_value = payload
            mock_session_file.return_value = file_path
            mock_read.return_value = (offset, line_count)
            mock_read_new_lines.return_value = ([], 0)

            result = tail_flush(SESSION_ID, home=home)

        assert result is None
        mock_sleep.assert_called_once()
        mock_config.assert_called_once_with(home=home)
        mock_session_file.assert_called_once_with(SESSION_ID, home=home)
        mock_write_cursor.assert_called_once_with(
            SESSION_ID,
            offset,
            line_count,
            finalized=True,
            home=home,
        )

    def test_pushes_new_lines_successfully(self) -> None:
        home = _home()
        payload = _payload()
        file_path = _file_path()
        changes = _changes()
        offset, line_count = _cursor_values()
        bytes_read = 38
        new_offset = offset + bytes_read

        with (
            patch(f"{_SESSIONS}.load_config") as mock_config,
            patch(f"{_CMD_RECONCILE}._find_session_file") as mock_session_file,
            patch(f"{_SESSIONS}.read_cursor") as mock_read,
            patch(f"{_SESSIONS}.read_new_lines") as mock_read_new_lines,
            patch(f"{_SESSIONS}.write_cursor") as mock_write_cursor,
            patch(f"{_SESSIONS}.build_payload") as mock_build_payload,
            patch(f"{_SESSIONS}.post_to_server") as mock_post,
            patch(f"{_SESSION_SUBAGENT}.get_parent_session_id") as mock_parent_session_id,
            patch("time.sleep") as mock_sleep,
        ):
            mock_config.return_value = payload
            mock_session_file.return_value = file_path
            mock_read.return_value = (offset, line_count)
            mock_read_new_lines.return_value = (changes, bytes_read)
            mock_build_payload.return_value = {"session_id": SESSION_ID}
            mock_post.return_value = True
            mock_parent_session_id.return_value = "sandbox-parent-id"

            result = tail_flush(SESSION_ID, home=home)

        assert result is None
        mock_sleep.assert_called_once()
        mock_config.assert_called_once_with(home=home)
        mock_session_file.assert_called_once_with(SESSION_ID, home=home)
        mock_write_cursor.assert_called_once_with(
            SESSION_ID,
            new_offset,
            line_count + len(changes),
            finalized=True,
            home=home,
        )

    def test_pushes_subagent_sessions_for_parent(self) -> None:
        home = _home()
        payload = _payload()
        file_path = _file_path()
        changes = _changes()
        offset, line_count = _cursor_values()
        bytes_read = 38
        new_offset = offset + bytes_read

        with (
            patch(f"{_SESSIONS}.load_config") as mock_config,
            patch(f"{_CMD_RECONCILE}._find_session_file") as mock_session_file,
            patch(f"{_SESSIONS}.read_cursor") as mock_read,
            patch(f"{_SESSIONS}.read_new_lines") as mock_read_new_lines,
            patch(f"{_SESSIONS}.write_cursor") as mock_write_cursor,
            patch(f"{_SESSIONS}.build_payload") as mock_build_payload,
            patch(f"{_SESSIONS}.post_to_server") as mock_post,
            patch(f"{_SESSION_SUBAGENT}.get_parent_session_id") as mock_parent_session_id,
            patch(f"{_SESSION_SUBAGENT}.push_subagent_sessions") as mock_subagent_session,
            patch("time.sleep") as mock_sleep,
        ):
            mock_config.return_value = payload
            mock_session_file.return_value = file_path
            mock_read.return_value = (offset, line_count)
            mock_read_new_lines.return_value = (changes, bytes_read)
            mock_build_payload.return_value = {"session_id": SESSION_ID}
            mock_post.return_value = True
            mock_parent_session_id.return_value = None

            result = tail_flush(SESSION_ID, home=home)

        assert result is None
        mock_sleep.assert_called_once()
        mock_config.assert_called_once_with(home=home)
        mock_session_file.assert_called_once_with(SESSION_ID, home=home)
        mock_write_cursor.assert_called_once_with(
            SESSION_ID,
            new_offset,
            line_count + len(changes),
            finalized=True,
            home=home,
        )
        mock_subagent_session.assert_called_once_with(SESSION_ID, file_path, payload, home=home)

    def test_retries_and_logs_failure(self) -> None:
        home = _home()
        payload = _payload()
        file_path = _file_path()
        changes = _changes()
        offset, line_count = _cursor_values()

        with (
            patch(f"{_SESSIONS}.load_config") as mock_config,
            patch(f"{_CMD_RECONCILE}._find_session_file") as mock_session_file,
            patch(f"{_SESSIONS}.read_cursor") as mock_read,
            patch(f"{_SESSIONS}.read_new_lines") as mock_read_new_lines,
            patch(f"{_SESSIONS}.write_cursor") as mock_write_cursor,
            patch(f"{_SESSIONS}.build_payload") as mock_build_payload,
            patch(f"{_SESSIONS}.post_to_server") as mock_post,
            patch(f"{_SESSIONS}.log_error") as mock_log_error,
            patch("time.sleep") as mock_sleep,
        ):
            mock_config.return_value = payload
            mock_session_file.return_value = file_path
            mock_read.return_value = (offset, line_count)
            mock_read_new_lines.return_value = (changes, 38)
            mock_build_payload.return_value = {"session_id": SESSION_ID}
            mock_post.return_value = False

            result = tail_flush(SESSION_ID, home=home)

        assert result is None
        assert mock_sleep.call_count == 1 + _MAX_RETRIES
        assert mock_post.call_count == _MAX_RETRIES + 1
        mock_config.assert_called_once_with(home=home)
        mock_session_file.assert_called_once_with(SESSION_ID, home=home)
        mock_write_cursor.assert_not_called()
        mock_log_error.assert_called_once_with(
            f"tail_flush: POST failed for session {SESSION_ID} after {_MAX_RETRIES + 1} attempts",
            home=home,
        )

    def test_retries_then_succeeds(self) -> None:
        home = _home()
        payload = _payload()
        file_path = _file_path()
        changes = _changes()
        offset, line_count = _cursor_values()
        bytes_read = 38
        new_offset = offset + bytes_read

        with (
            patch(f"{_SESSIONS}.load_config") as mock_config,
            patch(f"{_CMD_RECONCILE}._find_session_file") as mock_session_file,
            patch(f"{_SESSIONS}.read_cursor") as mock_read,
            patch(f"{_SESSIONS}.read_new_lines") as mock_read_new_lines,
            patch(f"{_SESSIONS}.write_cursor") as mock_write_cursor,
            patch(f"{_SESSIONS}.build_payload") as mock_build_payload,
            patch(f"{_SESSIONS}.post_to_server") as mock_post,
            patch("time.sleep") as mock_sleep,
        ):
            mock_config.return_value = payload
            mock_session_file.return_value = file_path
            mock_read.return_value = (offset, line_count)
            mock_read_new_lines.return_value = (changes, bytes_read)
            mock_build_payload.return_value = {"session_id": SESSION_ID}
            mock_post.side_effect = [False, True]

            result = tail_flush(SESSION_ID, home=home)

        assert result is None
        assert mock_sleep.call_count == 2
        assert mock_post.call_count == 2
        mock_config.assert_called_once_with(home=home)
        mock_session_file.assert_called_once_with(SESSION_ID, home=home)
        mock_write_cursor.assert_called_once_with(
            SESSION_ID,
            new_offset,
            line_count + len(changes),
            finalized=True,
            home=home,
        )


class TestMain:
    """Tests for the subprocess entry point."""

    def test_returns_when_no_args(self) -> None:
        with (
            patch("sys.argv", ["observal_cli"]),
            patch("observal_cli.cmd_tail_flush.tail_flush") as mock_tail,
        ):
            main()

        mock_tail.assert_not_called()

    def test_returns_when_session_id_empty(self) -> None:
        with (
            patch("sys.argv", ["observal_cli", ""]),
            patch("observal_cli.cmd_tail_flush.tail_flush") as mock_tail,
        ):
            main()

        mock_tail.assert_not_called()

    def test_calls_tail_flush_with_session_id(self) -> None:
        with (
            patch("sys.argv", ["observal_cli", SESSION_ID]),
            patch("observal_cli.cmd_tail_flush.tail_flush") as mock_tail,
        ):
            main()

        mock_tail.assert_called_once_with(SESSION_ID)

    def test_swallows_exceptions(self) -> None:
        with (
            patch("sys.argv", ["observal_cli", SESSION_ID]),
            patch("observal_cli.cmd_tail_flush.tail_flush", side_effect=RuntimeError("boom")),
        ):
            main()
