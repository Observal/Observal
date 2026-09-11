# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: Apache-2.0

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from api.deps import get_registry_user
from api.routes import prompt
from models.mcp import ListingStatus
from schemas.prompt import PromptRenderRequest
from services import dynamic_settings


def _request(path: str = "/api/v1/agents") -> Request:
    return Request({"type": "http", "method": "GET", "path": path, "headers": []})


@pytest.mark.asyncio
async def test_public_registry_rejects_guest_when_disabled():
    with (
        patch("services.dynamic_settings.get_bool", new=AsyncMock(return_value=False)) as get_bool,
        pytest.raises(HTTPException) as exc_info,
    ):
        await get_registry_user(_request(), None)

    assert exc_info.value.status_code == 401
    get_bool.assert_awaited_once_with("deployment.public_registry_enabled")


@pytest.mark.asyncio
async def test_public_registry_accepts_guest_when_enabled():
    with patch("services.dynamic_settings.get_bool", new=AsyncMock(return_value=True)):
        assert await get_registry_user(_request(), None) is None


@pytest.mark.asyncio
async def test_public_registry_accepts_authenticated_user_without_setting_lookup():
    user = SimpleNamespace(id="user-id")
    redis = MagicMock(get=AsyncMock(return_value=None))
    with (
        patch("services.dynamic_settings.get_bool", new=AsyncMock()) as get_bool,
        patch("api.deps.get_redis", return_value=redis),
    ):
        assert await get_registry_user(_request(), user) is user

    get_bool.assert_not_awaited()
    redis.get.assert_awaited_once_with("must_change_password:user-id")


@pytest.mark.asyncio
async def test_public_registry_preserves_required_password_change_gate():
    user = SimpleNamespace(id="user-id")
    redis = MagicMock(get=AsyncMock(return_value="1"))
    with patch("api.deps.get_redis", return_value=redis), pytest.raises(HTTPException) as exc_info:
        await get_registry_user(_request(), user)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Password change required"


def test_public_registry_setting_is_default_off_and_described():
    assert dynamic_settings.DEFAULTS["deployment.public_registry_enabled"] == "false"
    deployment = next(section for section in dynamic_settings.settings_schema() if section["id"] == "deployment")
    setting = next(item for item in deployment["settings"] if item["key"] == "deployment.public_registry_enabled")
    assert setting["default"] == "false"
    assert "signed-out visitors" in setting["subtitle"]


@pytest.mark.asyncio
async def test_public_prompt_render_treats_variable_values_literally():
    listing = SimpleNamespace(id=uuid.UUID(int=1), template=r"Path: {{ value }}", status=ListingStatus.approved)
    with patch("api.routes.prompt.resolve_visible_listing", new=AsyncMock(return_value=listing)):
        result = await prompt.render_prompt(
            "public/prompt",
            PromptRenderRequest(variables={"value": r"C:\new\q"}),
            AsyncMock(),
            None,
        )

    assert result.rendered == r"Path: C:\new\q"


@pytest.mark.asyncio
async def test_public_prompt_render_does_not_reprocess_replacement_placeholders():
    listing = SimpleNamespace(id=uuid.UUID(int=1), template="{{ first }}", status=ListingStatus.approved)
    with patch("api.routes.prompt.resolve_visible_listing", new=AsyncMock(return_value=listing)):
        result = await prompt.render_prompt(
            "public/prompt",
            PromptRenderRequest(variables={"first": "{{ second }}", "second": "secret"}),
            AsyncMock(),
            None,
        )

    assert result.rendered == "{{ second }}"
