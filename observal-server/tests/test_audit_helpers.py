# SPDX-FileCopyrightText: 2026 Shanmukh Sharma <satejmore28@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""
observal-server/tests/test_audit_helpers.py

Unit tests for services/audit_helpers.py.
All event bus I/O is mocked so no live services are running.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# 1. Top-Level Imports (Fixes Moderator Comments)
from services.audit_helpers import audit


# ---------------------------------------------------------------------------
# Fixtures & Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_bus():
    """Provides a fresh, clean AsyncMock for the event bus to track emitted events."""
    with patch("services.audit_helpers.bus") as mock_bus_module:
        mock_bus_module.emit = AsyncMock()
        yield mock_bus_module.emit


def _mock_user(user_id: str = "user-abc-123", role: str = "admin") -> MagicMock:
    """Helper to mock a user object with standard attributes."""
    user = MagicMock()
    user.id = user_id
    user.role = MagicMock()
    user.role.value = role
    user.email = "admin@example.com"
    return user


# ---------------------------------------------------------------------------
# audit Tests
# ---------------------------------------------------------------------------

class TestLogAuditEvent:
    """Tests for services.audit_helpers.audit."""

    @pytest.mark.asyncio
    async def test_no_op_when_user_is_none(self, mock_bus):
        """audit must return immediately and emit nothing if user is None."""
        await audit(
            user=None,
            action="approve",
            resource_type="mcp",
            resource_id="mcp-uuid-1",
        )
        mock_bus.assert_not_called()

    @pytest.mark.asyncio
    async def test_emits_event_to_bus(self, mock_bus):
        """audit must call bus.emit() exactly once when a valid user is provided."""
        user = _mock_user()
        await audit(
            user=user,
            action="approve",
            resource_type="mcp",
            resource_id="mcp-uuid-1",
        )
        mock_bus.assert_called_once()

    @pytest.mark.asyncio
    async def test_stores_correct_actor_details(self, mock_bus):
        """The emitted event payload must carry the correct user attributes."""
        user = _mock_user(user_id="custom-id-123", role="moderator")
        user.email = "mod@example.com"
        
        await audit(
            user=user,
            action="delete",
            resource_type="agent",
        )

        # Grab the AuditableAction instance passed to bus.emit()
        emitted_event = mock_bus.call_args[0][0]
        
        assert emitted_event.actor_id == "custom-id-123"
        assert emitted_event.actor_email == "mod@example.com"
        assert emitted_event.actor_role == "moderator"

    @pytest.mark.asyncio
    async def test_stores_action_and_resource_meta(self, mock_bus):
        """The event payload must correctly forward action and resource variables."""
        user = _mock_user()
        await audit(
            user=user,
            action="reject",
            resource_type="skill",
            resource_id="s-1",
            resource_name="test-skill",
            detail="failed linting tests",
        )

        emitted_event = mock_bus.call_args[0][0]
        
        assert emitted_event.action == "reject"
        assert emitted_event.resource_type == "skill"
        assert emitted_event.resource_id == "s-1"
        assert emitted_event.resource_name == "test-skill"
        assert emitted_event.detail == "failed linting tests"
