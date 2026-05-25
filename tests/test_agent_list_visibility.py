# SPDX-FileCopyrightText: 2026 Harishankar <harishankar0301@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

import uuid
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from api.deps import get_db, optional_current_user
from main import app
from models.agent import Agent, AgentStatus, AgentTeamAccess, AgentVersion, AgentVisibility
from models.base import Base
from models.user import UserRole

# Create an in-memory SQLite engine for the tests
engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
TestingSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def db_session():
    async with TestingSessionLocal() as session:
        yield session


def mock_user(org_id, groups=None):
    from unittest.mock import MagicMock

    u = MagicMock()
    u.id = uuid.uuid4()
    u.role = UserRole.user
    u.org_id = org_id
    u._groups = groups or []
    return u


@pytest.mark.asyncio
@patch("api.routes.agent.crud.settings.DEPLOYMENT_MODE", "enterprise")
async def test_private_agents_not_leaked_to_org_members(db_session):
    """
    Validates that a private agent is NOT returned in the agent list for users
    who are simply in the same organization, unless they have the required group access.
    """
    org_id = uuid.uuid4()
    owner_id = uuid.uuid4()

    # Create agents
    agent_public = Agent(
        id=uuid.uuid4(),
        name="Public Agent",
        visibility=AgentVisibility.public,
        owner="testowner",
        created_by=owner_id,
        owner_org_id=org_id,
    )

    agent_private = Agent(
        id=uuid.uuid4(),
        name="Private Agent",
        visibility=AgentVisibility.private,
        owner="testowner",
        created_by=owner_id,
        owner_org_id=org_id,
    )

    agent_private_with_group = Agent(
        id=uuid.uuid4(),
        name="Group Agent",
        visibility=AgentVisibility.private,
        owner="testowner",
        created_by=owner_id,
        owner_org_id=org_id,
    )

    db_session.add_all([agent_public, agent_private, agent_private_with_group])
    await db_session.flush()

    # Add versions (list_agents joins with AgentVersion)
    v1 = AgentVersion(
        agent_id=agent_public.id, version="1.0.0", status=AgentStatus.approved, released_by=owner_id, model_name="test"
    )
    v2 = AgentVersion(
        agent_id=agent_private.id, version="1.0.0", status=AgentStatus.approved, released_by=owner_id, model_name="test"
    )
    v3 = AgentVersion(
        agent_id=agent_private_with_group.id,
        version="1.0.0",
        status=AgentStatus.approved,
        released_by=owner_id,
        model_name="test",
    )
    db_session.add_all([v1, v2, v3])
    await db_session.flush()

    # Update latest_version_id
    agent_public.latest_version_id = v1.id
    agent_private.latest_version_id = v2.id
    agent_private_with_group.latest_version_id = v3.id

    # Add team access to the third agent
    ta = AgentTeamAccess(agent_id=agent_private_with_group.id, group_name="engineering", permission="view")
    db_session.add(ta)

    await db_session.commit()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    # User 1: Regular user in the same org (no groups)
    user1 = mock_user(org_id)
    app.dependency_overrides[optional_current_user] = lambda: user1

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        resp1 = await client.get("/api/v1/agents")
        assert resp1.status_code == 200
        data1 = resp1.json()
        agent_names = [a["name"] for a in data1]

        # User 1 should see the public agent, but NOT the private agents
        assert "Public Agent" in agent_names
        assert "Private Agent" not in agent_names
        assert "Group Agent" not in agent_names

    # User 2: User in the same org WITH "engineering" group
    user2 = mock_user(org_id, groups=["engineering"])
    app.dependency_overrides[optional_current_user] = lambda: user2

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        resp2 = await client.get("/api/v1/agents")
        assert resp2.status_code == 200
        data2 = resp2.json()
        agent_names2 = [a["name"] for a in data2]

        # User 2 should see the public agent AND the group agent, but NOT the strictly private agent
        assert "Public Agent" in agent_names2
        assert "Group Agent" in agent_names2
        assert "Private Agent" not in agent_names2

    app.dependency_overrides.clear()
    print("\nSUCCESS: Agent listing API properly applies visibility filtering and group-based access control!")
