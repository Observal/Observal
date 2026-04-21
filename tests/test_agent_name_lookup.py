"""Tests for agent name lookup with hyphens and short names.

Verifies that _load_agent falls through to name-based lookup when
resolve_prefix_id fails, so agent names like 'my-agent' or 'a-b'
work correctly regardless of UUID/prefix resolution.
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


def _agent_mock(status=AgentStatus.active, created_by=None, **extra):
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
    m.required_ide_features = []
    m.inferred_supported_ides = []
    m.status = status
    m.rejection_reason = None
    m.download_count = 0
    m.unique_users = 0
    m.is_private = False
    m.owner_org_id = None
    m.git_url = None
    m.created_by = created_by or uuid.uuid4()
    m.created_at = datetime.now(UTC)
    m.updated_at = datetime.now(UTC)
    m.components = extra.get("components", [])
    m.goal_template = extra.get("goal_template")
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
        "is_private",
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


# ═══════════════════════════════════════════════════════════
# GET /api/v1/agents/{agent_id} — name-based lookup
# ═══════════════════════════════════════════════════════════


class TestAgentNameLookup:
    """Ensure _load_agent resolves hyphenated and short names correctly."""

    @pytest.mark.asyncio
    @patch("api.routes.agent._resolve_component_names", return_value={})
    @patch("api.routes.agent._load_agent")
    async def test_hyphenated_name_resolves(self, mock_load, mock_names):
        """GET /agents/my-cool-agent resolves via name lookup."""
        user = _user()
        agent = _agent_mock(name="my-cool-agent", created_by=user.id)
        mock_load.return_value = agent

        app, db, _ = _app_with(user=user, db=_mock_db())

        # Mock the user query for created_by_email
        user_row = MagicMock()
        user_row.__getitem__ = lambda self, i: {0: user.email, 1: user.username}[i]
        db.execute = AsyncMock(return_value=MagicMock(first=MagicMock(return_value=user_row)))

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/v1/agents/my-cool-agent")

        assert r.status_code == 200
        assert r.json()["name"] == "my-cool-agent"

    @pytest.mark.asyncio
    @patch("api.routes.agent._resolve_component_names", return_value={})
    @patch("api.routes.agent._load_agent")
    async def test_short_hyphenated_name_resolves(self, mock_load, mock_names):
        """GET /agents/a-b resolves via name lookup (not rejected as short prefix)."""
        user = _user()
        agent = _agent_mock(name="a-b", created_by=user.id)
        mock_load.return_value = agent

        app, db, _ = _app_with(user=user, db=_mock_db())

        user_row = MagicMock()
        user_row.__getitem__ = lambda self, i: {0: user.email, 1: user.username}[i]
        db.execute = AsyncMock(return_value=MagicMock(first=MagicMock(return_value=user_row)))

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/v1/agents/a-b")

        assert r.status_code == 200
        assert r.json()["name"] == "a-b"


class TestAgentNameValidation:
    """Ensure agent name regex accepts hyphens in creation payloads."""

    def test_hyphenated_name_accepted_by_schema(self):
        from schemas.agent import AgentCreateRequest

        req = AgentCreateRequest(
            name="my-cool-agent",
            version="1.0.0",
            description="test",
            owner="testowner",
            model_name="claude-sonnet-4",
            goal_template={"description": "g", "sections": [{"name": "s"}]},
        )
        assert req.name == "my-cool-agent"

    def test_multiple_hyphens_accepted(self):
        from schemas.agent import AgentCreateRequest

        req = AgentCreateRequest(
            name="my-cool-agent-v2",
            version="1.0.0",
            description="test",
            owner="testowner",
            model_name="claude-sonnet-4",
            goal_template={"description": "g", "sections": [{"name": "s"}]},
        )
        assert req.name == "my-cool-agent-v2"

    def test_short_hyphenated_name_accepted(self):
        from schemas.agent import AgentCreateRequest

        req = AgentCreateRequest(
            name="a-b",
            version="1.0.0",
            description="test",
            owner="testowner",
            model_name="claude-sonnet-4",
            goal_template={"description": "g", "sections": [{"name": "s"}]},
        )
        assert req.name == "a-b"

    def test_leading_hyphen_rejected(self):
        from schemas.agent import AgentCreateRequest

        with pytest.raises(ValueError, match="Invalid name"):
            AgentCreateRequest(
                name="-agent",
                version="1.0.0",
                description="test",
                owner="testowner",
                model_name="claude-sonnet-4",
                goal_template={"description": "g", "sections": [{"name": "s"}]},
            )

    def test_update_schema_accepts_hyphens(self):
        from schemas.agent import AgentUpdateRequest

        req = AgentUpdateRequest(name="my-new-name")
        assert req.name == "my-new-name"
