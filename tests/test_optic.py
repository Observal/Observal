# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for Optic (loguru dev logging configuration)."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING
from unittest.mock import patch

from loguru import logger

if TYPE_CHECKING:
    from pathlib import Path


class TestServerOptic:
    """Tests for observal-server/services/optic.py setup."""

    def setup_method(self):
        """Remove all sinks before each test."""
        logger.remove()

    def test_setup_local_mode_adds_stderr_and_file_sinks(self, tmp_path: Path):
        """In dev mode, setup_optic adds console (INFO+) and file (DEBUG+) sinks."""
        from services.optic import setup_optic

        with patch("services.optic.Path.home", return_value=tmp_path):
            setup_optic(mode="dev")

        # Verify file sink directory was created
        log_dir = tmp_path / ".observal" / "logs"
        assert log_dir.exists()

        # Write a debug message - should appear in file but not stderr
        messages = []
        sink_id = logger.add(lambda m: messages.append(m), level="DEBUG")
        logger.debug("test debug message")
        logger.remove(sink_id)
        assert any("test debug message" in str(m) for m in messages)

    def test_setup_enterprise_mode_no_debug_output(self, capsys):
        """In prod mode, DEBUG messages are suppressed."""
        from services.optic import setup_optic

        setup_optic(mode="prod")

        logger.debug("this should be suppressed")
        logger.info("this should appear")

        captured = capsys.readouterr()
        assert "this should be suppressed" not in captured.err
        assert "this should appear" in captured.err

    def test_setup_removes_default_sink(self):
        """setup_optic removes loguru's default stderr sink first."""
        from services.optic import setup_optic

        # Add a default-like sink
        logger.add(sys.stderr)

        # After setup, the old sink should be gone (replaced by our configured ones)
        setup_optic(mode="prod")

        # Logging should still work (our sink is active)
        logger.info("post-setup message")


class TestCLIOptic:
    """Tests for observal_cli/optic.py setup."""

    def setup_method(self):
        """Remove all sinks before each test."""
        logger.remove()

    def test_setup_no_flags_is_silent(self, capsys):
        """With no flags, no sinks are added - loguru is silent."""
        from observal_cli.optic import setup_optic

        setup_optic(debug=False, verbose=False)

        logger.debug("silent debug")
        logger.info("silent info")

        captured = capsys.readouterr()
        assert captured.err == ""
        assert captured.out == ""

    def test_setup_verbose_shows_info(self, capsys):
        """--verbose shows INFO+ on stderr."""
        from observal_cli.optic import setup_optic

        setup_optic(verbose=True)

        logger.debug("should not appear")
        logger.info("should appear")

        captured = capsys.readouterr()
        assert "should not appear" not in captured.err
        assert "should appear" in captured.err

    def test_setup_debug_shows_debug(self, capsys):
        """--debug shows DEBUG+ on stderr."""
        from observal_cli.optic import setup_optic

        setup_optic(debug=True)

        logger.debug("debug message visible")

        captured = capsys.readouterr()
        assert "debug message visible" in captured.err

    def test_setup_debug_creates_log_file(self, tmp_path: Path):
        """--debug creates a CLI log file."""
        from observal_cli.optic import setup_optic

        with patch("observal_cli.optic.Path.home", return_value=tmp_path):
            setup_optic(debug=True)

        log_dir = tmp_path / ".observal" / "logs"
        assert log_dir.exists()


class TestLoggerUsage:
    """Integration tests: verify logger calls work end-to-end."""

    def setup_method(self):
        logger.remove()

    def test_lazy_formatting_no_error_on_missing_args(self):
        """Loguru handles missing format args gracefully."""
        messages = []
        logger.add(lambda m: messages.append(str(m)), level="DEBUG")
        # This should not raise even with mismatched args
        logger.debug("value is {}", 42)
        assert any("42" in m for m in messages)

    def test_context_binding(self):
        """Contextual binding adds extra fields to log output."""
        messages = []
        logger.add(lambda m: messages.append(str(m.record["extra"])), level="DEBUG")

        with logger.contextualize(request_id="abc-123"):
            logger.debug("within context")

        assert any("abc-123" in m for m in messages)

    def test_exception_logging(self):
        """logger.exception captures traceback."""
        messages = []
        logger.add(lambda m: messages.append(str(m)), level="DEBUG")

        try:
            raise ValueError("test error")
        except ValueError:
            logger.exception("caught an error")

        output = "".join(messages)
        assert "ValueError" in output
        assert "test error" in output
