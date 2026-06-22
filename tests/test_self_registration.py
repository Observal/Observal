# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True, scope="module")
def _init_key_manager(tmp_path_factory):
    from services.crypto import init_key_manager

    key_dir = tmp_path_factory.mktemp("keys")
    init_key_manager(key_dir=str(key_dir), key_password=None)


def _client():
    from httpx import ASGITransport, AsyncClient

    from api.ratelimit import limiter
    from main import app

    limiter.enabled = False
    return AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test")


def _db_override():
    from api.deps import get_db
    from main import app

    db = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()

    async def refresh(user):
        user.id = uuid.uuid4()
        user.created_at = datetime.now(UTC)

    db.refresh = AsyncMock(side_effect=refresh)

    async def get_mock_db():
        yield db

    app.dependency_overrides[get_db] = get_mock_db
    return db


def _cleanup():
    from main import app

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_register_disabled_returns_403():
    _db_override()
    try:

        async def get_bool(key):
            return False

        with patch("api.routes.auth.ds.get_bool", new=AsyncMock(side_effect=get_bool)):
            async with _client() as client:
                resp = await client.post(
                    "/api/v1/auth/register",
                    json={
                        "email": "new@example.com",
                        "name": "New User",
                        "password": "Str0ng!P",
                    },
                )

        assert resp.status_code == 403
        assert resp.json()["detail"] == "Registration is disabled"
    finally:
        _cleanup()


@pytest.mark.asyncio
async def test_register_creates_user_role():
    from models.user import UserRole

    db = _db_override()
    org_id = uuid.uuid4()
    try:

        async def get_bool(key):
            return key == "auth.self_registration_enabled"

        with (
            patch("api.routes.auth.ds.get_bool", new=AsyncMock(side_effect=get_bool)),
            patch("api.routes.auth.get_or_create_default_org", new=AsyncMock(return_value=SimpleNamespace(id=org_id))),
            patch("api.routes.auth._issue_tokens", new=AsyncMock(return_value=("access", "refresh", 3600))),
            patch("api.routes.auth.emit_security_event", new=AsyncMock()),
        ):
            async with _client() as client:
                resp = await client.post(
                    "/api/v1/auth/register",
                    json={
                        "email": "new@example.com",
                        "name": "New User",
                        "username": "new-user",
                        "password": "Str0ng!P",
                    },
                )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["user"]["role"] == UserRole.user.value
        assert body["access_token"] == "access"
        db.add.assert_called_once()
        created_user = db.add.call_args.args[0]
        assert created_user.email == "new@example.com"
        assert created_user.role == UserRole.user
        assert created_user.org_id == org_id
    finally:
        _cleanup()
