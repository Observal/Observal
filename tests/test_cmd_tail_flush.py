# SPDX-FileCopyrightText: 2026 Piyush <pranyasharma55555@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for cmd_tail_flush.tail_flush — delayed tail-flush after Stop hook."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from observal_cli.cmd_tail_flush import _MAX_RETRIES, main, tail_flush

SESSION_ID = "sandbox-123"

_SESSIONS = "observal_cli.sessions.base"
_CMD_RECONCILE = "observal_cli.cmd_reconcile"
_SESSION_SUBAGENT = "observal_cli.sessions.claude_code"


@pytest.fixture
def home():
    return Path("/path/to/test")


@pytest.fixture
def payload():
    return {"server_url": "https://api.observal.dev", "access_token": "secret-token"}


@pytest.fixture
def file_path():
    return Path("/path/to/file.jsonl")


@pytest.fixture
def changes():
    return ["lines that have been added to the file"]


@pytest.fixture
def read_cursor_values():
    return 1024, 42


def test_tail_flush_returns_when_config_missing(home):
    """load_config returns None → early return, no sleep."""
    with patch(f"{_SESSIONS}.load_config") as mock_config:
        mock_config.return_value = None
        result = tail_flush(SESSION_ID, home=home)
    assert result is None
    mock_config.assert_called_once_with(home=home)


def test_tail_flush_returns_when_session_file_missing(home, payload):
    """_find_session_file returns None → early return after flush delay."""
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


def test_tail_flush_finalizes_when_no_new_lines(home, payload, file_path, read_cursor_values):
    """read_new_lines returns empty → cursor finalized, no POST."""
    offset, line_count = read_cursor_values
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
        mock_read.return_value = read_cursor_values
        mock_read_new_lines.return_value = ([], 0)
        result = tail_flush(SESSION_ID, home=home)
    assert result is None
    mock_sleep.assert_called_once()
    mock_config.assert_called_once_with(home=home)
    mock_session_file.assert_called_once_with(SESSION_ID, home=home)
    mock_write_cursor.assert_called_once_with(SESSION_ID, offset, line_count, finalized=True, home=home)


def test_tail_flush_pushes_new_lines_successfully(home, payload, file_path, changes, read_cursor_values):
    """POST succeeds, has parent → write cursor, skip subagent push."""
    offset, line_count = read_cursor_values
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
        mock_read.return_value = read_cursor_values
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
        SESSION_ID, new_offset, line_count + len(changes), finalized=True, home=home
    )


def test_tail_flush_parent_id_missing(home, payload, file_path, changes, read_cursor_values):
    """POST succeeds, *is* parent (no parent ID) → write cursor + subagent push."""
    offset, line_count = read_cursor_values
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
        mock_read.return_value = read_cursor_values
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
        SESSION_ID, new_offset, line_count + len(changes), finalized=True, home=home
    )
    mock_subagent_session.assert_called_once_with(SESSION_ID, file_path, payload, home=home)


def test_tail_flush_retries_and_logs_failure(home, payload, file_path, changes, read_cursor_values):
    """POST fails on all retries → cursor left un-finalized, error logged."""
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
        mock_read.return_value = read_cursor_values
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


def test_tail_flush_retries_success(home, payload, file_path, changes, read_cursor_values):
    """POST fails on first attempt, succeeds on retry → cursor finalized."""
    offset, line_count = read_cursor_values
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
        mock_read.return_value = read_cursor_values
        mock_read_new_lines.return_value = (changes, 38)
        mock_build_payload.return_value = {"session_id": SESSION_ID}
        mock_post.side_effect = [False, True]
        result = tail_flush(SESSION_ID, home=home)
    assert result is None
    assert mock_sleep.call_count == 2
    assert mock_post.call_count == 2
    mock_config.assert_called_once_with(home=home)
    mock_session_file.assert_called_once_with(SESSION_ID, home=home)
    mock_write_cursor.assert_called_once_with(
        SESSION_ID, new_offset, line_count + len(changes), finalized=True, home=home
    )


def test_main_returns_when_no_args():
    """len(sys.argv) < 2 → early return, tail_flush not called."""
    with (
        patch("sys.argv", ["observal_cli"]),
        patch("observal_cli.cmd_tail_flush.tail_flush") as mock_tail,
    ):
        main()
    mock_tail.assert_not_called()


def test_main_returns_when_session_id_empty():
    """sys.argv[1] is empty string → early return, tail_flush not called."""
    with (
        patch("sys.argv", ["observal_cli", ""]),
        patch("observal_cli.cmd_tail_flush.tail_flush") as mock_tail,
    ):
        main()
    mock_tail.assert_not_called()


def test_main_calls_tail_flush_with_session_id():
    """Valid session_id → delegates to tail_flush with correct arg."""
    with (
        patch("sys.argv", ["observal_cli", "sandbox-123"]),
        patch("observal_cli.cmd_tail_flush.tail_flush") as mock_tail,
    ):
        main()
    mock_tail.assert_called_once_with("sandbox-123")


def test_main_swallows_exceptions():
    """tail_flush raises → main() catches and silently returns (no zombie)."""
    with (
        patch("sys.argv", ["observal_cli", "sandbox-123"]),
        patch("observal_cli.cmd_tail_flush.tail_flush", side_effect=RuntimeError("boom")),
    ):
        main()
