# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Team publishing auto-approval rules (Feature 3).

Team owners and team reviewers clear the review queue for TEAM-visibility listings
only. Publishing a PUBLIC listing out of a team namespace still goes through global
review, because team roles are self-service and would otherwise be a privilege
escalation path into the global catalog. Global reviewers, admins and super_admins
keep auto-approval for every visibility.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.deps import get_current_user, get_db
from models.agent import AgentStatus
from models.mcp import ListingStatus
from models.team import TeamRole
from models.user import User, UserRole
from services.teamspace import publish_auto_approves_for_entity, resolve_publish_target

# ── Helpers ──────────────────────────────────────────────


def _user(role=UserRole.user, **kw):
    u = MagicMock(spec=User)
    u.id = kw.get("id", uuid.uuid4())
    u.role = role
    u.username = kw.get("username", "testuser")
    u.email = kw.get("email", "test@example.com")
    return u


def _membership(role: TeamRole | None):
    return SimpleNamespace(role=role) if role is not None else None


def _result(value):
    """Stand in for a SQLAlchemy Result whose scalar lookup yields *value*."""
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _mock_db(execute_values=()):
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock(side_effect=[_result(v) for v in execute_values])
    return db


def _app_with(router, user, db):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db
    return app


# (label, user role, team role or None, visibility, expected auto approval)
MATRIX = [
    ("team-owner-public", UserRole.user, TeamRole.owner, "public", False),
    ("team-owner-team", UserRole.user, TeamRole.owner, "team", True),
    ("team-reviewer-public", UserRole.user, TeamRole.reviewer, "public", False),
    ("team-reviewer-team", UserRole.user, TeamRole.reviewer, "team", True),
    ("team-member-public", UserRole.user, TeamRole.member, "public", False),
    ("team-member-team", UserRole.user, TeamRole.member, "team", False),
    ("global-reviewer-public", UserRole.reviewer, None, "public", True),
    ("global-reviewer-team", UserRole.reviewer, None, "team", True),
    ("admin-public", UserRole.admin, None, "public", True),
    ("admin-team", UserRole.admin, None, "team", True),
    ("super-admin-public", UserRole.super_admin, None, "public", True),
    ("super-admin-team", UserRole.super_admin, None, "team", True),
]

MATRIX_PARAMS = [pytest.param(*row[1:], id=row[0]) for row in MATRIX]


# ═══════════════════════════════════════════════════════════
# resolve_publish_target: new listings
# ═══════════════════════════════════════════════════════════


class TestResolvePublishTargetAutoApprove:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(("user_role", "team_role", "visibility", "expected"), MATRIX_PARAMS)
    async def test_matrix(self, user_role, team_role, visibility, expected):
        team_id = uuid.uuid4()
        db = _mock_db([_membership(team_role)])
        db.get = AsyncMock(return_value=SimpleNamespace(id=team_id, handle="platform-tools"))

        target = await resolve_publish_target(
            db, _user(user_role), "Internal Tool", team_id=team_id, visibility=visibility
        )

        assert target.namespace == "platform-tools"
        assert target.visibility == visibility
        assert target.auto_approve is expected

    @pytest.mark.asyncio
    async def test_personal_public_listing_never_auto_approves(self):
        target = await resolve_publish_target(_mock_db(), _user(UserRole.super_admin), "Internal Tool")
        assert (target.team_id, target.visibility, target.auto_approve) == (None, "public", False)


# ═══════════════════════════════════════════════════════════
# publish_auto_approves_for_entity: saved drafts
# ═══════════════════════════════════════════════════════════


class TestEntityAutoApprove:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(("user_role", "team_role", "visibility", "expected"), MATRIX_PARAMS)
    async def test_matrix(self, user_role, team_role, visibility, expected):
        entity = SimpleNamespace(team_id=uuid.uuid4(), is_private=visibility == "team")
        db = _mock_db([_membership(team_role)])

        assert await publish_auto_approves_for_entity(entity, _user(user_role), db) is expected

    @pytest.mark.asyncio
    @pytest.mark.parametrize("visibility", ["public", "team"])
    async def test_non_member_never_auto_approves(self, visibility):
        entity = SimpleNamespace(team_id=uuid.uuid4(), is_private=visibility == "team")
        assert await publish_auto_approves_for_entity(entity, _user(), _mock_db([None])) is False

    @pytest.mark.asyncio
    async def test_personal_listing_skips_membership_lookup(self):
        db = _mock_db()
        entity = SimpleNamespace(team_id=None, is_private=False)
        assert await publish_auto_approves_for_entity(entity, _user(UserRole.super_admin), db) is False
        db.execute.assert_not_awaited()


# ═══════════════════════════════════════════════════════════
# Route level: the auto-approval decision becomes a status
# ═══════════════════════════════════════════════════════════


class TestSkillSubmitStatus:
    """POST /skills/submit resolves a publish target, so the status follows the matrix."""

    @staticmethod
    async def _submit(user, team_role, visibility):
        from api.routes.skill import router
        from models.skill import SkillListing, SkillVersion

        team_id = uuid.uuid4()
        # membership lookup, then the namespace/slug collision check.
        db = _mock_db([_membership(team_role), None])
        db.get = AsyncMock(return_value=SimpleNamespace(id=team_id, handle="platform-tools"))

        def _refresh(obj):
            obj.id = uuid.uuid4()
            obj.created_at = datetime.now(UTC)
            obj.updated_at = datetime.now(UTC)

        db.refresh = AsyncMock(side_effect=_refresh)
        app = _app_with(router, user, db)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(
                "/api/v1/skills/submit",
                json={
                    "name": "s",
                    "version": "1.0",
                    "description": "d",
                    "owner": "o",
                    "task_type": "code-review",
                    "team_id": str(team_id),
                    "visibility": visibility,
                },
            )

        assert r.status_code == 200, r.text
        listing = next(c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], SkillListing))
        version = next(c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], SkillVersion))
        return listing, version

    @pytest.mark.asyncio
    async def test_team_owner_public_stays_pending(self):
        listing, version = await self._submit(_user(), TeamRole.owner, "public")
        assert listing.is_private is False
        assert version.status == ListingStatus.pending
        assert version.reviewed_by is None
        assert version.reviewed_at is None

    @pytest.mark.asyncio
    async def test_team_owner_team_is_approved(self):
        listing, version = await self._submit(_user(), TeamRole.owner, "team")
        assert listing.is_private is True
        assert version.status == ListingStatus.approved
        assert version.reviewed_by is not None

    @pytest.mark.asyncio
    async def test_team_reviewer_public_stays_pending(self):
        _listing, version = await self._submit(_user(), TeamRole.reviewer, "public")
        assert version.status == ListingStatus.pending

    @pytest.mark.asyncio
    async def test_global_reviewer_public_is_approved(self):
        _listing, version = await self._submit(_user(UserRole.reviewer), None, "public")
        assert version.status == ListingStatus.approved
        assert version.reviewed_by is not None


class TestAgentSubmitStatus:
    """POST /agents/{id}/submit reads the saved agent's own visibility."""

    @staticmethod
    def _agent(is_private):
        m = MagicMock()
        m.id = uuid.uuid4()
        m.name = "test-agent"
        m.status = AgentStatus.draft
        m.team_id = uuid.uuid4()
        m.is_private = is_private
        m.components = []
        m.description = "A test agent"
        m.owner = "testowner"
        m.rejection_reason = None
        m.deleted_at = None
        m.latest_version.prompt = "Test prompt"
        m.latest_version.reviewed_by = None
        m.latest_version.reviewed_at = None
        return m

    @staticmethod
    async def _submit(user, team_role, is_private):
        from api.routes.agent import draft as draft_routes

        agent = TestAgentSubmitStatus._agent(is_private)
        agent.created_by = user.id
        db = _mock_db([_membership(team_role)])

        with (
            patch("services.agent_snapshot.build_yaml_snapshot", new=AsyncMock(return_value="snapshot")),
            patch.object(draft_routes, "emit_registry_event"),
            patch.object(draft_routes, "_resolve_component_names", new=AsyncMock(return_value={})),
            patch.object(draft_routes, "_load_agent", new=AsyncMock(return_value=agent)),
            patch.object(draft_routes, "_agent_to_response", new=MagicMock(return_value={"status": "ok"})),
        ):
            await draft_routes.submit_draft(str(agent.id), db, user)

        return agent

    @pytest.mark.asyncio
    async def test_team_owner_public_agent_stays_pending(self):
        agent = await self._submit(_user(), TeamRole.owner, is_private=False)
        assert agent.status == AgentStatus.pending
        assert agent.latest_version.reviewed_by is None

    @pytest.mark.asyncio
    async def test_team_owner_team_agent_is_approved(self):
        agent = await self._submit(_user(), TeamRole.owner, is_private=True)
        assert agent.status == AgentStatus.approved
        assert agent.latest_version.reviewed_by is not None

    @pytest.mark.asyncio
    async def test_team_reviewer_public_agent_stays_pending(self):
        agent = await self._submit(_user(), TeamRole.reviewer, is_private=False)
        assert agent.status == AgentStatus.pending

    @pytest.mark.asyncio
    async def test_team_member_team_agent_stays_pending(self):
        agent = await self._submit(_user(), TeamRole.member, is_private=True)
        assert agent.status == AgentStatus.pending

    @pytest.mark.asyncio
    async def test_admin_public_agent_is_approved(self):
        agent = await self._submit(_user(UserRole.admin), None, is_private=False)
        assert agent.status == AgentStatus.approved
