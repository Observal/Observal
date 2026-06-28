# SPDX-FileCopyrightText: 2026 Harishankar <harishankar0301@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for agent RBAC permission evaluation."""

import uuid
from unittest.mock import MagicMock

from api.deps import get_effective_agent_permission
from models.user import UserRole


def _mock_agent(created_by=None):
    agent = MagicMock()
    agent.created_by = created_by or uuid.uuid4()
    return agent


def _mock_user(user_id=None, role=UserRole.user):
    user = MagicMock()
    user.id = user_id or uuid.uuid4()
    user.role = role
    return user


class TestGetEffectiveAgentPermission:
    def test_unauthenticated_user_returns_view_permission(self) -> None:
        agent = _mock_agent()
        result = get_effective_agent_permission(agent, None)
        assert result == "view"

    def test_owner_returns_owner_permission(self) -> None:
        uid = uuid.uuid4()
        agent = _mock_agent(created_by=uid)
        user = _mock_user(user_id=uid)
        result = get_effective_agent_permission(agent, user)
        assert result == "owner"

    def test_admin_returns_owner_permission(self) -> None:
        agent = _mock_agent()
        user = _mock_user(role=UserRole.admin)
        result = get_effective_agent_permission(agent, user)
        assert result == "owner"

    def test_super_admin_returns_owner_permission(self) -> None:
        agent = _mock_agent()
        user = _mock_user(role=UserRole.super_admin)
        result = get_effective_agent_permission(agent, user)
        assert result == "owner"

    def test_regular_user_returns_view_permission(self) -> None:
        agent = _mock_agent()
        user = _mock_user()
        result = get_effective_agent_permission(agent, user)
        assert result == "view"
