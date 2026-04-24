"""Tests for the endpoint discovery system.

Tests derive_endpoints logic and the hooks_spec OTLP grpc URL handling.
The derive_endpoints tests mock enough of the module chain to avoid
needing FastAPI, pydantic_settings, etc.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "observal-server"))


def _import_derive_endpoints(settings_mock):
    """Import derive_endpoints with all server deps mocked."""
    # Build a fake config module with the given settings
    config_mod = ModuleType("config")
    config_mod.settings = settings_mock

    # Fake fastapi
    fastapi_mod = MagicMock()
    fastapi_mod.APIRouter = MagicMock()
    fastapi_mod.Request = type("Request", (), {})

    api_deps_mod = MagicMock()

    saved_modules = {}
    to_mock = {"fastapi": fastapi_mod, "config": config_mod, "api.deps": api_deps_mod}
    for name, mod in to_mock.items():
        saved_modules[name] = sys.modules.get(name)
        sys.modules[name] = mod

    # Remove cached import so it gets re-imported with mocked deps
    sys.modules.pop("api.routes.config", None)

    try:
        from api.routes.config import derive_endpoints

        return derive_endpoints
    finally:
        # Restore
        for name, mod in saved_modules.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod
        sys.modules.pop("api.routes.config", None)


def _make_settings(**kwargs):
    s = MagicMock()
    s.PUBLIC_URL = kwargs.get("public_url", "")
    s.OTLP_HTTP_URL = kwargs.get("otlp_http_url", "")
    s.OTLP_GRPC_URL = kwargs.get("otlp_grpc_url", "")
    s.FRONTEND_URL = kwargs.get("frontend_url", "")
    return s


class TestDeriveEndpoints:
    def test_all_settings_explicit(self):
        settings = _make_settings(
            public_url="https://observal.company.com",
            otlp_http_url="https://otel.company.com:4318",
            otlp_grpc_url="https://otel.company.com:4317",
            frontend_url="https://dash.company.com",
        )
        fn = _import_derive_endpoints(settings)
        result = fn()
        assert result["api"] == "https://observal.company.com"
        assert result["otlp_http"] == "https://otel.company.com:4318"
        assert result["otlp_grpc"] == "https://otel.company.com:4317"
        assert result["web"] == "https://dash.company.com"

    def test_derives_otlp_from_public_url(self):
        settings = _make_settings(
            public_url="https://observal.company.com",
            frontend_url="https://dash.company.com",
        )
        fn = _import_derive_endpoints(settings)
        result = fn()
        assert result["api"] == "https://observal.company.com"
        assert result["otlp_http"] == "https://observal.company.com:4318"
        assert result["otlp_grpc"] == "https://observal.company.com:4317"

    def test_derives_from_request_base_url(self):
        settings = _make_settings()
        fn = _import_derive_endpoints(settings)
        request = MagicMock()
        request.base_url = "https://api.myhost.io/"
        result = fn(request)
        assert result["api"] == "https://api.myhost.io"
        assert result["otlp_http"] == "https://api.myhost.io:4318"
        assert result["otlp_grpc"] == "https://api.myhost.io:4317"

    def test_localhost_uses_http(self):
        settings = _make_settings(public_url="http://localhost:8000")
        fn = _import_derive_endpoints(settings)
        result = fn()
        assert result["otlp_http"] == "http://localhost:4318"
        assert result["otlp_grpc"] == "http://localhost:4317"

    def test_fallback_when_no_request_no_settings(self):
        settings = _make_settings()
        fn = _import_derive_endpoints(settings)
        result = fn()
        assert result["api"] == "http://localhost:8000"
        assert result["otlp_http"] == "http://localhost:4318"
        assert result["otlp_grpc"] == "http://localhost:4317"

    def test_trailing_slash_stripped(self):
        settings = _make_settings(
            public_url="https://observal.io/",
            otlp_http_url="https://otel.io:4318/",
            otlp_grpc_url="https://otel.io:4317/",
            frontend_url="https://dash.io/",
        )
        fn = _import_derive_endpoints(settings)
        result = fn()
        assert result["api"] == "https://observal.io"
        assert result["otlp_http"] == "https://otel.io:4318"
        assert result["otlp_grpc"] == "https://otel.io:4317"
        assert result["web"] == "https://dash.io"

    def test_http_non_localhost_preserves_scheme(self):
        """HTTP on a non-localhost host should stay HTTP, not upgrade to HTTPS."""
        settings = _make_settings(public_url="http://intranet.corp:8000")
        fn = _import_derive_endpoints(settings)
        result = fn()
        assert result["api"] == "http://intranet.corp:8000"
        assert result["otlp_http"] == "http://intranet.corp:4318"
        assert result["otlp_grpc"] == "http://intranet.corp:4317"
        assert result["web"] == "http://intranet.corp:3000"

    def test_https_localhost_preserves_scheme(self):
        """HTTPS on localhost (local dev with TLS) should stay HTTPS."""
        settings = _make_settings(public_url="https://localhost:8000")
        fn = _import_derive_endpoints(settings)
        result = fn()
        assert result["otlp_http"] == "https://localhost:4318"
        assert result["otlp_grpc"] == "https://localhost:4317"
        assert result["web"] == "https://localhost:3000"


class TestHooksSpecOtlpGrpc:
    def test_uses_passed_otlp_grpc_url(self):
        from observal_cli.hooks_spec import get_desired_env

        env = get_desired_env("http://localhost:8000", "token123", otlp_grpc_url="https://otel.company.com:4317")
        assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == "https://otel.company.com:4317"

    def test_derives_when_no_otlp_grpc_url(self):
        from observal_cli.hooks_spec import get_desired_env

        env = get_desired_env("http://localhost:8000", "token123")
        assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://localhost:4317"

    def test_derives_https_for_remote(self):
        from observal_cli.hooks_spec import get_desired_env

        env = get_desired_env("https://observal.company.com", "token123")
        assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == "https://observal.company.com:4317"

    def test_http_non_localhost_preserves_scheme(self):
        from observal_cli.hooks_spec import get_desired_env

        env = get_desired_env("http://intranet.corp:8000", "token123")
        assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://intranet.corp:4317"
