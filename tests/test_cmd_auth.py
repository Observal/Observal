# SPDX-FileCopyrightText: 2026 OpenAI contributors
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Behavioral tests for :mod:`observal_cli.cmd_auth`."""

from __future__ import annotations

import json
import platform
import subprocess
import sys
import time
import webbrowser
from contextlib import nullcontext
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, call

import httpx
import pytest
import typer
from typer.testing import CliRunner

import observal_cli.cmd_auth as auth

if TYPE_CHECKING:
    from pathlib import Path

SERVER_URL = "https://registry.example.test"
ACCESS_TOKEN = "test-access-token-value"
REFRESH_TOKEN = "test-refresh-token-value"
VALID_PASSWORD = "ValidPassword1!"
_MISSING = object()


def _response(
    status_code: int = 200,
    data: object = _MISSING,
    *,
    text: str | None = None,
) -> httpx.Response:
    request = httpx.Request("GET", SERVER_URL)
    if data is not _MISSING:
        return httpx.Response(status_code, json=data, request=request)
    return httpx.Response(status_code, text=text or "", request=request)


def _user(**overrides: str) -> dict[str, str]:
    return {
        "id": "user-123",
        "name": "Ada Lovelace",
        "email": "ada@example.test",
        "role": "admin",
        "username": "ada",
        **overrides,
    }


def _login_payload(**overrides: object) -> dict[str, object]:
    return {
        "access_token": ACCESS_TOKEN,
        "refresh_token": REFRESH_TOKEN,
        "user": _user(),
        **overrides,
    }


def _device_authorization(**overrides: object) -> dict[str, object]:
    return {
        "device_code": "private-device-code",
        "user_code": "ABCD-EFGH",
        "verification_uri": "http://localhost/device",
        "verification_uri_complete": "http://localhost/device?code=ABCD-EFGH",
        "expires_in": 10,
        "interval": 1,
        **overrides,
    }


@pytest.fixture(autouse=True)
def _isolate_side_effects(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(auth, "spinner", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(auth, "welcome_banner", MagicMock())
    monkeypatch.setattr(auth.config, "CONFIG_FILE", tmp_path / "config.json")


@pytest.fixture
def printed(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    messages: list[str] = []

    def record(*values: object, **_kwargs: object) -> None:
        messages.append(" ".join(str(value) for value in values))

    monkeypatch.setattr(auth, "rprint", record)
    return messages


@pytest.fixture(scope="module")
def config_cli() -> typer.Typer:
    root = typer.Typer()
    local_config_app = typer.Typer()
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(auth, "config_app", local_config_app)
        auth.register_config(root)
    return root


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def device_runtime(monkeypatch: pytest.MonkeyPatch) -> tuple[_Clock, MagicMock]:
    clock = _Clock()
    browser_open = MagicMock(return_value=True)
    monkeypatch.setattr(time, "monotonic", clock.monotonic)
    monkeypatch.setattr(time, "sleep", clock.sleep)
    monkeypatch.setattr(platform, "system", lambda: "Other")
    monkeypatch.setattr(webbrowser, "open", browser_open)
    return clock, browser_open


@pytest.mark.parametrize(
    ("password", "missing"),
    [
        ("Short1!", ["At least 12 characters"]),
        ("longpassword1!", ["One uppercase letter"]),
        ("Longpassword!", ["One number"]),
        ("Longpassword1", ["One special character"]),
        (
            "short",
            ["At least 12 characters", "One uppercase letter", "One number", "One special character"],
        ),
        (VALID_PASSWORD, []),
    ],
)
def test_validate_password_reports_exact_requirements(password: str, missing: list[str]) -> None:
    assert auth._validate_password(password) == missing


def test_prompt_password_retries_without_echoing_password(
    monkeypatch: pytest.MonkeyPatch,
    printed: list[str],
) -> None:
    password_input = MagicMock(side_effect=["weak", VALID_PASSWORD])
    monkeypatch.setattr(auth, "password_input", password_input)

    assert auth._prompt_password("Choose password") == VALID_PASSWORD

    assert password_input.call_args_list == [call("Choose password"), call("Choose password")]
    output = "\n".join(printed)
    assert "Password does not meet requirements" in output
    assert "At least 12 characters" in output
    assert "weak" not in output
    assert VALID_PASSWORD not in output


@pytest.mark.parametrize("cli_version", ["0.0.0"])
def test_version_check_skips_uninstalled_cli(
    cli_version: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import observal_cli.version_check as version_check

    get = MagicMock()
    monkeypatch.setattr(version_check, "get_current_version", lambda: cli_version)
    monkeypatch.setattr(auth.httpx, "get", get)

    auth._ensure_cli_matches_server(SERVER_URL)

    get.assert_not_called()


@pytest.mark.parametrize(
    "server_response",
    [
        RuntimeError("offline"),
        _response(200, {}),
        _response(200, {"server_version": "dev"}),
        _response(200, {"server_version": "invalid version"}),
        _response(200, {"server_version": "1.2.3"}),
    ],
)
def test_version_check_allows_unavailable_or_compatible_server(
    server_response: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import observal_cli.version_check as version_check

    monkeypatch.setattr(version_check, "get_current_version", lambda: "1.2.3")
    get = MagicMock(side_effect=server_response if isinstance(server_response, Exception) else None)
    if not isinstance(server_response, Exception):
        get.return_value = server_response
    monkeypatch.setattr(auth.httpx, "get", get)

    auth._ensure_cli_matches_server(SERVER_URL)


@pytest.mark.parametrize(
    ("cli_version", "server_version", "expected_text", "upgrade_result"),
    [
        ("2.0.0", "1.9.0", "self downgrade", None),
        ("1.9.0", "2.0.0", "install-observal 2.0.0", "install-observal 2.0.0"),
    ],
)
def test_version_check_blocks_mismatch_with_correct_remediation(
    cli_version: str,
    server_version: str,
    expected_text: str,
    upgrade_result: str | None,
    monkeypatch: pytest.MonkeyPatch,
    printed: list[str],
) -> None:
    import observal_cli.install_detector as install_detector
    import observal_cli.version_check as version_check

    monkeypatch.setattr(version_check, "get_current_version", lambda: cli_version)
    monkeypatch.setattr(auth.httpx, "get", lambda *_args, **_kwargs: _response(200, {"server_version": server_version}))
    upgrade = MagicMock(return_value=upgrade_result)
    monkeypatch.setattr(install_detector, "upgrade_command", upgrade)

    with pytest.raises(typer.Exit) as exc_info:
        auth._ensure_cli_matches_server(SERVER_URL)

    assert exc_info.value.exit_code == 1
    assert expected_text in "\n".join(printed)
    if upgrade_result is None:
        upgrade.assert_not_called()
    else:
        upgrade.assert_called_once_with(server_version)


def _prepare_login(
    monkeypatch: pytest.MonkeyPatch,
    *,
    initialized: bool = True,
    public: dict[str, object] | None = None,
    public_status: int = 200,
    previous_server: str = "",
) -> tuple[MagicMock, MagicMock, MagicMock]:
    import observal_cli.lockfile as lockfile

    responses = [
        _response(200, {"initialized": initialized}),
        _response(public_status, public or {}),
    ]
    get = MagicMock(side_effect=responses)
    ensure_version = MagicMock()
    migrate = MagicMock()
    monkeypatch.setattr(auth.httpx, "get", get)
    monkeypatch.setattr(auth, "_ensure_cli_matches_server", ensure_version)
    monkeypatch.setattr(auth.config, "load", lambda: {"server_url": previous_server})
    monkeypatch.setattr(lockfile, "migrate_lockfile_v1", migrate)
    return get, ensure_version, migrate


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (httpx.ConnectError("connection refused"), "Connection failed"),
        (RuntimeError("bad health response"), "Server error"),
    ],
)
def test_login_stops_when_health_check_fails(
    error: Exception,
    message: str,
    monkeypatch: pytest.MonkeyPatch,
    printed: list[str],
) -> None:
    monkeypatch.setattr(auth.config, "load", lambda: {})
    monkeypatch.setattr(auth.httpx, "get", MagicMock(side_effect=error))

    with pytest.raises(typer.Exit) as exc_info:
        auth.login(SERVER_URL, "ada@example.test", VALID_PASSWORD, None, False, False)

    assert exc_info.value.exit_code == 1
    assert message in "\n".join(printed)


def test_login_initializes_fresh_server_and_persists_only_returned_tokens(
    monkeypatch: pytest.MonkeyPatch,
    printed: list[str],
) -> None:
    _, ensure_version, migrate = _prepare_login(
        monkeypatch,
        initialized=False,
        previous_server="https://old.example.test",
    )
    text_input = MagicMock(side_effect=["ada@example.test", "Ada"])
    password_input = MagicMock(return_value=VALID_PASSWORD)
    post = MagicMock(return_value=_response(200, _login_payload()))
    save = MagicMock()
    setup = MagicMock()
    monkeypatch.setattr(auth, "text_input", text_input)
    monkeypatch.setattr(auth, "_prompt_password", MagicMock(return_value=VALID_PASSWORD))
    monkeypatch.setattr(auth, "password_input", password_input)
    monkeypatch.setattr(auth.httpx, "post", post)
    monkeypatch.setattr(auth, "_fetch_endpoints", lambda _url: {"web": "https://app.example.test"})
    monkeypatch.setattr(auth.config, "save", save)
    monkeypatch.setattr(auth, "_post_login_setup", setup)

    auth.login(f"{SERVER_URL}/", None, None, None, False, False)

    ensure_version.assert_called_once_with(SERVER_URL)
    migrate.assert_called_once_with("https://old.example.test")
    post.assert_called_once_with(
        f"{SERVER_URL}/api/v1/auth/init",
        json={"email": "ada@example.test", "name": "Ada", "password": VALID_PASSWORD},
        timeout=30,
    )
    save.assert_called_once_with(
        {
            "server_url": SERVER_URL,
            "access_token": ACCESS_TOKEN,
            "refresh_token": REFRESH_TOKEN,
            "user_id": "user-123",
            "user_name": "Ada Lovelace",
            "username": "ada",
            "web_url": "https://app.example.test",
        }
    )
    setup.assert_called_once_with()
    output = "\n".join(printed)
    assert "Logged in as Ada Lovelace" in output
    assert VALID_PASSWORD not in output
    assert ACCESS_TOKEN not in output
    assert REFRESH_TOKEN not in output


def test_login_fresh_server_rejects_mismatched_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    printed: list[str],
) -> None:
    _prepare_login(monkeypatch, initialized=False)
    post = MagicMock()
    monkeypatch.setattr(auth, "_prompt_password", lambda _prompt: VALID_PASSWORD)
    monkeypatch.setattr(auth, "password_input", lambda _prompt: "DifferentPassword2!")
    monkeypatch.setattr(auth.httpx, "post", post)

    with pytest.raises(typer.Exit):
        auth.login(SERVER_URL, "ada@example.test", None, "Ada", False, False)

    post.assert_not_called()
    assert "Passwords do not match" in "\n".join(printed)


@pytest.mark.parametrize(
    ("status", "body", "should_raise", "message"),
    [
        (400, "Already Initialized by another request", False, "just initialized"),
        (500, "database unavailable", True, "Setup failed"),
    ],
)
def test_login_handles_admin_initialization_failures(
    status: int,
    body: str,
    should_raise: bool,
    message: str,
    monkeypatch: pytest.MonkeyPatch,
    printed: list[str],
) -> None:
    _prepare_login(monkeypatch, initialized=False)
    monkeypatch.setattr(auth.httpx, "post", lambda *_args, **_kwargs: _response(status, text=body))
    save = MagicMock()
    monkeypatch.setattr(auth.config, "save", save)

    if should_raise:
        with pytest.raises(typer.Exit):
            auth.login(SERVER_URL, "ada@example.test", VALID_PASSWORD, "Ada", False, False)
    else:
        auth.login(SERVER_URL, "ada@example.test", VALID_PASSWORD, "Ada", False, False)

    save.assert_not_called()
    assert message in "\n".join(printed)


def test_login_with_credentials_routes_to_password_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, migrate = _prepare_login(
        monkeypatch,
        public={"sso_enabled": False, "saml_enabled": False, "sso_only": False},
        previous_server=SERVER_URL,
    )
    password_login = MagicMock()
    monkeypatch.setattr(auth, "_do_password_login", password_login)

    auth.login(f"{SERVER_URL}/", "ada", VALID_PASSWORD, None, False, False)

    password_login.assert_called_once_with(SERVER_URL, "ada", VALID_PASSWORD)
    migrate.assert_called_once_with(SERVER_URL)


@pytest.mark.parametrize(
    ("choice", "public", "expected_direct", "expected_provider"),
    [
        ("2", {}, False, None),
        ("3", {"sso_enabled": True}, True, "oidc"),
        ("3", {"saml_enabled": True}, True, "saml"),
        ("4", {"sso_enabled": True, "saml_enabled": True}, True, "saml"),
    ],
)
def test_login_method_menu_routes_browser_flows(
    choice: str,
    public: dict[str, object],
    expected_direct: bool,
    expected_provider: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_login(monkeypatch, public=public)
    monkeypatch.setattr(auth, "quick_choice", lambda _prompt, _valid: choice)
    device_login = MagicMock()
    monkeypatch.setattr(auth, "_do_device_flow_login", device_login)

    auth.login(SERVER_URL, None, None, None, False, False)

    device_login.assert_called_once_with(
        SERVER_URL,
        direct_sso=expected_direct,
        provider=expected_provider,
    )


@pytest.mark.parametrize(
    ("sso", "saml", "provider"),
    [(True, False, None), (False, True, "saml")],
)
def test_login_sso_flags_bypass_method_prompt(
    sso: bool,
    saml: bool,
    provider: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_login(monkeypatch, public={"sso_enabled": True, "saml_enabled": True})
    quick_choice = MagicMock()
    device_login = MagicMock()
    monkeypatch.setattr(auth, "quick_choice", quick_choice)
    monkeypatch.setattr(auth, "_do_device_flow_login", device_login)

    auth.login(SERVER_URL, None, None, None, sso, saml)

    quick_choice.assert_not_called()
    device_login.assert_called_once_with(SERVER_URL, direct_sso=True, provider=provider)


def test_login_sso_only_server_forces_browser_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    _prepare_login(monkeypatch, public={"sso_only": True, "sso_enabled": True})
    device_login = MagicMock()
    monkeypatch.setattr(auth, "_do_device_flow_login", device_login)

    auth.login(SERVER_URL, None, None, None, False, False)

    device_login.assert_called_once_with(SERVER_URL, direct_sso=True, provider=None)


def test_login_password_menu_prompts_for_identifier_and_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_login(monkeypatch)
    monkeypatch.setattr(auth, "quick_choice", lambda _prompt, _valid: "1")
    monkeypatch.setattr(auth, "text_input", lambda _prompt: "ada")
    monkeypatch.setattr(auth, "password_input", lambda _prompt: VALID_PASSWORD)
    password_login = MagicMock()
    monkeypatch.setattr(auth, "_do_password_login", password_login)

    auth.login(SERVER_URL, None, None, None, False, False)

    password_login.assert_called_once_with(SERVER_URL, "ada", VALID_PASSWORD)


def test_login_ignores_unavailable_public_config(monkeypatch: pytest.MonkeyPatch) -> None:
    _prepare_login(monkeypatch, public_status=503)
    monkeypatch.setattr(auth, "quick_choice", lambda _prompt, _valid: "1")
    monkeypatch.setattr(auth, "text_input", lambda _prompt: "ada")
    monkeypatch.setattr(auth, "password_input", lambda _prompt: VALID_PASSWORD)
    password_login = MagicMock()
    monkeypatch.setattr(auth, "_do_password_login", password_login)

    auth.login(SERVER_URL, None, None, None, False, False)

    password_login.assert_called_once_with(SERVER_URL, "ada", VALID_PASSWORD)


def test_login_reports_unavailable_saml_before_credential_fallback(
    monkeypatch: pytest.MonkeyPatch,
    printed: list[str],
) -> None:
    _prepare_login(monkeypatch, public={"saml_enabled": False})
    password_login = MagicMock()
    monkeypatch.setattr(auth, "_do_password_login", password_login)

    auth.login(SERVER_URL, "ada", VALID_PASSWORD, None, False, True)

    assert "SAML SSO is not configured" in "\n".join(printed)
    password_login.assert_called_once_with(SERVER_URL, "ada", VALID_PASSWORD)


def test_login_sso_only_uses_single_fallback_after_unavailable_saml(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_login(monkeypatch, public={"sso_only": True, "saml_enabled": False})
    choice = MagicMock(return_value="1")
    device_login = MagicMock()
    monkeypatch.setattr(auth, "quick_choice", choice)
    monkeypatch.setattr(auth, "_do_device_flow_login", device_login)

    auth.login(SERVER_URL, None, None, None, False, True)

    choice.assert_called_once_with("Login method", ["1"])
    device_login.assert_called_once_with(SERVER_URL, direct_sso=True, provider=None)


def test_logout_revokes_remote_session_then_removes_every_local_token(
    monkeypatch: pytest.MonkeyPatch,
    printed: list[str],
) -> None:
    auth.config.CONFIG_FILE.write_text(
        json.dumps(
            {
                "server_url": f"{SERVER_URL}/",
                "access_token": ACCESS_TOKEN,
                "refresh_token": REFRESH_TOKEN,
                "api_key": "legacy-secret",
                "output": "json",
            }
        )
    )
    post = MagicMock(return_value=_response())
    monkeypatch.setattr(auth.httpx, "post", post)

    auth.logout()

    post.assert_called_once_with(
        f"{SERVER_URL}/api/v1/auth/logout",
        json={"refresh_token": REFRESH_TOKEN},
        headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
        timeout=5,
    )
    assert json.loads(auth.config.CONFIG_FILE.read_text()) == {
        "server_url": f"{SERVER_URL}/",
        "output": "json",
    }
    output = "\n".join(printed)
    assert "Logged out" in output
    assert ACCESS_TOKEN not in output
    assert REFRESH_TOKEN not in output
    assert "legacy-secret" not in output


def test_logout_cleans_local_tokens_when_revocation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth.config.CONFIG_FILE.write_text(
        json.dumps({"server_url": SERVER_URL, "access_token": ACCESS_TOKEN, "refresh_token": REFRESH_TOKEN})
    )
    monkeypatch.setattr(auth.httpx, "post", MagicMock(side_effect=httpx.ConnectError("offline")))

    auth.logout()

    assert json.loads(auth.config.CONFIG_FILE.read_text()) == {"server_url": SERVER_URL}


def test_logout_without_config_does_not_contact_server(
    monkeypatch: pytest.MonkeyPatch,
    printed: list[str],
) -> None:
    post = MagicMock()
    monkeypatch.setattr(auth.httpx, "post", post)

    auth.logout()

    post.assert_not_called()
    assert "No config to clear" in "\n".join(printed)


def test_whoami_renders_profile_panel(monkeypatch: pytest.MonkeyPatch) -> None:
    user = _user()
    get = MagicMock(return_value=user)
    panel = object()
    kv_panel = MagicMock(return_value=panel)
    console_print = MagicMock()
    monkeypatch.setattr(auth.client, "get", get)
    monkeypatch.setattr(auth, "status_badge", lambda role: f"badge:{role}")
    monkeypatch.setattr(auth, "kv_panel", kv_panel)
    monkeypatch.setattr(auth.console, "print", console_print)

    auth.whoami("table")

    get.assert_called_once_with("/api/v1/auth/whoami")
    kv_panel.assert_called_once_with(
        "Ada Lovelace",
        [
            ("Username", "@ada"),
            ("Email", "ada@example.test"),
            ("Role", "badge:admin"),
            ("ID", "[dim]user-123[/dim]"),
        ],
    )
    console_print.assert_called_once_with(panel)


def test_whoami_json_delegates_to_safe_json_renderer(monkeypatch: pytest.MonkeyPatch) -> None:
    import observal_cli.render as render

    user = _user(username="")
    output_json = MagicMock()
    monkeypatch.setattr(auth.client, "get", lambda _path: user)
    monkeypatch.setattr(render, "output_json", output_json)

    auth.whoami("json")

    output_json.assert_called_once_with(user)


@pytest.mark.parametrize(
    ("ok", "latency", "expected"),
    [(True, 42.0, "[green]ok"), (True, 500.0, "[yellow]ok"), (True, 1500.0, "[red]ok"), (False, 0.0, "unreachable")],
)
def test_status_reports_health_and_auth_state(
    ok: bool,
    latency: float,
    expected: str,
    monkeypatch: pytest.MonkeyPatch,
    printed: list[str],
) -> None:
    telemetry_buffer = ModuleType("observal_cli.telemetry_buffer")
    telemetry_buffer.stats = lambda: {"total": 0}  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "observal_cli.telemetry_buffer", telemetry_buffer)
    monkeypatch.setattr(auth.config, "load", lambda: {"server_url": SERVER_URL, "access_token": ACCESS_TOKEN})
    monkeypatch.setattr(auth.client, "health", lambda: (ok, latency))

    auth.status()

    output = "\n".join(printed)
    assert SERVER_URL in output
    assert "configured" in output
    assert expected in output


def test_status_reports_pending_outbox_while_offline(
    monkeypatch: pytest.MonkeyPatch,
    printed: list[str],
) -> None:
    telemetry_buffer = ModuleType("observal_cli.telemetry_buffer")
    telemetry_buffer.stats = lambda: {  # type: ignore[attr-defined]
        "total": 3,
        "pending": 2,
        "bytes": 2048,
        "oldest_pending": "2026-01-02 03:04:05",
    }
    monkeypatch.setitem(sys.modules, "observal_cli.telemetry_buffer", telemetry_buffer)
    monkeypatch.setattr(auth.config, "load", lambda: {})
    monkeypatch.setattr(auth.client, "health", lambda: (False, 0.0))

    auth.status()

    output = "\n".join(printed)
    assert "Auth:    [red]not set" in output
    assert "2 pending" in output
    assert "2.0 KiB" in output
    assert "2026-01-02 03:04:05 UTC" in output
    assert "observal doctor" in output


def test_status_ignores_broken_outbox_stats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    telemetry_buffer = ModuleType("observal_cli.telemetry_buffer")

    def broken_stats() -> dict[str, object]:
        raise RuntimeError("corrupt outbox")

    telemetry_buffer.stats = broken_stats  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "observal_cli.telemetry_buffer", telemetry_buffer)
    monkeypatch.setattr(auth.config, "load", lambda: {})
    monkeypatch.setattr(auth.client, "health", lambda: (False, 0.0))

    auth.status()


def test_change_password_requires_saved_session(
    monkeypatch: pytest.MonkeyPatch,
    printed: list[str],
) -> None:
    password_input = MagicMock()
    monkeypatch.setattr(auth.config, "load", lambda: {})
    monkeypatch.setattr(auth, "password_input", password_input)

    with pytest.raises(typer.Exit):
        auth.change_password()

    password_input.assert_not_called()
    assert "Not logged in" in "\n".join(printed)


def test_change_password_sends_current_and_validated_password_with_bearer_token(
    monkeypatch: pytest.MonkeyPatch,
    printed: list[str],
) -> None:
    current_password = "CurrentPassword1!"
    put = MagicMock(return_value=_response())
    monkeypatch.setattr(auth.config, "load", lambda: {"server_url": SERVER_URL, "access_token": ACCESS_TOKEN})
    monkeypatch.setattr(auth, "password_input", MagicMock(side_effect=[current_password, VALID_PASSWORD]))
    monkeypatch.setattr(auth, "_prompt_password", lambda _prompt: VALID_PASSWORD)
    monkeypatch.setattr(auth.httpx, "put", put)

    auth.change_password()

    put.assert_called_once_with(
        f"{SERVER_URL}/api/v1/auth/profile/password",
        json={"current_password": current_password, "new_password": VALID_PASSWORD},
        headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
        timeout=30,
    )
    output = "\n".join(printed)
    assert "Password changed successfully" in output
    assert current_password not in output
    assert VALID_PASSWORD not in output
    assert ACCESS_TOKEN not in output


def test_change_password_rejects_mismatched_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    put = MagicMock()
    monkeypatch.setattr(auth.config, "load", lambda: {"server_url": SERVER_URL, "access_token": ACCESS_TOKEN})
    monkeypatch.setattr(auth, "password_input", MagicMock(side_effect=["CurrentPassword1!", "DifferentPassword2!"]))
    monkeypatch.setattr(auth, "_prompt_password", lambda _prompt: VALID_PASSWORD)
    monkeypatch.setattr(auth.httpx, "put", put)

    with pytest.raises(typer.Exit):
        auth.change_password()

    put.assert_not_called()


@pytest.mark.parametrize(
    ("response", "detail"),
    [
        (_response(400, {"detail": "Current password is incorrect"}), "Current password is incorrect"),
        (_response(500, text="upstream unavailable"), "upstream unavailable"),
    ],
)
def test_change_password_surfaces_server_detail_without_secrets(
    response: httpx.Response,
    detail: str,
    monkeypatch: pytest.MonkeyPatch,
    printed: list[str],
) -> None:
    monkeypatch.setattr(auth.config, "load", lambda: {"server_url": SERVER_URL, "access_token": ACCESS_TOKEN})
    monkeypatch.setattr(auth, "password_input", MagicMock(side_effect=["CurrentPassword1!", VALID_PASSWORD]))
    monkeypatch.setattr(auth, "_prompt_password", lambda _prompt: VALID_PASSWORD)
    monkeypatch.setattr(auth.httpx, "put", lambda *_args, **_kwargs: response)

    with pytest.raises(typer.Exit):
        auth.change_password()

    output = "\n".join(printed)
    assert detail in output
    assert ACCESS_TOKEN not in output
    assert VALID_PASSWORD not in output


def test_set_username_validates_before_request(
    monkeypatch: pytest.MonkeyPatch,
    printed: list[str],
) -> None:
    put = MagicMock()
    monkeypatch.setattr(auth.client, "put", put)

    with pytest.raises(typer.Exit):
        auth.set_username("Invalid Namespace")

    put.assert_not_called()
    assert auth.NAMESPACE_RULE_TEXT in "\n".join(printed)


def test_set_username_updates_profile(monkeypatch: pytest.MonkeyPatch, printed: list[str]) -> None:
    put = MagicMock(return_value={"username": "ada.dev"})
    monkeypatch.setattr(auth.client, "put", put)

    auth.set_username("ada.dev")

    put.assert_called_once_with("/api/v1/auth/profile/username", {"username": "ada.dev"})
    assert "@ada.dev" in "\n".join(printed)


def test_set_username_reports_client_error(monkeypatch: pytest.MonkeyPatch, printed: list[str]) -> None:
    monkeypatch.setattr(auth.client, "put", MagicMock(side_effect=RuntimeError("name already used")))

    with pytest.raises(typer.Exit):
        auth.set_username("ada.dev")

    assert "name already used" in "\n".join(printed)


@pytest.mark.parametrize(("package_result", "expected"), [("1.2.3", "1.2.3"), (RuntimeError("missing"), "dev")])
def test_version_callback_has_installed_and_development_fallbacks(
    package_result: str | Exception,
    expected: str,
    monkeypatch: pytest.MonkeyPatch,
    printed: list[str],
) -> None:
    import importlib.metadata

    version = MagicMock(
        side_effect=package_result if isinstance(package_result, Exception) else None,
        return_value=package_result if isinstance(package_result, str) else None,
    )
    monkeypatch.setattr(importlib.metadata, "version", version)

    auth.version_callback()

    assert expected in "\n".join(printed)


def test_fetch_endpoints_returns_discovery_document(monkeypatch: pytest.MonkeyPatch) -> None:
    get = MagicMock(return_value=_response(200, {"api": SERVER_URL, "web": "https://app.example.test"}))
    monkeypatch.setattr(auth.httpx, "get", get)

    assert auth._fetch_endpoints(f"{SERVER_URL}/") == {
        "api": SERVER_URL,
        "web": "https://app.example.test",
    }
    get.assert_called_once_with(f"{SERVER_URL}/api/v1/config/endpoints", timeout=5)


def test_fetch_endpoints_fails_closed_for_404(monkeypatch: pytest.MonkeyPatch) -> None:
    get = MagicMock(return_value=_response(404, {}))
    monkeypatch.setattr(auth.httpx, "get", get)

    assert auth._fetch_endpoints(SERVER_URL) == {}


def test_fetch_endpoints_fails_closed_when_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    get = MagicMock(side_effect=RuntimeError("offline"))
    monkeypatch.setattr(auth.httpx, "get", get)

    assert auth._fetch_endpoints(SERVER_URL) == {}


def test_password_login_saves_tokens_and_profile(monkeypatch: pytest.MonkeyPatch, printed: list[str]) -> None:
    response = MagicMock()
    response.json.return_value = _login_payload()
    post = MagicMock(return_value=response)
    save = MagicMock()
    fetch_endpoints = MagicMock(return_value={"web": "https://app.example.test"})
    setup = MagicMock()
    monkeypatch.setattr(auth.httpx, "post", post)
    monkeypatch.setattr(auth, "_fetch_endpoints", fetch_endpoints)
    monkeypatch.setattr(auth.config, "save", save)
    monkeypatch.setattr(auth, "_post_login_setup", setup)

    auth._do_password_login(SERVER_URL, "ada", VALID_PASSWORD)

    post.assert_called_once_with(
        f"{SERVER_URL}/api/v1/auth/login",
        json={"email": "ada", "password": VALID_PASSWORD},
        timeout=30,
    )
    response.raise_for_status.assert_called_once_with()
    fetch_endpoints.assert_called_once_with(SERVER_URL)
    save.assert_called_once_with(
        {
            "server_url": SERVER_URL,
            "access_token": ACCESS_TOKEN,
            "refresh_token": REFRESH_TOKEN,
            "user_id": "user-123",
            "user_name": "Ada Lovelace",
            "username": "ada",
            "web_url": "https://app.example.test",
        }
    )
    setup.assert_called_once_with()
    output = "\n".join(printed)
    assert "Logged in as Ada Lovelace" in output
    assert VALID_PASSWORD not in output
    assert ACCESS_TOKEN not in output


def test_password_login_completes_mandatory_password_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    login_response = _response(200, _login_payload(must_change_password=True))
    changed_response = _response(200, {})
    post = MagicMock(return_value=login_response)
    put = MagicMock(return_value=changed_response)
    save = MagicMock()
    monkeypatch.setattr(auth.httpx, "post", post)
    monkeypatch.setattr(auth.httpx, "put", put)
    monkeypatch.setattr(auth, "password_input", MagicMock(side_effect=[VALID_PASSWORD, VALID_PASSWORD]))
    monkeypatch.setattr(auth, "_fetch_endpoints", lambda _url: {})
    monkeypatch.setattr(auth.config, "save", save)
    monkeypatch.setattr(auth, "_post_login_setup", MagicMock())

    auth._do_password_login(SERVER_URL, "ada", "Temporary1!")

    put.assert_called_once_with(
        f"{SERVER_URL}/api/v1/auth/profile/password",
        json={"current_password": "Temporary1!", "new_password": VALID_PASSWORD},
        headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
        timeout=30,
    )
    assert "web_url" not in save.call_args.args[0]


@pytest.mark.parametrize(
    ("new_password", "confirmation", "expected"),
    [
        ("LongEnough1!", "Different1!", "Passwords do not match"),
        ("Short1!", "Short1!", "at least 8 characters"),
    ],
)
def test_password_login_rejects_invalid_mandatory_password_change(
    new_password: str,
    confirmation: str,
    expected: str,
    monkeypatch: pytest.MonkeyPatch,
    printed: list[str],
) -> None:
    monkeypatch.setattr(
        auth.httpx, "post", lambda *_args, **_kwargs: _response(200, _login_payload(must_change_password=True))
    )
    put = MagicMock()
    save = MagicMock()
    monkeypatch.setattr(auth.httpx, "put", put)
    monkeypatch.setattr(auth, "password_input", MagicMock(side_effect=[new_password, confirmation]))
    monkeypatch.setattr(auth.config, "save", save)

    with pytest.raises(typer.Exit):
        auth._do_password_login(SERVER_URL, "ada", "Temporary1!")

    put.assert_not_called()
    save.assert_not_called()
    assert expected in "\n".join(printed)


@pytest.mark.parametrize(
    ("response", "detail"),
    [
        (_response(401, {"detail": "Invalid credentials"}), "Invalid credentials"),
        (_response(502, text="bad gateway"), "bad gateway"),
    ],
)
def test_password_login_surfaces_http_errors_without_saving(
    response: httpx.Response,
    detail: str,
    monkeypatch: pytest.MonkeyPatch,
    printed: list[str],
) -> None:
    save = MagicMock()
    monkeypatch.setattr(auth.httpx, "post", lambda *_args, **_kwargs: response)
    monkeypatch.setattr(auth.config, "save", save)

    with pytest.raises(typer.Exit):
        auth._do_password_login(SERVER_URL, "ada", VALID_PASSWORD)

    save.assert_not_called()
    assert detail in "\n".join(printed)
    assert VALID_PASSWORD not in "\n".join(printed)


def test_device_flow_rewrites_local_verification_url_and_saves_authorized_session(
    monkeypatch: pytest.MonkeyPatch,
    printed: list[str],
    device_runtime: tuple[_Clock, MagicMock],
) -> None:
    clock, browser_open = device_runtime
    authorize = _response(200, _device_authorization())
    token = _response(200, _login_payload())
    post = MagicMock(side_effect=[authorize, token])
    save = MagicMock()
    setup = MagicMock()
    monkeypatch.setattr(auth.httpx, "post", post)
    monkeypatch.setattr(auth, "_fetch_endpoints", lambda _url: {"web": "https://app.example.test"})
    monkeypatch.setattr(auth.config, "save", save)
    monkeypatch.setattr(auth, "_post_login_setup", setup)

    auth._do_device_flow_login(SERVER_URL, direct_sso=True, provider="oidc")

    assert post.call_args_list == [
        call(
            f"{SERVER_URL}/api/v1/auth/device/authorize",
            json={"sso": True, "provider": "oidc"},
            timeout=10,
        ),
        call(
            f"{SERVER_URL}/api/v1/auth/device/token",
            json={
                "device_code": "private-device-code",
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
            timeout=10,
        ),
    ]
    browser_open.assert_called_once_with(f"{SERVER_URL}/device?code=ABCD-EFGH")
    assert clock.sleeps == [1]
    save.assert_called_once_with(
        {
            "server_url": SERVER_URL,
            "access_token": ACCESS_TOKEN,
            "refresh_token": REFRESH_TOKEN,
            "user_id": "user-123",
            "user_name": "Ada Lovelace",
            "username": "ada",
            "web_url": "https://app.example.test",
        }
    )
    setup.assert_called_once_with()
    output = "\n".join(printed)
    assert "ABCD-EFGH" in output
    assert "private-device-code" not in output
    assert ACCESS_TOKEN not in output
    assert REFRESH_TOKEN not in output


def test_device_flow_keeps_local_url_for_local_server(
    monkeypatch: pytest.MonkeyPatch,
    device_runtime: tuple[_Clock, MagicMock],
) -> None:
    _, browser_open = device_runtime
    local_server = "http://localhost:8080"
    post = MagicMock(
        side_effect=[
            _response(200, _device_authorization()),
            _response(400, {"error": "access_denied"}),
        ]
    )
    monkeypatch.setattr(auth.httpx, "post", post)

    with pytest.raises(typer.Exit):
        auth._do_device_flow_login(local_server)

    browser_open.assert_called_once_with("http://localhost/device?code=ABCD-EFGH")


def test_device_flow_reports_authorization_request_error(
    monkeypatch: pytest.MonkeyPatch,
    printed: list[str],
) -> None:
    monkeypatch.setattr(auth.httpx, "post", lambda *_args, **_kwargs: _response(503, text="unavailable"))

    with pytest.raises(typer.Exit):
        auth._do_device_flow_login(SERVER_URL)

    output = "\n".join(printed)
    assert "Device authorization failed (503)" in output
    assert "unavailable" in output


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        ("expired_token", "Device code expired"),
        ("access_denied", "Authorization was denied"),
        ("server_error", "error: server_error"),
    ],
)
def test_device_flow_stops_on_terminal_poll_error(
    error: str,
    expected: str,
    monkeypatch: pytest.MonkeyPatch,
    printed: list[str],
    device_runtime: tuple[_Clock, MagicMock],
) -> None:
    monkeypatch.setattr(
        auth.httpx,
        "post",
        MagicMock(
            side_effect=[
                _response(200, _device_authorization()),
                _response(400, {"error": error}),
            ]
        ),
    )

    with pytest.raises(typer.Exit):
        auth._do_device_flow_login(SERVER_URL)

    assert expected in "\n".join(printed)


def test_device_flow_polls_pending_until_success(
    monkeypatch: pytest.MonkeyPatch,
    device_runtime: tuple[_Clock, MagicMock],
) -> None:
    save = MagicMock()
    monkeypatch.setattr(
        auth.httpx,
        "post",
        MagicMock(
            side_effect=[
                _response(200, _device_authorization()),
                _response(428, {"error": "authorization_pending"}),
                _response(200, _login_payload()),
            ]
        ),
    )
    monkeypatch.setattr(auth, "_fetch_endpoints", lambda _url: {})
    monkeypatch.setattr(auth.config, "save", save)
    monkeypatch.setattr(auth, "_post_login_setup", MagicMock())

    auth._do_device_flow_login(SERVER_URL)

    assert save.call_count == 1
    assert device_runtime[0].sleeps == [1, 1]


def test_device_flow_retries_network_errors_until_timeout(
    monkeypatch: pytest.MonkeyPatch,
    printed: list[str],
    device_runtime: tuple[_Clock, MagicMock],
) -> None:
    request = httpx.Request("POST", SERVER_URL)
    monkeypatch.setattr(
        auth.httpx,
        "post",
        MagicMock(
            side_effect=[
                _response(200, _device_authorization(expires_in=2)),
                httpx.ConnectError("offline", request=request),
                httpx.ConnectError("offline", request=request),
            ]
        ),
    )

    with pytest.raises(typer.Exit):
        auth._do_device_flow_login(SERVER_URL)

    assert device_runtime[0].sleeps == [1, 1]
    assert "Authorization timed out" in "\n".join(printed)


@pytest.mark.parametrize(
    ("system_name", "wsl_result", "expected_program"),
    [
        ("Darwin", None, "open"),
        ("Linux", 0, "powershell.exe"),
        ("Linux", 1, "xdg-open"),
    ],
)
def test_device_flow_uses_platform_browser_launcher(
    system_name: str,
    wsl_result: int | None,
    expected_program: str,
    monkeypatch: pytest.MonkeyPatch,
    device_runtime: tuple[_Clock, MagicMock],
) -> None:
    monkeypatch.setattr(platform, "system", lambda: system_name)
    popen = MagicMock()
    monkeypatch.setattr(subprocess, "Popen", popen)
    if wsl_result is not None:
        monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(returncode=wsl_result))
    monkeypatch.setattr(
        auth.httpx,
        "post",
        MagicMock(
            side_effect=[
                _response(200, _device_authorization()),
                _response(400, {"error": "expired_token"}),
            ]
        ),
    )

    with pytest.raises(typer.Exit):
        auth._do_device_flow_login(SERVER_URL)

    assert popen.call_args.args[0][0] == expected_program
    launched = " ".join(popen.call_args.args[0])
    assert f"{SERVER_URL}/device?code=ABCD-EFGH" in launched


def test_device_flow_browser_failure_keeps_manual_flow_available(
    monkeypatch: pytest.MonkeyPatch,
    printed: list[str],
    device_runtime: tuple[_Clock, MagicMock],
) -> None:
    device_runtime[1].side_effect = RuntimeError("no browser")
    monkeypatch.setattr(
        auth.httpx,
        "post",
        MagicMock(
            side_effect=[
                _response(200, _device_authorization()),
                _response(400, {"error": "access_denied"}),
            ]
        ),
    )

    with pytest.raises(typer.Exit):
        auth._do_device_flow_login(SERVER_URL)

    assert "Please open the URL manually" in "\n".join(printed)


@pytest.mark.parametrize(
    ("access_token", "refresh_token", "expected_access", "expected_refresh"),
    [
        ("abcdefghijklmno", "123456789012345", "abcdefgh...lmno", "12345678...2345"),
        ("short", "tiny", "***", "***"),
    ],
)
def test_config_show_masks_tokens_and_removes_legacy_key(
    access_token: str,
    refresh_token: str,
    expected_access: str,
    expected_refresh: str,
    config_cli: typer.Typer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = {
        "server_url": SERVER_URL,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "api_key": "legacy-secret",
    }
    print_json = MagicMock()
    monkeypatch.setattr(auth.config, "load", lambda: stored)
    monkeypatch.setattr(auth.console, "print_json", print_json)

    result = CliRunner().invoke(config_cli, ["config", "show"])

    assert result.exit_code == 0, result.output
    rendered = json.loads(print_json.call_args.args[0])
    assert rendered == {
        "server_url": SERVER_URL,
        "access_token": expected_access,
        "refresh_token": expected_refresh,
    }
    assert stored["access_token"] == access_token
    assert stored["refresh_token"] == refresh_token
    assert stored["api_key"] == "legacy-secret"


@pytest.mark.parametrize(
    ("key", "value", "saved_value"),
    [("color", "YES", True), ("color", "no", False), ("output", "json", "json")],
)
def test_config_set_normalizes_boolean_values(
    key: str,
    value: str,
    saved_value: object,
    config_cli: typer.Typer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save = MagicMock()
    monkeypatch.setattr(auth.config, "save", save)

    result = CliRunner().invoke(config_cli, ["config", "set", key, value])

    assert result.exit_code == 0, result.output
    save.assert_called_once_with({key: saved_value})


def test_config_set_server_migrates_previous_lockfile(
    config_cli: typer.Typer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import observal_cli.lockfile as lockfile

    migrate = MagicMock()
    save = MagicMock()
    monkeypatch.setattr(auth.config, "load", lambda: {"server_url": "https://old.example.test"})
    monkeypatch.setattr(auth.config, "save", save)
    monkeypatch.setattr(lockfile, "migrate_lockfile_v1", migrate)

    result = CliRunner().invoke(config_cli, ["config", "set", "server_url", SERVER_URL])

    assert result.exit_code == 0, result.output
    migrate.assert_called_once_with("https://old.example.test")
    save.assert_called_once_with({"server_url": SERVER_URL})


def test_config_path_prints_config_location(
    config_cli: typer.Typer,
    printed: list[str],
) -> None:
    result = CliRunner().invoke(config_cli, ["config", "path"])

    assert result.exit_code == 0, result.output
    assert str(auth.config.CONFIG_FILE) in printed


def test_config_alias_sets_and_removes_mapping(
    config_cli: typer.Typer,
    monkeypatch: pytest.MonkeyPatch,
    printed: list[str],
) -> None:
    aliases = {"old": "old-id"}
    save_aliases = MagicMock()
    monkeypatch.setattr(auth.config, "load_aliases", lambda: dict(aliases))
    monkeypatch.setattr(auth.config, "save_aliases", save_aliases)

    set_result = CliRunner().invoke(config_cli, ["config", "alias", "agent", "agent-id"])
    remove_result = CliRunner().invoke(config_cli, ["config", "alias", "old"])

    assert set_result.exit_code == 0, set_result.output
    assert remove_result.exit_code == 0, remove_result.output
    assert save_aliases.call_args_list == [
        call({"old": "old-id", "agent": "agent-id"}),
        call({}),
    ]
    assert any("@agent" in message for message in printed)
    assert any("Removed @old" in message for message in printed)


def test_config_alias_reports_missing_mapping(
    config_cli: typer.Typer,
    monkeypatch: pytest.MonkeyPatch,
    printed: list[str],
) -> None:
    save_aliases = MagicMock()
    monkeypatch.setattr(auth.config, "load_aliases", lambda: {})
    monkeypatch.setattr(auth.config, "save_aliases", save_aliases)

    result = CliRunner().invoke(config_cli, ["config", "alias", "missing"])

    assert result.exit_code == 0, result.output
    save_aliases.assert_called_once_with({})
    assert any("not found" in message for message in printed)


@pytest.mark.parametrize("aliases", [{}, {"zeta": "2", "alpha": "1"}])
def test_config_aliases_lists_sorted_or_empty_state(
    aliases: dict[str, str],
    config_cli: typer.Typer,
    monkeypatch: pytest.MonkeyPatch,
    printed: list[str],
) -> None:
    monkeypatch.setattr(auth.config, "load_aliases", lambda: aliases)

    result = CliRunner().invoke(config_cli, ["config", "aliases"])

    assert result.exit_code == 0, result.output
    if aliases:
        alpha = next(index for index, message in enumerate(printed) if "@alpha" in message)
        zeta = next(index for index, message in enumerate(printed) if "@zeta" in message)
        assert alpha < zeta
    else:
        assert any("No aliases set" in message for message in printed)


def test_post_login_setup_installs_skills_snapshots_and_runs_doctor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import observal_cli.cmd_doctor as cmd_doctor

    install = MagicMock()
    snapshot = MagicMock()
    doctor = MagicMock()
    monkeypatch.setattr(auth, "_install_observal_skill", install)
    monkeypatch.setattr(auth, "_generate_initial_layer_snapshot", snapshot)
    monkeypatch.setattr(cmd_doctor, "doctor", doctor)

    auth._post_login_setup()

    install.assert_called_once_with()
    snapshot.assert_called_once_with()
    assert doctor.call_args.kwargs["yes"] is False
    assert doctor.call_args.kwargs["ctx"].invoked_subcommand is None


@pytest.mark.parametrize("error", [typer.Exit(1), RuntimeError("doctor unavailable")])
def test_post_login_setup_contains_doctor_failures(
    error: Exception,
    monkeypatch: pytest.MonkeyPatch,
    printed: list[str],
) -> None:
    import observal_cli.cmd_doctor as cmd_doctor

    monkeypatch.setattr(auth, "_install_observal_skill", MagicMock())
    monkeypatch.setattr(auth, "_generate_initial_layer_snapshot", MagicMock())
    monkeypatch.setattr(cmd_doctor, "doctor", MagicMock(side_effect=error))

    auth._post_login_setup()

    if type(error) is RuntimeError:
        assert "Could not run doctor" in "\n".join(printed)
        assert "manually" in "\n".join(printed)


def test_post_auth_onboarding_scans_detected_harnesses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    printed: list[str],
) -> None:
    import observal_cli.harness as harness

    for directory in (".claude", ".kiro", ".cursor"):
        (tmp_path / directory).mkdir()
    results = {
        "claude-code": SimpleNamespace(agents=[object()], mcps=[]),
        "kiro": SimpleNamespace(agents=[object(), object()], mcps=[object(), object()]),
    }

    def get_adapter(name: str) -> SimpleNamespace:
        if name == "cursor":
            raise KeyError(name)
        return SimpleNamespace(scan_home=MagicMock(return_value=results[name]))

    ensure_loaded = MagicMock()
    monkeypatch.setattr(auth.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(harness, "ensure_loaded", ensure_loaded)
    monkeypatch.setattr(harness, "get_adapter", get_adapter)

    auth._post_auth_onboarding()

    assert ensure_loaded.call_count == 3
    output = "\n".join(printed)
    assert "Detected local harness configs" in output
    assert "1 agent found" in output
    assert "2 agents, 2 MCPs found" in output
    assert "all-harnesses" in output


def test_post_auth_onboarding_is_silent_when_none_found(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    printed: list[str],
) -> None:
    monkeypatch.setattr(auth.Path, "home", lambda: tmp_path)

    auth._post_auth_onboarding()

    assert printed == []


def test_post_auth_onboarding_contains_detection_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth.Path, "home", MagicMock(side_effect=OSError("home unavailable")))

    auth._post_auth_onboarding()


def test_snapshot_generation_is_best_effort(monkeypatch: pytest.MonkeyPatch) -> None:
    import observal_cli.layer as layer

    snapshot = MagicMock(side_effect=[None, RuntimeError("scan failed")])
    monkeypatch.setattr(layer, "ensure_local_snapshot", snapshot)

    auth._generate_initial_layer_snapshot()
    auth._generate_initial_layer_snapshot()

    assert snapshot.call_count == 2


def test_install_observal_skill_delegates_to_installer(monkeypatch: pytest.MonkeyPatch) -> None:
    import observal_cli.skill_installer as skill_installer

    install = MagicMock()
    monkeypatch.setattr(skill_installer, "install_observal_skill", install)

    auth._install_observal_skill()

    install.assert_called_once_with()


def test_run_doctor_patch_uses_isolated_subprocess_environment(
    monkeypatch: pytest.MonkeyPatch,
    printed: list[str],
) -> None:
    completed = SimpleNamespace(returncode=1, stdout="doctor output\n", stderr="doctor warning\n")
    run = MagicMock(return_value=completed)
    monkeypatch.setattr(subprocess, "run", run)

    auth._run_doctor_patch("cursor")

    command = run.call_args.args[0]
    assert command[:4] == [sys.executable, "-m", "observal_cli.main", "doctor"]
    assert command[-1] == "cursor"
    assert run.call_args.kwargs["capture_output"] is True
    assert run.call_args.kwargs["timeout"] == 30
    assert run.call_args.kwargs["env"]["PYTHONIOENCODING"] == "utf-8"
    assert printed == ["doctor output", "[yellow]doctor warning[/yellow]"]


def test_run_doctor_patch_reports_subprocess_failure(
    monkeypatch: pytest.MonkeyPatch,
    printed: list[str],
) -> None:
    monkeypatch.setattr(subprocess, "run", MagicMock(side_effect=OSError("cannot execute")))

    auth._run_doctor_patch("cursor")

    output = "\n".join(printed)
    assert "cannot execute" in output
    assert "manually" in output


@pytest.mark.parametrize(
    ("function_name", "directory", "harness_name"),
    [
        ("_configure_cursor", ".cursor", "cursor"),
        ("_configure_kiro", ".kiro", "kiro"),
        ("_configure_codex", ".codex", "codex"),
    ],
)
def test_basic_harness_configurators_patch_detected_installation(
    function_name: str,
    directory: str,
    harness_name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / directory).mkdir()
    patch_doctor = MagicMock()
    monkeypatch.setattr(auth.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(auth.shutil, "which", lambda _name: None)
    monkeypatch.setattr(auth.typer, "confirm", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(auth, "_run_doctor_patch", patch_doctor)

    getattr(auth, function_name)(SERVER_URL)

    patch_doctor.assert_called_once_with(harness_name)


@pytest.mark.parametrize(
    "function_name",
    [
        "_configure_cursor",
        "_configure_kiro",
        "_configure_codex",
        "_configure_copilot",
        "_configure_copilot_cli",
        "_configure_opencode",
        "_configure_claude_code",
    ],
)
def test_harness_configurators_respect_decline(
    function_name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = {
        "_configure_cursor": ".cursor",
        "_configure_kiro": ".kiro",
        "_configure_codex": ".codex",
        "_configure_claude_code": ".claude",
    }.get(function_name)
    if directory:
        (tmp_path / directory).mkdir()
    if function_name == "_configure_copilot":
        extension = tmp_path / ".vscode" / "extensions" / "github.copilot-1.0.0"
        extension.mkdir(parents=True)
    if function_name == "_configure_opencode":
        binary = tmp_path / ".opencode" / "bin" / "opencode"
        binary.parent.mkdir(parents=True)
        binary.write_text("")

    patch_doctor = MagicMock()
    monkeypatch.setattr(auth.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(
        auth.shutil,
        "which",
        lambda name: "/bin/copilot" if function_name == "_configure_copilot_cli" and name == "copilot" else None,
    )
    monkeypatch.setattr(auth.typer, "confirm", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(auth, "_run_doctor_patch", patch_doctor)

    function = getattr(auth, function_name)
    if function_name == "_configure_claude_code":
        function(SERVER_URL, ACCESS_TOKEN)
    else:
        function(SERVER_URL)

    patch_doctor.assert_not_called()


@pytest.mark.parametrize(
    "function_name",
    [
        "_configure_cursor",
        "_configure_kiro",
        "_configure_codex",
        "_configure_copilot",
        "_configure_copilot_cli",
        "_configure_opencode",
        "_configure_claude_code",
    ],
)
def test_harness_configurators_skip_missing_installation(
    function_name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    confirm = MagicMock()
    monkeypatch.setattr(auth.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(auth.shutil, "which", lambda _name: None)
    monkeypatch.setattr(auth.typer, "confirm", confirm)

    function = getattr(auth, function_name)
    if function_name == "_configure_claude_code":
        function(SERVER_URL, ACCESS_TOKEN)
    else:
        function(SERVER_URL)

    confirm.assert_not_called()


@pytest.mark.parametrize("function_name", ["_configure_cursor", "_configure_kiro", "_configure_codex"])
def test_basic_harness_configurators_report_detection_errors(
    function_name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    printed: list[str],
) -> None:
    directory = {"_configure_cursor": ".cursor", "_configure_kiro": ".kiro", "_configure_codex": ".codex"}[
        function_name
    ]
    (tmp_path / directory).mkdir()
    monkeypatch.setattr(auth.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(auth.typer, "confirm", MagicMock(side_effect=RuntimeError("prompt failed")))

    getattr(auth, function_name)(SERVER_URL)

    output = "\n".join(printed)
    assert "prompt failed" in output
    assert "manually" in output


def test_configure_copilot_requires_actual_extension(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extensions = tmp_path / ".vscode" / "extensions"
    extensions.mkdir(parents=True)
    (extensions / "github.copilot-1.0.0").mkdir()
    patch_doctor = MagicMock()
    monkeypatch.setattr(auth.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(auth.typer, "confirm", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(auth, "_run_doctor_patch", patch_doctor)

    auth._configure_copilot(SERVER_URL)

    patch_doctor.assert_called_once_with("copilot")


def test_configure_copilot_skips_vscode_without_extension(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".vscode" / "extensions").mkdir(parents=True)
    confirm = MagicMock()
    monkeypatch.setattr(auth.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(auth.typer, "confirm", confirm)

    auth._configure_copilot(SERVER_URL)

    confirm.assert_not_called()


def test_configure_copilot_cli_uses_binary_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_doctor = MagicMock()
    monkeypatch.setattr(auth.shutil, "which", lambda name: "/bin/copilot" if name == "copilot" else None)
    monkeypatch.setattr(auth.typer, "confirm", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(auth, "_run_doctor_patch", patch_doctor)

    auth._configure_copilot_cli(SERVER_URL)

    patch_doctor.assert_called_once_with("copilot-cli")


def test_configure_opencode_detects_off_path_binary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binary = tmp_path / ".opencode" / "bin" / "opencode"
    binary.parent.mkdir(parents=True)
    binary.write_text("")
    patch_doctor = MagicMock()
    monkeypatch.setattr(auth.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(auth.shutil, "which", lambda _name: None)
    monkeypatch.setattr(auth.typer, "confirm", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(auth, "_run_doctor_patch", patch_doctor)

    auth._configure_opencode(SERVER_URL)

    patch_doctor.assert_called_once_with("opencode")


def test_configure_claude_code_stores_hooks_token_before_patching(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".claude").mkdir()
    save = MagicMock()
    patch_doctor = MagicMock()
    monkeypatch.setattr(auth.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(auth.shutil, "which", lambda _name: None)
    monkeypatch.setattr(auth.typer, "confirm", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(auth, "_fetch_hooks_token", lambda _url, _token: "hooks-token")
    monkeypatch.setattr(auth.config, "load", lambda: {"server_url": SERVER_URL})
    monkeypatch.setattr(auth.config, "save", save)
    monkeypatch.setattr(auth, "_run_doctor_patch", patch_doctor)

    auth._configure_claude_code(SERVER_URL, ACCESS_TOKEN)

    save.assert_called_once_with({"server_url": SERVER_URL, "api_key": "hooks-token"})
    patch_doctor.assert_called_once_with("claude-code")


@pytest.mark.parametrize("function_name", ["_configure_copilot", "_configure_copilot_cli", "_configure_opencode"])
def test_silent_harness_configurators_contain_prompt_errors(
    function_name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if function_name == "_configure_copilot":
        (tmp_path / ".vscode" / "extensions" / "github.copilot-1.0.0").mkdir(parents=True)
    if function_name == "_configure_opencode":
        binary = tmp_path / ".opencode" / "bin" / "opencode"
        binary.parent.mkdir(parents=True)
        binary.write_text("")
    monkeypatch.setattr(auth.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(
        auth.shutil,
        "which",
        lambda name: "/bin/copilot" if function_name == "_configure_copilot_cli" and name == "copilot" else None,
    )
    monkeypatch.setattr(auth.typer, "confirm", MagicMock(side_effect=RuntimeError("prompt failed")))

    getattr(auth, function_name)(SERVER_URL)


def test_configure_claude_code_reports_prompt_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    printed: list[str],
) -> None:
    (tmp_path / ".claude").mkdir()
    monkeypatch.setattr(auth.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(auth.typer, "confirm", MagicMock(side_effect=RuntimeError("prompt failed")))

    auth._configure_claude_code(SERVER_URL, ACCESS_TOKEN)

    output = "\n".join(printed)
    assert "prompt failed" in output
    assert "manually" in output


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (_response(200, {"access_token": "hooks-token"}), "hooks-token"),
        (_response(200, {}), ACCESS_TOKEN),
        (_response(503, {}), ACCESS_TOKEN),
        (httpx.ConnectError("offline"), ACCESS_TOKEN),
    ],
)
def test_fetch_hooks_token_uses_authenticated_endpoint_with_safe_fallback(
    result: object,
    expected: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post = MagicMock(side_effect=result if isinstance(result, Exception) else None)
    if not isinstance(result, Exception):
        post.return_value = result
    monkeypatch.setattr(auth.httpx, "post", post)

    assert auth._fetch_hooks_token(f"{SERVER_URL}/", ACCESS_TOKEN) == expected
    post.assert_called_once_with(
        f"{SERVER_URL}/api/v1/auth/hooks-token",
        headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
        timeout=10,
    )
