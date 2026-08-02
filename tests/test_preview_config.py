# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Tests for the preview-config endpoint.

Verifies that POST /api/v1/agents/preview-config returns harness config files
for all target harnesses without persisting anything to the database.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.deps import get_current_user, get_db
from api.routes.preview import router
from models.user import User, UserRole


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
    db.execute = AsyncMock()
    return db


def _app_with(user=None, db=None):
    user = user or _user()
    db = db or _mock_db()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db
    return app, db, user


@pytest.mark.asyncio
class TestPreviewConfigNoComponents:
    """Preview with no components should return configs for all harnesses."""

    async def test_returns_configs_for_all_harnesses(self):
        app, db, _user = _app_with()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            res = await client.post(
                "/api/v1/agents/preview-config",
                json={
                    "name": "test-agent",
                    "description": "A test agent",
                    "prompt": "You are helpful.",
                    "model_name": "claude-sonnet-4",
                    "components": [],
                },
            )

        assert res.status_code == 200
        data = res.json()
        configs = data["configs"]
        assert "claude-code" in configs
        assert "kiro" in configs
        assert "cursor" in configs
        assert "codex" in configs
        assert "copilot" in configs
        assert "opencode" in configs
        assert "copilot-cli" in configs

    async def test_claude_code_has_agent_profile(self):
        app, db, _user = _app_with()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            res = await client.post(
                "/api/v1/agents/preview-config",
                json={
                    "name": "my-agent",
                    "description": "desc",
                    "prompt": "Be helpful",
                    "model_name": "",
                    "components": [],
                },
            )

        assert res.status_code == 200
        files = res.json()["configs"]["claude-code"]
        assert ".claude/agents/my-agent.md" in files
        content = files[".claude/agents/my-agent.md"]
        assert "name: my-agent" in content

    async def test_kiro_has_correct_structure(self):
        app, db, _user = _app_with()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            res = await client.post(
                "/api/v1/agents/preview-config",
                json={
                    "name": "kiro-test",
                    "description": "test kiro",
                    "prompt": "Do stuff",
                    "model_name": "",
                    "components": [],
                },
            )

        assert res.status_code == 200
        import json

        files = res.json()["configs"]["kiro"]
        kiro_path = "~/.kiro/agents/kiro-test.json"
        assert kiro_path in files
        agent_json = json.loads(files[kiro_path])
        assert agent_json["name"] == "kiro-test"
        assert agent_json["tools"] == ["*"]
        assert agent_json["includeMcpJson"] is True
        assert "Agent Specialization" in agent_json["prompt"]

    async def test_copilot_uses_agent_md_path(self):
        app, db, _user = _app_with()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            res = await client.post(
                "/api/v1/agents/preview-config",
                json={
                    "name": "cop-test",
                    "description": "",
                    "prompt": "",
                    "model_name": "",
                    "components": [],
                },
            )

        assert res.status_code == 200
        files = res.json()["configs"]["copilot"]
        assert ".github/agents/cop-test.agent.md" in files

    async def test_no_real_urls_in_output(self):
        app, db, _user = _app_with()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            res = await client.post(
                "/api/v1/agents/preview-config",
                json={
                    "name": "url-test",
                    "description": "",
                    "prompt": "",
                    "model_name": "",
                    "components": [],
                },
            )

        assert res.status_code == 200
        raw = res.text
        assert "localhost" not in raw
        assert "127.0.0.1" not in raw

    async def test_validates_payload_limits(self):
        app, db, _user = _app_with()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            res = await client.post(
                "/api/v1/agents/preview-config",
                json={
                    "name": "x" * 200,
                    "description": "",
                    "prompt": "",
                    "model_name": "",
                    "components": [],
                },
            )

        assert res.status_code == 422

    async def test_rejects_unauthenticated(self):
        app = FastAPI()
        app.include_router(router)
        # Don't override get_current_user — it will raise 401

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            res = await client.post(
                "/api/v1/agents/preview-config",
                json={"name": "test", "description": "", "prompt": "", "model_name": "", "components": []},
            )

        assert res.status_code == 401


@pytest.mark.asyncio
class TestPreviewConfigVisibility:
    """Preview renders real component content, so it must apply the same
    visibility rules as every other read path.

    A team-private MCP command, hook handler, prompt template, or SKILL.md must
    never reach a caller who is not a member of the owning teamspace. Selecting a
    component in the builder UI is not an authorization boundary: the endpoint
    takes raw component ids from the request body.
    """

    @staticmethod
    def _db_returning(rows):
        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = rows
        db.execute = AsyncMock(return_value=result)
        return db

    async def test_invisible_component_returns_404(self):
        """A component the caller cannot see is reported as not found."""
        hidden_id = str(uuid.uuid4())
        app, _db, _u = _app_with(db=self._db_returning([]))

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            res = await client.post(
                "/api/v1/agents/preview-config",
                json={
                    "name": "probe",
                    "description": "",
                    "prompt": "",
                    "model_name": "",
                    "components": [{"component_type": "skill", "component_id": hidden_id}],
                },
            )

        assert res.status_code == 404
        # Same wording a genuinely nonexistent id would produce, so the response is
        # not an existence oracle for team-private listings.
        assert res.json()["detail"] == f"Component not found: {hidden_id}"

    async def test_visibility_filter_applied_to_every_component_query(self):
        """Every component lookup is scoped to the requesting user."""
        from unittest.mock import patch

        seen = []

        def _spy(stmt, model, current_user):
            seen.append((model.__name__, current_user))
            return stmt

        user = _user()
        app, _db, _u = _app_with(user=user, db=self._db_returning([]))

        with patch("api.routes.preview.apply_visibility_filter", side_effect=_spy):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                res = await client.post(
                    "/api/v1/agents/preview-config",
                    json={
                        "name": "probe",
                        "description": "",
                        "prompt": "",
                        "model_name": "",
                        "components": [
                            {"component_type": "mcp", "component_id": str(uuid.uuid4())},
                            {"component_type": "skill", "component_id": str(uuid.uuid4())},
                            {"component_type": "hook", "component_id": str(uuid.uuid4())},
                            {"component_type": "prompt", "component_id": str(uuid.uuid4())},
                        ],
                    },
                )

        assert res.status_code == 404
        assert {m for m, _ in seen} == {"McpListing", "SkillListing", "HookListing", "PromptListing"}
        assert all(u is user for _, u in seen)

    async def test_no_component_lookup_without_visibility_filter(self):
        """The endpoint issues no unfiltered component query."""
        from unittest.mock import patch

        db = self._db_returning([])
        app, _db, _u = _app_with(db=db)

        with patch("api.routes.preview.apply_visibility_filter", side_effect=lambda s, m, u: s) as spy:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                await client.post(
                    "/api/v1/agents/preview-config",
                    json={
                        "name": "probe",
                        "description": "",
                        "prompt": "",
                        "model_name": "",
                        "components": [{"component_type": "mcp", "component_id": str(uuid.uuid4())}],
                    },
                )

        assert db.execute.await_count == spy.call_count == 1
