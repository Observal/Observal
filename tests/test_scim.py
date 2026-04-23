"""Tests for SCIM 2.0 provisioning service and endpoints."""

import hashlib
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient


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


class TestScimEndpoints:
    @pytest.fixture
    def scim_app(self):
        from fastapi import FastAPI

        from ee.observal_server.routes.scim import router

        app = FastAPI()
        app.include_router(router)
        return app

    @pytest.mark.asyncio
    async def test_list_users_requires_auth(self, scim_app):
        async with AsyncClient(transport=ASGITransport(app=scim_app), base_url="http://test") as ac:
            r = await ac.get("/api/v1/scim/Users")
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_create_user_requires_auth(self, scim_app):
        async with AsyncClient(transport=ASGITransport(app=scim_app), base_url="http://test") as ac:
            r = await ac.post("/api/v1/scim/Users", json={"userName": "test@test.com"})
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_get_user_requires_auth(self, scim_app):
        async with AsyncClient(transport=ASGITransport(app=scim_app), base_url="http://test") as ac:
            r = await ac.get("/api/v1/scim/Users/550e8400-e29b-41d4-a716-446655440000")
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_update_user_requires_auth(self, scim_app):
        async with AsyncClient(transport=ASGITransport(app=scim_app), base_url="http://test") as ac:
            r = await ac.put("/api/v1/scim/Users/550e8400-e29b-41d4-a716-446655440000", json={})
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_delete_user_requires_auth(self, scim_app):
        async with AsyncClient(transport=ASGITransport(app=scim_app), base_url="http://test") as ac:
            r = await ac.delete("/api/v1/scim/Users/550e8400-e29b-41d4-a716-446655440000")
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_patch_user_requires_auth(self, scim_app):
        async with AsyncClient(transport=ASGITransport(app=scim_app), base_url="http://test") as ac:
            r = await ac.patch(
                "/api/v1/scim/Users/550e8400-e29b-41d4-a716-446655440000",
                json={
                    "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
                    "Operations": [{"op": "replace", "path": "displayName", "value": "X"}],
                },
            )
        assert r.status_code == 401

    # -- Discovery endpoints (no auth required) --

    @pytest.mark.asyncio
    async def test_service_provider_config(self, scim_app):
        async with AsyncClient(transport=ASGITransport(app=scim_app), base_url="http://test") as ac:
            r = await ac.get("/api/v1/scim/ServiceProviderConfig")
        assert r.status_code == 200
        data = r.json()
        assert "urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig" in data["schemas"]
        assert data["patch"]["supported"] is True
        assert data["bulk"]["supported"] is False

    @pytest.mark.asyncio
    async def test_schemas_endpoint(self, scim_app):
        async with AsyncClient(transport=ASGITransport(app=scim_app), base_url="http://test") as ac:
            r = await ac.get("/api/v1/scim/Schemas")
        assert r.status_code == 200
        data = r.json()
        assert data["totalResults"] == 1
        resource = data["Resources"][0]
        assert resource["id"] == "urn:ietf:params:scim:schemas:core:2.0:User"
        assert resource["name"] == "User"
        assert len(resource["attributes"]) > 0

    @pytest.mark.asyncio
    async def test_resource_types_endpoint(self, scim_app):
        async with AsyncClient(transport=ASGITransport(app=scim_app), base_url="http://test") as ac:
            r = await ac.get("/api/v1/scim/ResourceTypes")
        assert r.status_code == 200
        data = r.json()
        assert data["totalResults"] == 1
        resource = data["Resources"][0]
        assert resource["id"] == "User"
        assert resource["endpoint"] == "/Users"
        assert resource["schema"] == "urn:ietf:params:scim:schemas:core:2.0:User"

    @pytest.mark.asyncio
    async def test_discovery_endpoints_no_auth_required(self, scim_app):
        """Discovery endpoints must return 200 without any bearer token."""
        async with AsyncClient(transport=ASGITransport(app=scim_app), base_url="http://test") as ac:
            for path in [
                "/api/v1/scim/ServiceProviderConfig",
                "/api/v1/scim/Schemas",
                "/api/v1/scim/ResourceTypes",
            ]:
                r = await ac.get(path)
                assert r.status_code == 200, f"{path} returned {r.status_code}"


class TestScimPatchOp:
    """Tests for _apply_patch_op and the PATCH endpoint logic."""

    def test_patch_replace_display_name(self):
        from ee.observal_server.routes.scim import _apply_patch_op

        user = MagicMock()
        user.name = "Old Name"
        err = _apply_patch_op(user, "replace", "displayName", "New Name")
        assert err is None
        assert user.name == "New Name"

    def test_patch_replace_active_false_deactivates(self):
        from ee.observal_server.routes.scim import _apply_patch_op

        user = MagicMock()
        user.auth_provider = "scim"
        err = _apply_patch_op(user, "replace", "active", False)
        assert err is None
        assert user.auth_provider == "deactivated"
        assert user.password_hash is None

    def test_patch_invalid_op_returns_error(self):
        from ee.observal_server.routes.scim import _apply_patch_op

        user = MagicMock()
        err = _apply_patch_op(user, "invalid_op", "displayName", "X")
        assert err is not None
        assert "Unsupported op" in err

    def test_patch_remove_returns_error(self):
        from ee.observal_server.routes.scim import _apply_patch_op

        user = MagicMock()
        err = _apply_patch_op(user, "remove", "displayName", None)
        assert err is not None
        assert "Cannot remove" in err

    def test_patch_replace_given_name(self):
        from ee.observal_server.routes.scim import _apply_patch_op

        user = MagicMock()
        user.name = "Jane Smith"
        err = _apply_patch_op(user, "replace", "name.givenName", "Janet")
        assert err is None
        assert user.name == "Janet Smith"

    def test_patch_replace_email_via_username(self):
        from ee.observal_server.routes.scim import _apply_patch_op

        user = MagicMock()
        user.email = "old@example.com"
        err = _apply_patch_op(user, "replace", "userName", "NEW@Example.COM")
        assert err is None
        assert user.email == "new@example.com"

    def test_patch_add_treated_as_replace(self):
        from ee.observal_server.routes.scim import _apply_patch_op

        user = MagicMock()
        user.name = "Old"
        err = _apply_patch_op(user, "add", "displayName", "New")
        assert err is None
        assert user.name == "New"

    def test_patch_replace_email_bracket_notation(self):
        from ee.observal_server.routes.scim import _apply_patch_op

        user = MagicMock()
        user.email = "old@example.com"
        err = _apply_patch_op(user, "replace", 'emails[type eq "work"].value', "new@example.com")
        assert err is None
        assert user.email == "new@example.com"

    def test_patch_reactivate_user(self):
        from ee.observal_server.routes.scim import _apply_patch_op

        user = MagicMock()
        user.auth_provider = "deactivated"
        err = _apply_patch_op(user, "replace", "active", True)
        assert err is None
        assert user.auth_provider == "scim"
