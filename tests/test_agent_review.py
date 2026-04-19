"""Tests for agent review workflow (approve/reject via review endpoints).

Covers approval with component readiness checks, rejection with reason,
and 404 handling for nonexistent agents.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.deps import get_current_user, get_db
from api.routes.review import router
from models.agent import AgentStatus
from models.user import User, UserRole

# ── Helpers ──────────────────────────────────────────────


def _user(**kw):
    u = MagicMock(spec=User)
    u.id = kw.get("id", uuid.uuid4())
    u.role = kw.get("role", UserRole.admin)
    return u


def _mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = MagicMock()
    return db


def _app_with(user=None, db=None):
    user = user or _user()
    db = db or _mock_db()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db
    return app, db, user


def _agent_mock(status=AgentStatus.pending, **extra):
    """Return a MagicMock that looks like an Agent ORM instance."""
    m = MagicMock()
    m.id = extra.get("id", uuid.uuid4())
    m.name = extra.get("name", "test-agent")
    m.version = extra.get("version", "1.0.0")
    m.description = extra.get("description", "A test agent")
    m.owner = extra.get("owner", "testowner")
    m.status = status
    m.rejection_reason = None
    m.created_by = extra.get("created_by", uuid.uuid4())
    m.created_at = datetime.now(UTC)
    m.updated_at = datetime.now(UTC)
    m.components = extra.get("components", [])
    for k, v in extra.items():
        setattr(m, k, v)
    return m


def _empty_result():
    r = MagicMock()
    r.scalars.return_value.all.return_value = []
    r.scalar_one_or_none.return_value = None
    return r


def _result_with_agent(agent):
    """Return a mock result that yields the agent via scalar_one_or_none."""
    r = MagicMock()
    r.scalar_one_or_none.return_value = agent
    r.scalars.return_value.all.return_value = [agent]
    return r


# ═══════════════════════════════════════════════════════════
# approve_agent (POST /api/v1/review/agents/{id}/approve)
# ═══════════════════════════════════════════════════════════


class TestAgentApprove:
    """Test agent approval via review endpoint."""

    @pytest.mark.asyncio
    async def test_sets_status_to_active(self):
        """Approving a pending agent with all components ready sets status to active."""
        app, db, _ = _app_with()
        agent = _agent_mock(status=AgentStatus.pending, components=[])

        # First execute: select Agent -> returns agent
        # The endpoint uses selectinload, so scalar_one_or_none is the path
        db.execute = AsyncMock(return_value=_result_with_agent(agent))

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(f"/api/v1/review/agents/{agent.id}/approve")

        assert r.status_code == 200
        assert agent.status == AgentStatus.active
        assert r.json()["status"] == "active"
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_422_when_components_not_ready(self):
        """Approving an agent with unapproved components returns 422."""
        app, db, _ = _app_with()

        comp = MagicMock()
        comp.component_type = "mcp"
        comp.component_id = uuid.uuid4()
        agent = _agent_mock(status=AgentStatus.pending, components=[comp])

        # First call: select Agent -> agent
        # Second call: select component status -> component not approved
        blocking_row = MagicMock()
        blocking_row.id = comp.component_id
        blocking_row.name = "unapproved-mcp"
        blocking_row.status = MagicMock()
        blocking_row.status.value = "pending"
        # The status comparison != ListingStatus.approved should be truthy
        from models.mcp import ListingStatus

        blocking_row.status = ListingStatus.pending

        component_result = MagicMock()
        component_result.all.return_value = [blocking_row]

        db.execute = AsyncMock(
            side_effect=[_result_with_agent(agent), component_result]
        )

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(f"/api/v1/review/agents/{agent.id}/approve")

        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_response_includes_id_and_name(self):
        """Approval response includes agent id, name, and status."""
        app, db, _ = _app_with()
        agent = _agent_mock(status=AgentStatus.pending, name="my-agent", components=[])
        db.execute = AsyncMock(return_value=_result_with_agent(agent))

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(f"/api/v1/review/agents/{agent.id}/approve")

        data = r.json()
        assert data["name"] == "my-agent"
        assert data["id"] == str(agent.id)
        assert data["status"] == "active"


# ═══════════════════════════════════════════════════════════
# reject_agent (POST /api/v1/review/agents/{id}/reject)
# ═══════════════════════════════════════════════════════════


class TestAgentReject:
    """Test agent rejection via review endpoint."""

    @pytest.mark.asyncio
    async def test_sets_status_and_stores_reason(self):
        """Rejecting a pending agent stores the rejection reason."""
        app, db, _ = _app_with()
        agent = _agent_mock(status=AgentStatus.pending)
        db.execute = AsyncMock(return_value=_result_with_agent(agent))

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(
                f"/api/v1/review/agents/{agent.id}/reject",
                json={"reason": "missing documentation"},
            )

        assert r.status_code == 200
        assert agent.status == AgentStatus.rejected
        assert agent.rejection_reason == "missing documentation"
        assert r.json()["status"] == "rejected"
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reject_active_agent(self):
        """An active agent can also be rejected."""
        app, db, _ = _app_with()
        agent = _agent_mock(status=AgentStatus.active)
        db.execute = AsyncMock(return_value=_result_with_agent(agent))

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(
                f"/api/v1/review/agents/{agent.id}/reject",
                json={"reason": "policy violation"},
            )

        assert r.status_code == 200
        assert agent.status == AgentStatus.rejected

    @pytest.mark.asyncio
    async def test_reject_draft_agent_returns_400(self):
        """Rejecting a draft agent is not allowed (status must be pending or active)."""
        app, db, _ = _app_with()
        agent = _agent_mock(status=AgentStatus.draft)
        db.execute = AsyncMock(return_value=_result_with_agent(agent))

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(
                f"/api/v1/review/agents/{agent.id}/reject",
                json={"reason": "nope"},
            )

        assert r.status_code == 400


# ═══════════════════════════════════════════════════════════
# Not found (404)
# ═══════════════════════════════════════════════════════════


class TestAgentNotFound:
    """Test 404 for nonexistent agent in review endpoints."""

    @pytest.mark.asyncio
    async def test_approve_not_found(self):
        """Approving a nonexistent agent returns 404."""
        app, db, _ = _app_with()
        db.execute = AsyncMock(return_value=_empty_result())

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(f"/api/v1/review/agents/{uuid.uuid4()}/approve")

        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_reject_not_found(self):
        """Rejecting a nonexistent agent returns 404."""
        app, db, _ = _app_with()
        db.execute = AsyncMock(return_value=_empty_result())

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(
                f"/api/v1/review/agents/{uuid.uuid4()}/reject",
                json={"reason": "bad"},
            )

        assert r.status_code == 404
