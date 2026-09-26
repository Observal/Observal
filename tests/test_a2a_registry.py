# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Remote A2A agents in discovery: card parsing, registration, review, search and delegation flags."""

from __future__ import annotations

import json

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import services.dynamic_settings as ds
from api.deps import get_current_user, get_db
from api.ratelimit import limiter
from api.routes import ard, ard_imports
from models.discovery_entry import DiscoveryEntry, DiscoveryKind, DiscoveryLifecycle
from models.user import UserRole
from services.discovery import a2a
from services.discovery.projection import reproject_all
from services.discovery.serialize import delegable
from tests import discovery_support as fx

PUBLIC_URL = "https://observal.example.com"
CARD_URL = "https://agents.acme.com/.well-known/agent-card.json"

V1_CARD = {
    "name": "Incident Triage",
    "description": "Triages production incidents. Correlates alerts, deploys and logs.",
    "version": "2.1.0",
    "supportedInterfaces": [
        {"url": "https://agents.acme.com/a2a/v1", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"},
        {"url": "https://agents.acme.com/a2a/grpc", "protocolBinding": "GRPC", "protocolVersion": "1.0"},
    ],
    "provider": {"organization": "Acme SRE", "url": "https://acme.com"},
    "capabilities": {"streaming": True, "pushNotifications": False},
    "securitySchemes": {"bearer": {"httpAuthSecurityScheme": {"scheme": "Bearer"}}},
    "defaultInputModes": ["text/plain"],
    "defaultOutputModes": ["text/plain"],
    "skills": [
        {
            "id": "triage",
            "name": "Triage incident",
            "description": "Find the likely cause of an incident.",
            "tags": ["incident", "sre"],
            "examples": ["why is checkout returning 500s", "triage INC-42"],
        }
    ],
}

V03_CARD = {
    "name": "Legacy Helper",
    "description": "An older agent.",
    "version": "0.9.0",
    "protocolVersion": "0.3.0",
    "url": "https://legacy.acme.com/a2a",
    "preferredTransport": "JSONRPC",
    "additionalInterfaces": [{"url": "https://legacy.acme.com/rest", "transport": "HTTP+JSON"}],
    "skills": [{"id": "help", "name": "Help", "description": "Helps.", "tags": [], "examples": []}],
}


# ── Card parsing ─────────────────────────────────────────────────────────


def test_parse_v1_card_orders_interfaces_by_preference():
    card = a2a.parse_agent_card(V1_CARD)
    assert card.name == "Incident Triage"
    assert [i.binding for i in card.interfaces] == ["JSONRPC", "GRPC"]
    assert card.callable_interface.url == "https://agents.acme.com/a2a/v1"
    assert card.skills[0].examples == ("why is checkout returning 500s", "triage INC-42")
    assert card.security_schemes == ("bearer",)
    assert card.digest.startswith("sha256:")


def test_parse_v03_card_normalises_url_and_transports():
    card = a2a.parse_agent_card(V03_CARD)
    assert [(i.url, i.binding) for i in card.interfaces] == [
        ("https://legacy.acme.com/a2a", "JSONRPC"),
        ("https://legacy.acme.com/rest", "HTTP+JSON"),
    ]
    assert card.callable_interface.protocol_version == "0.3.0"


@pytest.mark.parametrize(
    "raw",
    [
        [],
        {"description": "no name", "supportedInterfaces": [{"url": "https://x.example.com"}]},
        {"name": "No endpoint"},
        {"name": "Bad endpoint", "url": "ftp://x.example.com"},
    ],
)
def test_parse_rejects_unusable_cards(raw):
    with pytest.raises(a2a.AgentCardError):
        a2a.parse_agent_card(raw)


def test_card_url_defaults_to_well_known_path():
    assert a2a.normalize_card_url("https://agents.acme.com") == CARD_URL
    assert a2a.normalize_card_url("https://agents.acme.com/custom/card.json").endswith("/custom/card.json")
    with pytest.raises(a2a.AgentCardError):
        a2a.normalize_card_url("https://user:pw@agents.acme.com/")


def test_card_host_must_be_public_https_unless_allowed(monkeypatch):
    import services.ssrf_guard as guard

    monkeypatch.setattr(guard, "is_private_url", lambda url: "internal" in url)
    a2a.check_card_host("https://agents.acme.com/card.json", frozenset())
    with pytest.raises(a2a.AgentCardError):
        a2a.check_card_host("http://agents.acme.com/card.json", frozenset())
    with pytest.raises(a2a.AgentCardError):
        a2a.check_card_host("https://triage.internal/card.json", frozenset())
    a2a.check_card_host("http://triage.internal/card.json", frozenset({"triage.internal"}))


@pytest.mark.asyncio
async def test_fetch_refuses_redirects_and_oversized_cards(monkeypatch):
    monkeypatch.setattr(a2a, "check_card_host", lambda *_a, **_k: None)

    def redirect(_request):
        return httpx.Response(302, headers={"Location": "http://169.254.169.254/"})

    with pytest.raises(a2a.AgentCardError, match="HTTP 302"):
        await a2a.fetch_agent_card(CARD_URL, transport=httpx.MockTransport(redirect))

    def huge(_request):
        return httpx.Response(200, content=b"{" + b" " * (a2a.MAX_CARD_BYTES + 10) + b"}")

    with pytest.raises(a2a.AgentCardError, match="larger"):
        await a2a.fetch_agent_card(CARD_URL, transport=httpx.MockTransport(huge))

    def ok(_request):
        return httpx.Response(200, json=V1_CARD)

    card, url = await a2a.fetch_agent_card("https://agents.acme.com", transport=httpx.MockTransport(ok))
    assert card.name == "Incident Triage" and url == CARD_URL


def test_identifier_uses_card_host_or_falls_back_to_registry_domain():
    card = a2a.parse_agent_card(V1_CARD)
    import uuid

    entry_id = uuid.uuid4()
    assert a2a.a2a_identifier(card, CARD_URL, "observal.example.com", entry_id) == (
        "urn:air:agents.acme.com:a2a:incident-triage"
    )
    assert a2a.a2a_identifier(card, "http://10.0.0.5:8080/card.json", "observal.example.com", entry_id) == (
        f"urn:air:observal.example.com:a2a:{entry_id}"
    )


# ── Routes ───────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _disable_rate_limits():
    enabled = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = enabled


@pytest.fixture()
def settings(monkeypatch):
    state = {"public": True}

    async def fake_get(key, default=None):
        if key == "deployment.public_url":
            return PUBLIC_URL
        return default or ""

    async def fake_get_bool(key, default=None):
        if key == ard.PUBLIC_SEARCH_SETTING:
            return state["public"]
        return bool(default)

    monkeypatch.setattr(ds, "get", fake_get)
    monkeypatch.setattr(ds, "get_bool", fake_get_bool)
    return state


@pytest.fixture()
def card_server(monkeypatch):
    """Serve cards from a dict instead of the network."""
    cards = {CARD_URL: dict(V1_CARD)}

    async def fake_fetch(url, *, private_hosts=frozenset(), transport=None):
        card_url = a2a.normalize_card_url(url)
        if card_url not in cards:
            raise a2a.AgentCardError("The Agent Card could not be fetched.")
        return a2a.parse_agent_card(cards[card_url]), card_url

    monkeypatch.setattr(ard_imports, "fetch_agent_card", fake_fetch)
    return cards


@pytest_asyncio.fixture()
async def sessions():
    from models.base import Base
    from models.enterprise_config import EnterpriseConfig

    engine = fx.make_engine()
    try:
        factory = await fx.create_schema(engine)
        async with engine.begin() as conn:  # registration pins the publisher domain there
            await conn.run_sync(Base.metadata.create_all, tables=[EnterpriseConfig.__table__])
        yield factory
    finally:
        await engine.dispose()


def _app(sessions, user) -> FastAPI:
    app = FastAPI()
    app.include_router(ard.router)
    app.include_router(ard_imports.router)

    async def db_override():
        async with sessions() as db:
            yield db

    async def user_override():
        return user

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[ard.discovery_user] = user_override
    app.dependency_overrides[get_current_user] = user_override
    return app


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _users(sessions):
    async with sessions() as db:
        owner = await fx.user(db)
        stranger = await fx.user(db)
        reviewer = await fx.user(db, role=UserRole.reviewer)
        await db.commit()
        return owner, stranger, reviewer


async def _search(sessions, user, text="triage production incident"):
    async with _client(_app(sessions, user)) as client:
        resp = await client.post("/api/v1/ard/search", json={"query": {"text": text}, "federation": "none"})
    assert resp.status_code == 200
    return resp.json()["results"]


@pytest.mark.asyncio
async def test_register_review_and_search(sessions, settings, card_server, monkeypatch):
    owner, stranger, reviewer = await _users(sessions)

    async with _client(_app(sessions, owner)) as client:
        resp = await client.post(
            "/api/v1/ard/imports/a2a", json={"cardUrl": "https://agents.acme.com", "visibility": "public"}
        )
    assert resp.status_code == 201, resp.text
    entry = resp.json()
    urn = entry["identifier"]
    assert urn == "urn:air:agents.acme.com:a2a:incident-triage"
    assert entry["type"] == "application/a2a-agent-card+json"
    assert entry["obs:lifecycle"] == "pending"
    assert entry["obs:delegable"] is False
    assert entry["obs:agentCard"]["name"] == "Incident Triage"

    # Pending: invisible to others, visible to its owner.
    assert await _search(sessions, stranger) == []
    assert [r["identifier"] for r in await _search(sessions, owner)] == [urn]

    # Only reviewers may review.
    async with _client(_app(sessions, reviewer)) as client:
        resp = await client.post(f"/api/v1/ard/imports/{urn}/review", json={"action": "approve"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["obs:lifecycle"] == "approved"
    assert resp.json()["obs:delegable"] is True

    results = await _search(sessions, stranger)
    assert [r["identifier"] for r in results] == [urn]
    top = results[0]
    assert top["obs:availability"] == "delegate"
    assert top["obs:delegable"] is True
    assert top["obs:publisher"] == "agents.acme.com"
    assert top["obs:provider"] == "Acme SRE"

    # Fetch the full entry: the reviewed card is pinned inside it.
    async with _client(_app(sessions, stranger)) as client:
        full = (await client.get(f"/api/v1/ard/entries/{urn}")).json()
    assert full["obs:a2aInterface"] == {
        "url": "https://agents.acme.com/a2a/v1",
        "protocolBinding": "JSONRPC",
        "protocolVersion": "1.0",
    }

    # The well-known manifest lists only this deployment's own resources.
    async with _client(_app(sessions, None)) as client:
        manifest = (await client.get("/.well-known/ard.json")).json()
    assert urn not in {e["identifier"] for e in manifest["entries"]}


@pytest.mark.asyncio
async def test_plain_user_cannot_review(sessions, settings, card_server):
    owner, _stranger, _reviewer = await _users(sessions)
    async with _client(_app(sessions, owner)) as client:
        urn = (await client.post("/api/v1/ard/imports/a2a", json={"cardUrl": CARD_URL})).json()["identifier"]
    app = _app(sessions, owner)
    app.dependency_overrides.pop(get_current_user)

    async def as_owner():
        return owner

    app.dependency_overrides[get_current_user] = as_owner
    async with _client(app) as client:
        resp = await client.post(f"/api/v1/ard/imports/{urn}/review", json={"action": "approve"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_changed_card_goes_back_to_review_and_unchanged_stays_approved(sessions, settings, card_server):
    owner, _stranger, reviewer = await _users(sessions)
    async with _client(_app(sessions, owner)) as client:
        urn = (await client.post("/api/v1/ard/imports/a2a", json={"cardUrl": CARD_URL})).json()["identifier"]
    async with _client(_app(sessions, reviewer)) as client:
        await client.post(f"/api/v1/ard/imports/{urn}/review", json={"action": "approve"})

    async with _client(_app(sessions, owner)) as client:
        same = await client.post("/api/v1/ard/imports/a2a", json={"cardUrl": CARD_URL})
    assert same.status_code == 200 and same.json()["obs:lifecycle"] == "approved"

    card_server[CARD_URL] = {**V1_CARD, "supportedInterfaces": [{"url": "https://evil.example.net/a2a"}]}
    async with _client(_app(sessions, owner)) as client:
        changed = await client.post("/api/v1/ard/imports/a2a", json={"cardUrl": CARD_URL})
    assert changed.json()["obs:lifecycle"] == "pending"
    assert changed.json()["obs:delegable"] is False


@pytest.mark.asyncio
async def test_someone_else_cannot_take_over_a_registered_card(sessions, settings, card_server):
    owner, stranger, _reviewer = await _users(sessions)
    async with _client(_app(sessions, owner)) as client:
        await client.post("/api/v1/ard/imports/a2a", json={"cardUrl": CARD_URL})
    async with _client(_app(sessions, stranger)) as client:
        resp = await client.post("/api/v1/ard/imports/a2a", json={"cardUrl": CARD_URL})
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_rejection_needs_reason_and_removal_is_owner_only(sessions, settings, card_server):
    owner, stranger, reviewer = await _users(sessions)
    async with _client(_app(sessions, owner)) as client:
        urn = (await client.post("/api/v1/ard/imports/a2a", json={"cardUrl": CARD_URL})).json()["identifier"]
    async with _client(_app(sessions, reviewer)) as client:
        assert (await client.post(f"/api/v1/ard/imports/{urn}/review", json={"action": "reject"})).status_code == 400
        resp = await client.post(
            f"/api/v1/ard/imports/{urn}/review", json={"action": "reject", "reason": "No auth on the endpoint"}
        )
    assert resp.json()["obs:lifecycle"] == "rejected"
    assert resp.json()["obs:reviewNote"] == "No auth on the endpoint"

    async with _client(_app(sessions, stranger)) as client:
        assert (await client.delete(f"/api/v1/ard/imports/{urn}")).status_code == 403
    async with _client(_app(sessions, owner)) as client:
        assert (await client.delete(f"/api/v1/ard/imports/{urn}")).status_code == 200
        assert (await client.get("/api/v1/ard/imports")).json()["items"] == []


@pytest.mark.asyncio
async def test_team_visibility_requires_membership(sessions, settings, card_server):
    owner, stranger, _reviewer = await _users(sessions)
    async with sessions() as db:
        team = await fx.team_with_member(db, owner)
        await db.commit()
    body = {"cardUrl": CARD_URL, "visibility": "team", "teamId": str(team.id)}
    async with _client(_app(sessions, stranger)) as client:
        assert (await client.post("/api/v1/ard/imports/a2a", json=body)).status_code == 403
    async with _client(_app(sessions, owner)) as client:
        resp = await client.post("/api/v1/ard/imports/a2a", json=body)
    assert resp.status_code == 201 and resp.json()["obs:visibility"] == "team"


@pytest.mark.asyncio
async def test_bad_card_is_a_clear_422(sessions, settings, card_server):
    owner, _stranger, _reviewer = await _users(sessions)
    async with _client(_app(sessions, owner)) as client:
        resp = await client.post("/api/v1/ard/imports/a2a", json={"cardUrl": "https://nowhere.example.com"})
    assert resp.status_code == 422
    assert resp.json()["errorCode"] == "INVALID_AGENT_CARD"


# ── Delegable flag on native agents ──────────────────────────────────────


@pytest.mark.asyncio
async def test_native_agents_are_delegable_when_a_supported_harness_runs_headless(sessions):
    async with sessions() as db:
        owner = await fx.user(db)
        skill = await fx.skill(db, owner)
        await fx.agent(db, owner, components=[("skill", skill.id, "Security Review")])
        await reproject_all(db, ctx=fx.CTX)
        from sqlalchemy import select

        entries = (await db.execute(select(DiscoveryEntry))).scalars().all()
    by_kind = {e.kind: e for e in entries}
    agent_entry = by_kind[DiscoveryKind.agent]
    assert agent_entry.lifecycle_status == DiscoveryLifecycle.approved
    agent_entry.supported_harnesses = ["claude-code"]
    assert delegable(agent_entry) is True
    agent_entry.supported_harnesses = ["goose", "copilot"]  # neither has a verified headless mode
    assert delegable(agent_entry) is False
    assert delegable(by_kind[DiscoveryKind.skill]) is False


def test_delegation_mcp_entry_shape():
    from types import SimpleNamespace

    from services.harness import helpers

    agent = SimpleNamespace(id="11111111-2222-3333-4444-555555555555")
    entry = helpers._build_delegation_mcp_entry(agent, "kiro")
    assert entry == {
        "observal-agents": {
            "command": "python3",
            "args": [
                "-m",
                "observal_cli.delegation.mcp_server",
                "--harness",
                "kiro",
                "--parent-id",
                "11111111-2222-3333-4444-555555555555",
            ],
            "env": {},
        }
    }
    assert json.dumps(entry)  # serialisable into every harness config format
