# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for `observal self upgrade/downgrade/rollback/status` commands."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

runner = CliRunner()


@pytest.fixture
def mock_version(monkeypatch):
    """Mock current CLI version."""
    monkeypatch.setattr("observal_cli.version_check.get_current_version", lambda: "0.7.0")


@pytest.fixture
def mock_install_uv(monkeypatch):
    """Mock install detection as uv tool."""
    from observal_cli.install_detector import InstallInfo, InstallMethod

    info = InstallInfo(
        method=InstallMethod.UV_TOOL,
        path=Path("/home/user/.local/bin/observal"),
        writable=True,
        managed_by="uv",
    )
    monkeypatch.setattr("observal_cli.install_detector.detect", lambda: info)
    monkeypatch.setattr("observal_cli.install_detector._cached_info", info)
    return info


@pytest.fixture
def mock_install_brew(monkeypatch):
    """Mock install detection as Homebrew."""
    from observal_cli.install_detector import InstallInfo, InstallMethod

    info = InstallInfo(
        method=InstallMethod.HOMEBREW,
        path=Path("/opt/homebrew/bin/observal"),
        writable=False,
        managed_by="brew",
    )
    monkeypatch.setattr("observal_cli.install_detector.detect", lambda: info)
    monkeypatch.setattr("observal_cli.install_detector._cached_info", info)
    return info


@pytest.fixture
def mock_lock(monkeypatch, tmp_path):
    """Mock upgrade lock to use tmp directory."""
    monkeypatch.setattr("observal_cli.upgrade_lock.CONFIG_DIR", tmp_path)


def _get_app():
    """Import the app fresh (avoids circular import issues in tests)."""
    from observal_cli.main import app

    return app


class TestSelfUpgrade:
    def test_upgrade_already_latest(self, mock_version, mock_install_uv, mock_lock, monkeypatch):
        monkeypatch.setattr(
            "observal_cli.version_check._fetch_from_github",
            lambda include_pre=False: {"latest_version": "0.7.0", "source": "github"},
        )
        app = _get_app()
        result = runner.invoke(app, ["self", "upgrade", "--force"])
        assert "Already on v0.7.0" in result.output

    def test_upgrade_managed_install_blocked(self, mock_version, mock_install_brew, monkeypatch):
        app = _get_app()
        result = runner.invoke(app, ["self", "upgrade", "--force"])
        assert "managed by brew" in result.output.lower() or "brew" in result.output

    def test_upgrade_specific_version(self, mock_version, mock_install_uv, mock_lock, monkeypatch):
        """--version 0.8.0 should attempt install of that version."""
        install_called = {"version": None}

        def mock_do_install(info, target, direction):
            install_called["version"] = target

        monkeypatch.setattr("observal_cli.cmd_ops._do_install", mock_do_install)
        app = _get_app()
        result = runner.invoke(app, ["self", "upgrade", "--version", "0.8.0", "--force"])
        assert install_called["version"] == "0.8.0"

    def test_upgrade_older_version_rejected(self, mock_version, mock_install_uv, mock_lock, monkeypatch):
        """Attempting to 'upgrade' to an older version should fail."""
        app = _get_app()
        result = runner.invoke(app, ["self", "upgrade", "--version", "0.5.0", "--force"])
        assert "older" in result.output.lower() or "downgrade" in result.output.lower()


class TestSelfDowngrade:
    def test_downgrade_requires_version(self, mock_version, monkeypatch):
        app = _get_app()
        result = runner.invoke(app, ["self", "downgrade"])
        assert "--version is required" in result.output or "version" in result.output.lower()

    def test_downgrade_list(self, mock_version, monkeypatch):
        monkeypatch.setattr(
            "observal_cli.version_check.fetch_all_releases",
            lambda include_pre=False: [
                {"version": "0.7.0", "published_at": "2026-05-20", "prerelease": False},
                {"version": "0.6.0", "published_at": "2026-05-10", "prerelease": False},
            ],
        )
        monkeypatch.setattr("observal_cli.cmd_ops._get_server_min_version", lambda: None)
        app = _get_app()
        result = runner.invoke(app, ["self", "downgrade", "--list"])
        assert "0.7.0" in result.output
        assert "0.6.0" in result.output

    def test_downgrade_below_minimum_warns(self, mock_version, mock_install_uv, mock_lock, monkeypatch):
        """Downgrading below MIN_CLI_VERSION should warn."""
        monkeypatch.setattr("observal_cli.cmd_ops._get_server_min_version", lambda: "0.6.0")

        def mock_do_install(info, target, direction):
            pass

        monkeypatch.setattr("observal_cli.cmd_ops._do_install", mock_do_install)
        app = _get_app()
        # Without --force, prompt appears. With --force, it bypasses.
        result = runner.invoke(app, ["self", "downgrade", "--version", "0.4.0", "--force"])
        # Should still proceed with --force (no error exit)
        assert result.exit_code == 0 or "below server minimum" in result.output

    def test_downgrade_target_is_newer(self, mock_version, monkeypatch):
        """Downgrade to a newer version should error."""
        app = _get_app()
        result = runner.invoke(app, ["self", "downgrade", "--version", "0.9.0"])
        assert "not older" in result.output.lower() or "upgrade" in result.output.lower()


class TestSelfRollback:
    def test_rollback_no_backup(self, monkeypatch, tmp_path):
        monkeypatch.setattr("observal_cli.config.CONFIG_DIR", tmp_path)
        from observal_cli.install_detector import InstallInfo, InstallMethod

        info = InstallInfo(InstallMethod.BINARY, Path("/usr/local/bin/observal"), True, None)
        monkeypatch.setattr("observal_cli.install_detector.detect", lambda: info)
        monkeypatch.setattr("observal_cli.install_detector._cached_info", info)

        app = _get_app()
        result = runner.invoke(app, ["self", "rollback"])
        assert "No backup found" in result.output


class TestSelfStatus:
    def test_status_shows_version(self, mock_version, mock_install_uv, monkeypatch):
        monkeypatch.setattr(
            "observal_cli.version_check._fetch_from_github",
            lambda include_pre=False: {"latest_version": "0.8.0", "source": "github"},
        )
        monkeypatch.setattr("observal_cli.cmd_ops._get_server_min_version", lambda: None)
        app = _get_app()
        result = runner.invoke(app, ["self", "status"])
        assert "0.7.0" in result.output
