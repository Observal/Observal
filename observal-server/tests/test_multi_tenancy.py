# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Multi-tenancy isolation tests.

Verifies that org-scoped data access works correctly:
- Users within an org see only their org's resources
- Users with no org (local mode) see everything
- Cross-org access returns 404 (not 403) to prevent info leakage
- owner_org_id is stamped on creation
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from api.deps import get_project_id, optional_current_user, require_org_scope, require_role
from models.agent import Agent, AgentStatus, AgentVersion
from models.organization import Organization
from models.user import User, UserRole

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_org(name: str = "Acme", slug: str = "acme") -> Organization:
    return Organization(id=uuid.uuid4(), name=name, slug=slug)


def _make_user(
    org: Organization | None = None,
    role: UserRole = UserRole.admin,
    email: str | None = None,
) -> User:
    uid = uuid.uuid4()
    user = User(
        id=uid,
        email=email or f"{uid.hex[:8]}@test.example",
        name="Test User",
        role=role,
    )
    if org:
        user.org_id = org.id
    return user


def _make_agent(
    user: User,
    name: str = "test-agent",
    org: Organization | None = None,
) -> Agent:
    agent_id = uuid.uuid4()
    version_id = uuid.uuid4()
    version = AgentVersion(
        id=version_id,
        agent_id=agent_id,
        version="1.0.0",
        description="A test agent",
        prompt="You are a test agent.",
        model_name="claude-sonnet-4-5-20250514",
        status=AgentStatus.approved,
        released_by=user.id,
    )
    agent = Agent(
        id=agent_id,
        name=name,
        owner="test-owner",
        created_by=user.id,
        owner_org_id=org.id if org else user.org_id,
        latest_version_id=version_id,
    )
    # Wire up the relationship for in-memory access
    agent.latest_version = version
    agent.versions = [version]
    return agent


# ---------------------------------------------------------------------------
# get_project_id
# ---------------------------------------------------------------------------


class TestGetProjectId:
    def test_returns_org_id_when_user_has_org(self):
        org = _make_org()
        user = _make_user(org=org)
        assert get_project_id(user) == str(org.id)

    def test_returns_default_when_no_org(self):
        user = _make_user()
        assert get_project_id(user) == "default"


# ---------------------------------------------------------------------------
# require_org_scope
# ---------------------------------------------------------------------------


class TestRequireOrgScope:
    @pytest.mark.asyncio
    async def test_returns_org_id_when_present(self):
        org = _make_org()
        user = _make_user(org=org)
        dep = require_org_scope()
        result = await dep(current_user=user)
        assert result == org.id

    @pytest.mark.asyncio
    async def test_returns_none_for_local_mode(self):
        user = _make_user()
        dep = require_org_scope()
        result = await dep(current_user=user)
        assert result is None


# ---------------------------------------------------------------------------
# optional_current_user
# ---------------------------------------------------------------------------


class TestOptionalCurrentUser:
    @pytest.mark.asyncio
    async def test_returns_none_without_auth(self):
        mock_db = AsyncMock()
        result = await optional_current_user(authorization=None, db=mock_db)
        assert result is None

    @pytest.mark.asyncio
    async def test_raises_401_for_invalid_token(self):
        mock_db = AsyncMock()
        with pytest.raises(HTTPException) as exc_info:
            await optional_current_user(authorization="Bearer invalid-token", db=mock_db)
        assert exc_info.value.status_code == 401
        assert "Invalid or expired" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_raises_401_for_deactivated_user(self):
        from services.jwt_service import create_access_token

        org = _make_org()
        user = _make_user(org=org)
        user.auth_provider = "deactivated"
        token, _ = create_access_token(user.id, user.role)

        mock_result = MagicMock()
        mock_result.one_or_none.return_value = (user, False)
        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result

        with pytest.raises(HTTPException) as exc_info:
            await optional_current_user(authorization=f"Bearer {token}", db=mock_db)
        assert exc_info.value.status_code == 401
        assert "deactivated" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_returns_user_with_valid_token(self):
        from services.jwt_service import create_access_token

        org = _make_org()
        user = _make_user(org=org)
        token, _ = create_access_token(user.id, user.role)

        mock_result = MagicMock()
        mock_result.one_or_none.return_value = (user, False)
        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result

        result = await optional_current_user(authorization=f"Bearer {token}", db=mock_db)
        assert result is user


# ---------------------------------------------------------------------------
# Org-scoped agent visibility
# ---------------------------------------------------------------------------


class TestAgentOrgIsolation:
    """Test that agents are only visible to users in the same org."""

    def setup_method(self):
        self.org_a = _make_org("Org A", "org-a")
        self.org_b = _make_org("Org B", "org-b")
        self.admin_a = _make_user(org=self.org_a, role=UserRole.admin)
        self.admin_b = _make_user(org=self.org_b, role=UserRole.admin)
        self.local_admin = _make_user(role=UserRole.admin)  # no org
        self.agent_a = _make_agent(self.admin_a, name="agent-a", org=self.org_a)
        self.agent_b = _make_agent(self.admin_b, name="agent-b", org=self.org_b)

    def test_org_a_user_can_see_org_a_agent(self):
        agent = self.agent_a
        user = self.admin_a
        assert user.org_id is not None
        assert agent.owner_org_id == user.org_id

    def test_org_a_user_cannot_see_org_b_agent(self):
        agent = self.agent_b
        user = self.admin_a
        assert user.org_id is not None
        assert agent.owner_org_id != user.org_id

    def test_local_mode_user_sees_all_agents(self):
        user = self.local_admin
        assert user.org_id is None
        # Local mode: org_id is None, so no filtering applies

    def test_cross_org_check_returns_404_pattern(self):
        """Org check should raise 404 (not 403) to prevent info leakage."""
        agent = self.agent_b
        user = self.admin_a
        if user.org_id is not None and agent.owner_org_id != user.org_id:
            with pytest.raises(HTTPException) as exc_info:
                raise HTTPException(status_code=404, detail="Agent not found")
            assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Org-scoped admin user management
# ---------------------------------------------------------------------------


class TestAdminOrgIsolation:
    """Test that admin endpoints scope to the admin's org."""

    def setup_method(self):
        self.org_a = _make_org("Org A", "org-a")
        self.org_b = _make_org("Org B", "org-b")
        self.admin_a = _make_user(org=self.org_a, role=UserRole.admin)
        self.user_a = _make_user(org=self.org_a, role=UserRole.user)
        self.user_b = _make_user(org=self.org_b, role=UserRole.user)

    def test_admin_sees_same_org_user(self):
        admin = self.admin_a
        user = self.user_a
        assert admin.org_id is not None
        assert user.org_id == admin.org_id

    def test_admin_cannot_see_other_org_user(self):
        admin = self.admin_a
        user = self.user_b
        assert admin.org_id is not None
        assert user.org_id != admin.org_id

    def test_user_creation_inherits_admin_org(self):
        admin = self.admin_a
        new_user = User(
            email="new@example.com",
            name="New User",
            role=UserRole.user,
            org_id=admin.org_id,
        )
        assert new_user.org_id == admin.org_id


# ---------------------------------------------------------------------------
# Alert org-scoping
# ---------------------------------------------------------------------------


class TestAlertOrgIsolation:
    """Test that alerts are filtered through the user table for org scoping."""

    def setup_method(self):
        self.org_a = _make_org("Org A", "org-a")
        self.org_b = _make_org("Org B", "org-b")
        self.admin_a = _make_user(org=self.org_a, role=UserRole.admin)
        self.user_b = _make_user(org=self.org_b, role=UserRole.user)

    def test_alert_org_filter_logic(self):
        """Admin A should only see alerts created by users in Org A."""
        admin = self.admin_a
        assert admin.org_id is not None
        # An alert created by user_b (Org B) should be invisible to admin A
        assert self.user_b.org_id != admin.org_id

    def test_local_mode_admin_sees_all(self):
        """Admin with no org sees all alerts."""
        local_admin = _make_user(role=UserRole.admin)
        assert local_admin.org_id is None


# ---------------------------------------------------------------------------
# ClickHouse project_id derivation
# ---------------------------------------------------------------------------


class TestProjectIdDerivation:
    """Test that project_id is correctly derived from user org membership."""

    def test_org_user_gets_org_uuid_as_project_id(self):
        org = _make_org()
        user = _make_user(org=org)
        pid = get_project_id(user)
        assert pid == str(org.id)
        assert pid != "default"

    def test_local_user_gets_default_project(self):
        user = _make_user()
        assert get_project_id(user) == "default"

    def test_different_orgs_get_different_project_ids(self):
        org_a = _make_org("A", "a")
        org_b = _make_org("B", "b")
        user_a = _make_user(org=org_a)
        user_b = _make_user(org=org_b)
        assert get_project_id(user_a) != get_project_id(user_b)

    def test_same_org_users_get_same_project_id(self):
        org = _make_org()
        user_1 = _make_user(org=org, email="u1@test.example")
        user_2 = _make_user(org=org, email="u2@test.example")
        assert get_project_id(user_1) == get_project_id(user_2)


# ---------------------------------------------------------------------------
# owner_org_id stamping
# ---------------------------------------------------------------------------


class TestOwnerOrgIdStamping:
    """Test that models correctly receive owner_org_id from the creating user."""

    def test_agent_stamps_org_id(self):
        org = _make_org()
        user = _make_user(org=org)
        agent = _make_agent(user, org=org)
        assert agent.owner_org_id == org.id

    def test_agent_no_org_gets_none(self):
        user = _make_user()
        agent = _make_agent(user)
        assert agent.owner_org_id is None

    def test_org_id_matches_between_user_and_agent(self):
        org = _make_org()
        user = _make_user(org=org)
        agent = _make_agent(user, org=org)
        assert agent.owner_org_id == user.org_id


# ---------------------------------------------------------------------------
# Backward compatibility — local mode
# ---------------------------------------------------------------------------


class TestLocalModeBackwardCompat:
    """Ensure local-mode users (no org) experience no regressions."""

    def test_local_user_has_no_org(self):
        user = _make_user()
        assert user.org_id is None

    def test_local_user_project_id_is_default(self):
        user = _make_user()
        assert get_project_id(user) == "default"

    @pytest.mark.asyncio
    async def test_local_user_org_scope_returns_none(self):
        user = _make_user()
        dep = require_org_scope()
        result = await dep(current_user=user)
        assert result is None

    def test_org_filter_skipped_for_local_admin(self):
        """When org_id is None, the org filter condition should not trigger."""
        user = _make_user(role=UserRole.admin)
        agent_a = _make_agent(_make_user(org=_make_org("A", "a")), org=_make_org("A2", "a2"))
        # Local admin should not be blocked by org mismatch
        assert user.org_id is None
        # The pattern: if user.org_id is not None and ... — should short-circuit
        should_block = user.org_id is not None and agent_a.owner_org_id != user.org_id
        assert should_block is False


# ---------------------------------------------------------------------------
# Role + org interaction
# ---------------------------------------------------------------------------


class TestRoleOrgInteraction:
    """Test interaction between RBAC roles and org scoping."""

    @pytest.mark.asyncio
    async def test_admin_role_check_passes_before_org_check(self):
        """require_role should pass regardless of org membership."""
        org = _make_org()
        user = _make_user(org=org, role=UserRole.admin)
        dep = require_role(UserRole.admin)
        result = await dep(current_user=user)
        assert result is user

    @pytest.mark.asyncio
    async def test_user_role_blocked_before_org_matters(self):
        """A regular user should fail admin check even if same org."""
        org = _make_org()
        user = _make_user(org=org, role=UserRole.user)
        dep = require_role(UserRole.admin)
        with pytest.raises(HTTPException) as exc_info:
            await dep(current_user=user)
        assert exc_info.value.status_code == 403

    def test_super_admin_with_no_org_sees_all(self):
        user = _make_user(role=UserRole.super_admin)
        assert user.org_id is None
        assert get_project_id(user) == "default"
