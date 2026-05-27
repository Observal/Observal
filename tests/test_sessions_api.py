# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 tsitu0 <tomsitu0102@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


def _user(role="user"):
    from models.user import User, UserRole

    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.role = getattr(UserRole, role)
    return user


@pytest.mark.asyncio
async def test_bind_session_agent_denied_raises_404():
    """Mutation access failures should use HTTP errors, matching other ownership checks."""
    from api.routes.sessions import bind_session_agent

    with (
        patch("api.routes.sessions._ch_json", new=AsyncMock(return_value=[])),
        pytest.raises(HTTPException) as exc,
    ):
        await bind_session_agent("session-123", agent_name="agent", current_user=_user())

    assert exc.value.status_code == 404
    assert exc.value.detail == "Session not found or access denied"
