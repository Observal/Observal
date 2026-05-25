# SPDX-FileCopyrightText: 2026 Harishankar <harishankar0301@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.deps import _authenticate_via_jwt, get_effective_agent_permission
from models.agent import AgentVisibility
from models.user import User, UserRole
from services.jwt_service import create_access_token


@pytest.fixture(autouse=True, scope="module")
def _init_key_manager(tmp_path_factory):
    from services.crypto import init_key_manager

    key_dir = tmp_path_factory.mktemp("keys")
    init_key_manager(key_dir=str(key_dir), key_password=None)


@pytest.mark.asyncio
async def test_sso_token_to_rbac_flow():
    """
    Validates that:
    1. A JWT containing 'groups' (from IDP) is correctly decoded by _authenticate_via_jwt.
    2. The groups are securely attached to the user object as `_groups`.
    3. get_effective_agent_permission correctly consumes these groups to grant access.
    """
    user_id = uuid.uuid4()
    org_id = uuid.uuid4()

    # 1. Create a real access token with the "engineering" group
    # This simulates what the auth endpoints generate after SSO login
    token, _ = create_access_token(user_id, UserRole.user, groups=["engineering"])

    # Mock request containing the token
    mock_request = MagicMock()
    mock_request.headers.get.return_value = f"Bearer {token}"

    # Mock the database returning our user
    mock_user = User(id=user_id, email="sso_user@example.com", role=UserRole.user, org_id=org_id)

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.one_or_none.return_value = (mock_user, False)
    mock_db.execute.return_value = mock_result

    # Mock Redis to avoid revocation checks failing
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None

    with patch("api.deps.get_redis", return_value=mock_redis):
        # 2. Authenticate the user via the JWT
        authenticated_user = await _authenticate_via_jwt(token, mock_db)

        # Verify the groups were correctly extracted and attached
        assert authenticated_user is not None
        assert hasattr(authenticated_user, "_groups")
        assert "engineering" in authenticated_user._groups

        # 3. Validate the RBAC logic with this user
        agent = MagicMock()
        agent.visibility = AgentVisibility.private
        agent.created_by = uuid.uuid4()
        agent.owner_org_id = org_id

        # Define the agent's team access requirements
        class MockAccess:
            def __init__(self, name, perm):
                self.group_name = name
                self.permission = perm

        # The agent requires the "engineering" group for "edit" access
        agent.team_accesses = [MockAccess("engineering", "edit")]

        # Evaluate permissions
        permission = get_effective_agent_permission(agent, authenticated_user)

        # Assert the user received the correct group-based permission
        assert permission == "edit"

        # Verify negative case: Agent requires a different group
        agent.team_accesses = [MockAccess("marketing", "view")]
        permission_negative = get_effective_agent_permission(agent, authenticated_user)
        assert permission_negative == "none"

        print("\nSUCCESS: End-to-end group-based RBAC validated via IDP token!")
