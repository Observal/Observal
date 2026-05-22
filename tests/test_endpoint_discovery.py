# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""
Tests derive_endpoints logic.
derive_endpoints now reads from dynamic_settings (async).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_ds_get(public_url="", otlp_http_url="", frontend_url=""):
    """Create a mock for ds.get that returns URL settings."""
    mapping = {
        "deployment.public_url": public_url,
        "deployment.otlp_http_url": otlp_http_url,
        "deployment.frontend_url": frontend_url,
    }

    async def mock_get(key, *args, **kwargs):
        return mapping.get(key, "")

    return mock_get


class TestDeriveEndpoints:
    @pytest.mark.asyncio
    async def test_all_settings_explicit(self):
        with patch("services.dynamic_settings") as mock_ds:
            mock_ds.get = AsyncMock(
                side_effect=_make_ds_get(
                    public_url="https://observal.company.com",
                    otlp_http_url="https://otel.company.com",
                    frontend_url="https://dash.company.com",
                )
            )
            from api.routes.config import derive_endpoints

            result = await derive_endpoints()
        assert result["api"] == "https://observal.company.com"
        assert result["otlp_http"] == "https://otel.company.com"
        assert result["web"] == "https://dash.company.com"

    @pytest.mark.asyncio
    async def test_derives_otlp_from_public_url(self):
        with patch("services.dynamic_settings") as mock_ds:
            mock_ds.get = AsyncMock(
                side_effect=_make_ds_get(
                    public_url="https://observal.company.com",
                    otlp_http_url="",
                    frontend_url="",
                )
            )
            from api.routes.config import derive_endpoints

            result = await derive_endpoints()
        assert result["api"] == "https://observal.company.com"
        assert result["otlp_http"] == "https://observal.company.com"

    @pytest.mark.asyncio
    async def test_derives_from_request_base_url(self):
        request = MagicMock()
        request.base_url = "https://api.myhost.io/"
        with patch("services.dynamic_settings") as mock_ds:
            mock_ds.get = AsyncMock(side_effect=_make_ds_get())
            from api.routes.config import derive_endpoints

            result = await derive_endpoints(request)
        assert result["api"] == "https://api.myhost.io"
        assert result["otlp_http"] == "https://api.myhost.io"

    @pytest.mark.asyncio
    async def test_localhost_uses_http(self):
        with patch("services.dynamic_settings") as mock_ds:
            mock_ds.get = AsyncMock(side_effect=_make_ds_get())
            from api.routes.config import derive_endpoints

            result = await derive_endpoints()
        assert result["otlp_http"] == "http://localhost:8000"

    @pytest.mark.asyncio
    async def test_fallback_when_no_request_no_settings(self):
        with patch("services.dynamic_settings") as mock_ds:
            mock_ds.get = AsyncMock(side_effect=_make_ds_get())
            from api.routes.config import derive_endpoints

            result = await derive_endpoints()
        assert result["api"] == "http://localhost:8000"

    @pytest.mark.asyncio
    async def test_trailing_slash_stripped(self):
        with patch("services.dynamic_settings") as mock_ds:
            mock_ds.get = AsyncMock(
                side_effect=_make_ds_get(
                    public_url="https://api.example.com/",
                )
            )
            from api.routes.config import derive_endpoints

            result = await derive_endpoints()
        assert result["api"] == "https://api.example.com"
