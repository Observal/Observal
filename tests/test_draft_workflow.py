"""Tests for the draft agent lifecycle (save, update, submit).

Covers creating a draft, updating it, submitting for review,
and error handling when agent is not in draft status.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.deps import get_current_user, get_db
from api.routes.agent import router
from models.agent import AgentStatus
from models.user import User, UserRole

# ── Helpers ──────────────────────────────────────────────


def _user(**kw):
    u = MagicMock(spec=User)
    u.id = kw.get("id", uuid.uuid4())
    u.role = kw.get("role", UserRole.user)
    u.email = kw.get("email", "test@example.com")
    u.username = kw.get("username", "testuser")
    u.org_id = kw.get("org_id")
    return u


def _mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = MagicMock()
    db.flush = AsyncMock()
    return db


def _app_with(user=None, db=None):
    user = user or _user()
    db = db or _mock_db()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db
    return app, db, user


def _agent_mock(status=AgentStatus.draft, created_by=None, **extra):
    """Return a MagicMock that looks like an Agent ORM instance."""
    m = MagicMock()
    m.id = extra.get("id", uuid.uuid4())
    m.name = extra.get("name", "test-agent")
    m.version = extra.get("version", "1.0.0")
    m.description = extra.get("description", "A test agent")
    m.owner = extra.get("owner", "testowner")
    m.prompt = extra.get("prompt", "Test prompt")
    m.model_name = extra.get("model_name", "claude-sonnet-4")
    m.model_config_json = {}
    m.external_mcps = []
    m.supported_ides = []
    m.status = status
    m.rejection_reason = None
    m.download_count = 0
    m.unique_users = 0
    m.visibility = "private"
    m.owner_org_id = None
    m.git_url = None
    m.created_by = created_by or uuid.uuid4()
    m.created_at = datetime.now(UTC)
    m.updated_at = datetime.now(UTC)
    m.components = extra.get("components", [])
    m.goal_template = extra.get("goal_template")
    # Edit-lock fields on the latest_version mock
    m.latest_version.is_editing = False
    m.latest_version.editing_by = None
    m.latest_version.editing_since = None
    m.latest_version.prompt = extra.get("prompt", "Test prompt")
    # Make __table__.columns iterable for _agent_to_response
    col_keys = [
        "id",
        "name",
        "version",
        "description",
        "owner",
        "git_url",
        "prompt",
        "model_name",
        "model_config_json",
        "external_mcps",
        "supported_ides",
        "visibility",
        "owner_org_id",
        "status",
        "rejection_reason",
        "download_count",
        "unique_users",
        "created_by",
        "created_at",
        "updated_at",
    ]
    cols = []
    for key in col_keys:
        col = MagicMock()
        col.key = key
        cols.append(col)
    m.__table__ = MagicMock()
    m.__table__.columns = cols
    return m


def _draft_request_body(**overrides) -> dict:
    """Build a minimal AgentCreateRequest body for the draft endpoint."""
    body = {
        "name": "my-draft-agent",
        "version": "1.0.0",
        "description": "Draft agent",
        "owner": "testowner",
        "prompt": "Do things",
        "model_name": "claude-sonnet-4",
        "goal_template": {
            "description": "Test goal",
            "sections": [{"name": "section-1"}],
        },
    }
    body.update(overrides)
    return body


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
# save_draft (POST /api/v1/agents/draft)
# ═══════════════════════════════════════════════════════════


class TestDraftSave:
    """Test creating a new draft agent."""

    @pytest.mark.asyncio
    @patch("api.routes.agent._load_agent")
    async def test_creates_agent_with_draft_status(self, mock_load):
        """POST /agents/draft creates an agent in draft status."""
        user = _user()
        app, db, _ = _app_with(user=user)
        agent = _agent_mock(status=AgentStatus.draft, created_by=user.id)
        mock_load.return_value = agent

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(
                "/api/v1/agents/draft",
                json=_draft_request_body(),
            )

        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "draft"
        db.commit.assert_awaited()

    @pytest.mark.asyncio
    @patch("api.routes.agent._load_agent")
    async def test_response_includes_agent_fields(self, mock_load):
        """Draft response includes id, name, and status fields."""
        user = _user()
        app, db, _ = _app_with(user=user)
        agent = _agent_mock(status=AgentStatus.draft, name="my-draft-agent", created_by=user.id)
        mock_load.return_value = agent

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(
                "/api/v1/agents/draft",
                json=_draft_request_body(),
            )

        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "my-draft-agent"
        assert "id" in data


# ═══════════════════════════════════════════════════════════
# update_draft (PUT /api/v1/agents/{id}/draft)
# ═══════════════════════════════════════════════════════════


class TestDraftUpdate:
    """Test updating a draft agent."""

    @pytest.mark.asyncio
    @patch("api.routes.agent._load_agent")
    async def test_updates_draft_fields(self, mock_load):
        """PUT /agents/{id}/draft updates the draft agent."""
        user = _user()
        app, db, _ = _app_with(user=user)
        agent = _agent_mock(status=AgentStatus.draft, created_by=user.id)
        mock_load.return_value = agent

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.put(
                f"/api/v1/agents/{agent.id}/draft",
                json={"description": "Updated draft description"},
            )

        assert r.status_code == 200
        db.commit.assert_awaited()

    @pytest.mark.asyncio
    @patch("api.routes.agent._load_agent")
    async def test_rejects_update_on_non_draft(self, mock_load):
        """Updating an approved agent returns 400."""
        user = _user()
        app, db, _ = _app_with(user=user)
        agent = _agent_mock(status=AgentStatus.approved, created_by=user.id)
        mock_load.return_value = agent

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.put(
                f"/api/v1/agents/{agent.id}/draft",
                json={"description": "Nope"},
            )

        assert r.status_code == 400

    @pytest.mark.asyncio
    @patch("api.routes.agent._load_agent")
    async def test_rejects_update_by_non_owner(self, mock_load):
        """Non-owner cannot update a draft agent (403)."""
        user = _user()
        app, db, _ = _app_with(user=user)
        agent = _agent_mock(status=AgentStatus.draft, created_by=uuid.uuid4())
        mock_load.return_value = agent

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.put(
                f"/api/v1/agents/{agent.id}/draft",
                json={"description": "Not my agent"},
            )

        assert r.status_code == 403


# ═══════════════════════════════════════════════════════════
# submit_draft (POST /api/v1/agents/{id}/submit)
# ═══════════════════════════════════════════════════════════


class TestDraftSubmit:
    """Test submitting a draft for review."""

    @pytest.mark.asyncio
    @patch("api.routes.agent.emit_registry_event")
    @patch("api.routes.agent._resolve_component_names")
    @patch("api.routes.agent._load_agent")
    async def test_transitions_to_pending(self, mock_load, mock_resolve, mock_emit):
        """POST /agents/{id}/submit transitions a draft to pending status."""
        user = _user()
        app, db, _ = _app_with(user=user)
        agent = _agent_mock(status=AgentStatus.draft, created_by=user.id, components=[])
        mock_load.return_value = agent
        mock_resolve.return_value = {}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(f"/api/v1/agents/{agent.id}/submit")

        assert r.status_code == 200
        assert agent.status == AgentStatus.pending
        db.commit.assert_awaited()

    @pytest.mark.asyncio
    @patch("api.routes.agent.emit_registry_event")
    @patch("api.routes.agent._resolve_component_names")
    @patch("api.routes.agent._load_agent")
    async def test_submit_response_includes_status(self, mock_load, mock_resolve, mock_emit):
        """Submit response body includes the new pending status."""
        user = _user()
        app, db, _ = _app_with(user=user)
        agent = _agent_mock(status=AgentStatus.draft, created_by=user.id, components=[])
        # After status change, _load_agent is called again; return the same agent
        mock_load.return_value = agent
        mock_resolve.return_value = {}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(f"/api/v1/agents/{agent.id}/submit")

        data = r.json()
        assert data["status"] == "pending"


# ═══════════════════════════════════════════════════════════
# Submit non-draft (error cases)
# ═══════════════════════════════════════════════════════════


class TestDraftSubmitNotDraft:
    """Test submitting a non-draft agent returns an error."""

    @pytest.mark.asyncio
    @patch("api.routes.agent._load_agent")
    async def test_submit_pending_returns_400(self, mock_load):
        """Submitting a pending agent returns 400."""
        user = _user()
        app, db, _ = _app_with(user=user)
        agent = _agent_mock(status=AgentStatus.pending, created_by=user.id)
        mock_load.return_value = agent

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(f"/api/v1/agents/{agent.id}/submit")

        assert r.status_code == 400

    @pytest.mark.asyncio
    @patch("api.routes.agent._load_agent")
    async def test_submit_active_returns_400(self, mock_load):
        """Submitting an active agent returns 400."""
        user = _user()
        app, db, _ = _app_with(user=user)
        agent = _agent_mock(status=AgentStatus.approved, created_by=user.id)
        mock_load.return_value = agent

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(f"/api/v1/agents/{agent.id}/submit")

        assert r.status_code == 400

    @pytest.mark.asyncio
    @patch("api.routes.agent._load_agent")
    async def test_submit_not_found_returns_404(self, mock_load):
        """Submitting a nonexistent agent returns 404."""
        user = _user()
        app, db, _ = _app_with(user=user)
        mock_load.return_value = None

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(f"/api/v1/agents/{uuid.uuid4()}/submit")

        assert r.status_code == 404
