# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Agent installs generate every component from the version the agent release pinned.

Before pins were enforced, only sandboxes honoured them: MCP servers, skills,
hooks, and prompts were generated from each listing's latest release, so the
same agent version installed different content as soon as a component shipped
a new version.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from api.routes.agent.install import install_agent
from models.agent import AgentStatus, AgentVersion
from models.agent_component import AgentComponent
from models.hook import HookVersion
from models.mcp import ListingStatus, McpVersion
from models.prompt import PromptVersion
from models.sandbox import SandboxVersion
from models.skill import SkillVersion
from schemas.agent import AgentInstallRequest
from services.agent_lock import VERSION_MODELS, content_digest, lock_agent_version
from tests import discovery_support as ds


@pytest.fixture
async def session():
    engine = ds.make_engine()
    maker = await ds.create_schema(engine)
    async with maker() as db:
        yield db
    await engine.dispose()


def _new_release(kind: str, listing, owner, marker: str):
    common = {
        "id": uuid.uuid4(),
        "listing_id": listing.id,
        "version": "9.0.0",
        "description": "newer release",
        "status": ListingStatus.approved,
        "released_by": owner.id,
        "released_at": ds.NOW,
    }
    if kind == "mcp":
        return McpVersion(**common, transport="stdio", command="npx", args=["-y", marker])
    if kind == "skill":
        return SkillVersion(
            **common, task_type="code_review", delivery_mode="registry_direct", skill_md_content=f"---\n---\n{marker}"
        )
    if kind == "hook":
        return HookVersion(**common, event="PostToolUse", handler_type="command", handler_config={"command": marker})
    if kind == "prompt":
        return PromptVersion(**common, category="documentation", template=marker)
    return SandboxVersion(**common, runtime_type="docker", image=marker, network_policy="none")


_FACTORIES = {
    "mcp": (ds.mcp, "@modelcontextprotocol/server-github"),
    "skill": (ds.skill, "Look for auth bugs."),
    "hook": (ds.hook, "npm run lint"),
    "prompt": (ds.prompt, "Write release notes for"),
    "sandbox": (ds.sandbox, "python:3.12-slim"),
}


async def _pinned_agent(db, owner, kind: str):
    factory, pinned_marker = _FACTORIES[kind]
    listing = await factory(db, owner)
    agent = await ds.agent(db, owner, components=[(kind, listing.id, listing.name)])
    link = (await db.execute(select(AgentComponent))).scalar_one()
    version_model = VERSION_MODELS[kind]
    pinned = (await db.execute(select(version_model).where(version_model.id == listing.latest_version_id))).scalar_one()
    link.resolved_version = pinned.version
    version = (await db.execute(select(AgentVersion))).scalar_one()
    await lock_agent_version(db, agent, version)
    await db.commit()
    return listing, agent, pinned_marker


async def _install(db, agent, user, **request):
    with (
        patch("api.routes.config.derive_endpoints", AsyncMock(return_value={"api": "http://observal.test"})),
        patch("services.download_tracker.record_agent_download", AsyncMock()),
    ):
        return await install_agent(
            str(agent.id),
            AgentInstallRequest(harness="claude-code", options={"scope": "project"}, **request),
            request=None,
            db=db,
            current_user=user,
        )


@pytest.mark.parametrize("kind", sorted(_FACTORIES))
async def test_install_uses_the_pinned_release_after_a_newer_one_is_approved(session, kind):
    owner = await ds.user(session)
    listing, agent, pinned_marker = await _pinned_agent(session, owner, kind)
    newer = _new_release(kind, listing, owner, "NEWER-RELEASE-MARKER")
    session.add(newer)
    await session.flush()
    listing.latest_version_id = newer.id
    await session.commit()

    response = await _install(session, agent, owner)

    generated = json.dumps(response.config_snippet)
    assert "NEWER-RELEASE-MARKER" not in generated
    assert pinned_marker in generated
    assert response.version == "3.1.0"
    assert response.lock["status"] == "locked"
    assert response.lock["problems"] == []
    assert response.lock["components"][0]["source"] == "lock"
    assert response.lock["digest"].startswith("sha256:")


async def test_legacy_pin_falls_back_to_latest_with_a_warning_and_strict_refuses(session):
    owner = await ds.user(session)
    listing = await ds.mcp(session, owner)
    agent = await ds.agent(session, owner, components=[("mcp", listing.id, "GitHub")])
    link = (await session.execute(select(AgentComponent))).scalar_one()
    link.resolved_version = "latest"
    await session.commit()

    response = await _install(session, agent, owner)
    with pytest.raises(HTTPException) as refused:
        await _install(session, agent, owner, strict=True)

    assert response.lock["status"] == "unlocked"
    assert response.lock["components"][0]["source"] == "fallback-latest"
    assert any("has no locked version" in warning for warning in response.warnings)
    assert refused.value.status_code == 409
    assert refused.value.detail.startswith("Strict install refused: mcp 'GitHub' is not locked.")


async def test_content_changed_after_locking_is_reported(session):
    owner = await ds.user(session)
    listing, agent, _marker = await _pinned_agent(session, owner, "mcp")
    pinned = (await session.execute(select(McpVersion).where(McpVersion.listing_id == listing.id))).scalar_one()
    pinned.args = ["-y", "@evil/server-github"]
    await session.commit()

    response = await _install(session, agent, owner)
    with pytest.raises(HTTPException) as refused:
        await _install(session, agent, owner, strict=True)

    assert content_digest("mcp", pinned) != (await session.execute(select(AgentComponent))).scalar_one().resolved_digest
    assert response.lock["problems"] == ["mcp 'GitHub' 1.4.2 changed after it was locked"]
    assert refused.value.status_code == 409


async def test_requested_older_agent_version_installs_its_own_pins(session):
    owner = await ds.user(session)
    listing, agent, _marker = await _pinned_agent(session, owner, "mcp")
    newer_mcp = _new_release("mcp", listing, owner, "NEWER-RELEASE-MARKER")
    session.add(newer_mcp)
    await session.flush()
    listing.latest_version_id = newer_mcp.id
    newer_agent = AgentVersion(
        id=uuid.uuid4(),
        agent_id=agent.id,
        version="4.0.0",
        description="Uses the newer MCP",
        prompt="Review.",
        model_name="claude-sonnet-4",
        status=AgentStatus.approved,
        released_by=owner.id,
        released_at=ds.NOW,
    )
    session.add(newer_agent)
    await session.flush()
    session.add(
        AgentComponent(
            agent_version_id=newer_agent.id,
            component_type="mcp",
            component_id=listing.id,
            component_name="GitHub",
            resolved_version="9.0.0",
            resolved_version_id=newer_mcp.id,
        )
    )
    agent.latest_version_id = newer_agent.id
    await session.commit()

    latest = await _install(session, agent, owner)
    pinned = await _install(session, agent, owner, version="3.1.0")

    assert latest.version == "4.0.0"
    assert "NEWER-RELEASE-MARKER" in json.dumps(latest.config_snippet)
    assert pinned.version == "3.1.0"
    assert "NEWER-RELEASE-MARKER" not in json.dumps(pinned.config_snippet)
