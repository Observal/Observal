

"""Tests for observal_cli.cmd_auth."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
import typer

from observal_cli import config
from observal_cli.cmd_auth import (
    _fetch_endpoints,
    _fetch_hooks_token,
    _validate_password,
    _do_password_login,
    logout,
)


def test_validate_password_valid():
    """Valid password should return empty list."""
    result = _validate_password("StrongPass123!")
    assert result == []


def test_validate_password_missing_uppercase():
    """Password without uppercase should fail."""
    result = _validate_password("strongpass123!")
    assert "One uppercase letter" in result


def test_validate_password_missing_special_character():
    """Password without special character should fail."""
    result = _validate_password("StrongPass123")
    assert "One special character" in result


def test_fetch_endpoints_returns_empty_on_failure(monkeypatch):
    """Should return empty dict if endpoint fetch fails."""

    def mock_get(*args, **kwargs):
        raise httpx.ConnectError("connection failed")

    monkeypatch.setattr(httpx, "get", mock_get)

    result = _fetch_endpoints("http://localhost:8000")

    assert result == {}


def test_fetch_hooks_token_falls_back_to_access_token(monkeypatch):
    """Should return original token if hooks-token endpoint fails."""

    def mock_post(*args, **kwargs):
        raise httpx.ConnectError("failed")

    monkeypatch.setattr(httpx, "post", mock_post)

    token = _fetch_hooks_token(
        "http://localhost:8000",
        "original_access_token",
    )

    assert token == "original_access_token"


def test_logout_clears_tokens_preserves_server_url(monkeypatch, tmp_path):
    """Logout should remove tokens but keep server_url."""

    config_file = tmp_path / "config.json"

    initial_data = {
        "server_url": "http://localhost:8000",
        "access_token": "access123",
        "refresh_token": "refresh123",
        "api_key": "apikey123",
    }

    config_file.write_text(json.dumps(initial_data))

    monkeypatch.setattr(config, "CONFIG_FILE", config_file)

    def mock_post(*args, **kwargs):
        response = MagicMock()
        response.raise_for_status.return_value = None
        return response

    monkeypatch.setattr(httpx, "post", mock_post)

    logout()

    saved = json.loads(config_file.read_text())

    assert "access_token" not in saved
    assert "refresh_token" not in saved
    assert "api_key" not in saved

    assert saved["server_url"] == "http://localhost:8000"


def test_password_login_saves_config(monkeypatch):
    """Successful login should save config."""

    saved_config = {}

    fake_response = MagicMock()
    fake_response.raise_for_status.return_value = None
    fake_response.json.return_value = {
        "access_token": "access123",
        "refresh_token": "refresh123",
        "user": {
            "id": "user-id",
            "name": "Test User",
            "email": "test@example.com",
            "role": "admin",
        },
    }

    def mock_post(*args, **kwargs):
        return fake_response

    def mock_save(data):
        saved_config.update(data)

    monkeypatch.setattr(httpx, "post", mock_post)
    monkeypatch.setattr(config, "save", mock_save)

    monkeypatch.setattr(
        "observal_cli.cmd_auth._fetch_endpoints",
        lambda *args: {},
    )

    monkeypatch.setattr(
        "observal_cli.cmd_auth._fetch_server_public_key",
        lambda *args: None,
    )

    monkeypatch.setattr(
        "observal_cli.cmd_auth._configure_claude_code",
        lambda *args: None,
    )

    monkeypatch.setattr(
        "observal_cli.cmd_auth._configure_kiro",
        lambda *args: None,
    )

    monkeypatch.setattr(
        "observal_cli.cmd_auth._configure_gemini_cli",
        lambda *args: None,
    )

    monkeypatch.setattr(
        "observal_cli.cmd_auth._configure_codex",
        lambda *args: None,
    )

    monkeypatch.setattr(
        "observal_cli.cmd_auth._configure_copilot",
        lambda *args: None,
    )

    monkeypatch.setattr(
        "observal_cli.cmd_auth._configure_copilot_cli",
        lambda *args: None,
    )

    monkeypatch.setattr(
        "observal_cli.cmd_auth._configure_opencode",
        lambda *args: None,
    )

    monkeypatch.setattr(
        "observal_cli.cmd_auth._post_auth_onboarding",
        lambda *args: None,
    )

    _do_password_login(
        "http://localhost:8000",
        "test@example.com",
        "password123",
    )

    assert saved_config["server_url"] == "http://localhost:8000"
    assert saved_config["access_token"] == "access123"
    assert saved_config["refresh_token"] == "refresh123"


def test_password_login_http_error(monkeypatch):
    """HTTP error during login should raise typer.Exit."""

    response = MagicMock()
    response.status_code = 401
    response.text = "Unauthorized"

    error = httpx.HTTPStatusError(
        "Unauthorized",
        request=MagicMock(),
        response=response,
    )

    def mock_post(*args, **kwargs):
        raise error

    monkeypatch.setattr(httpx, "post", mock_post)

    with pytest.raises(typer.Exit):
        _do_password_login(
            "http://localhost:8000",
            "test@example.com",
            "wrongpassword",
        )