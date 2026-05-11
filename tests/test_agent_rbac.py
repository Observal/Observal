# SPDX-FileCopyrightText: 2026 Harishankar <harishankar0301@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for agent RBAC permission evaluation."""

import uuid
from unittest.mock import MagicMock

from api.deps import get_effective_agent_permission
from models.agent import AgentVisibility
from models.user import UserRole


def _mock_agent(visibility="private", created_by=None, team_accesses=None):
    agent = MagicMock()
    agent.visibility = AgentVisibility(visibility)
    agent.created_by = created_by or uuid.uuid4()
    agent.team_accesses = team_accesses or []
    return agent


def _mock_user(user_id=None, role=UserRole.user, groups=None):
    user = MagicMock()
    user.id = user_id or uuid.uuid4()
    user.role = role
    user._groups = groups or []
    return user


def _mock_access(group_name, permission):
    acc = MagicMock()
    acc.group_name = group_name
    acc.permission = permission
    return acc


class TestGetEffectiveAgentPermission:
    def test_unauthenticated_public_agent_returns_view(self):
        agent = _mock_agent(visibility="public")
        assert get_effective_agent_permission(agent, None) == "view"

    def test_unauthenticated_private_agent_returns_none(self):
        agent = _mock_agent(visibility="private")
        assert get_effective_agent_permission(agent, None) == "none"

    def test_owner_returns_owner(self):
        uid = uuid.uuid4()
        agent = _mock_agent(created_by=uid)
        user = _mock_user(user_id=uid)
        assert get_effective_agent_permission(agent, user) == "owner"

    def test_admin_returns_owner(self):
        agent = _mock_agent()
        user = _mock_user(role=UserRole.admin)
        assert get_effective_agent_permission(agent, user) == "owner"

    def test_super_admin_returns_owner(self):
        agent = _mock_agent()
        user = _mock_user(role=UserRole.super_admin)
        assert get_effective_agent_permission(agent, user) == "owner"

    def test_group_membership_edit(self):
        accesses = [_mock_access("engineering", "edit")]
        agent = _mock_agent(team_accesses=accesses)
        user = _mock_user(groups=["engineering"])
        assert get_effective_agent_permission(agent, user) == "edit"

    def test_group_membership_view(self):
        accesses = [_mock_access("marketing", "view")]
        agent = _mock_agent(team_accesses=accesses)
        user = _mock_user(groups=["marketing"])
        assert get_effective_agent_permission(agent, user) == "view"

    def test_best_permission_wins(self):
        accesses = [
            _mock_access("readers", "view"),
            _mock_access("editors", "edit"),
        ]
        agent = _mock_agent(team_accesses=accesses)
        user = _mock_user(groups=["readers", "editors"])
        assert get_effective_agent_permission(agent, user) == "edit"

    def test_no_group_match_private_returns_none(self):
        accesses = [_mock_access("engineering", "edit")]
        agent = _mock_agent(team_accesses=accesses)
        user = _mock_user(groups=["marketing"])
        assert get_effective_agent_permission(agent, user) == "none"

    def test_no_group_match_public_returns_view(self):
        accesses = [_mock_access("engineering", "edit")]
        agent = _mock_agent(visibility="public", team_accesses=accesses)
        user = _mock_user(groups=["marketing"])
        assert get_effective_agent_permission(agent, user) == "view"

    def test_no_groups_private_returns_none(self):
        agent = _mock_agent()
        user = _mock_user(groups=[])
        assert get_effective_agent_permission(agent, user) == "none"
