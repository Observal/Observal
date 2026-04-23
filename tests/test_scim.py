"""Tests for SCIM 2.0 provisioning service and endpoints."""

import hashlib
from unittest.mock import MagicMock


class TestScimService:
    def test_parse_scim_user_resource_extracts_fields(self):
        from ee.observal_server.services.scim_service import parse_scim_user

        resource = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "jsmith@example.com",
            "name": {"givenName": "Jane", "familyName": "Smith"},
            "emails": [{"value": "jsmith@example.com", "primary": True}],
            "active": True,
        }
        result = parse_scim_user(resource)
        assert result["email"] == "jsmith@example.com"
        assert result["name"] == "Jane Smith"
        assert result["active"] is True

    def test_parse_scim_user_falls_back_to_username_for_email(self):
        from ee.observal_server.services.scim_service import parse_scim_user

        resource = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "jsmith@example.com",
            "active": True,
        }
        result = parse_scim_user(resource)
        assert result["email"] == "jsmith@example.com"
        assert result["name"] == "jsmith@example.com"

    def test_parse_scim_user_normalizes_email_case(self):
        from ee.observal_server.services.scim_service import parse_scim_user

        resource = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "JSmith@Example.COM",
            "emails": [{"value": "  JSmith@Example.COM  ", "primary": True}],
            "active": True,
        }
        result = parse_scim_user(resource)
        assert result["email"] == "jsmith@example.com"

    def test_parse_scim_user_uses_display_name(self):
        from ee.observal_server.services.scim_service import parse_scim_user

        resource = {
            "userName": "jsmith@example.com",
            "displayName": "Jane S.",
            "active": True,
        }
        result = parse_scim_user(resource)
        assert result["name"] == "Jane S."

    def test_format_scim_user_response(self):
        from ee.observal_server.services.scim_service import format_scim_user

        user = MagicMock()
        user.id = "550e8400-e29b-41d4-a716-446655440000"
        user.email = "jsmith@example.com"
        user.name = "Jane Smith"
        user.created_at.isoformat.return_value = "2026-01-01T00:00:00Z"
        user.auth_provider = "scim"

        result = format_scim_user(user, base_url="https://app.example.com/api/v1/scim")
        assert result["id"] == "550e8400-e29b-41d4-a716-446655440000"
        assert result["userName"] == "jsmith@example.com"
        assert "urn:ietf:params:scim:schemas:core:2.0:User" in result["schemas"]
        assert result["active"] is True

    def test_format_scim_user_deactivated(self):
        from ee.observal_server.services.scim_service import format_scim_user

        user = MagicMock()
        user.id = "550e8400-e29b-41d4-a716-446655440000"
        user.email = "jsmith@example.com"
        user.name = "Jane Smith"
        user.created_at.isoformat.return_value = "2026-01-01T00:00:00Z"
        user.auth_provider = "deactivated"

        result = format_scim_user(user)
        assert result["active"] is False

    def test_hash_scim_token(self):
        from ee.observal_server.services.scim_service import hash_scim_token

        token = "test-scim-bearer-token-1234"
        hashed = hash_scim_token(token)
        assert hashed == hashlib.sha256(token.encode()).hexdigest()

    def test_format_scim_list(self):
        from ee.observal_server.services.scim_service import format_scim_list

        resources = [{"id": "1"}, {"id": "2"}]
        result = format_scim_list(resources, total=10, start_index=1)
        assert result["totalResults"] == 10
        assert result["itemsPerPage"] == 2
        assert result["startIndex"] == 1
        assert len(result["Resources"]) == 2

    def test_format_scim_error(self):
        from ee.observal_server.services.scim_service import format_scim_error

        result = format_scim_error(404, "User not found")
        assert result["status"] == "404"
        assert result["detail"] == "User not found"
