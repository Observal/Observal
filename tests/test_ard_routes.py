# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""ARD endpoints, artifact endpoint, and conformance against the vendored spec tool."""

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.pool import NullPool

import services.dynamic_settings as ds
from api.deps import get_db
from api.ratelimit import limiter
from api.routes import ard, artifacts
from models.discovery_entry import DiscoveryKind
from models.mcp import ListingStatus
from services.discovery.projection import reproject_all
from tests import discovery_support as fx

VENDOR = Path(__file__).resolve().parents[1] / "observal-server" / "vendor" / "ard"
CONFORMANCE_TOOL = VENDOR / "conformance" / "bin" / "conformance-test"
PUBLIC_URL = "https://observal.example.com"


@pytest.fixture(autouse=True)
def _disable_rate_limits():
    enabled = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = enabled


@pytest.fixture()
def settings(monkeypatch):
    """Patch dynamic settings: public URL fixed, public search toggled per test."""
    state = {"public": False}

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


@pytest_asyncio.fixture()
async def sessions():
    engine = fx.make_engine()
    try:
        yield await fx.create_schema(engine)
    finally:
        await engine.dispose()


def _app(sessions, user=None) -> FastAPI:
    app = FastAPI()
    app.include_router(ard.router)
    app.include_router(artifacts.router)

    async def db_override():
        async with sessions() as db:
            yield db

    async def user_override():
        return user

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[ard.discovery_user] = user_override
    return app


async def _seed(sessions):
    async with sessions() as db:
        owner = await fx.user(db)
        stranger = await fx.user(db)
        skill = await fx.skill(db, owner)
        await fx.skill(db, owner, name="Draft Skill", slug="draft-skill", status=ListingStatus.pending)
        await fx.skill(db, owner, name="Secret Skill", slug="secret-skill", is_private=True)
        mcp = await fx.mcp(db, owner)
        await fx.prompt(db, owner)
        await fx.hook(db, owner)
        await fx.sandbox(db, owner)
        await fx.agent(db, owner, components=[("skill", skill.id, "Security Review"), ("mcp", mcp.id, "GitHub")])
        await reproject_all(db, ctx=fx.CTX)
        return owner, stranger, skill


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ── Search ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_response_shape(sessions, settings):
    owner, _, skill = await _seed(sessions)
    async with _client(_app(sessions, owner)) as client:
        resp = await client.post(
            "/api/v1/ard/search",
            json={"query": {"text": "review pull request authentication"}, "federation": "none", "pageSize": 3},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) <= {"results", "pageToken", "referrals"}
    assert body["results"]
    top = body["results"][0]
    assert top["identifier"] == f"urn:air:observal.example.com:skill:{skill.id}"
    assert isinstance(top["score"], int) and 0 <= top["score"] <= 100
    assert top["source"] == f"{PUBLIC_URL}/api/v1/ard"
    assert top["type"] == "application/ai-skill+md"
    assert top["obs:approval"] == "approved"
    assert top["obs:availability"] == "now"
    assert top["matchedOn"]
    assert "SHOULD-NEVER-LEAK" not in resp.text


@pytest.mark.asyncio
async def test_search_referrals_mode_returns_an_explicit_empty_list(sessions, settings):
    owner, _, _ = await _seed(sessions)
    async with _client(_app(sessions, owner)) as client:
        resp = await client.post("/api/v1/ard/search", json={"query": {"text": "review"}, "federation": "referrals"})
    assert resp.status_code == 200
    assert resp.json()["referrals"] == []


@pytest.mark.asyncio
async def test_search_requires_text(sessions, settings):
    owner, _, _ = await _seed(sessions)
    async with _client(_app(sessions, owner)) as client:
        resp = await client.post(
            "/api/v1/ard/search", json={"query": {"filter": {"type": ["application/ai-skill+md"]}}}
        )
    assert resp.status_code == 400
    assert resp.json() == {"errorCode": "INVALID_ARGUMENT", "message": "query.text is required"}


@pytest.mark.asyncio
async def test_search_rejects_unknown_filter_and_bad_page_token(sessions, settings):
    owner, _, _ = await _seed(sessions)
    async with _client(_app(sessions, owner)) as client:
        resp = await client.post("/api/v1/ard/search", json={"query": {"text": "x", "filter": {"nope": ["y"]}}})
        assert resp.status_code == 400 and resp.json()["errorCode"] == "INVALID_ARGUMENT"
        resp = await client.post("/api/v1/ard/search", json={"query": {"text": "review"}, "pageToken": "garbage"})
        assert resp.status_code == 400


@pytest.mark.asyncio
async def test_search_anonymous_is_closed_until_public_search_is_on(sessions, settings):
    await _seed(sessions)
    async with _client(_app(sessions, None)) as client:
        closed = await client.post("/api/v1/ard/search", json={"query": {"text": "security review"}})
        assert closed.status_code == 200 and closed.json()["results"] == []
        settings["public"] = True
        opened = await client.post("/api/v1/ard/search", json={"query": {"text": "security review"}})
        names = [r["displayName"] for r in opened.json()["results"]]
        assert "Security Review" in names
        assert "Secret Skill" not in names and "Draft Skill" not in names


@pytest.mark.asyncio
async def test_search_owner_sees_own_pending_and_private(sessions, settings):
    owner, stranger, _ = await _seed(sessions)
    async with _client(_app(sessions, owner)) as client:
        resp = await client.post("/api/v1/ard/search", json={"query": {"text": "skill"}, "pageSize": 20})
    names = {r["displayName"] for r in resp.json()["results"]}
    assert {"Draft Skill", "Secret Skill"} <= names
    async with _client(_app(sessions, stranger)) as client:
        resp = await client.post("/api/v1/ard/search", json={"query": {"text": "skill"}, "pageSize": 20})
    names = {r["displayName"] for r in resp.json()["results"]}
    assert not ({"Draft Skill", "Secret Skill"} & names)


@pytest.mark.asyncio
async def test_search_harness_filter_marks_availability(sessions, settings):
    owner, _, _ = await _seed(sessions)
    async with _client(_app(sessions, owner)) as client:
        resp = await client.post(
            "/api/v1/ard/search",
            json={"query": {"text": "release notes", "filter": {"obs:supportedHarnesses": ["copilot-cli"]}}},
        )
    results = resp.json()["results"]
    assert results and results[0]["displayName"] == "Release Notes"
    assert results[0]["obs:availability"] == "now"


@pytest.mark.asyncio
async def test_explore_is_501(sessions, settings):
    async with _client(_app(sessions, None)) as client:
        resp = await client.post("/api/v1/ard/explore", json={"query": {"text": "x"}, "resultType": {"facets": []}})
    assert resp.status_code == 501
    assert resp.json()["errorCode"] == "NOT_IMPLEMENTED"


# ── List ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_is_deterministic_and_filterable(sessions, settings):
    owner, _, _ = await _seed(sessions)
    async with _client(_app(sessions, owner)) as client:
        resp = await client.get("/api/v1/ard/agents", params={"pageSize": 3})
        body = resp.json()
        assert resp.status_code == 200
        assert [i["displayName"] for i in body["items"]] == sorted(i["displayName"] for i in body["items"])
        assert body["total"] == 8 and body["pageToken"]

        rest = await client.get("/api/v1/ard/agents", params={"pageSize": 3, "pageToken": body["pageToken"]})
        assert rest.status_code == 200 and len(rest.json()["items"]) == 3

        filtered = await client.get(
            "/api/v1/ard/agents", params={"filter": "type = 'application/mcp-server-card+json'"}
        )
        assert [i["displayName"] for i in filtered.json()["items"]] == ["GitHub"]

        ordered = await client.get("/api/v1/ard/agents", params={"orderBy": "displayName DESC", "pageSize": 1})
        assert ordered.json()["items"][0]["displayName"] == "Security Review"

        bad = await client.get("/api/v1/ard/agents", params={"filter": "colour = 'blue'"})
        assert bad.status_code == 400
        empty = await client.get("/api/v1/ard/agents", params={"filter": "displayName=,,,"})
        assert empty.status_code == 400 and empty.json()["errorCode"] == "INVALID_ARGUMENT"


@pytest.mark.asyncio
async def test_list_anonymous_closed(sessions, settings):
    await _seed(sessions)
    async with _client(_app(sessions, None)) as client:
        resp = await client.get("/api/v1/ard/agents")
    assert resp.json() == {"items": [], "total": 0}


# ── Entry by identifier ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_entry_by_identifier_and_legacy_prefix(sessions, settings):
    owner, stranger, skill = await _seed(sessions)
    urn = f"urn:air:observal.example.com:skill:{skill.id}"
    async with _client(_app(sessions, owner)) as client:
        resp = await client.get(f"/api/v1/ard/entries/{urn}")
        assert resp.status_code == 200
        assert resp.json()["identifier"] == urn
        assert resp.json()["representativeQueries"]
        legacy = await client.get(f"/api/v1/ard/entries/{urn.replace('urn:air:', 'urn:ai:')}")
        assert legacy.status_code == 200
        missing = await client.get("/api/v1/ard/entries/urn:air:observal.example.com:skill:nope")
        assert missing.status_code == 404 and missing.json()["errorCode"] == "NOT_FOUND"


# ── Manifest ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_manifest_publishes_registry_entry_and_public_resources(sessions, settings):
    await _seed(sessions)
    async with _client(_app(sessions, None)) as client:
        closed = (await client.get("/.well-known/ard.json")).json()
        assert [e["type"] for e in closed["entries"]] == ["application/ai-registry+json"]
        assert closed["entries"][0]["url"] == f"{PUBLIC_URL}/api/v1/ard"

        settings["public"] = True
        opened = (await client.get("/.well-known/ard.json")).json()
        names = [e["displayName"] for e in opened["entries"][1:]]
        assert "Security Review" in names and "GitHub" in names
        assert "Draft Skill" not in names and "Secret Skill" not in names

        legacy = (await client.get("/.well-known/ai-catalog.json")).json()
        assert legacy == opened


# ── Artifacts ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_artifact_serves_bytes_with_digest(sessions, settings):
    owner, _, skill = await _seed(sessions)
    async with _client(_app(sessions, owner)) as client:
        resp = await client.get(f"/api/v1/artifacts/skill/{skill.id}/1.2.0")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert resp.headers["Digest"].startswith("sha-256=")
    assert resp.headers["X-Artifact-Digest"].startswith("sha256:")
    assert resp.headers["Cache-Control"].startswith("public")
    assert "Look for auth bugs" in resp.text


@pytest.mark.asyncio
async def test_artifact_hides_unapproved_versions_from_non_owners(sessions, settings):
    owner, stranger, skill = await _seed(sessions)
    async with sessions() as db:
        row = await db.get(type(skill), skill.id)
        await fx.add_skill_version(db, row, owner, version="1.3.0", status=ListingStatus.pending, set_latest=False)
        await db.commit()
    async with _client(_app(sessions, stranger)) as client:
        assert (await client.get(f"/api/v1/artifacts/skill/{skill.id}/1.3.0")).status_code == 404
        assert (await client.get(f"/api/v1/artifacts/skill/{skill.id}/1.2.0")).status_code == 200
    async with _client(_app(sessions, owner)) as client:
        assert (await client.get(f"/api/v1/artifacts/skill/{skill.id}/1.3.0")).status_code == 200


@pytest.mark.asyncio
async def test_artifact_anonymous_and_unknown(sessions, settings):
    _, _, skill = await _seed(sessions)
    async with _client(_app(sessions, None)) as client:
        assert (await client.get(f"/api/v1/artifacts/skill/{skill.id}/1.2.0")).status_code == 404
        settings["public"] = True
        assert (await client.get(f"/api/v1/artifacts/skill/{skill.id}/1.2.0")).status_code == 200
        assert (await client.get(f"/api/v1/artifacts/skill/{skill.id}/9.9.9")).status_code == 404
        assert (await client.get(f"/api/v1/artifacts/rocket/{skill.id}/1.2.0")).status_code == 404


@pytest.mark.asyncio
async def test_mcp_artifact_never_contains_env_values(sessions, settings):
    owner, _, _ = await _seed(sessions)
    async with sessions() as db:
        from sqlalchemy import select

        from models.discovery_entry import DiscoveryEntry

        entry = (await db.execute(select(DiscoveryEntry).where(DiscoveryEntry.kind == DiscoveryKind.mcp))).scalar_one()
    async with _client(_app(sessions, owner)) as client:
        resp = await client.get(f"/api/v1/artifacts/mcp/{entry.local_entity_id}/{entry.version}")
    assert resp.status_code == 200
    card = resp.json()
    assert card["environmentVariables"] == ["GITHUB_TOKEN"]
    assert "SHOULD-NEVER-LEAK" not in resp.text
    assert resp.headers["X-Artifact-Digest"] == entry.artifact_digest


# ── Conformance ──────────────────────────────────────────────────────────


def _run_tool(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(CONFORMANCE_TOOL), *args], capture_output=True, text=True, timeout=120)


@pytest.mark.asyncio
async def test_manifest_passes_official_conformance(sessions, settings, tmp_path):
    await _seed(sessions)
    settings["public"] = True
    async with _client(_app(sessions, None)) as client:
        manifest = (await client.get("/.well-known/ard.json")).json()
    assert len(manifest["entries"]) >= 7
    path = tmp_path / "ard.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    result = _run_tool("manifest", str(path))
    assert result.returncode == 0, result.stdout
    assert "CONFORMANCE STATUS: PASS" in result.stdout
    assert "critical specification errors" in result.stdout and " 0 critical" in result.stdout


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.mark.asyncio
async def test_registry_api_passes_official_conformance(settings, tmp_path):
    """Run the tool's registry mode against a live server backed by a file SQLite database."""
    import uvicorn

    db_path = tmp_path / "registry.sqlite"
    engine = fx.make_engine(f"sqlite+aiosqlite:///{db_path}", poolclass=NullPool)
    sessions = await fx.create_schema(engine)
    owner, _, _ = await _seed(sessions)
    settings["public"] = True

    app = _app(sessions, owner)
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", loop="asyncio")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.time() + 15
        while not server.started and time.time() < deadline:
            await asyncio.sleep(0.05)
        assert server.started, "uvicorn did not start"
        result = await asyncio.to_thread(_run_tool, "registry", f"http://127.0.0.1:{port}/api/v1/ard")
        assert result.returncode == 0, result.stdout
        assert "CONFORMANCE STATUS: PASS" in result.stdout
        assert "POST /search responded successfully" in result.stdout
        assert "GET /agents responded successfully" in result.stdout
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        await engine.dispose()


# ── List filter parser ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("clause", "expected"),
    [
        ("type = 'application/ai-skill+md'", ("type", "=", "'application/ai-skill+md'")),
        ("createdAfter>='2026-01-01'", ("createdAfter", ">=", "'2026-01-01'")),
        ("  displayName   =   Review  ", ("displayName", "=", "Review")),
        ("publisherId = a.com,b.com", ("publisherId", "=", "a.com,b.com")),
    ],
)
def test_parse_clause_accepts_spec_shapes(clause, expected):
    assert ard._parse_clause(clause.strip()) == expected


@pytest.mark.parametrize("clause", ["= x", "type", "type ~ x", "type =", "1abc = x"])
def test_parse_clause_rejects_malformed(clause):
    with pytest.raises(ard.InvalidSearchRequestError):
        ard._parse_clause(clause)


def test_split_clauses_is_case_insensitive_and_ignores_blanks():
    assert ard._split_clauses("type = a and displayName = b AND  ") == ["type = a", "displayName = b"]


def test_split_clauses_keeps_and_inside_quotes():
    assert ard._split_clauses("displayName = 'Research AND Development' AND type = x") == [
        "displayName = 'Research AND Development'",
        "type = x",
    ]
    assert ard._split_clauses('displayName = "a and b"') == ['displayName = "a and b"']
    assert ard._split_clauses("brandname = x") == ["brandname = x"], "AND inside a word is not a separator"


def test_filter_parser_is_linear_on_adversarial_whitespace():
    """The inputs CodeQL described for the old regex: long runs of spaces after a field."""
    import time

    for expression in ("A=" + " " * 5000, "A=a" + " " * 5000, " " * 5000 + "AND" + " " * 5000):
        started = time.perf_counter()
        try:
            for clause in ard._split_clauses(expression):
                ard._parse_clause(clause)
        except ard.InvalidSearchRequestError:
            pass
        assert time.perf_counter() - started < 0.05, expression[:10]


def test_filter_errors_never_echo_foreign_exception_text():
    with pytest.raises(ard.InvalidSearchRequestError) as info:
        ard._parse_timestamp("'not a date'")
    assert info.value.message == "timestamp filters must be ISO 8601 values"
    assert info.value.__cause__ is None
