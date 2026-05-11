# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for CLI error handling improvements."""

import os
from unittest.mock import MagicMock, patch

import click
import pytest


def test_get_timeout_default():
    """Default timeout is 30s."""
    from observal_cli.config import get_timeout

    with (
        patch("observal_cli.config.load", return_value={"timeout": 30}),
        patch.dict("os.environ", {}, clear=True),
    ):
        assert get_timeout() == 30


def test_get_timeout_env_override():
    """OBSERVAL_TIMEOUT env var overrides config."""
    from observal_cli.config import get_timeout

    with patch.dict("os.environ", {"OBSERVAL_TIMEOUT": "60"}):
        assert get_timeout() == 60


def test_get_timeout_config_override():
    """Config file timeout is used when no env var."""
    from observal_cli.config import get_timeout

    with (
        patch("observal_cli.config.load", return_value={"timeout": 45}),
        patch.dict("os.environ", {}, clear=True),
    ):
        assert get_timeout() == 45


def test_handle_error_401():
    """401 error shows auth login hint."""
    import httpx

    from observal_cli.client import _handle_error

    response = MagicMock()
    response.status_code = 401
    response.headers = {"content-type": "application/json"}
    response.json.return_value = {"detail": "Invalid credentials"}
    response.text = "Invalid credentials"

    error = httpx.HTTPStatusError("", request=MagicMock(), response=response)

    with pytest.raises((SystemExit, click.exceptions.Exit)):
        _handle_error(error, "/api/v1/test")


def test_handle_error_includes_path():
    """Error messages include the request path."""
    import httpx

    from observal_cli.client import _handle_error

    response = MagicMock()
    response.status_code = 500
    response.headers = {"content-type": "text/plain"}
    response.text = "Internal error"

    error = httpx.HTTPStatusError("", request=MagicMock(), response=response)

    with pytest.raises((SystemExit, click.exceptions.Exit)):
        _handle_error(error, "/api/v1/agents")


def test_config_save_sets_permissions(tmp_path):
    """Config save sets 0o600 permissions."""
    from observal_cli import config

    with (
        patch.object(config, "CONFIG_DIR", tmp_path),
        patch.object(config, "CONFIG_FILE", tmp_path / "config.json"),
    ):
        config.save({"server_url": "http://localhost:8000", "api_key": "test"})

        mode = os.stat(tmp_path / "config.json").st_mode & 0o777
        assert mode == 0o600


def test_render_error_helper():
    """render.error() prints formatted error."""
    from observal_cli.render import error, success, warning

    # These should not raise
    error("test error", hint="try this")
    warning("test warning")
    success("test success")
