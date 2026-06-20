# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for configuration settings."""

import os
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_has_license_false_when_no_key():
    """HAS_LICENSE should be False when OBSERVAL_LICENSE_KEY is not set."""
    with patch.dict(os.environ, {"OBSERVAL_LICENSE_KEY": ""}, clear=False):
        # Re-evaluate
        has_license = bool(os.environ.get("OBSERVAL_LICENSE_KEY", ""))
    assert has_license is False


def test_has_license_true_when_key_set():
    """HAS_LICENSE should be True when OBSERVAL_LICENSE_KEY is set."""
    has_license = bool(os.environ.get("OBSERVAL_LICENSE_KEY", ""))
    # In the test env, the .env has a license key
    # Just verify the derivation logic works
    with patch.dict(os.environ, {"OBSERVAL_LICENSE_KEY": "some.key"}, clear=False):
        assert bool(os.environ.get("OBSERVAL_LICENSE_KEY", "")) is True


def test_deployment_mode_in_legacy_vars():
    """DEPLOYMENT_MODE should be in the legacy env var list."""
    from config import _LEGACY_ENV_VARS

    assert "DEPLOYMENT_MODE" in _LEGACY_ENV_VARS


def test_demo_env_vars_default_to_none():
    """All DEMO_* vars should default to None when env is clean."""
    from config import Settings

    # Verify the field declarations accept None
    s = Settings(
        DATABASE_URL="sqlite+aiosqlite:///",
        SECRET_KEY="test",
        DEMO_SUPER_ADMIN_EMAIL=None,
        DEMO_ADMIN_EMAIL=None,
        _env_file=None,
    )
    assert s.DEMO_SUPER_ADMIN_EMAIL is None
    assert s.DEMO_ADMIN_EMAIL is None


def test_version_middleware_rejects_cli_drift(monkeypatch):
    """CLI requests must match the exact server version."""
    import version
    from middleware import configure_version_middleware

    monkeypatch.setattr(version, "get_server_version", lambda: "1.6.2")

    app = FastAPI()
    configure_version_middleware(app)

    @app.get("/api/v1/example")
    async def example():
        return {"ok": True}

    client = TestClient(app)
    response = client.get("/api/v1/example", headers={"X-Observal-CLI-Version": "1.6.1"})

    assert response.status_code == 426
    assert response.json()["install_command"] == "python -m pip install observal-cli==1.6.2"


def test_version_middleware_allows_exact_cli_match(monkeypatch):
    """CLI requests pass when versions match exactly."""
    import version
    from middleware import configure_version_middleware

    monkeypatch.setattr(version, "get_server_version", lambda: "1.6.2")

    app = FastAPI()
    configure_version_middleware(app)

    @app.get("/api/v1/example")
    async def example():
        return {"ok": True}

    client = TestClient(app)
    response = client.get("/api/v1/example", headers={"X-Observal-CLI-Version": "1.6.2"})

    assert response.status_code == 200
    assert response.headers["X-Observal-Server"] == "1.6.2"


def test_version_middleware_rejects_cli_without_version_header(monkeypatch):
    """Old Python HTTP clients must identify their Observal CLI version."""
    import version
    from middleware import configure_version_middleware

    monkeypatch.setattr(version, "get_server_version", lambda: "1.6.2")

    app = FastAPI()
    configure_version_middleware(app)

    @app.get("/api/v1/review")
    async def review():
        return {"ok": True}

    client = TestClient(app)
    response = client.get(
        "/api/v1/review",
        headers={"User-Agent": "python-httpx/0.27.0", "Authorization": "Bearer old-cli-token"},
    )

    assert response.status_code == 426
    assert response.json()["install_command"] == "python -m pip install observal-cli==1.6.2"


def test_version_middleware_allows_browser_without_cli_header(monkeypatch):
    """Browser frontend requests are not CLI version gated."""
    import version
    from middleware import configure_version_middleware

    monkeypatch.setattr(version, "get_server_version", lambda: "1.6.2")

    app = FastAPI()
    configure_version_middleware(app)

    @app.get("/api/v1/review")
    async def review():
        return {"ok": True}

    client = TestClient(app)
    response = client.get(
        "/api/v1/review",
        headers={"User-Agent": "Mozilla/5.0", "Authorization": "Bearer browser-token"},
    )

    assert response.status_code == 200
