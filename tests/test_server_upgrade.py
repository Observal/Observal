# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for server upgrade/rollback commands."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

runner = CliRunner()


def _get_app():
    """Build a test app with server commands registered."""
    from observal_cli.cmd_server import server_app
    from observal_cli.main import app

    # Ensure server sub-app is registered
    try:
        app.add_typer(server_app, name="server")
    except Exception:
        pass  # Already registered
    return app


@pytest.fixture
def compose_dir(tmp_path):
    """Create a fake compose dir with .env."""
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("version: '3'\nservices: {}\n")
    env = tmp_path / ".env"
    env.write_text("OBSERVAL_VERSION=0.7.0\n")
    return tmp_path


class TestServerUpgrade:
    def test_already_on_version(self, compose_dir, monkeypatch):
        monkeypatch.setattr("observal_cli.cmd_server._find_compose_dir", lambda: compose_dir)
        monkeypatch.setattr(
            "observal_cli.version_check._fetch_from_github",
            lambda include_pre=False: {"latest_version": "0.7.0", "source": "github"},
        )
        app = _get_app()
        result = runner.invoke(app, ["server", "upgrade", "--force"])
        assert "Already on v0.7.0" in result.output

    def test_image_not_found_aborts(self, compose_dir, monkeypatch):
        monkeypatch.setattr("observal_cli.cmd_server._find_compose_dir", lambda: compose_dir)
        monkeypatch.setattr(
            "observal_cli.version_check.verify_server_image_exists",
            lambda v: False,
        )
        app = _get_app()
        result = runner.invoke(app, ["server", "upgrade", "--version", "99.0.0", "--force"])
        assert "not found on GHCR" in result.output

    def test_dry_run(self, compose_dir, monkeypatch):
        monkeypatch.setattr("observal_cli.cmd_server._find_compose_dir", lambda: compose_dir)
        monkeypatch.setattr("observal_cli.version_check.verify_server_image_exists", lambda v: True)
        app = _get_app()
        result = runner.invoke(app, ["server", "upgrade", "--version", "0.8.0", "--dry-run"])
        assert "Dry run" in result.output
        assert "0.8.0" in result.output


class TestServerRollback:
    def test_no_backups_exits(self, compose_dir, monkeypatch):
        monkeypatch.setattr("observal_cli.cmd_server._find_compose_dir", lambda: compose_dir)
        monkeypatch.setattr("observal_cli.server.backup.list_backups", lambda: [])
        app = _get_app()
        result = runner.invoke(app, ["server", "rollback"])
        assert "No backups found" in result.output


class TestServerVersions:
    def test_versions_output(self, compose_dir, monkeypatch):
        monkeypatch.setattr("observal_cli.cmd_server._find_compose_dir", lambda: compose_dir)
        monkeypatch.setattr(
            "observal_cli.version_check.fetch_available_server_images",
            lambda: ["0.8.0", "0.7.0", "0.6.0"],
        )
        monkeypatch.setattr("observal_cli.server.backup.list_backups", lambda: [])
        app = _get_app()
        result = runner.invoke(app, ["server", "versions"])
        assert "0.7.0" in result.output
        assert "current" in result.output


class TestEnvVersionUpdate:
    def test_update_existing(self, compose_dir):
        from observal_cli.cmd_server import _update_env_version

        _update_env_version(compose_dir, "0.9.0")
        content = (compose_dir / ".env").read_text()
        assert "OBSERVAL_VERSION=0.9.0" in content
        assert "0.7.0" not in content

    def test_add_new(self, tmp_path):
        from observal_cli.cmd_server import _update_env_version

        env = tmp_path / ".env"
        env.write_text("OTHER_VAR=hello\n")
        _update_env_version(tmp_path, "0.8.0")
        content = env.read_text()
        assert "OBSERVAL_VERSION=0.8.0" in content
        assert "OTHER_VAR=hello" in content
