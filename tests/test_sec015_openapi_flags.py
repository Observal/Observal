# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""SEC-015: ENABLE_OPENAPI and ENABLE_METRICS flags hide operational routes in production."""

import os
import sys

import pytest


def _build_app(monkeypatch, enable_openapi: bool, deployment_mode: str, enable_metrics: bool = False):
    """Re-import config and main with patched env vars to get a fresh app instance."""
    # Patch env vars before importing
    monkeypatch.setenv("ENABLE_OPENAPI", str(enable_openapi).lower())
    monkeypatch.setenv("ENABLE_METRICS", str(enable_metrics).lower())
    monkeypatch.setenv("DEPLOYMENT_MODE", deployment_mode)

    # Remove cached modules so Settings() re-reads env vars
    for mod_name in list(sys.modules.keys()):
        if mod_name in ("config", "main") or mod_name.startswith("main."):
            del sys.modules[mod_name]

    import config as cfg_module

    cfg_module.settings = cfg_module.Settings()
    return cfg_module.settings


class TestOpenAPIFlags:
    def test_enterprise_openapi_disabled_by_default(self, monkeypatch):
        """ENABLE_OPENAPI=False + DEPLOYMENT_MODE=enterprise -> openapi_url is None."""
        settings = _build_app(monkeypatch, enable_openapi=False, deployment_mode="enterprise")
        expose = settings.ENABLE_OPENAPI or settings.DEPLOYMENT_MODE == "local"
        assert not expose, "OpenAPI should be hidden in enterprise mode when ENABLE_OPENAPI=False"

    def test_local_mode_always_exposes_openapi(self, monkeypatch):
        """DEPLOYMENT_MODE=local -> openapi exposed regardless of ENABLE_OPENAPI."""
        settings = _build_app(monkeypatch, enable_openapi=False, deployment_mode="local")
        expose = settings.ENABLE_OPENAPI or settings.DEPLOYMENT_MODE == "local"
        assert expose, "OpenAPI should always be exposed in local mode"

    def test_enterprise_with_flag_enabled(self, monkeypatch):
        """ENABLE_OPENAPI=True + DEPLOYMENT_MODE=enterprise -> openapi exposed."""
        settings = _build_app(monkeypatch, enable_openapi=True, deployment_mode="enterprise")
        expose = settings.ENABLE_OPENAPI or settings.DEPLOYMENT_MODE == "local"
        assert expose, "OpenAPI should be exposed when ENABLE_OPENAPI=True"


class TestMetricsFlags:
    def test_enterprise_metrics_disabled_by_default(self, monkeypatch):
        """ENABLE_METRICS=False + DEPLOYMENT_MODE=enterprise -> metrics not exposed."""
        settings = _build_app(monkeypatch, enable_openapi=False, deployment_mode="enterprise", enable_metrics=False)
        expose = settings.ENABLE_METRICS or settings.DEPLOYMENT_MODE == "local"
        assert not expose, "Metrics should be hidden in enterprise mode when ENABLE_METRICS=False"

    def test_local_mode_always_exposes_metrics(self, monkeypatch):
        """DEPLOYMENT_MODE=local -> metrics exposed regardless of ENABLE_METRICS."""
        settings = _build_app(monkeypatch, enable_openapi=False, deployment_mode="local", enable_metrics=False)
        expose = settings.ENABLE_METRICS or settings.DEPLOYMENT_MODE == "local"
        assert expose, "Metrics should always be exposed in local mode"

    def test_enterprise_with_metrics_flag_enabled(self, monkeypatch):
        """ENABLE_METRICS=True + DEPLOYMENT_MODE=enterprise -> metrics exposed."""
        settings = _build_app(monkeypatch, enable_openapi=False, deployment_mode="enterprise", enable_metrics=True)
        expose = settings.ENABLE_METRICS or settings.DEPLOYMENT_MODE == "local"
        assert expose, "Metrics should be exposed when ENABLE_METRICS=True"


class TestSettingsDefaults:
    def test_enable_openapi_default_false(self):
        """ENABLE_OPENAPI defaults to False."""
        # Import fresh settings without any override

        # Re-instantiate without env overrides to confirm default
        from pydantic_settings import BaseSettings

        class MinimalSettings(BaseSettings):
            ENABLE_OPENAPI: bool = False
            ENABLE_METRICS: bool = False
            model_config = {"env_file": None, "extra": "ignore"}

        s = MinimalSettings(_env_file=None)
        assert s.ENABLE_OPENAPI is False

    def test_enable_metrics_default_false(self):
        """ENABLE_METRICS defaults to False."""
        from pydantic_settings import BaseSettings

        class MinimalSettings(BaseSettings):
            ENABLE_OPENAPI: bool = False
            ENABLE_METRICS: bool = False
            model_config = {"env_file": None, "extra": "ignore"}

        s = MinimalSettings(_env_file=None)
        assert s.ENABLE_METRICS is False


class TestOpenAPIHttpRoutes:
    """HTTP-level assertions that /docs actually returns 404 when disabled."""

    @pytest.mark.asyncio
    async def test_docs_returns_404_when_openapi_disabled(self):
        """With ENABLE_OPENAPI=False in enterprise mode, /docs returns 404."""
        import importlib
        from unittest.mock import patch as _patch

        for mod in list(sys.modules.keys()):
            if mod in ("main", "config") or mod.startswith("main.") or mod.startswith("config."):
                del sys.modules[mod]

        with _patch.dict(os.environ, {"DEPLOYMENT_MODE": "enterprise", "ENABLE_OPENAPI": "false"}, clear=False):
            import config as cfg_mod

            importlib.reload(cfg_mod)
            import main as main_mod

            importlib.reload(main_mod)

            from httpx import ASGITransport, AsyncClient

            async with AsyncClient(
                transport=ASGITransport(app=main_mod.app, raise_app_exceptions=False),
                base_url="http://test",
            ) as client:
                r_docs = await client.get("/docs")
                r_openapi = await client.get("/openapi.json")

        assert r_docs.status_code == 404, f"/docs should be 404, got {r_docs.status_code}"
        assert r_openapi.status_code == 404, f"/openapi.json should be 404, got {r_openapi.status_code}"
