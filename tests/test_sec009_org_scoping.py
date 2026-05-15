# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for org-scoped visibility on registry list and detail endpoints.

Verifies that private listings are hidden from users in other organisations,
visible to users in the same organisation, and always visible to admins.
The same rules apply to MCP, skill, hook, prompt, and sandbox routes.
"""

import uuid
from unittest.mock import MagicMock

from api.deps import apply_visibility_filter, check_listing_visibility

# ── Unit tests for the shared helpers ─────────────────────────────────────────


def _user(role="user", org_id=None):
    from models.user import User, UserRole

    u = MagicMock(spec=User)
    u.id = uuid.uuid4()
    u.role = getattr(UserRole, role)
    u.org_id = org_id or uuid.uuid4()
    return u


def _listing(is_private=False, owner_org_id=None, submitted_by=None):
    m = MagicMock()
    m.is_private = is_private
    m.owner_org_id = owner_org_id or uuid.uuid4()
    m.submitted_by = submitted_by or uuid.uuid4()
    return m


class TestCheckListingVisibility:
    def test_public_listing_always_visible(self):
        assert check_listing_visibility(_listing(is_private=False), None) is True
        assert check_listing_visibility(_listing(is_private=False), _user()) is True

    def test_private_hidden_from_anonymous(self):
        assert check_listing_visibility(_listing(is_private=True), None) is False

    def test_private_hidden_from_other_org(self):
        org_a = uuid.uuid4()
        org_b = uuid.uuid4()
        listing = _listing(is_private=True, owner_org_id=org_a)
        user = _user(org_id=org_b)
        assert check_listing_visibility(listing, user) is False

    def test_private_visible_to_same_org(self):
        org = uuid.uuid4()
        listing = _listing(is_private=True, owner_org_id=org)
        user = _user(org_id=org)
        assert check_listing_visibility(listing, user) is True

    def test_private_visible_to_submitter(self):
        user = _user()
        listing = _listing(is_private=True, submitted_by=user.id)
        assert check_listing_visibility(listing, user) is True

    def test_private_visible_to_admin(self):
        listing = _listing(is_private=True)
        assert check_listing_visibility(listing, _user(role="admin")) is True
        assert check_listing_visibility(listing, _user(role="reviewer")) is True

    def test_no_is_private_attr_is_visible(self):
        m = MagicMock(spec=[])  # no is_private attribute
        assert check_listing_visibility(m, None) is True


class TestApplyVisibilityFilter:
    def _stmt(self):
        s = MagicMock()
        s.where = MagicMock(return_value=s)
        return s

    def _model(self):
        from models.mcp import McpListing

        return McpListing

    def test_no_is_private_attr_passes_through(self):
        model = MagicMock(spec=[])
        stmt = self._stmt()
        result = apply_visibility_filter(stmt, model, None)
        stmt.where.assert_not_called()
        assert result is stmt

    def test_anonymous_sees_only_public(self):
        from models.mcp import McpListing

        stmt = self._stmt()
        apply_visibility_filter(stmt, McpListing, None)
        stmt.where.assert_called_once()

    def test_admin_sees_all(self):
        from models.mcp import McpListing

        stmt = self._stmt()
        result = apply_visibility_filter(stmt, McpListing, _user(role="admin"))
        stmt.where.assert_not_called()
        assert result is stmt

    def test_regular_user_filter_applied(self):
        from models.mcp import McpListing

        stmt = self._stmt()
        apply_visibility_filter(stmt, McpListing, _user(role="user"))
        stmt.where.assert_called_once()
