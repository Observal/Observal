# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for listing detail endpoint access control.

Verifies that GET /{listing_id} endpoints for all 5 registry types
enforce status-based visibility:
- Unauthenticated: only approved listings visible
- Owner: any status visible
- Admin/reviewer: any status visible
- Non-owner regular user: only approved listings visible
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.deps import get_db, optional_current_user
from models.mcp import ListingStatus
from models.user import User, UserRole

# ── Helpers ──────────────────────────────────────────────


def _user(role=UserRole.user, user_id=None, **kw):
    u = MagicMock(spec=User)
    u.id = user_id or uuid.uuid4()
    u.role = role
    u.email = kw.get("email", "test@example.com")
    u.username = kw.get("username", "testuser")
    u.org_id = kw.get("org_id")
    return u


def _mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    return db


def _app_with(router, user=None):
    db = _mock_db()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    if user is not None:
        app.dependency_overrides[optional_current_user] = lambda: user
    else:
        app.dependency_overrides[optional_current_user] = lambda: None
    return app


def _listing_mock(status=ListingStatus.approved, submitted_by=None):
    m = MagicMock()
    m.id = uuid.uuid4()
    m.name = "test-listing"
    m.version = "1.0.0"
    m.description = "A test listing"
    m.owner = "testowner"
    m.status = status
    m.rejection_reason = None
    m.submitted_by = submitted_by or uuid.uuid4()
    m.owner_org_id = None
    m.supported_ides = []
    m.created_at = datetime(2025, 1, 1, tzinfo=UTC)
    m.updated_at = datetime(2025, 1, 1, tzinfo=UTC)
    m.category = "general"
    m.git_url = None
    m.command = None
    m.args = None
    m.url = None
    m.headers = None
    m.auto_approve = []
    m.transport = None
    m.framework = None
    m.docker_image = None
    m.mcp_validated = False
    m.changelog = None
    m.setup_instructions = None
    m.environment_variables = []
    m.custom_fields = []
    m.validation_results = []
    m.download_count = 0
    m.unique_users = 0
    m.template = "Hello {{ name }}"
    m.variables = []
    m.model_hints = []
    m.tags = []
    m.task_type = "code-review"
    m.target_agents = []
    m.skill_path = None
    m.triggers = []
    m.slash_command = None
    m.has_scripts = False
    m.has_templates = False
    m.is_power = False
    m.power_md = None
    m.mcp_server_config = None
    m.activation_keywords = []
    m.event = "PreToolUse"
    m.execution_mode = "blocking"
    m.priority = 0
    m.handler_type = "command"
    m.handler_config = {}
    m.input_schema = None
    m.output_schema = None
    m.scope = "project"
    m.tool_filter = None
    m.file_pattern = None
    m.runtime_type = "docker"
    m.image = "python:3.11"
    m.dockerfile_url = None
    m.resource_limits = {}
    m.network_policy = "none"
    m.allowed_mounts = []
    m.env_vars = []
    m.entrypoint = None
    return m


# ── Endpoint configs for parametrization ─────────────────

ENDPOINTS = [
    ("mcp", "/api/v1/mcps", "api.routes.mcp"),
    ("prompt", "/api/v1/prompts", "api.routes.prompt"),
    ("skill", "/api/v1/skills", "api.routes.skill"),
    ("hook", "/api/v1/hooks", "api.routes.hook"),
    ("sandbox", "/api/v1/sandboxes", "api.routes.sandbox"),
]


def _get_router(route_type):
    if route_type == "mcp":
        from api.routes.mcp import router
    elif route_type == "prompt":
        from api.routes.prompt import router
    elif route_type == "skill":
        from api.routes.skill import router
    elif route_type == "hook":
        from api.routes.hook import router
    elif route_type == "sandbox":
        from api.routes.sandbox import router
    else:
        raise ValueError(f"Unknown route type: {route_type}")
    return router


# ── Tests ────────────────────────────────────────────────


@pytest.mark.parametrize("route_type,base_path,module_path", ENDPOINTS)
class TestUnauthenticatedAccess:
    """Unauthenticated users can only see approved listings."""

    @pytest.mark.asyncio
    async def test_sees_approved(self, route_type, base_path, module_path):
        router = _get_router(route_type)
        listing = _listing_mock(status=ListingStatus.approved)
        app = _app_with(router, user=None)

        with patch(f"{module_path}.resolve_listing", new_callable=AsyncMock) as mock_resolve:
            mock_resolve.return_value = listing
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                r = await ac.get(f"{base_path}/{listing.id}")
            assert r.status_code == 200

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "status",
        [ListingStatus.draft, ListingStatus.pending, ListingStatus.rejected, ListingStatus.archived],
    )
    async def test_blocked_from_non_approved(self, route_type, base_path, module_path, status):
        router = _get_router(route_type)
        listing = _listing_mock(status=status)
        app = _app_with(router, user=None)

        with patch(f"{module_path}.resolve_listing", new_callable=AsyncMock) as mock_resolve:
            mock_resolve.side_effect = [None, listing]
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                r = await ac.get(f"{base_path}/{listing.id}")
            assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_nonexistent_returns_404(self, route_type, base_path, module_path):
        router = _get_router(route_type)
        app = _app_with(router, user=None)

        with patch(f"{module_path}.resolve_listing", new_callable=AsyncMock) as mock_resolve:
            mock_resolve.side_effect = [None, None]
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                r = await ac.get(f"{base_path}/{uuid.uuid4()}")
            assert r.status_code == 404


@pytest.mark.parametrize("route_type,base_path,module_path", ENDPOINTS)
class TestOwnerAccess:
    """Listing owners can see their own listings in any status."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "status",
        [ListingStatus.draft, ListingStatus.pending, ListingStatus.rejected],
    )
    async def test_owner_sees_own_non_approved(self, route_type, base_path, module_path, status):
        owner = _user()
        router = _get_router(route_type)
        listing = _listing_mock(status=status, submitted_by=owner.id)
        app = _app_with(router, user=owner)

        with patch(f"{module_path}.resolve_listing", new_callable=AsyncMock) as mock_resolve:
            mock_resolve.side_effect = [None, listing]
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                r = await ac.get(f"{base_path}/{listing.id}")
            assert r.status_code == 200


@pytest.mark.parametrize("route_type,base_path,module_path", ENDPOINTS)
class TestNonOwnerRegularUser:
    """Non-owner regular users cannot see non-approved listings."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "status",
        [ListingStatus.draft, ListingStatus.pending],
    )
    async def test_blocked_from_others_non_approved(self, route_type, base_path, module_path, status):
        other_user = _user()
        router = _get_router(route_type)
        listing = _listing_mock(status=status)
        app = _app_with(router, user=other_user)

        with patch(f"{module_path}.resolve_listing", new_callable=AsyncMock) as mock_resolve:
            mock_resolve.side_effect = [None, listing]
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                r = await ac.get(f"{base_path}/{listing.id}")
            assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_sees_approved(self, route_type, base_path, module_path):
        other_user = _user()
        router = _get_router(route_type)
        listing = _listing_mock(status=ListingStatus.approved)
        app = _app_with(router, user=other_user)

        with patch(f"{module_path}.resolve_listing", new_callable=AsyncMock) as mock_resolve:
            mock_resolve.return_value = listing
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                r = await ac.get(f"{base_path}/{listing.id}")
            assert r.status_code == 200


@pytest.mark.parametrize("route_type,base_path,module_path", ENDPOINTS)
class TestPrivilegedAccess:
    """Admins and reviewers can see any listing in any status."""

    @pytest.mark.asyncio
    async def test_reviewer_sees_pending(self, route_type, base_path, module_path):
        reviewer = _user(role=UserRole.reviewer)
        router = _get_router(route_type)
        listing = _listing_mock(status=ListingStatus.pending)
        app = _app_with(router, user=reviewer)

        with patch(f"{module_path}.resolve_listing", new_callable=AsyncMock) as mock_resolve:
            mock_resolve.side_effect = [None, listing]
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                r = await ac.get(f"{base_path}/{listing.id}")
            assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_sees_draft(self, route_type, base_path, module_path):
        admin = _user(role=UserRole.admin)
        router = _get_router(route_type)
        listing = _listing_mock(status=ListingStatus.draft)
        app = _app_with(router, user=admin)

        with patch(f"{module_path}.resolve_listing", new_callable=AsyncMock) as mock_resolve:
            mock_resolve.side_effect = [None, listing]
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                r = await ac.get(f"{base_path}/{listing.id}")
            assert r.status_code == 200
