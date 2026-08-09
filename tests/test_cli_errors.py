# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Tests for the CLI HTTP client and its user-facing failures."""

from __future__ import annotations

import importlib.metadata
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import click
import httpx
import pytest
import typer

from observal_cli import client

_MISSING = object()


def _response(
    status: int = 200,
    *,
    data: object = _MISSING,
    text: str | None = None,
    headers: dict[str, str] | None = None,
    url: str = "https://registry.example.test/api/v1/items",
) -> httpx.Response:
    kwargs: dict[str, object] = {
        "headers": headers or {},
        "request": httpx.Request("GET", url),
    }
    if data is not _MISSING:
        kwargs["json"] = data
    elif text is not None:
        kwargs["text"] = text
    return httpx.Response(status, **kwargs)


@pytest.fixture(autouse=True)
def isolated_client(monkeypatch):
    """Block live I/O and make client timing and logging deterministic."""

    def unexpected_http(*_args, **_kwargs):
        raise AssertionError("unexpected live HTTP request")

    for method in ("get", "post", "put", "patch", "delete"):
        monkeypatch.setattr(client.httpx, method, unexpected_http)

    clock = SimpleNamespace(
        monotonic=MagicMock(return_value=100.0),
        sleep=MagicMock(side_effect=AssertionError("unexpected real retry delay")),
    )
    monkeypatch.setattr(client, "time", clock)
    monkeypatch.setattr(client, "optic", MagicMock())
    monkeypatch.setattr(client, "logger", MagicMock())
    monkeypatch.setattr(client, "_version_enforced", False)
    monkeypatch.setattr(client, "_server_version_cache", None)
    return clock


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


def test_cli_version_header_uses_installed_version(monkeypatch):
    monkeypatch.setattr(importlib.metadata, "version", lambda package: "1.2.3")

    assert client._get_cli_version() == "1.2.3"


def test_cli_version_header_falls_back_for_uninstalled_package(monkeypatch):
    def missing(_package):
        raise importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(importlib.metadata, "version", missing)

    assert client._get_cli_version() == "0.0.0"


def test_client_builds_bearer_and_version_headers(monkeypatch):
    get_config = MagicMock(
        return_value={
            "server_url": "https://registry.example.test/",
            "access_token": "fake-access-token",
        }
    )
    enforce = MagicMock()
    monkeypatch.setattr(client.config, "get_or_exit", get_config)
    monkeypatch.setattr(client, "_get_cli_version", lambda: "2.4.1")
    monkeypatch.setattr(client, "_enforce_version_once", enforce)

    base_url, headers = client._client()

    assert base_url == "https://registry.example.test"
    assert headers == {
        "Authorization": "Bearer fake-access-token",
        "X-Observal-CLI-Version": "2.4.1",
    }
    get_config.assert_called_once_with()
    enforce.assert_called_once_with(base_url)


def test_request_requires_authenticated_configuration(monkeypatch):
    get_config = MagicMock(side_effect=typer.Exit(1))
    enforce = MagicMock()
    monkeypatch.setattr(client.config, "get_or_exit", get_config)
    monkeypatch.setattr(client, "_enforce_version_once", enforce)

    with pytest.raises(typer.Exit) as error:
        client.get("/api/v1/items")

    assert error.value.exit_code == 1
    get_config.assert_called_once_with()
    enforce.assert_not_called()


def test_version_enforcement_runs_once(monkeypatch):
    from observal_cli import version_check

    check = MagicMock()
    monkeypatch.setattr(version_check, "check_version_compatibility", check)
    monkeypatch.setattr(sys, "argv", ["observal", "registry", "mcp", "list"])

    client._enforce_version_once("https://one.example.test")
    client._enforce_version_once("https://two.example.test")

    check.assert_called_once_with("https://one.example.test")


@pytest.mark.parametrize(
    "argv",
    [
        ["observal", "self", "upgrade"],
        ["observal", "-v", "server", "status"],
    ],
)
def test_version_enforcement_exempts_recovery_commands(monkeypatch, argv):
    from observal_cli import version_check

    check = MagicMock()
    monkeypatch.setattr(version_check, "check_version_compatibility", check)
    monkeypatch.setattr(sys, "argv", argv)

    client._enforce_version_once("https://registry.example.test")

    check.assert_not_called()
    assert client._version_enforced is True


def test_version_enforcement_without_subcommand_still_checks(monkeypatch):
    from observal_cli import version_check

    check = MagicMock()
    monkeypatch.setattr(version_check, "check_version_compatibility", check)
    monkeypatch.setattr(sys, "argv", ["observal", "-v"])

    client._enforce_version_once("https://registry.example.test")

    check.assert_called_once_with("https://registry.example.test")


@pytest.mark.parametrize(
    ("status", "data", "text", "headers", "path", "expected", "excluded"),
    [
        pytest.param(
            401,
            {"detail": "fake-sensitive-detail"},
            None,
            {},
            "/api/v1/items",
            ("Authentication failed", "observal auth login"),
            ("fake-sensitive-detail",),
            id="authentication",
        ),
        pytest.param(
            403,
            {"detail": "Team membership required"},
            None,
            {},
            "/api/v1/items",
            ("Permission denied", "Team membership required"),
            (),
            id="permission-structured-json",
        ),
        pytest.param(
            403,
            {"detail": ""},
            None,
            {},
            "/api/v1/items",
            ("You do not have permission",),
            (),
            id="permission-without-detail",
        ),
        pytest.param(
            404,
            {"detail": "missing"},
            None,
            {},
            "/api/v1/sandboxes/id",
            ("Not found", "observal registry sandbox list"),
            (),
            id="sandbox-not-found",
        ),
        pytest.param(
            404,
            {"detail": "missing"},
            None,
            {},
            "/api/v1/agents/id",
            ("Not found", "observal agent list"),
            (),
            id="agent-not-found",
        ),
        pytest.param(
            404,
            {"detail": "missing"},
            None,
            {},
            "/api/v1/insights/agents/id",
            ("Not found", "observal agent list"),
            (),
            id="agent-insight-not-found",
        ),
        pytest.param(
            404,
            {"detail": "missing"},
            None,
            {},
            "/api/v1/info/id",
            ("Not found", "observal registry info list"),
            (),
            id="unpluralized-resource-not-found",
        ),
        pytest.param(
            426,
            {"detail": "Install the matching CLI"},
            None,
            {},
            "/api/v1/items",
            ("Version mismatch", "Install the matching CLI"),
            (),
            id="version-mismatch",
        ),
        pytest.param(
            426,
            {"detail": ""},
            None,
            {},
            "/api/v1/items",
            ("Version mismatch",),
            (),
            id="version-mismatch-without-detail",
        ),
        pytest.param(
            429,
            _MISSING,
            "slow down",
            {"content-type": "text/plain", "Retry-After": "12 seconds"},
            "/api/v1/items",
            ("Rate limited", "Try again in 12 seconds"),
            (),
            id="rate-limit-text",
        ),
        pytest.param(
            503,
            _MISSING,
            "unavailable",
            {"content-type": "text/plain"},
            "/api/v1/items",
            ("Server error 503", "observal doctor"),
            (),
            id="server-error-text",
        ),
        pytest.param(
            400,
            _MISSING,
            "plain failure",
            {"content-type": "text/plain"},
            "",
            ("Error 400", "plain failure"),
            (),
            id="unstructured-text",
        ),
        pytest.param(
            422,
            _MISSING,
            "{broken-json",
            {"content-type": "application/json"},
            "/api/v1/items",
            ("Error 422", "{broken-json"),
            (),
            id="malformed-json",
        ),
    ],
)
def test_http_errors_are_actionable_and_redacted(
    monkeypatch,
    status,
    data,
    text,
    headers,
    path,
    expected,
    excluded,
):
    printed = []
    monkeypatch.setattr(client, "rprint", lambda message: printed.append(str(message)))
    response = _response(status, data=data, text=text, headers=headers)
    error = httpx.HTTPStatusError("request failed", request=response.request, response=response)

    with pytest.raises(typer.Exit) as raised:
        client._handle_error(error, path)

    assert raised.value.exit_code == 1
    output = "\n".join(printed)
    assert all(value in output for value in expected)
    assert all(value not in output for value in excluded)


def test_rate_limit_without_header_uses_general_guidance(monkeypatch):
    printed = []
    monkeypatch.setattr(client, "rprint", lambda message: printed.append(str(message)))
    response = _response(429, data={"detail": "later"})
    error = httpx.HTTPStatusError("request failed", request=response.request, response=response)

    with pytest.raises(typer.Exit):
        client._handle_error(error)

    assert "a few seconds" in "\n".join(printed)


def test_connection_failure_shows_server_without_token(monkeypatch):
    printed = []
    monkeypatch.setattr(
        client.config,
        "load",
        lambda: {"server_url": "https://registry.example.test", "access_token": "fake-secret-token"},
    )
    monkeypatch.setattr(client, "rprint", lambda message: printed.append(str(message)))

    with pytest.raises(typer.Exit) as error:
        client._handle_connect()

    output = "\n".join(printed)
    assert error.value.exit_code == 1
    assert "Connection failed" in output
    assert "https://registry.example.test" in output
    assert "fake-secret-token" not in output


def test_connection_failure_handles_missing_server(monkeypatch):
    printed = []
    monkeypatch.setattr(client.config, "load", lambda: {})
    monkeypatch.setattr(client, "rprint", lambda message: printed.append(str(message)))

    with pytest.raises(typer.Exit):
        client._handle_connect()

    assert "Server URL: not set" in "\n".join(printed)


def test_timeout_failure_shows_path_and_configured_timeout(monkeypatch):
    printed = []
    monkeypatch.setattr(client.config, "get_timeout", lambda: 17)
    monkeypatch.setattr(client, "rprint", lambda message: printed.append(str(message)))

    with pytest.raises(typer.Exit) as error:
        client._handle_timeout("/api/v1/items")

    output = "\n".join(printed)
    assert error.value.exit_code == 1
    assert "Request timed out (/api/v1/items)" in output
    assert "Timeout: 17s" in output


@pytest.mark.parametrize(
    "stored",
    [
        {},
        {"server_url": "https://registry.example.test"},
        {"refresh_token": "fake-refresh-token"},
    ],
)
def test_refresh_requires_server_and_refresh_token(monkeypatch, stored):
    post = MagicMock()
    save = MagicMock()
    monkeypatch.setattr(client.config, "load", lambda: stored)
    monkeypatch.setattr(client.config, "save", save)
    monkeypatch.setattr(client.httpx, "post", post)

    assert client._try_refresh_token() is False
    post.assert_not_called()
    save.assert_not_called()


def test_refresh_saves_rotated_tokens(monkeypatch):
    post = MagicMock(
        return_value=_response(
            200,
            data={
                "access_token": "fake-new-access-token",
                "refresh_token": "fake-new-refresh-token",
            },
        )
    )
    save = MagicMock()
    monkeypatch.setattr(
        client.config,
        "load",
        lambda: {
            "server_url": "https://registry.example.test/",
            "refresh_token": "fake-old-refresh-token",
        },
    )
    monkeypatch.setattr(client.config, "save", save)
    monkeypatch.setattr(client.httpx, "post", post)

    assert client._try_refresh_token() is True
    post.assert_called_once_with(
        "https://registry.example.test/api/v1/auth/token/refresh",
        json={"refresh_token": "fake-old-refresh-token"},
        timeout=10,
    )
    save.assert_called_once_with(
        {
            "access_token": "fake-new-access-token",
            "refresh_token": "fake-new-refresh-token",
        }
    )


@pytest.mark.parametrize(
    "outcome",
    [
        _response(401, data={"detail": "expired"}),
        _response(200, data={"access_token": "missing-rotated-refresh"}),
        _response(200, text="not-json", headers={"content-type": "text/plain"}),
        httpx.ConnectError("refresh unavailable"),
    ],
)
def test_refresh_failures_do_not_overwrite_tokens(monkeypatch, outcome):
    post = MagicMock()
    if isinstance(outcome, Exception):
        post.side_effect = outcome
    else:
        post.return_value = outcome
    save = MagicMock()
    monkeypatch.setattr(
        client.config,
        "load",
        lambda: {
            "server_url": "https://registry.example.test",
            "refresh_token": "fake-old-refresh-token",
        },
    )
    monkeypatch.setattr(client.config, "save", save)
    monkeypatch.setattr(client.httpx, "post", post)

    assert client._try_refresh_token() is False
    save.assert_not_called()


@pytest.mark.parametrize("status", [429, 503, 504])
def test_transient_status_retries_once_then_succeeds(monkeypatch, isolated_client, status):
    responses = [_response(status, data={"detail": "retry"}), _response(200, data={"ok": True})]
    get = MagicMock(side_effect=responses)
    isolated_client.sleep.side_effect = None
    monkeypatch.setattr(client.config, "get_timeout", lambda: 19)
    monkeypatch.setattr(client.httpx, "get", get)

    result = client._request_with_retry(
        "get",
        "https://registry.example.test/api/v1/items",
        {"Authorization": "Bearer fake-access-token"},
        params={"page": 2},
    )

    assert result is responses[1]
    assert get.call_count == 2
    assert all(item.kwargs["timeout"] == 19 for item in get.call_args_list)
    assert all(item.kwargs["params"] == {"page": 2} for item in get.call_args_list)
    isolated_client.sleep.assert_called_once_with(0.5)


def test_retry_honors_header_and_stops_after_three_attempts(monkeypatch, isolated_client):
    responses = [
        _response(429, data={"detail": "retry"}, headers={"Retry-After": "2.5"}),
        _response(503, data={"detail": "retry"}),
        _response(504, data={"detail": "failed"}),
    ]
    get = MagicMock(side_effect=responses)
    isolated_client.sleep.side_effect = None
    monkeypatch.setattr(client.config, "get_timeout", lambda: 30)
    monkeypatch.setattr(client.httpx, "get", get)

    with pytest.raises(httpx.HTTPStatusError) as error:
        client._request_with_retry("get", "https://registry.example.test/api/v1/items", {})

    assert error.value.response is responses[-1]
    assert get.call_count == 3
    assert isolated_client.sleep.call_args_list == [call(2.5), call(1.0)]


def test_unauthorized_request_refreshes_and_retries_once(monkeypatch):
    responses = iter([_response(401, data={"detail": "expired"}), _response(200, data={"ok": True})])
    requests = []

    def get(url, **kwargs):
        requests.append((url, {**kwargs, "headers": dict(kwargs["headers"])}))
        return next(responses)

    refresh = MagicMock(return_value=True)
    monkeypatch.setattr(client.config, "get_timeout", lambda: 21)
    monkeypatch.setattr(client.config, "load", lambda: {"access_token": "fake-new-access-token"})
    monkeypatch.setattr(client, "_try_refresh_token", refresh)
    monkeypatch.setattr(client.httpx, "get", get)
    headers = {"Authorization": "Bearer fake-old-access-token"}

    response = client._request_with_retry("get", "https://registry.example.test/api/v1/items", headers)

    assert response.status_code == 200
    assert len(requests) == 2
    assert requests[0][1]["headers"]["Authorization"] == "Bearer fake-old-access-token"
    assert requests[1][1]["headers"]["Authorization"] == "Bearer fake-new-access-token"
    assert requests[0][1]["timeout"] == requests[1][1]["timeout"] == 21
    assert headers["Authorization"] == "Bearer fake-new-access-token"
    refresh.assert_called_once_with()


def test_unauthorized_request_never_refreshes_twice(monkeypatch):
    responses = [_response(401, data={"detail": "expired"}), _response(401, data={"detail": "still expired"})]
    get = MagicMock(side_effect=responses)
    refresh = MagicMock(return_value=True)
    monkeypatch.setattr(client.config, "get_timeout", lambda: 30)
    monkeypatch.setattr(client.config, "load", lambda: {"access_token": "fake-new-access-token"})
    monkeypatch.setattr(client, "_try_refresh_token", refresh)
    monkeypatch.setattr(client.httpx, "get", get)

    with pytest.raises(httpx.HTTPStatusError) as error:
        client._request_with_retry(
            "get",
            "https://registry.example.test/api/v1/items",
            {"Authorization": "Bearer fake-old-access-token"},
        )

    assert error.value.response is responses[1]
    assert get.call_count == 2
    refresh.assert_called_once_with()


def test_unauthorized_request_does_not_retry_when_refresh_fails(monkeypatch):
    response = _response(401, data={"detail": "expired"})
    get = MagicMock(return_value=response)
    refresh = MagicMock(return_value=False)
    monkeypatch.setattr(client.config, "get_timeout", lambda: 30)
    monkeypatch.setattr(client, "_try_refresh_token", refresh)
    monkeypatch.setattr(client.httpx, "get", get)

    with pytest.raises(httpx.HTTPStatusError):
        client._request_with_retry("get", "https://registry.example.test/api/v1/items", {})

    get.assert_called_once()
    refresh.assert_called_once_with()


def test_debug_request_url_redacts_userinfo(monkeypatch):
    url = "https://fake-user:fake-password@registry.example.test:8443/api/v1/items"
    get = MagicMock(return_value=_response(200, data={"ok": True}, url=url))
    monkeypatch.setattr(client.config, "get_timeout", lambda: 30)
    monkeypatch.setattr(client.httpx, "get", get)

    client._request_with_retry("get", url, {})

    debug_calls = repr(client.optic.debug.call_args_list)
    assert "https://registry.example.test/api/v1/items" in debug_calls
    assert "fake-user" not in debug_calls
    assert "fake-password" not in debug_calls
    assert "8443" not in debug_calls
    assert get.call_args.args[0] == url


@pytest.mark.parametrize("method", ["get", "post", "put", "patch", "delete"])
def test_http_wrappers_construct_authenticated_requests(monkeypatch, method):
    response = _response(200, data={"method": method})
    transport = MagicMock(return_value=response)
    enforce = MagicMock()
    monkeypatch.setattr(
        client.config,
        "get_or_exit",
        lambda: {
            "server_url": "https://registry.example.test/",
            "access_token": "fake-access-token",
        },
    )
    monkeypatch.setattr(client.config, "get_timeout", lambda: 13)
    monkeypatch.setattr(client, "_get_cli_version", lambda: "3.2.1")
    monkeypatch.setattr(client, "_enforce_version_once", enforce)
    monkeypatch.setattr(client.httpx, method, transport)

    path = "/api/v1/items/id"
    if method == "get":
        result = client.get(path, params={"page": 4})
        payload = {"params": {"page": 4}}
    elif method == "delete":
        result = client.delete(path)
        payload = {}
    else:
        result = getattr(client, method)(path, json_data={"name": "example"})
        payload = {"json": {"name": "example"}}

    assert result == {"method": method}
    transport.assert_called_once_with(
        f"https://registry.example.test{path}",
        headers={
            "Authorization": "Bearer fake-access-token",
            "X-Observal-CLI-Version": "3.2.1",
        },
        timeout=13,
        **payload,
    )
    enforce.assert_called_once_with("https://registry.example.test")


def test_get_text_returns_validated_raw_response(monkeypatch):
    response = _response(200, text="a,b\n1,2\n", headers={"Content-Type": "text/csv; charset=utf-8"})
    request = MagicMock(return_value=response)
    monkeypatch.setattr(
        client,
        "_client",
        lambda: ("https://registry.example.test", {"Authorization": "Bearer fake-access-token"}),
    )
    monkeypatch.setattr(client, "_request_with_retry", request)

    result = client.get_text("/api/v1/admin/audit-log/export", content_type="text/csv")

    assert result == "a,b\n1,2\n"
    request.assert_called_once_with(
        "get",
        "https://registry.example.test/api/v1/admin/audit-log/export",
        {"Authorization": "Bearer fake-access-token"},
        params=None,
    )


def test_get_text_rejects_unexpected_content_type(monkeypatch):
    response = _response(200, data={"detail": "not csv"}, headers={"Content-Type": "application/json"})
    monkeypatch.setattr(client, "_client", lambda: ("https://registry.example.test", {}))
    monkeypatch.setattr(client, "_request_with_retry", MagicMock(return_value=response))
    printed = []
    monkeypatch.setattr(client, "rprint", lambda message: printed.append(str(message)))

    with pytest.raises(typer.Exit) as error:
        client.get_text("/api/v1/admin/audit-log/export", content_type="text/csv")

    assert error.value.exit_code == 1
    assert printed == ["[red]Unexpected response content type:[/red] application/json"]


def test_get_with_headers_normalizes_pagination_headers(monkeypatch):
    response = _response(
        200,
        data={"items": [1, 2]},
        headers={"X-Total-Count": "42", "X-Next-Page": "3"},
    )
    request = MagicMock(return_value=response)
    monkeypatch.setattr(
        client,
        "_client",
        lambda: ("https://registry.example.test", {"Authorization": "Bearer fake-access-token"}),
    )
    monkeypatch.setattr(client, "_request_with_retry", request)

    data, headers = client.get_with_headers("/api/v1/items", params={"page": 2})

    assert data == {"items": [1, 2]}
    assert headers["x-total-count"] == "42"
    assert headers["x-next-page"] == "3"
    assert "X-Total-Count" not in headers
    request.assert_called_once_with(
        "get",
        "https://registry.example.test/api/v1/items",
        {"Authorization": "Bearer fake-access-token"},
        params={"page": 2},
    )


@pytest.mark.parametrize(
    ("method", "response"),
    [
        ("post", _response(204)),
        ("post", _response(200)),
        ("delete", _response(204)),
        ("delete", _response(200)),
    ],
)
def test_empty_post_and_delete_responses_return_empty_dict(monkeypatch, method, response):
    monkeypatch.setattr(client, "_client", lambda: ("https://registry.example.test", {}))
    monkeypatch.setattr(client, "_request_with_retry", MagicMock(return_value=response))

    if method == "post":
        result = client.post("/api/v1/items", json_data={"name": "example"})
    else:
        result = client.delete("/api/v1/items/id")

    assert result == {}


def _invoke_wrapper(name: str):
    if name in {"get", "get_text", "get_with_headers"}:
        return getattr(client, name)("/api/v1/items", params={"page": 1})
    if name == "delete":
        return client.delete("/api/v1/items/id")
    return getattr(client, name)("/api/v1/items/id", json_data={"name": "example"})


@pytest.mark.parametrize("wrapper", ["get", "get_text", "get_with_headers", "post", "put", "patch", "delete"])
@pytest.mark.parametrize("failure", ["status", "timeout", "connection"])
def test_wrappers_route_transport_failures_to_user_facing_handlers(monkeypatch, wrapper, failure):
    response = _response(400, data={"detail": "invalid"})
    status_error = httpx.HTTPStatusError("invalid", request=response.request, response=response)
    exception = {
        "status": status_error,
        "timeout": httpx.ReadTimeout("slow request"),
        "connection": httpx.ConnectError("connection refused"),
    }[failure]
    monkeypatch.setattr(client, "_client", lambda: ("https://registry.example.test", {}))
    monkeypatch.setattr(client, "_request_with_retry", MagicMock(side_effect=exception))
    handle_error = MagicMock(side_effect=typer.Exit(1))
    handle_timeout = MagicMock(side_effect=typer.Exit(1))
    handle_connect = MagicMock(side_effect=typer.Exit(1))
    monkeypatch.setattr(client, "_handle_error", handle_error)
    monkeypatch.setattr(client, "_handle_timeout", handle_timeout)
    monkeypatch.setattr(client, "_handle_connect", handle_connect)

    with pytest.raises(typer.Exit):
        _invoke_wrapper(wrapper)

    path = "/api/v1/items" if wrapper in {"get", "get_text", "get_with_headers"} else "/api/v1/items/id"
    if failure == "status":
        handle_error.assert_called_once_with(status_error, path)
        handle_timeout.assert_not_called()
        handle_connect.assert_not_called()
    elif failure == "timeout":
        handle_timeout.assert_called_once_with(path)
        handle_error.assert_not_called()
        handle_connect.assert_not_called()
    else:
        handle_connect.assert_called_once_with()
        handle_error.assert_not_called()
        handle_timeout.assert_not_called()


@pytest.mark.parametrize(
    ("item_type", "expected_type"),
    [
        ("agents", "agent"),
        ("mcps", "mcp"),
        ("skills", "skill"),
        ("hooks", "hook"),
        ("prompts", "prompt"),
        ("sandboxes", "sandbox"),
        ("custom", "custom"),
    ],
)
def test_registry_reference_resolves_qualified_alias(monkeypatch, item_type, expected_type):
    resolve_alias = MagicMock(return_value="owner/item")
    get = MagicMock(return_value={"id": 123})
    monkeypatch.setattr(client.config, "resolve_alias", resolve_alias)
    monkeypatch.setattr(client, "get", get)

    assert client.resolve_registry_reference(item_type, "@favorite") == "123"
    resolve_alias.assert_called_once_with("@favorite")
    get.assert_called_once_with(
        "/api/v1/registry/resolve",
        params={"type": expected_type, "identifier": "owner/item"},
    )


@pytest.mark.parametrize("resolved", ["item", "00000000-0000-0000-0000-000000000123"])
def test_registry_reference_preserves_bare_and_uuid_aliases(monkeypatch, resolved):
    monkeypatch.setattr(client.config, "resolve_alias", lambda _reference: resolved)
    get = MagicMock()
    monkeypatch.setattr(client, "get", get)

    assert client.resolve_registry_reference("agent", "input") == resolved
    get.assert_not_called()


@pytest.mark.parametrize(
    ("item", "expected"),
    [
        ({"qualified_name": "owner/item", "name": "Item"}, "owner/item"),
        ({"name": "Legacy"}, "Legacy"),
        ({}, ""),
    ],
)
def test_canonical_name_prefers_qualified_identity(item, expected):
    assert client.canonical_name(item) == expected


def test_team_uuid_is_returned_without_lookup(monkeypatch):
    team_id = "11111111-1111-1111-1111-111111111111"
    get = MagicMock()
    monkeypatch.setattr(client, "get", get)

    assert client.resolve_team_id(f"  {team_id.upper()}  ") == team_id
    get.assert_not_called()


@pytest.mark.parametrize(
    ("reference", "encoded_handle"),
    [
        ("  @PLATFORM-tools ", "platform-tools"),
        ("@../admin/secrets", "..%2Fadmin%2Fsecrets"),
    ],
)
def test_team_handle_lookup_is_normalized_and_path_safe(monkeypatch, reference, encoded_handle):
    headers = {"Authorization": "Bearer test-token"}
    request = MagicMock(return_value=_response(200, data={"id": 42}))
    fallback = MagicMock()
    monkeypatch.setattr(client, "_client", lambda: ("https://registry.example.test", headers))
    monkeypatch.setattr(client, "_request_with_retry", request)
    monkeypatch.setattr(client, "get", fallback)

    assert client.resolve_team_id(reference) == "42"
    request.assert_called_once_with(
        "get",
        f"https://registry.example.test/api/v1/teams/by-handle/{encoded_handle}",
        headers,
    )
    fallback.assert_not_called()


def test_unknown_team_handle_is_a_parameter_error(monkeypatch):
    headers = {"Authorization": "Bearer test-token"}
    request = MagicMock(side_effect=httpx.ConnectError("lookup unavailable"))
    fallback = MagicMock(return_value=[{"id": "team-1", "handle": "other"}])
    monkeypatch.setattr(client, "_client", lambda: ("https://registry.example.test", headers))
    monkeypatch.setattr(client, "_request_with_retry", request)
    monkeypatch.setattr(client, "get", fallback)

    with pytest.raises(typer.BadParameter) as error:
        client.resolve_team_id("@missing")

    request.assert_called_once()
    fallback.assert_called_once_with("/api/v1/teams/all")
    assert "No teamspace with handle '@missing'" in str(error.value)
    assert error.value.param_hint == "team"


def test_publish_target_defaults_to_public():
    payload = {"name": "Example"}

    client.add_publish_target(payload, team=None, visibility=None)

    assert payload == {"name": "Example", "visibility": "public"}


def test_publish_target_resolves_team_for_team_visibility(monkeypatch):
    resolve = MagicMock(return_value="team-id")
    monkeypatch.setattr(client, "resolve_team_id", resolve)
    payload = {}

    client.add_publish_target(payload, team="@platform", visibility=" TEAM ")

    assert payload == {"visibility": "team", "team_id": "team-id"}
    resolve.assert_called_once_with("@platform")


def test_public_publish_target_can_retain_team_namespace(monkeypatch):
    monkeypatch.setattr(client, "resolve_team_id", lambda _team: "team-id")
    payload = {}

    client.add_publish_target(payload, team="platform", visibility="PUBLIC")

    assert payload == {"visibility": "public", "team_id": "team-id"}


@pytest.mark.parametrize(
    ("team", "visibility", "message", "hint"),
    [
        (None, "team", "requires", "team"),
        (None, "private", "visibility must be", "visibility"),
    ],
)
def test_publish_target_rejects_invalid_combinations(team, visibility, message, hint):
    with pytest.raises(typer.BadParameter) as error:
        client.add_publish_target({}, team=team, visibility=visibility)

    assert message in str(error.value)
    assert error.value.param_hint == hint


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ({}, False),
        ({"server_url": "https://registry.example.test"}, False),
        ({"access_token": "fake-access-token"}, False),
    ],
)
def test_registered_agent_policy_requires_configuration(monkeypatch, stored, expected):
    get = MagicMock()
    monkeypatch.setattr(client.config, "load", lambda: stored)
    monkeypatch.setattr(client.httpx, "get", get)

    assert client.get_registered_agents_only() is expected
    get.assert_not_called()


def test_registered_agent_policy_uses_bearer_header(monkeypatch):
    get = MagicMock(return_value=_response(200, data={"registered_agents_only": True}))
    monkeypatch.setattr(
        client.config,
        "load",
        lambda: {
            "server_url": "https://registry.example.test/",
            "access_token": "fake-access-token",
        },
    )
    monkeypatch.setattr(client.httpx, "get", get)

    assert client.get_registered_agents_only() is True
    get.assert_called_once_with(
        "https://registry.example.test/api/v1/admin/registered-agents-only",
        headers={"Authorization": "Bearer fake-access-token"},
        timeout=5,
    )


@pytest.mark.parametrize(
    "outcome",
    [
        _response(200, data={}),
        _response(503, data={"detail": "unavailable"}),
        httpx.ConnectError("unavailable"),
    ],
)
def test_registered_agent_policy_defaults_to_disabled_on_error(monkeypatch, outcome):
    get = MagicMock()
    if isinstance(outcome, Exception):
        get.side_effect = outcome
    else:
        get.return_value = outcome
    monkeypatch.setattr(
        client.config,
        "load",
        lambda: {"server_url": "https://registry.example.test", "access_token": "fake-access-token"},
    )
    monkeypatch.setattr(client.httpx, "get", get)

    assert client.get_registered_agents_only() is False


@pytest.mark.parametrize(
    ("function_name", "path"),
    [
        ("get_registered_agent_names", "/api/v1/agents"),
        ("get_registered_mcp_names", "/api/v1/mcp"),
    ],
)
def test_registered_name_helpers_filter_empty_names(monkeypatch, function_name, path):
    get = MagicMock(
        return_value=_response(
            200,
            data=[{"name": "alpha"}, {"name": ""}, {}, {"name": "beta"}],
        )
    )
    monkeypatch.setattr(
        client.config,
        "load",
        lambda: {"server_url": "https://registry.example.test/", "access_token": "fake-access-token"},
    )
    monkeypatch.setattr(client.httpx, "get", get)

    assert getattr(client, function_name)() == {"alpha", "beta"}
    get.assert_called_once_with(
        f"https://registry.example.test{path}",
        headers={"Authorization": "Bearer fake-access-token"},
        timeout=5,
    )


@pytest.mark.parametrize("function_name", ["get_registered_agent_names", "get_registered_mcp_names"])
@pytest.mark.parametrize("failure", ["missing-config", "bad-status", "connection"])
def test_registered_name_helpers_fail_open(monkeypatch, function_name, failure):
    if failure == "missing-config":
        stored = {}
        get = MagicMock()
    elif failure == "bad-status":
        stored = {"server_url": "https://registry.example.test", "access_token": "fake-access-token"}
        get = MagicMock(return_value=_response(503, data={"detail": "unavailable"}))
    else:
        stored = {"server_url": "https://registry.example.test", "access_token": "fake-access-token"}
        get = MagicMock(side_effect=httpx.ConnectError("unavailable"))
    monkeypatch.setattr(client.config, "load", lambda: stored)
    monkeypatch.setattr(client.httpx, "get", get)

    assert getattr(client, function_name)() == set()
    if failure == "missing-config":
        get.assert_not_called()


def test_health_without_server_skips_transport(monkeypatch):
    get = MagicMock()
    monkeypatch.setattr(client.config, "load", lambda: {})
    monkeypatch.setattr(client.httpx, "get", get)

    assert client.health() == (False, 0)
    get.assert_not_called()


@pytest.mark.parametrize(("status", "expected"), [(200, True), (503, False)])
def test_health_reports_status_and_latency(monkeypatch, isolated_client, status, expected):
    get = MagicMock(return_value=_response(status, data={"status": "ok"}))
    isolated_client.monotonic.side_effect = [10.0, 10.125]
    monkeypatch.setattr(client.config, "load", lambda: {"server_url": "https://registry.example.test/"})
    monkeypatch.setattr(client.httpx, "get", get)

    assert client.health() == (expected, 125.0)
    get.assert_called_once_with("https://registry.example.test/health", timeout=5)


def test_health_connection_failure_returns_zero_latency(monkeypatch):
    monkeypatch.setattr(client.config, "load", lambda: {"server_url": "https://registry.example.test"})
    monkeypatch.setattr(client.httpx, "get", MagicMock(side_effect=httpx.ConnectError("unavailable")))

    assert client.health() == (False, 0)


def test_server_supports_fetches_and_caches_effective_version(monkeypatch):
    from observal_cli import features

    get = MagicMock(return_value={"server_version": "2.0.0"})
    available = MagicMock(return_value=True)
    monkeypatch.setattr(client, "get", get)
    monkeypatch.setattr(client, "_get_cli_version", lambda: "1.5.0")
    monkeypatch.setattr(features, "is_available", available)

    assert client.server_supports("example-feature") is True
    assert client.server_supports("second-feature") is True

    get.assert_called_once_with("/api/v1/config/version")
    assert available.call_args_list == [
        call("example-feature", "1.5.0"),
        call("second-feature", "1.5.0"),
    ]


def test_server_supports_returns_false_when_version_lookup_fails(monkeypatch):
    monkeypatch.setattr(client, "get", MagicMock(side_effect=typer.Exit(1)))

    assert client.server_supports("example-feature") is False


def test_server_supports_uses_server_string_when_version_parsing_fails(monkeypatch):
    from observal_cli import features

    available = MagicMock(return_value=False)
    monkeypatch.setattr(client, "_server_version_cache", "development")
    monkeypatch.setattr(client, "_get_cli_version", lambda: "also-development")
    monkeypatch.setattr(features, "is_available", available)

    assert client.server_supports("example-feature") is False
    available.assert_called_once_with("example-feature", "development")
