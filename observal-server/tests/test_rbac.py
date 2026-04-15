"""Tests for the 4-tier RBAC system."""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from api.deps import ROLE_HIERARCHY, require_role
from models.user import User, UserRole


def test_userrole_enum_has_four_tiers():
    """UserRole must have exactly super_admin, admin, reviewer, user."""
    expected = {"super_admin", "admin", "reviewer", "user"}
    actual = {r.value for r in UserRole}
    assert actual == expected, f"Expected {expected}, got {actual}"


def test_userrole_enum_values():
    """Each role's .value matches its name."""
    assert UserRole.super_admin.value == "super_admin"
    assert UserRole.admin.value == "admin"
    assert UserRole.reviewer.value == "reviewer"
    assert UserRole.user.value == "user"


def test_developer_role_does_not_exist():
    """The old 'developer' role must not exist."""
    assert not hasattr(UserRole, "developer"), "developer role should be removed"


def test_user_model_has_is_demo_field():
    """User model must have is_demo boolean field."""
    user = User(
        email="test@example.com",
        name="Test",
    )
    assert user.is_demo is False, "is_demo should default to False"


def test_role_hierarchy_ordering():
    """super_admin has lowest number (highest privilege)."""
    assert ROLE_HIERARCHY[UserRole.super_admin] < ROLE_HIERARCHY[UserRole.admin]
    assert ROLE_HIERARCHY[UserRole.admin] < ROLE_HIERARCHY[UserRole.reviewer]
    assert ROLE_HIERARCHY[UserRole.reviewer] < ROLE_HIERARCHY[UserRole.user]


def test_role_hierarchy_has_all_roles():
    """Every UserRole must be in the hierarchy."""
    for role in UserRole:
        assert role in ROLE_HIERARCHY, f"{role} missing from ROLE_HIERARCHY"


@pytest.mark.asyncio
async def test_require_role_allows_exact_match():
    """User with exact required role should pass."""
    dep = require_role(UserRole.admin)
    mock_user = MagicMock()
    mock_user.role = UserRole.admin
    result = await dep(current_user=mock_user)
    assert result is mock_user


@pytest.mark.asyncio
async def test_require_role_allows_higher_role():
    """super_admin should pass an admin check."""
    dep = require_role(UserRole.admin)
    mock_user = MagicMock()
    mock_user.role = UserRole.super_admin
    result = await dep(current_user=mock_user)
    assert result is mock_user


@pytest.mark.asyncio
async def test_require_role_blocks_lower_role():
    """user should not pass an admin check."""
    dep = require_role(UserRole.admin)
    mock_user = MagicMock()
    mock_user.role = UserRole.user
    with pytest.raises(HTTPException) as exc_info:
        await dep(current_user=mock_user)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_require_role_reviewer_allows_admin():
    """admin should pass a reviewer check."""
    dep = require_role(UserRole.reviewer)
    mock_user = MagicMock()
    mock_user.role = UserRole.admin
    result = await dep(current_user=mock_user)
    assert result is mock_user


@pytest.mark.asyncio
async def test_require_role_reviewer_blocks_user():
    """user should not pass a reviewer check."""
    dep = require_role(UserRole.reviewer)
    mock_user = MagicMock()
    mock_user.role = UserRole.user
    with pytest.raises(HTTPException) as exc_info:
        await dep(current_user=mock_user)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_require_role_user_allows_everyone():
    """Every role should pass a user-level check."""
    dep = require_role(UserRole.user)
    for role in UserRole:
        mock_user = MagicMock()
        mock_user.role = role
        result = await dep(current_user=mock_user)
        assert result is mock_user
