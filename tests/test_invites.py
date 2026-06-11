# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for the teammate invite feature.

Covers:
- invite creation (link + email-pinned channels, role ceiling, dedupe)
- token storage (raw token never persisted, only SHA-256 hash)
- public lookup (uniform valid=false responses, never 404)
- acceptance flow (account creation, pinned-email enforcement, single use)
- revocation
- bus events (InviteSent / InviteAccepted / UserCreated utm_source=invite)
- PostHog handler contract (invite_sent / invite_accepted)
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import services.product_analytics_handlers as handlers
from models.base import Base
from models.invite import Invite, InviteChannel
from models.organization import Organization
from models.user import User, UserRole
from services.events import InviteAccepted, InviteSent, UserCreated

STRONG_PASSWORD = "Str0ng!Passw0rd42"


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture()
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture()
async def org(db):
    org = Organization(name="Acme Corp", slug="acme-corp")
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return org


@pytest.fixture()
async def admin(db, org):
    user = User(
        email="admin@example.com",
        username="acme-admin",
        name="Acme Admin",
        role=UserRole.admin,
        org_id=org.id,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


class _RecordingBus:
    def __init__(self):
        self.events = []

    async def emit(self, event):
        self.events.append(event)


@pytest.fixture()
def emitted(monkeypatch):
    """Replace the route module's bus with a recorder."""
    import api.routes.invite as invite_routes

    recorder = _RecordingBus()
    monkeypatch.setattr(invite_routes, "bus", recorder)
    return recorder.events


@pytest.fixture()
def client(db, admin, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    import api.routes.invite as invite_routes
    from api.deps import get_current_user, get_db, require_password_auth
    from api.ratelimit import limiter
    from main import app

    limiter.enabled = False
    monkeypatch.setattr(invite_routes, "emit_security_event", AsyncMock())

    async def _fake_db():
        yield db

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[require_password_auth] = lambda: None

    yield AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    )
    app.dependency_overrides.clear()


# ── Create ───────────────────────────────────────────────────────────


class TestCreate:
    @pytest.mark.asyncio
    async def test_create_link_invite(self, client, db, emitted):
        async with client as c:
            r = await c.post("/api/v1/invites", json={})
        assert r.status_code == 200
        body = r.json()
        assert body["channel"] == "link"
        assert body["email"] is None
        assert body["status"] == "pending"
        assert body["token"]
        assert f"/invite/{body['token']}" in body["invite_url"]

        # Raw token is never persisted, only its hash
        invite = (await db.execute(select(Invite))).scalar_one()
        assert invite.token_hash != body["token"]
        assert len(invite.token_hash) == 64

        sent = [e for e in emitted if isinstance(e, InviteSent)]
        assert len(sent) == 1
        assert sent[0].channel == "link"

    @pytest.mark.asyncio
    async def test_create_email_invite(self, client, emitted):
        async with client as c:
            r = await c.post("/api/v1/invites", json={"email": "new@example.com", "role": "reviewer"})
        assert r.status_code == 200
        body = r.json()
        assert body["channel"] == "email"
        assert body["email"] == "new@example.com"
        assert body["role"] == "reviewer"
        assert [e.channel for e in emitted if isinstance(e, InviteSent)] == ["email"]

    @pytest.mark.asyncio
    async def test_duplicate_pending_email_invite_rejected(self, client):
        async with client as c:
            r1 = await c.post("/api/v1/invites", json={"email": "dup@example.com"})
            r2 = await c.post("/api/v1/invites", json={"email": "dup@example.com"})
        assert r1.status_code == 200
        assert r2.status_code == 409

    @pytest.mark.asyncio
    async def test_existing_user_email_rejected(self, client, admin):
        async with client as c:
            r = await c.post("/api/v1/invites", json={"email": admin.email})
        assert r.status_code == 409

    @pytest.mark.asyncio
    async def test_cannot_invite_above_own_role(self, client):
        async with client as c:
            r = await c.post("/api/v1/invites", json={"role": "super_admin"})
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_invalid_role_rejected(self, client):
        async with client as c:
            r = await c.post("/api/v1/invites", json={"role": "emperor"})
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_anonymous_rejected(self, db):
        from httpx import ASGITransport, AsyncClient

        from main import app

        app.dependency_overrides.clear()
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
        ) as c:
            r = await c.post("/api/v1/invites", json={})
        assert r.status_code == 401


# ── List / revoke ────────────────────────────────────────────────────


class TestListRevoke:
    @pytest.mark.asyncio
    async def test_list_and_revoke(self, client, emitted):
        async with client as c:
            created = (await c.post("/api/v1/invites", json={})).json()

            listed = await c.get("/api/v1/invites")
            assert listed.status_code == 200
            assert [i["id"] for i in listed.json()] == [created["id"]]

            revoked = await c.delete(f"/api/v1/invites/{created['id']}")
            assert revoked.status_code == 204

            after = (await c.get("/api/v1/invites")).json()
            assert after[0]["status"] == "revoked"

    @pytest.mark.asyncio
    async def test_revoke_unknown_invite_404(self, client):
        async with client as c:
            r = await c.delete(f"/api/v1/invites/{uuid.uuid4()}")
        assert r.status_code == 404


# ── Lookup ───────────────────────────────────────────────────────────


class TestLookup:
    @pytest.mark.asyncio
    async def test_lookup_unknown_token_is_uniform(self, client):
        async with client as c:
            r = await c.get("/api/v1/invites/lookup/this-token-does-not-exist")
        assert r.status_code == 200
        assert r.json() == {
            "valid": False,
            "reason": "not_found",
            "org_name": None,
            "email": None,
            "role": None,
            "expires_at": None,
        }

    @pytest.mark.asyncio
    async def test_lookup_pending_invite(self, client, org):
        async with client as c:
            created = (await c.post("/api/v1/invites", json={"email": "peek@example.com"})).json()
            r = await c.get(f"/api/v1/invites/lookup/{created['token']}")
        body = r.json()
        assert body["valid"] is True
        assert body["org_name"] == org.name
        assert body["email"] == "peek@example.com"

    @pytest.mark.asyncio
    async def test_lookup_revoked_invite(self, client):
        async with client as c:
            created = (await c.post("/api/v1/invites", json={})).json()
            await c.delete(f"/api/v1/invites/{created['id']}")
            r = await c.get(f"/api/v1/invites/lookup/{created['token']}")
        assert r.json()["valid"] is False
        assert r.json()["reason"] == "revoked"


# ── Accept ───────────────────────────────────────────────────────────


@pytest.fixture()
def issue_tokens(monkeypatch):
    import api.routes.auth as auth_routes

    monkeypatch.setattr(auth_routes, "_issue_tokens", AsyncMock(return_value=("access-token", "refresh-token", 900)))


class TestAccept:
    @pytest.mark.asyncio
    async def test_accept_link_invite_creates_user(self, client, db, org, emitted, issue_tokens):
        async with client as c:
            created = (await c.post("/api/v1/invites", json={"role": "reviewer"})).json()
            r = await c.post(
                "/api/v1/invites/accept",
                json={
                    "token": created["token"],
                    "email": "joiner@example.com",
                    "name": "Joiner",
                    "password": STRONG_PASSWORD,
                },
            )
        assert r.status_code == 200
        body = r.json()
        assert body["access_token"] == "access-token"
        assert body["user"]["email"] == "joiner@example.com"

        user = (await db.execute(select(User).where(User.email == "joiner@example.com"))).scalar_one()
        assert user.role == UserRole.reviewer
        assert user.org_id == org.id

        # Signup attribution is forced to the invite loop
        signups = [e for e in emitted if isinstance(e, UserCreated)]
        assert len(signups) == 1
        assert signups[0].utm_source == "invite"
        accepted = [e for e in emitted if isinstance(e, InviteAccepted)]
        assert len(accepted) == 1
        assert accepted[0].user_id == str(user.id)

    @pytest.mark.asyncio
    async def test_accept_is_single_use(self, client, issue_tokens):
        async with client as c:
            created = (await c.post("/api/v1/invites", json={})).json()
            first = await c.post(
                "/api/v1/invites/accept",
                json={
                    "token": created["token"],
                    "email": "first@example.com",
                    "name": "First",
                    "password": STRONG_PASSWORD,
                },
            )
            second = await c.post(
                "/api/v1/invites/accept",
                json={
                    "token": created["token"],
                    "email": "second@example.com",
                    "name": "Second",
                    "password": STRONG_PASSWORD,
                },
            )
        assert first.status_code == 200
        assert second.status_code == 410

    @pytest.mark.asyncio
    async def test_accept_pinned_email_mismatch_rejected(self, client, issue_tokens):
        async with client as c:
            created = (await c.post("/api/v1/invites", json={"email": "pinned@example.com"})).json()
            r = await c.post(
                "/api/v1/invites/accept",
                json={
                    "token": created["token"],
                    "email": "other@example.com",
                    "name": "Other",
                    "password": STRONG_PASSWORD,
                },
            )
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_accept_link_invite_requires_email(self, client, issue_tokens):
        async with client as c:
            created = (await c.post("/api/v1/invites", json={})).json()
            r = await c.post(
                "/api/v1/invites/accept",
                json={"token": created["token"], "name": "NoEmail", "password": STRONG_PASSWORD},
            )
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_accept_revoked_invite_410(self, client, issue_tokens):
        async with client as c:
            created = (await c.post("/api/v1/invites", json={})).json()
            await c.delete(f"/api/v1/invites/{created['id']}")
            r = await c.post(
                "/api/v1/invites/accept",
                json={
                    "token": created["token"],
                    "email": "late@example.com",
                    "name": "Late",
                    "password": STRONG_PASSWORD,
                },
            )
        assert r.status_code == 410

    @pytest.mark.asyncio
    async def test_accept_unknown_token_404(self, client, issue_tokens):
        async with client as c:
            r = await c.post(
                "/api/v1/invites/accept",
                json={
                    "token": "x" * 43,
                    "email": "ghost@example.com",
                    "name": "Ghost",
                    "password": STRONG_PASSWORD,
                },
            )
        assert r.status_code == 404


# ── Model status lifecycle ───────────────────────────────────────────


class TestStatus:
    def _invite(self, **kw) -> Invite:
        defaults = dict(
            org_id=uuid.uuid4(),
            role=UserRole.user,
            channel=InviteChannel.link,
            token_hash="h" * 64,
            expires_at=datetime.now(UTC) + timedelta(days=7),
            revoked=False,
        )
        defaults.update(kw)
        return Invite(**defaults)

    def test_pending(self):
        assert self._invite().status == "pending"

    def test_expired(self):
        assert self._invite(expires_at=datetime.now(UTC) - timedelta(minutes=1)).status == "expired"

    def test_revoked_wins_over_everything(self):
        inv = self._invite(revoked=True, accepted_at=datetime.now(UTC))
        assert inv.status == "revoked"

    def test_accepted(self):
        assert self._invite(accepted_at=datetime.now(UTC)).status == "accepted"


# ── PostHog handler contract ─────────────────────────────────────────


@pytest.fixture
def captured(monkeypatch):
    events: list[tuple[str, str, dict]] = []

    async def fake_capture(distinct_id, event, properties=None):
        events.append((distinct_id, event, properties or {}))

    async def not_private(_org_id):
        return False

    monkeypatch.setattr(handlers.product_analytics, "is_enabled", lambda: True)
    monkeypatch.setattr(handlers.product_analytics, "capture", fake_capture)
    monkeypatch.setattr(handlers, "org_trace_private", not_private)
    return events


class TestAnalyticsContract:
    @pytest.mark.asyncio
    async def test_invite_sent_contract(self, captured):
        await handlers._capture_invite_sent(
            InviteSent(invite_id="inv-1", org_id="org-1", channel="email", invited_by="admin-1")
        )
        assert captured == [("admin-1", "invite_sent", {"workspace_id": "org-1", "invite_channel": "email"})]

    @pytest.mark.asyncio
    async def test_invite_accepted_contract(self, captured):
        await handlers._capture_invite_accepted(InviteAccepted(invite_id="inv-1", org_id="org-1", user_id="user-1"))
        assert captured == [("user-1", "invite_accepted", {"workspace_id": "org-1"})]

    @pytest.mark.asyncio
    async def test_handlers_respect_disable_gate(self, monkeypatch, captured):
        monkeypatch.setattr(handlers.product_analytics, "is_enabled", lambda: False)
        await handlers._capture_invite_sent(InviteSent(invite_id="i", org_id="o", channel="link", invited_by="a"))
        await handlers._capture_invite_accepted(InviteAccepted(invite_id="i", org_id="o", user_id="u"))
        assert captured == []

    @pytest.mark.asyncio
    async def test_trace_private_org_drops_invite_events(self, monkeypatch, captured):
        async def private(_org_id):
            return True

        monkeypatch.setattr(handlers, "org_trace_private", private)
        await handlers._capture_invite_sent(InviteSent(invite_id="i", org_id="o", channel="link", invited_by="a"))
        await handlers._capture_invite_accepted(InviteAccepted(invite_id="i", org_id="o", user_id="u"))
        assert captured == []
