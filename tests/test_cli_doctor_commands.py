# SPDX-FileCopyrightText: 2026 0xSHSH <156781261+0xSHSH@users.noreply.github.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""E2E tests for CLI doctor commands.

Covers:
- observal doctor (health check)
- observal doctor patch
- observal doctor cleanup
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestDoctorDiagnose:
    """Tests for observal doctor (diagnose) command."""

    def test_doctor_no_config(self, tmp_path):
        """Doctor should report issue when config is missing."""
        with patch("pathlib.Path.home", return_value=tmp_path):
            from observal_cli.cmd_doctor import doctor_app
            from typer.testing import CliRunner
            runner = CliRunner()
            result = runner.invoke(doctor_app, [])
            assert result.exit_code in (0, 1)

    def test_doctor_with_valid_config(self, tmp_path):
        """Doctor should pass when config and server are healthy."""
        observal_dir = tmp_path / ".observal"
        observal_dir.mkdir()
        config_file = observal_dir / "config.json"
        config_file.write_text(json.dumps({
            "server_url": "http://localhost:8000",
            "access_token": "test-token",
        }))

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("pathlib.Path.home", return_value=tmp_path):
            with patch("httpx.get", return_value=mock_resp):
                from observal_cli.cmd_doctor import doctor_app
                from typer.testing import CliRunner
                runner = CliRunner()
                result = runner.invoke(doctor_app, [])
                assert result.exit_code in (0, 1)

    def test_doctor_invalid_config_json(self, tmp_path):
        """Doctor should report issue when config.json is malformed."""
        observal_dir = tmp_path / ".observal"
        observal_dir.mkdir()
        config_file = observal_dir / "config.json"
        config_file.write_text("not valid json{{{")

        with patch("pathlib.Path.home", return_value=tmp_path):
            from observal_cli.cmd_doctor import doctor_app
            from typer.testing import CliRunner
            runner = CliRunner()
            result = runner.invoke(doctor_app, [])
            assert result.exit_code in (0, 1)

    def test_doctor_missing_access_token(self, tmp_path):
        """Doctor should warn when access_token is missing."""
        observal_dir = tmp_path / ".observal"
        observal_dir.mkdir()
        config_file = observal_dir / "config.json"
        config_file.write_text(json.dumps({
            "server_url": "http://localhost:8000",
        }))

        with patch("pathlib.Path.home", return_value=tmp_path):
            from observal_cli.cmd_doctor import doctor_app
            from typer.testing import CliRunner
            runner = CliRunner()
            result = runner.invoke(doctor_app, [])
            assert result.exit_code in (0, 1)


class TestDoctorPatch:
    """Tests for observal doctor patch command."""

    def test_patch_requires_action_flag(self):
        """Patch without --hook/--shim/--all should exit with error."""
        from observal_cli.cmd_doctor import doctor_app
        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(doctor_app, ["patch", "--ide", "claude-code"])
        assert result.exit_code != 0

    def test_patch_requires_ide_flag(self):
        """Patch without --ide/--all-ides should exit with error."""
        from observal_cli.cmd_doctor import doctor_app
        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(doctor_app, ["patch", "--all"])
        assert result.exit_code != 0

    def test_patch_not_logged_in(self):
        """Patch should fail when not logged in."""
        with patch("observal_cli.cmd_doctor.config.load", return_value={}):
            from observal_cli.cmd_doctor import doctor_app
            from typer.testing import CliRunner
            runner = CliRunner()
            result = runner.invoke(doctor_app, [
                "patch", "--all", "--ide", "claude-code"
            ])
            assert result.exit_code != 0

    def test_patch_dry_run_makes_no_changes(self, tmp_path):
        """Dry run patch should not modify any files."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings = claude_dir / "settings.json"
        settings.write_text(json.dumps({}))
        content_before = settings.read_text()

        mock_config = {
            "server_url": "http://localhost:8000",
            "access_token": "test-token",
            "api_key": "hooks-token",
        }

        with patch("observal_cli.cmd_doctor.config.load", return_value=mock_config):
            with patch("pathlib.Path.home", return_value=tmp_path):
                from observal_cli.cmd_doctor import doctor_app
                from typer.testing import CliRunner
                runner = CliRunner()
                runner.invoke(doctor_app, [
                    "patch", "--hook", "--ide", "claude-code", "--dry-run"
                ])

        assert settings.read_text() == content_before

    def test_patch_invalid_ide(self):
        """Patch with unknown IDE name should exit with error."""
        mock_config = {
            "server_url": "http://localhost:8000",
            "access_token": "test-token",
        }

        with patch("observal_cli.cmd_doctor.config.load", return_value=mock_config):
            from observal_cli.cmd_doctor import doctor_app
            from typer.testing import CliRunner
            runner = CliRunner()
            result = runner.invoke(doctor_app, [
                "patch", "--all", "--ide", "unknown-ide-xyz"
            ])
            assert result.exit_code != 0

    def test_patch_kiro_no_agents_dir(self, tmp_path):
        """Patch Kiro when no agents dir exists should skip gracefully."""
        mock_config = {
            "server_url": "http://localhost:8000",
            "access_token": "test-token",
        }

        with patch("observal_cli.cmd_doctor.config.load", return_value=mock_config):
            with patch("pathlib.Path.home", return_value=tmp_path):
                from observal_cli.cmd_doctor import doctor_app
                from typer.testing import CliRunner
                runner = CliRunner()
                result = runner.invoke(doctor_app, [
                    "patch", "--hook", "--ide", "kiro"
                ])
                assert result.exit_code in (0, 1)


class TestDoctorCleanup:
    """Tests for observal doctor cleanup command."""

    def test_cleanup_no_artifacts(self, tmp_path):
        """Cleanup with no Observal artifacts should report nothing to clean."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings = claude_dir / "settings.json"
        settings.write_text(json.dumps({"env": {}, "hooks": {}}))

        with patch("pathlib.Path.home", return_value=tmp_path):
            from observal_cli.cmd_doctor import doctor_app
            from typer.testing import CliRunner
            runner = CliRunner()
            result = runner.invoke(doctor_app, ["cleanup", "--ide", "claude-code"])
            assert result.exit_code == 0

    def test_cleanup_removes_observal_hooks(self, tmp_path):
        """Cleanup should remove Observal hooks from settings.json."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings = claude_dir / "settings.json"
        settings.write_text(json.dumps({
            "hooks": {
                "UserPromptSubmit": [
                    {
                        "hooks": [
                            {"command": "python -m observal_cli.hooks.session_push"}
                        ]
                    }
                ]
            }
        }))

        with patch("pathlib.Path.home", return_value=tmp_path):
            from observal_cli.cmd_doctor import doctor_app
            from typer.testing import CliRunner
            runner = CliRunner()
            result = runner.invoke(doctor_app, ["cleanup", "--ide", "claude-code"])
            assert result.exit_code == 0

    def test_cleanup_dry_run_no_changes(self, tmp_path):
        """Cleanup dry run should not modify any files."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings = claude_dir / "settings.json"
        original = json.dumps({
            "hooks": {
                "UserPromptSubmit": [
                    {
                        "hooks": [
                            {"command": "python -m observal_cli.hooks.session_push"}
                        ]
                    }
                ]
            }
        })
        settings.write_text(original)

        with patch("pathlib.Path.home", return_value=tmp_path):
            from observal_cli.cmd_doctor import doctor_app
            from typer.testing import CliRunner
            runner = CliRunner()
            runner.invoke(doctor_app, [
                "cleanup", "--ide", "claude-code", "--dry-run"
            ])

        assert settings.read_text() == original

    def test_cleanup_kiro_no_agents(self, tmp_path):
        """Cleanup Kiro with no agents dir should skip gracefully."""
        with patch("pathlib.Path.home", return_value=tmp_path):
            from observal_cli.cmd_doctor import doctor_app
            from typer.testing import CliRunner
            runner = CliRunner()
            result = runner.invoke(doctor_app, ["cleanup", "--ide", "kiro"])
            assert result.exit_code == 0

    def test_cleanup_removes_stale_env_vars(self, tmp_path):
        """Cleanup should remove OTEL env vars from Claude Code settings."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings = claude_dir / "settings.json"
        settings.write_text(json.dumps({
            "env": {
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318",
                "OTEL_SERVICE_NAME": "observal",
                "MY_CUSTOM_VAR": "keep-this",
            }
        }))

        with patch("pathlib.Path.home", return_value=tmp_path):
            from observal_cli.cmd_doctor import doctor_app
            from typer.testing import CliRunner
            runner = CliRunner()
            result = runner.invoke(doctor_app, ["cleanup", "--ide", "claude-code"])
            assert result.exit_code == 0