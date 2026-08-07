# SPDX-FileCopyrightText: 2026 OpenAI contributors
# SPDX-License-Identifier: Apache-2.0

"""Tests for password validation in :mod:`observal_cli.cmd_auth`."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from observal_cli.cmd_auth import _do_password_login, _fetch_endpoints, _fetch_server_public_key, _validate_password


@pytest.mark.parametrize(
    ("password", "missing"),
    [
        ("Short1!", ["At least 12 characters"]),
        ("longpassword1!", ["One uppercase letter"]),
        ("Longpassword!", ["One number"]),
        ("Longpassword1", ["One special character"]),
        ("short", ["At least 12 characters", "One uppercase letter", "One number", "One special character"]),
    ],
)
def test_validate_password_reports_each_unmet_requirement(password: str, missing: list[str]) -> None:
    assert _validate_password(password) == missing


def test_validate_password_accepts_password_meeting_all_requirements() -> None:
    assert _validate_password("LongPassword1!") == []


def test_fetch_endpoints_returns_discovered_urls() -> None:
    response = MagicMock(status_code=200)
    response.json.return_value = {"api": "https://api.example", "web": "https://app.example"}

    with patch("observal_cli.cmd_auth.httpx.get", return_value=response) as get:
        assert _fetch_endpoints("https://server.example/") == response.json.return_value

    get.assert_called_once_with("https://server.example/api/v1/config/endpoints", timeout=5)


@pytest.mark.parametrize("response", [MagicMock(status_code=404), RuntimeError("offline")])
def test_fetch_endpoints_returns_empty_mapping_when_discovery_fails(response: object) -> None:
    with patch("observal_cli.cmd_auth.httpx.get", side_effect=response):
        assert _fetch_endpoints("https://server.example") == {}


def test_fetch_server_public_key_writes_key_file(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    response = MagicMock(status_code=200)
    response.json.return_value = {"public_key_pem": "PUBLIC KEY"}
    monkeypatch.setattr("observal_cli.cmd_auth.Path.home", lambda: tmp_path)

    with patch("observal_cli.cmd_auth.httpx.get", return_value=response):
        _fetch_server_public_key("https://server.example/")

    assert (tmp_path / ".observal/keys/server_public.pem").read_text() == "PUBLIC KEY"


def test_do_password_login_saves_session_and_runs_post_login_setup() -> None:
    response = MagicMock()
    response.json.return_value = {
        "access_token": "access",
        "refresh_token": "refresh",
        "user": {"id": "user-1", "name": "Ada", "email": "ada@example.com", "role": "admin"},
    }

    with (
        patch("observal_cli.cmd_auth.httpx.post", return_value=response),
        patch("observal_cli.cmd_auth._fetch_endpoints", return_value={"web": "https://app.example"}),
        patch("observal_cli.cmd_auth._fetch_server_public_key"),
        patch("observal_cli.cmd_auth._post_login_setup"),
        patch("observal_cli.cmd_auth.config.save") as save,
    ):
        _do_password_login("https://server.example", "ada@example.com", "LongPassword1!")

    save.assert_called_once_with(
        {
            "server_url": "https://server.example",
            "access_token": "access",
            "refresh_token": "refresh",
            "user_id": "user-1",
            "user_name": "Ada",
            "username": "",
            "web_url": "https://app.example",
        }
    )
