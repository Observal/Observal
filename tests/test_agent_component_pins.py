# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Agent routes pin components through the lock service against a real registry."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from api.routes import agent_versions, bulk
from models.agent import AgentVersion
from models.agent_component import AgentComponent
from models.mcp import ListingStatus, McpVersion
from schemas.agent import AgentVersionCreateRequest, ComponentRef
from schemas.bulk import BulkAgentItem, BulkAgentRequest
from tests import discovery_support as ds


@pytest.fixture
async def registry(monkeypatch):
    monkeypatch.setattr(agent_versions.inbox, "on_publish", AsyncMock())
    monkeypatch.setattr(bulk.inbox, "on_publish", AsyncMock())
    engine = ds.make_engine()
    maker = await ds.create_schema(engine)
    async with maker() as db:
        owner = await ds.user(db)
        mcp = await ds.mcp(db, owner)  # 1.4.2
        agent = await ds.agent(db, owner, components=[("mcp", mcp.id, "GitHub")])
        link = (await db.execute(select(AgentComponent))).scalar_one()
        link.resolved_version = "1.4.2"
        link.resolved_version_id = mcp.latest_version_id
        await db.commit()
        yield db, owner, mcp, agent
    await engine.dispose()


async def _approve_mcp_release(db, listing, owner, version: str) -> McpVersion:
    row = McpVersion(
        id=uuid.uuid4(),
        listing_id=listing.id,
        version=version,
        description="GitHub tools",
        status=ListingStatus.approved,
        transport="stdio",
        command="npx",
        args=["-y", f"@acme/github@{version}"],
        released_by=owner.id,
        released_at=ds.NOW,
    )
    db.add(row)
    await db.flush()
    listing.latest_version_id = row.id
    await db.commit()
    return row


async def _release(db, owner, agent, mcp, version: str, **options) -> AgentVersion:
    ref = {"component_type": "mcp", "component_id": mcp.id, **options.pop("ref", {})}
    request = AgentVersionCreateRequest(
        version=version,
        description="release",
        prompt="Review carefully.",
        model_name="claude-sonnet-4",
        components=[ComponentRef(**ref)],
        **options,
    )
    await agent_versions._create_agent_version(str(agent.id), request, db, owner)
    return (
        await db.execute(select(AgentVersion).where(AgentVersion.agent_id == agent.id, AgentVersion.version == version))
    ).scalar_one()


async def _pins(db, version: AgentVersion) -> list[tuple[str, uuid.UUID | None]]:
    rows = (
        (await db.execute(select(AgentComponent).where(AgentComponent.agent_version_id == version.id))).scalars().all()
    )
    return [(row.resolved_version, row.resolved_version_id) for row in rows]


async def test_release_keeps_existing_pins_when_components_have_new_versions(registry):
    db, owner, mcp, agent = registry
    original = mcp.latest_version_id
    await _approve_mcp_release(db, mcp, owner, "2.0.0")

    released = await _release(db, owner, agent, mcp, "3.2.0")

    assert await _pins(db, released) == [("1.4.2", original)]
    lock = json.loads(released.lock_snapshot)
    assert lock["components"][0]["version"] == "1.4.2"
    assert lock["components"][0]["digest"].startswith("sha256:")


async def test_release_refresh_moves_unversioned_components_to_latest(registry):
    db, owner, mcp, agent = registry
    newest = await _approve_mcp_release(db, mcp, owner, "2.0.0")

    released = await _release(db, owner, agent, mcp, "3.2.0", refresh_components=True)

    assert await _pins(db, released) == [("2.0.0", newest.id)]


async def test_release_honours_an_explicit_component_version(registry):
    db, owner, mcp, agent = registry
    await _approve_mcp_release(db, mcp, owner, "2.0.0")
    middle = await _approve_mcp_release(db, mcp, owner, "1.5.0")

    released = await _release(db, owner, agent, mcp, "3.2.0", ref={"version": "1.5.0"})

    assert await _pins(db, released) == [("1.5.0", middle.id)]


async def test_bulk_create_pins_the_real_release_instead_of_latest(registry):
    db, owner, mcp, _agent = registry
    request = BulkAgentRequest(
        agents=[
            BulkAgentItem(
                name="bulk-reviewer",
                version="1.0.0",
                owner="alice",
                prompt="Review.",
                model_name="claude-sonnet-4",
                components=[{"component_type": "mcp", "component_id": str(mcp.id)}],
            )
        ]
    )

    result = await bulk.bulk_create_agents(request, db, owner)

    assert result.created == 1
    created = (
        await db.execute(select(AgentVersion).join(AgentVersion.agent).where(AgentVersion.version == "1.0.0"))
    ).scalar_one()
    assert await _pins(db, created) == [("1.4.2", mcp.latest_version_id)]
