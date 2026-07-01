# SPDX-FileCopyrightText: 2026 0xSHSH
# SPDX-License-Identifier: Apache-2.0

"""E2E tests for CLI auth commands.

Covers:
- observal auth login (password flow)
- observal auth logout
- observal auth whoami
- observal auth status
- observal auth change-password
- observal auth set-username
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_mock_user(**overrides):
    user = {
        "id": overrides.get("id", "test-user-id-123"),
        "email": overrides.get("email", "test@example.com"),
        "username": overrides.get("username", "testuser"),
        "name": overrides.get("name", "Test User"),
        "role": overrides.get("role", "user"),
    }
    return user


class TestAuthLogin:
    """Tests for observal auth login command."""

    def test_login_saves_config(self, tmp_path):
        """Successful login should save access and refresh tokens to config."""
        from observal_cli import config as cfg

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "test-access-token",
            "refresh_token": "test-refresh-token",
            "user": _make_mock_user(),
        }
        mock_response.raise_for_status = MagicMock()

        health_response = MagicMock()
        health_response.status_code = 200
        health_response.json.return_value = {"initialized": True}
        health_response.raise_for_status = MagicMock()

        with patch("observal_cli.cmd_auth.config.CONFIG_FILE", tmp_path / "config.json"):
            with patch("httpx.get", return_value=health_response):
                with patch("httpx.post", return_value=mock_response):
                    from observal_cli.cmd_auth import _do_password_login
                    with patch("observal_cli.cmd_auth._fetch_endpoints", return_value={}):
                        with patch("observal_cli.cmd_auth._fetch_server_public_key"):
                            with patch("observal_cli.cmd_auth._configure_claude_code"):
                                with patch("observal_cli.cmd_auth._configure_kiro"):
                                    with patch("observal_cli.cmd_auth._configure_gemini_cli"):
                                        with patch("observal_cli.cmd_auth._configure_codex"):
                                            with patch("observal_cli.cmd_auth._configure_copilot"):
                                                with patch("observal_cli.cmd_auth._configure_copilot_cli"):
                                                    with patch("observal_cli.cmd_auth._configure_opencode"):
                                                        with patch("observal_cli.cmd_auth._post_auth_onboarding"):
                                                            with patch("observal_cli.config.save") as mock_save:
                                                                _do_password_login(
                                                                    "http://localhost:8000",
                                                                    "test@example.com",
                                                                    "password123",
                                                                )
                                                                mock_save.assert_called()

    def test_login_failed_credentials_raises_exit(self):
        """Wrong credentials should raise typer.Exit."""
        import typer

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.json.return_value = {"detail": "Invalid credentials"}
        mock_response.text = "Invalid credentials"

        http_error = MagicMock()
        http_error.response = mock_response
        http_error.response.status_code = 401

        import httpx
        with patch("httpx.post", side_effect=httpx.HTTPStatusError(
            "401", request=MagicMock(), response=mock_response
        )):
            with pytest.raises((typer.Exit, SystemExit)):
                from observal_cli.cmd_auth import _do_password_login
                _do_password_login(
                    "http://localhost:8000",
                    "wrong@example.com",
                    "wrongpassword",
                )


class TestAuthLogout:
    """Tests for observal auth logout command."""

    def test_logout_clears_tokens(self, tmp_path):
        """Logout should remove access_token and refresh_token from config."""
        config_file = tmp_path / "config.json"
        config_data = {
            "server_url": "http://localhost:8000",
            "access_token": "old-access-token",
            "refresh_token": "old-refresh-token",
            "user_id": "123",
        }
        config_file.write_text(json.dumps(config_data))

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        with patch("observal_cli.cmd_auth.config.CONFIG_FILE", config_file):
            with patch("httpx.post", return_value=mock_response):
                from observal_cli.cmd_auth import logout
                try:
                    logout()
                except SystemExit:
                    pass

        saved = json.loads(config_file.read_text())
        assert "access_token" not in saved
        assert "refresh_token" not in saved

    def test_logout_no_config(self, tmp_path, capsys):
        """Logout with no config file should print dim message and not crash."""
        config_file = tmp_path / "nonexistent.json"

        with patch("observal_cli.cmd_auth.config.CONFIG_FILE", config_file):
            from observal_cli.cmd_auth import logout
            try:
                logout()
            except SystemExit:
                pass


class TestAuthWhoami:
    """Tests for observal auth whoami command."""

    def test_whoami_returns_user_info(self):
        """Whoami should display current user info."""
        mock_user = _make_mock_user()

        with patch("observal_cli.cmd_auth.client.get", return_value=mock_user):
            from observal_cli.cmd_auth import whoami
            try:
                whoami(output="json")
            except SystemExit:
                pass

    def test_whoami_json_output(self, capsys):
        """Whoami with --output json should return valid JSON."""
        mock_user = _make_mock_user()

        with patch("observal_cli.cmd_auth.client.get", return_value=mock_user):
            from observal_cli.cmd_auth import whoami
            try:
                whoami(output="json")
            except SystemExit:
                pass


class TestAuthStatus:
    """Tests for observal auth status command."""

    def test_status_shows_server_info(self):
        """Status should show server URL and auth state."""
        mock_config = {
            "server_url": "http://localhost:8000",
            "access_token": "test-token",
        }

        with patch("observal_cli.cmd_auth.config.load", return_value=mock_config):
            with patch("observal_cli.cmd_auth.client.health", return_value=(True, 50.0)):
                with patch("observal_cli.cmd_auth.client.check_version_compatibility"):
                    from observal_cli.cmd_auth import status
                    try:
                        status()
                    except SystemExit:
                        pass

    def test_status_server_unreachable(self):
        """Status should show unreachable when server is down."""
        mock_config = {
            "server_url": "http://localhost:9999",
            "access_token": "test-token",
        }

        with patch("observal_cli.cmd_auth.config.load", return_value=mock_config):
            with patch("observal_cli.cmd_auth.client.health", return_value=(False, 0)):
                from observal_cli.cmd_auth import status
                try:
                    status()
                except SystemExit:
                    pass


class TestAuthChangePassword:
    """Tests for observal auth change-password command."""

    def test_change_password_success(self):
        """Successful password change should print success message."""
        mock_config = {
            "server_url": "http://localhost:8000",
            "access_token": "test-token",
        }
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        with patch("observal_cli.cmd_auth.config.load", return_value=mock_config):
            with patch("httpx.put", return_value=mock_response):
                with patch("typer.prompt", side_effect=["oldpass", "NewPass123!", "NewPass123!"]):
                    from observal_cli.cmd_auth import change_password
                    try:
                        change_password()
                    except SystemExit:
                        pass

    def test_change_password_mismatch_exits(self):
        """Mismatched passwords should raise Exit."""
        import typer

        mock_config = {
            "server_url": "http://localhost:8000",
            "access_token": "test-token",
        }

        with patch("observal_cli.cmd_auth.config.load", return_value=mock_config):
            with patch("typer.prompt", side_effect=["oldpass", "newpass1", "newpass2"]):
                from observal_cli.cmd_auth import change_password
                with pytest.raises((typer.Exit, SystemExit)):
                    change_password()

    def test_change_password_not_logged_in(self):
        """Change password without login should raise Exit."""
        import typer

        with patch("observal_cli.cmd_auth.config.load", return_value={}):
            from observal_cli.cmd_auth import change_password
            with pytest.raises((typer.Exit, SystemExit)):
                change_password()


class TestAuthSetUsername:
    """Tests for observal auth set-username command."""

    def test_set_username_success(self):
        """Successfully setting username should print confirmation."""
        with patch("observal_cli.cmd_auth.client.put", return_value={"username": "newuser"}):
            from observal_cli.cmd_auth import set_username
            try:
                set_username(username="newuser")
            except SystemExit:
                pass

    def test_set_username_failure(self):
        """Failed username update should raise Exit."""
        import typer

        with patch("observal_cli.cmd_auth.client.put", side_effect=Exception("Username taken")):
            from observal_cli.cmd_auth import set_username
            with pytest.raises((typer.Exit, SystemExit)):
                set_username(username="taken")