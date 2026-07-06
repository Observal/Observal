# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Tests for shim error handling: startup failures and crash reporting."""

import json
from io import BytesIO, StringIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from observal_cli.shim import run_shim


def _make_stdio_mocks():
    """Create stdout (buffer=BytesIO) and stderr (StringIO) mocks."""
    stdout_buf = BytesIO()
    mock_stdout = MagicMock()
    mock_stdout.buffer = stdout_buf

    stderr_io = StringIO()
    mock_stderr = MagicMock()
    mock_stderr.write = stderr_io.write
    mock_stderr.flush = stderr_io.flush
    mock_stderr.buffer = MagicMock()

    return mock_stdout, stdout_buf, mock_stderr, stderr_io


class TestRunShimStartupErrors:
    """Tests for MCP process spawn failures in run_shim."""

    @pytest.mark.asyncio
    async def test_file_not_found_returns_1(self):
        """FileNotFoundError when spawning MCP returns exit code 1."""
        mock_stdout, stdout_buf, mock_stderr, stderr_io = _make_stdio_mocks()

        with (
            patch.dict("os.environ", {"OBSERVAL_KEY": "test", "OBSERVAL_SERVER": "http://localhost"}),
            patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError("No such file: nonexistent")),
            patch("sys.stdout", mock_stdout),
            patch("sys.stderr", mock_stderr),
        ):
            rc = await run_shim("test-mcp", ["nonexistent", "--stdio"])

        assert rc == 1
        output = stdout_buf.getvalue().decode()
        assert "notifications/message" in output
        assert "MCP server failed to start" in output
        assert "FileNotFoundError" in output

    @pytest.mark.asyncio
    async def test_permission_error_returns_1(self):
        """PermissionError when spawning MCP returns exit code 1."""
        mock_stdout, stdout_buf, mock_stderr, stderr_io = _make_stdio_mocks()

        with (
            patch.dict("os.environ", {"OBSERVAL_KEY": "test", "OBSERVAL_SERVER": "http://localhost"}),
            patch("asyncio.create_subprocess_exec", side_effect=PermissionError("Permission denied")),
            patch("sys.stdout", mock_stdout),
            patch("sys.stderr", mock_stderr),
        ):
            rc = await run_shim("test-mcp", ["./restricted-binary"])

        assert rc == 1
        output = stdout_buf.getvalue().decode()
        assert "PermissionError" in output

    @pytest.mark.asyncio
    async def test_os_error_returns_1(self):
        """OSError when spawning MCP returns exit code 1."""
        mock_stdout, stdout_buf, mock_stderr, stderr_io = _make_stdio_mocks()

        with (
            patch.dict("os.environ", {"OBSERVAL_KEY": "test", "OBSERVAL_SERVER": "http://localhost"}),
            patch("asyncio.create_subprocess_exec", side_effect=OSError("exec format error")),
            patch("sys.stdout", mock_stdout),
            patch("sys.stderr", mock_stderr),
        ):
            rc = await run_shim("test-mcp", ["bad-binary"])

        assert rc == 1
        output = stdout_buf.getvalue().decode()
        assert "OSError" in output

    @pytest.mark.asyncio
    async def test_immediate_crash_detected(self):
        """Process that exits immediately (returncode set after sleep) is caught."""
        mock_stdout, stdout_buf, mock_stderr, stderr_io = _make_stdio_mocks()

        mock_proc = AsyncMock()
        mock_proc.returncode = 1  # Already exited
        mock_proc.stderr = AsyncMock()
        mock_proc.stderr.read = AsyncMock(return_value=b"ModuleNotFoundError: No module named 'foo'\n")

        with (
            patch.dict("os.environ", {"OBSERVAL_KEY": "test", "OBSERVAL_SERVER": "http://localhost"}),
            patch("asyncio.create_subprocess_exec", return_value=mock_proc),
            patch("asyncio.sleep", new_callable=AsyncMock),  # Skip the 0.3s wait
            patch("sys.stdout", mock_stdout),
            patch("sys.stderr", mock_stderr),
        ):
            rc = await run_shim("test-mcp", ["python3", "-m", "broken_server"])

        assert rc == 1
        output = stdout_buf.getvalue().decode()
        assert "MCP server failed to start" in output
        assert "ModuleNotFoundError" in output

    @pytest.mark.asyncio
    async def test_immediate_crash_empty_stderr(self):
        """Process that exits immediately with no stderr gets a generic message."""
        mock_stdout, stdout_buf, mock_stderr, stderr_io = _make_stdio_mocks()

        mock_proc = AsyncMock()
        mock_proc.returncode = 127
        mock_proc.stderr = AsyncMock()
        mock_proc.stderr.read = AsyncMock(return_value=b"")

        with (
            patch.dict("os.environ", {"OBSERVAL_KEY": "test", "OBSERVAL_SERVER": "http://localhost"}),
            patch("asyncio.create_subprocess_exec", return_value=mock_proc),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch("sys.stdout", mock_stdout),
            patch("sys.stderr", mock_stderr),
        ):
            rc = await run_shim("test-mcp", ["missing-cmd"])

        assert rc == 127
        output = stdout_buf.getvalue().decode()
        assert "exited immediately with code 127" in output

    @pytest.mark.asyncio
    async def test_no_config_passthrough(self):
        """Without OBSERVAL_KEY/SERVER and no config file, falls through to passthrough."""
        mock_proc = AsyncMock()
        mock_proc.wait = AsyncMock(return_value=0)

        with (
            patch.dict("os.environ", {"OBSERVAL_KEY": "", "OBSERVAL_SERVER": ""}, clear=False),
            patch("observal_cli.shim.load_config", return_value={}),
            patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        ):
            with pytest.raises(SystemExit) as exc_info:
                await run_shim("test-mcp", ["echo", "hi"])
            assert exc_info.value.code == 0

    @pytest.mark.asyncio
    async def test_error_notification_is_valid_jsonrpc(self):
        """The error notification written to stdout is valid JSON-RPC."""
        mock_stdout, stdout_buf, mock_stderr, stderr_io = _make_stdio_mocks()

        with (
            patch.dict("os.environ", {"OBSERVAL_KEY": "test", "OBSERVAL_SERVER": "http://localhost"}),
            patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError("not found")),
            patch("sys.stdout", mock_stdout),
            patch("sys.stderr", mock_stderr),
        ):
            await run_shim("test-mcp", ["nonexistent"])

        output = stdout_buf.getvalue().decode().strip()
        msg = json.loads(output)
        assert msg["jsonrpc"] == "2.0"
        assert msg["method"] == "notifications/message"
        assert msg["params"]["level"] == "error"
        assert msg["params"]["logger"] == "observal-shim"

    @pytest.mark.asyncio
    async def test_stderr_message_on_spawn_failure(self):
        """Stderr gets a human-readable error message on spawn failure."""
        mock_stdout, stdout_buf, mock_stderr, stderr_io = _make_stdio_mocks()

        with (
            patch.dict("os.environ", {"OBSERVAL_KEY": "test", "OBSERVAL_SERVER": "http://localhost"}),
            patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError("/usr/bin/missing")),
            patch("sys.stdout", mock_stdout),
            patch("sys.stderr", mock_stderr),
        ):
            await run_shim("test-mcp", ["missing"])

        stderr_output = stderr_io.getvalue()
        assert "[observal-shim]" in stderr_output
        assert "MCP server failed to start" in stderr_output
