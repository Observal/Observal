# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 tsitu0 <tomsitu0102@gmail.com>
# SPDX-License-Identifier: Apache-2.0

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
async def test_session_detail_queries_use_owned_canonical_identity():
    from api.routes.sessions import get_session

    calls: list[tuple[str, dict]] = []

    async def query(sql, params=None):
        calls.append((sql, params or {}))
        if len(calls) == 1:
            return [{"project_id": "project", "user_id": str(user.id), "harness": "cursor"}]
        return []

    user = _user()
    with patch("api.routes.sessions._ch_json", side_effect=query):
        await get_session("shared-id", current_user=user)

    assert len(calls) == 3
    assert "user_id = {uid:String}" in calls[0][0]
    for sql, params in calls[1:]:
        assert "project_id = {pid:String}" in sql
        assert "user_id = {uid:String}" in sql
        assert "harness = {harness:String}" in sql
        assert params["param_pid"] == "project"
        assert params["param_uid"] == str(user.id)
        assert params["param_harness"] == "cursor"


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
