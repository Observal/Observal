"""Tests for deployment mode guards (require_local_mode)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


def _make_app_with_guarded_route():
    """Build a minimal FastAPI app with a route guarded by require_local_mode."""
    from fastapi import Depends, FastAPI

    from api.deps import require_local_mode

    app = FastAPI()

    @app.post("/guarded", dependencies=[Depends(require_local_mode)])
    async def guarded():
        return {"ok": True}

    return app


class TestRequireLocalMode:
    @pytest.mark.asyncio
    async def test_allows_request_in_local_mode(self):
        app = _make_app_with_guarded_route()
        with patch("api.deps.settings") as mock_settings:
            mock_settings.DEPLOYMENT_MODE = "local"
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                r = await ac.post("/guarded")
        assert r.status_code == 200
        assert r.json() == {"ok": True}

    @pytest.mark.asyncio
    async def test_blocks_request_in_enterprise_mode(self):
        app = _make_app_with_guarded_route()
        with patch("api.deps.settings") as mock_settings:
            mock_settings.DEPLOYMENT_MODE = "enterprise"
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                r = await ac.post("/guarded")
        assert r.status_code == 403
        assert "enterprise" in r.json()["detail"].lower()


class TestAuthRouteGuards:
    """Verify that bootstrap, register, invite, and redeem are guarded."""

    GUARDED_ROUTES = [
        ("POST", "/api/v1/auth/bootstrap"),
        ("POST", "/api/v1/auth/register"),
        ("POST", "/api/v1/auth/invite"),
        ("POST", "/api/v1/auth/redeem"),
    ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method,path", GUARDED_ROUTES)
    async def test_enterprise_mode_returns_403(self, method, path):
        """All local-only auth endpoints return 403 in enterprise mode."""
        from main import app

        with patch("api.deps.settings") as mock_settings:
            mock_settings.DEPLOYMENT_MODE = "enterprise"
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                r = await ac.request(method, path)
        assert r.status_code == 403
        assert "enterprise" in r.json()["detail"].lower()
