# SPDX-FileCopyrightText: 2026 Hemalatha Madeswaran <hemalathamadeswaran@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""E2E tests for the ``observal auth`` CLI commands.

Covers (per issue #959):
  * ``observal auth login --server --email --password``
  * ``observal auth whoami``
  * ``observal auth status``

All external services are mocked — no live server is required.
"""

from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from observal_cli.main import app

runner = CliRunner()


# ── Helpers ────────────────────────────────────────────────────


def _login_response(role: str = "developer") -> dict:
    """Return a canned ``/api/v1/auth/login`` response body."""
    return {
        "access_token": "test-access-token",
        "refresh_token": "test-refresh-token",
        "user": {
            "id": "user-uuid-1",
            "name": "Test User",
            "email": "test@example.com",
            "role": role,
            "username": "testuser",
        },
    }


def _make_response(status: int = 200, json_body: dict | None = None) -> MagicMock:
    """Build a MagicMock ``httpx.Response`` with status + JSON body."""
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_body or {}
    resp.text = ""
    # raise_for_status is a no-op when status < 400
    if status >= 400:
        import httpx

        def _raise() -> None:
            raise httpx.HTTPStatusError("error", request=MagicMock(), response=resp)

        resp.raise_for_status.side_effect = _raise
    else:
        resp.raise_for_status = MagicMock()
    return resp


def _fake_get(url: str, *_args, **_kwargs) -> MagicMock:
    """Route ``httpx.get`` calls used by the login flow."""
    if "/health" in url:
        return _make_response(200, {"initialized": True})
    if "/api/v1/config/public" in url:
        return _make_response(200, {"sso_enabled": False, "saml_enabled": False, "sso_only": False})
    if "/api/v1/config/endpoints" in url:
        return _make_response(
            200,
            {"otlp_http": "http://localhost:4318", "web": "http://localhost:3000"},
        )
    if "/api/v1/sessions/crypto/public-key" in url:
        return _make_response(404, {})
    return _make_response(200, {})


def _fake_post_login(url: str, *_args, **_kwargs) -> MagicMock:
    """Route ``httpx.post`` calls used by the login flow."""
    if "/api/v1/auth/login" in url:
        return _make_response(200, _login_response())
    return _make_response(200, {})


def _patch_post_login_hooks(stack: ExitStack) -> MagicMock:
    """Patch the IDE-configuration helpers and onboarding step.

    ``observal auth login`` invokes a series of best-effort, side-effecting
    helpers after a successful login (write Claude Code settings, configure
    Kiro hooks, run post-auth onboarding, …).  None of those helpers are
    relevant to the unit under test, so we replace them with no-ops to keep
    the CliRunner sandbox hermetic.

    Returns the ``config.save`` mock so callers can assert on it.
    """
    helper_names = [
        "_fetch_server_public_key",
        "_post_login_setup",
        "_configure_claude_code",
        "_configure_kiro",
        "_configure_gemini_cli",
        "_configure_codex",
        "_configure_copilot",
        "_configure_copilot_cli",
        "_configure_opencode",
        "_post_auth_onboarding",
    ]
    for name in helper_names:
        stack.enter_context(patch(f"observal_cli.cmd_auth.{name}"))
    return stack.enter_context(patch("observal_cli.cmd_auth.config.save"))


# ── auth login ─────────────────────────────────────────────────


class TestAuthLogin:
    """``observal auth login --server --email --password``."""

    def test_login_with_credentials_saves_config(self) -> None:
        """Happy path: server reachable, credentials valid, config persisted."""
        with ExitStack() as stack:
            stack.enter_context(patch("observal_cli.cmd_auth.httpx.get", side_effect=_fake_get))
            stack.enter_context(patch("observal_cli.cmd_auth.httpx.post", side_effect=_fake_post_login))
            mock_save = _patch_post_login_hooks(stack)

            result = runner.invoke(
                app,
                [
                    "auth",
                    "login",
                    "--server",
                    "http://localhost:8000",
                    "--email",
                    "test@example.com",
                    "--password",
                    "Sup3rSecret!Pw",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "Logged in" in result.output
        assert "test@example.com" in result.output

        # Config was saved with the credentials we expected.
        assert mock_save.called, "config.save should have been invoked"
        saved_payload = mock_save.call_args[0][0]
        assert saved_payload["server_url"] == "http://localhost:8000"
        assert saved_payload["access_token"] == "test-access-token"
        assert saved_payload["refresh_token"] == "test-refresh-token"
        assert saved_payload["user_id"] == "user-uuid-1"

    def test_login_strips_trailing_slash_from_server_url(self) -> None:
        """A trailing slash on ``--server`` must not propagate into the saved URL."""
        with ExitStack() as stack:
            stack.enter_context(patch("observal_cli.cmd_auth.httpx.get", side_effect=_fake_get))
            stack.enter_context(patch("observal_cli.cmd_auth.httpx.post", side_effect=_fake_post_login))
            mock_save = _patch_post_login_hooks(stack)

            result = runner.invoke(
                app,
                [
                    "auth",
                    "login",
                    "--server",
                    "http://localhost:8000/",
                    "--email",
                    "test@example.com",
                    "--password",
                    "Sup3rSecret!Pw",
                ],
            )

        assert result.exit_code == 0, result.output
        saved_payload = mock_save.call_args[0][0]
        assert saved_payload["server_url"] == "http://localhost:8000"

    def test_login_with_invalid_credentials_exits_nonzero(self) -> None:
        """A 401 from the login endpoint should surface a clear error."""
        import httpx

        def fake_post_unauth(url: str, *_a, **_k) -> MagicMock:
            if "/api/v1/auth/login" in url:
                resp = _make_response(401, {"detail": "Invalid email or password"})

                def _raise() -> None:
                    raise httpx.HTTPStatusError("unauthorized", request=MagicMock(), response=resp)

                resp.raise_for_status.side_effect = _raise
                return resp
            return _make_response(200, {})

        with ExitStack() as stack:
            stack.enter_context(patch("observal_cli.cmd_auth.httpx.get", side_effect=_fake_get))
            stack.enter_context(patch("observal_cli.cmd_auth.httpx.post", side_effect=fake_post_unauth))
            stack.enter_context(patch("observal_cli.cmd_auth._post_login_setup"))
            mock_save = stack.enter_context(patch("observal_cli.cmd_auth.config.save"))

            result = runner.invoke(
                app,
                [
                    "auth",
                    "login",
                    "--server",
                    "http://localhost:8000",
                    "--email",
                    "test@example.com",
                    "--password",
                    "wrong-password",
                ],
            )

        assert result.exit_code != 0
        assert "Login failed" in result.output
        assert not mock_save.called, "config.save must NOT run on auth failure"

    def test_login_when_server_unreachable_exits_nonzero(self) -> None:
        """If ``/health`` raises ConnectError, exit with a friendly message."""
        import httpx

        def fake_get_unreachable(*_a, **_k):
            raise httpx.ConnectError("connection refused")

        with ExitStack() as stack:
            stack.enter_context(patch("observal_cli.cmd_auth.httpx.get", side_effect=fake_get_unreachable))
            stack.enter_context(patch("observal_cli.cmd_auth.httpx.post"))
            mock_save = stack.enter_context(patch("observal_cli.cmd_auth.config.save"))

            result = runner.invoke(
                app,
                [
                    "auth",
                    "login",
                    "--server",
                    "http://localhost:9999",
                    "--email",
                    "test@example.com",
                    "--password",
                    "Sup3rSecret!Pw",
                ],
            )

        assert result.exit_code != 0
        assert "Connection failed" in result.output
        assert not mock_save.called


# ── auth whoami ────────────────────────────────────────────────


class TestAuthWhoami:
    """``observal auth whoami``."""

    def test_whoami_outputs_email_and_role(self) -> None:
        """Default (table) output must contain the user's email and role."""
        user_data = {
            "id": "user-uuid-99",
            "name": "Alice",
            "email": "alice@example.com",
            "role": "admin",
            "username": "alice",
        }
        with patch("observal_cli.cmd_auth.client.get", return_value=user_data) as mock_get:
            result = runner.invoke(app, ["auth", "whoami"])

        assert result.exit_code == 0, result.output
        mock_get.assert_called_once_with("/api/v1/auth/whoami")
        assert "alice@example.com" in result.output
        assert "admin" in result.output

    def test_whoami_json_output(self) -> None:
        """``--output json`` must emit a JSON document with the same fields."""
        user_data = {
            "id": "user-uuid-99",
            "name": "Alice",
            "email": "alice@example.com",
            "role": "admin",
            "username": "alice",
        }
        with patch("observal_cli.cmd_auth.client.get", return_value=user_data):
            result = runner.invoke(app, ["auth", "whoami", "--output", "json"])

        assert result.exit_code == 0, result.output
        assert "alice@example.com" in result.output
        assert "admin" in result.output

    def test_whoami_unset_username_is_handled(self) -> None:
        """A user without a username should still render cleanly."""
        user_data = {
            "id": "user-uuid-99",
            "name": "Bob",
            "email": "bob@example.com",
            "role": "developer",
            # username intentionally omitted
        }
        with patch("observal_cli.cmd_auth.client.get", return_value=user_data):
            result = runner.invoke(app, ["auth", "whoami"])

        assert result.exit_code == 0, result.output
        assert "bob@example.com" in result.output
        assert "developer" in result.output


# ── auth status ────────────────────────────────────────────────


class TestAuthStatus:
    """``observal auth status``."""

    def test_status_reports_ok_when_healthy(self) -> None:
        """A reachable server with stored credentials renders ``ok`` + latency."""
        cfg = {"server_url": "http://localhost:8000", "access_token": "tok"}
        with (
            patch("observal_cli.cmd_auth.config.load", return_value=cfg),
            patch("observal_cli.cmd_auth.client.health", return_value=(True, 42.0)),
        ):
            result = runner.invoke(app, ["auth", "status"])

        assert result.exit_code == 0, result.output
        assert "http://localhost:8000" in result.output
        assert "configured" in result.output
        assert "ok" in result.output

    def test_status_reports_unreachable_when_health_fails(self) -> None:
        """A failing health probe renders ``unreachable``."""
        cfg = {"server_url": "http://localhost:8000", "access_token": "tok"}
        with (
            patch("observal_cli.cmd_auth.config.load", return_value=cfg),
            patch("observal_cli.cmd_auth.client.health", return_value=(False, 0.0)),
        ):
            result = runner.invoke(app, ["auth", "status"])

        assert result.exit_code == 0, result.output
        assert "unreachable" in result.output

    def test_status_reports_auth_not_set_when_no_token(self) -> None:
        """When no access token is stored, the status output flags it."""
        cfg = {"server_url": "http://localhost:8000", "access_token": ""}
        with (
            patch("observal_cli.cmd_auth.config.load", return_value=cfg),
            patch("observal_cli.cmd_auth.client.health", return_value=(False, 0.0)),
        ):
            result = runner.invoke(app, ["auth", "status"])

        assert result.exit_code == 0, result.output
        assert "not set" in result.output


if __name__ == "__main__":  # pragma: no cover - manual debug entry point
    pytest.main([__file__, "-v"])
