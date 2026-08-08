# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Invite links: minting, preview, redemption, and every way a token dies.

An invite authorizes account creation only, while self-registration stays off.
These tests pin the boundaries: admin-only minting, hashed-at-rest tokens,
expiry, revocation, max-uses exhaustion, an oracle-free preview, and
redemption that is atomic with the created account.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.deps import get_current_user, get_db
from api.ratelimit import limiter
from api.routes.admin import router as admin_router
from api.routes.auth import router as auth_router
from models.base import Base
from models.invite import Invite, InviteRedemption
from models.team import Team
from models.user import User, UserRole

_TABLES = [
    User.__table__,
    Team.__table__,
    Invite.__table__,
    InviteRedemption.__table__,
]

_STRONG_PASSWORD = "Str0ng!Passw0rd"

# Self-registration off, password auth allowed — the exact deployment shape
# invites exist for. Individual tests override keys.
_DEFAULT_SETTINGS = {
    "auth.self_registration_enabled": False,
    "deployment.sso_only": False,
}


def _settings(overrides: dict | None = None):
    values = {**_DEFAULT_SETTINGS, **(overrides or {})}

    async def get_bool(key: str, default: bool | None = None) -> bool:
        return values.get(key, bool(default))

    return get_bool


@pytest_asyncio.fixture()
async def sessions():
    limiter.enabled = False
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=_TABLES)
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        limiter.enabled = True


async def _user(db, role=UserRole.user) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex[:8]}@example.test",
        username=uuid.uuid4().hex[:12],
        name="Test User",
        password_hash="x",
        role=role,
    )
    db.add(user)
    await db.flush()
    return user


@asynccontextmanager
async def _client(sessions, actor: User | None = None, settings: dict | None = None):
    async with sessions() as session:
        app = FastAPI()
        app.include_router(auth_router)
        app.include_router(admin_router)
        app.dependency_overrides[get_db] = lambda: session
        if actor is not None:
            app.dependency_overrides[get_current_user] = lambda: actor
        with (
            patch("services.dynamic_settings.get_bool", new=_settings(settings)),
            patch("api.routes.auth._issue_tokens", new=AsyncMock(return_value=("tok", "ref", 3600))),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                yield client, session


async def _admin_and_invite(sessions, *, invite_kwargs: dict | None = None) -> tuple[User, str]:
    """Mint an invite through the API and return (admin, plaintext token)."""
    async with sessions() as db:
        admin = await _user(db, role=UserRole.admin)
        await db.commit()
    async with _client(sessions, actor=admin) as (client, _):
        response = await client.post("/api/v1/admin/invites", json=invite_kwargs or {})
    assert response.status_code == 201, response.text
    return admin, response.json()["token"]


def _register_body(token: str | None = None) -> dict:
    body = {
        # EmailStr refuses reserved TLDs like .test, so registration bodies use
        # example.com while fixture users (never validated) keep .test.
        "email": f"{uuid.uuid4().hex[:8]}@example.com",
        "name": "New Person",
        "password": _STRONG_PASSWORD,
    }
    if token:
        body["invite_token"] = token
    return body


# ── Minting ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_minting_requires_admin(sessions):
    async with sessions() as db:
        admin = await _user(db, role=UserRole.admin)
        plain = await _user(db, role=UserRole.user)
        await db.commit()

    async with _client(sessions, actor=plain) as (client, _):
        forbidden = await client.post("/api/v1/admin/invites", json={})
    assert forbidden.status_code == 403

    async with _client(sessions, actor=admin) as (client, _):
        minted = await client.post("/api/v1/admin/invites", json={"max_uses": 5, "next_path": "/teamspaces/acme"})
    assert minted.status_code == 201
    body = minted.json()
    assert body["state"] == "active"
    assert "/register?invite=" in body["url"]
    assert "next=/teamspaces/acme" in body["url"]

    # Only the hash is stored, and it is not the plaintext.
    async with sessions() as db:
        invite = (await db.execute(select(Invite))).scalar_one()
        assert invite.token_hash != body["token"]
        assert len(invite.token_hash) == 64


@pytest.mark.asyncio
async def test_minting_rejects_unsafe_next_path(sessions):
    async with sessions() as db:
        admin = await _user(db, role=UserRole.admin)
        await db.commit()
    async with _client(sessions, actor=admin) as (client, _):
        response = await client.post("/api/v1/admin/invites", json={"next_path": "//evil.example"})
    assert response.status_code == 422


# ── Preview ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_preview_is_oracle_free(sessions):
    admin, token = await _admin_and_invite(sessions)

    async with _client(sessions) as (client, _):
        valid = await client.post("/api/v1/auth/invite/preview", json={"token": token})
        unknown = await client.post("/api/v1/auth/invite/preview", json={"token": "nope"})
    assert valid.status_code == 200
    assert valid.json()["valid"] is True
    assert valid.json()["invited_by"] == admin.name

    # Unknown and revoked answer the identical shape.
    assert unknown.json() == {"valid": False, "invited_by": None, "next_path": None}


# ── Redemption ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_valid_token_bypasses_closed_registration(sessions):
    _admin, token = await _admin_and_invite(sessions)

    async with _client(sessions) as (client, _):
        closed = await client.post("/api/v1/auth/register", json=_register_body())
        invited = await client.post("/api/v1/auth/register", json=_register_body(token))
    assert closed.status_code == 403
    assert closed.json()["detail"] == "Registration is disabled"
    assert invited.status_code == 200, invited.text
    assert invited.json()["user"]["role"] == "user"

    async with sessions() as db:
        invite = (await db.execute(select(Invite))).scalar_one()
        assert invite.use_count == 1
        redemption = (await db.execute(select(InviteRedemption))).scalar_one()
        assert redemption.invite_id == invite.id
        assert str(redemption.user_id) == invited.json()["user"]["id"]


@pytest.mark.asyncio
async def test_dead_tokens_are_403_with_a_neutral_message(sessions):
    admin, token = await _admin_and_invite(sessions)
    async with _client(sessions, actor=admin) as (client, session):
        invite_id = (await client.get("/api/v1/admin/invites")).json()[0]["id"]
        revoked = await client.post(f"/api/v1/admin/invites/{invite_id}/revoke")
        assert revoked.status_code == 200
        assert revoked.json()["state"] == "revoked"

    async with _client(sessions) as (client, _):
        response = await client.post("/api/v1/auth/register", json=_register_body(token))
    assert response.status_code == 403
    assert response.json()["detail"] == "This invite link is no longer valid"


@pytest.mark.asyncio
async def test_expired_token_is_invalid(sessions):
    _admin, token = await _admin_and_invite(sessions, invite_kwargs={"expires_in_days": 1})
    async with sessions() as db:
        invite = (await db.execute(select(Invite))).scalar_one()
        invite.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()

    async with _client(sessions) as (client, _):
        preview = await client.post("/api/v1/auth/invite/preview", json={"token": token})
        response = await client.post("/api/v1/auth/register", json=_register_body(token))
    assert preview.json()["valid"] is False
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_max_uses_is_exhausted_after_the_last_redemption(sessions):
    _admin, token = await _admin_and_invite(sessions, invite_kwargs={"max_uses": 1})

    async with _client(sessions) as (client, _):
        first = await client.post("/api/v1/auth/register", json=_register_body(token))
        second = await client.post("/api/v1/auth/register", json=_register_body(token))
    assert first.status_code == 200
    assert second.status_code == 403
    assert second.json()["detail"] == "This invite link is no longer valid"

    async with sessions() as db:
        invite = (await db.execute(select(Invite))).scalar_one()
        assert invite.use_count == 1


@pytest.mark.asyncio
async def test_sso_only_blocks_register_even_with_a_token(sessions):
    _admin, token = await _admin_and_invite(sessions)
    async with _client(sessions, settings={"deployment.sso_only": True}) as (client, _):
        response = await client.post("/api/v1/auth/register", json=_register_body(token))
    assert response.status_code == 403
    assert "SSO-only" in response.json()["detail"]


@pytest.mark.asyncio
async def test_sso_only_refuses_to_mint_dead_links(sessions):
    """An invite could never be redeemed on an SSO-only deployment, so minting
    one is refused with an explanation instead of handing out a dead URL."""
    async with sessions() as db:
        admin = await _user(db, role=UserRole.admin)
        await db.commit()
    async with _client(sessions, actor=admin, settings={"deployment.sso_only": True}) as (client, _):
        response = await client.post("/api/v1/admin/invites", json={})
    assert response.status_code == 400
    assert "SSO-only" in response.json()["detail"]


@pytest.mark.asyncio
async def test_open_registration_ignores_a_dead_token(sessions):
    """When self-registration is open, a stale token must not block sign-up."""
    async with _client(sessions, settings={"auth.self_registration_enabled": True}) as (client, _):
        response = await client.post("/api/v1/auth/register", json=_register_body("stale-token"))
    assert response.status_code == 200
