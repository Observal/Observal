# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: Apache-2.0

from unittest.mock import MagicMock, patch

import pytest

from observal_cli import client, config
from observal_cli.errors import CliError


def test_anonymous_read_defaults_to_public_server():
    assert config.DEFAULTS["server_url"] == ""
    with patch("observal_cli.config.load", return_value=dict(config.DEFAULTS)):
        resolved = config.get_or_exit(require_auth=False)

    assert resolved["server_url"] == "https://public.observal.io"
    assert resolved["access_token"] == ""


def test_token_without_server_does_not_fall_back_to_public_instance():
    persisted = {**config.DEFAULTS, "access_token": "token"}
    with patch("observal_cli.config.load", return_value=persisted), pytest.raises(CliError):
        config.get_or_exit(require_auth=False)


def test_optional_client_omits_authorization_header():
    cfg = {"server_url": "https://public.observal.io", "access_token": ""}
    with (
        patch("observal_cli.client.config.get_or_exit", return_value=cfg) as get_or_exit,
        patch("observal_cli.client._enforce_version_once"),
    ):
        token = client._OPTIONAL_AUTH.set(True)
        try:
            base_url, headers = client._client()
        finally:
            client._OPTIONAL_AUTH.reset(token)

    assert base_url == "https://public.observal.io"
    assert "Authorization" not in headers
    assert "X-Observal-CLI-Version" in headers
    get_or_exit.assert_called_once_with(require_auth=False)


def test_optional_client_uses_token_when_available():
    cfg = {"server_url": "https://public.observal.io", "access_token": "token"}
    with (
        patch("observal_cli.client.config.get_or_exit", return_value=cfg),
        patch("observal_cli.client._enforce_version_once"),
    ):
        token = client._OPTIONAL_AUTH.set(True)
        try:
            _, headers = client._client()
        finally:
            client._OPTIONAL_AUTH.reset(token)

    assert headers["Authorization"] == "Bearer token"


def test_post_public_uses_optional_auth_client():
    response = MagicMock(status_code=200, content=b"{}")
    response.json.return_value = {"ok": True}
    with (
        patch("observal_cli.client._client", return_value=("https://public.observal.io", {})) as make_client,
        patch("observal_cli.client._request_with_retry", return_value=response),
    ):
        result = client.post_public("/api/v1/agents/example/install", {"harness": "pi"})

    assert result == {"ok": True}
    make_client.assert_called_once_with()
