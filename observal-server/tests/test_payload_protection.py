# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for payload protection middleware.

Uses a minimal FastAPI app (no DB / external services) that exercises the
ContentTypeMiddleware, RequestIDMiddleware, and JSON depth protection.
"""

import json
import uuid

import pytest
from fastapi import FastAPI, status
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from api.middleware.content_type import MAX_JSON_DEPTH, ContentTypeMiddleware
from api.middleware.request_id import RequestIDMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Minimal copy for testing — mirrors main.SecurityHeadersMiddleware."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "font-src 'self'; "
            "connect-src 'self' https:; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
        return response


# ---------------------------------------------------------------------------
# Lightweight test app
# ---------------------------------------------------------------------------


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(ContentTypeMiddleware)
    app.add_middleware(RequestIDMiddleware)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/api/v1/echo")
    async def echo(request: Request):
        body = await request.json()
        return JSONResponse(content=body)

    @app.put("/api/v1/echo")
    async def echo_put(request: Request):
        body = await request.json()
        return JSONResponse(content=body)

    @app.patch("/api/v1/echo")
    async def echo_patch(request: Request):
        body = await request.json()
        return JSONResponse(content=body)

    @app.get("/api/v1/items")
    async def items():
        return {"items": []}

    @app.delete("/api/v1/items/1")
    async def delete_item():
        return {"deleted": True}

    # Simulate OTLP endpoint (should be exempt from content-type check)
    @app.post("/v1/traces")
    async def otlp_traces(request: Request):
        return JSONResponse(content={"partialSuccess": {}})

    return app


@pytest.fixture
def app():
    return _build_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ===================================================================
# Content-Type validation
# ===================================================================


class TestContentTypeValidation:
    @pytest.mark.asyncio
    async def test_post_json_accepted(self, client):
        resp = await client.post(
            "/api/v1/echo",
            content=json.dumps({"msg": "hello"}),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json() == {"msg": "hello"}

    @pytest.mark.asyncio
    async def test_post_text_plain_rejected(self, client):
        resp = await client.post(
            "/api/v1/echo",
            content="hello",
            headers={"Content-Type": "text/plain"},
        )
        assert resp.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
        assert "Unsupported media type" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_post_no_content_type_rejected(self, client):
        resp = await client.post(
            "/api/v1/echo",
            content=json.dumps({"msg": "hello"}),
            headers={"Content-Type": ""},
        )
        assert resp.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE

    @pytest.mark.asyncio
    async def test_put_text_xml_rejected(self, client):
        resp = await client.put(
            "/api/v1/echo",
            content="<x/>",
            headers={"Content-Type": "text/xml"},
        )
        assert resp.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE

    @pytest.mark.asyncio
    async def test_patch_json_accepted(self, client):
        resp = await client.patch(
            "/api/v1/echo",
            content=json.dumps({"field": "value"}),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == status.HTTP_200_OK

    @pytest.mark.asyncio
    async def test_get_skips_validation(self, client):
        resp = await client.get("/api/v1/items")
        assert resp.status_code == status.HTTP_200_OK

    @pytest.mark.asyncio
    async def test_delete_skips_validation(self, client):
        resp = await client.delete("/api/v1/items/1")
        assert resp.status_code == status.HTTP_200_OK

    @pytest.mark.asyncio
    async def test_health_skips_validation(self, client):
        resp = await client.post(
            "/health",
            content="not json",
            headers={"Content-Type": "text/plain"},
        )
        # Health is skipped, so even though POST+text/plain, it should not return 415.
        # (it may 405 if the route doesn't support POST, but not 415)
        assert resp.status_code != status.HTTP_415_UNSUPPORTED_MEDIA_TYPE

    @pytest.mark.asyncio
    async def test_otlp_traces_exempt(self, client):
        """OTLP endpoints are exempt from strict content-type enforcement."""
        resp = await client.post(
            "/v1/traces",
            content=json.dumps({"resourceSpans": []}),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == status.HTTP_200_OK

    @pytest.mark.asyncio
    async def test_json_with_charset_accepted(self, client):
        resp = await client.post(
            "/api/v1/echo",
            content=json.dumps({"msg": "utf8"}),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        assert resp.status_code == status.HTTP_200_OK


# ===================================================================
# JSON depth protection
# ===================================================================


def _nested_dict(depth: int) -> dict:
    """Build a dict nested to *depth* levels."""
    obj: dict = {"leaf": True}
    for _ in range(depth - 1):
        obj = {"nested": obj}
    return obj


class TestJsonDepthProtection:
    @pytest.mark.asyncio
    async def test_shallow_json_accepted(self, client):
        body = _nested_dict(5)
        resp = await client.post(
            "/api/v1/echo",
            content=json.dumps(body),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == status.HTTP_200_OK

    @pytest.mark.asyncio
    async def test_max_depth_accepted(self, client):
        body = _nested_dict(MAX_JSON_DEPTH)
        resp = await client.post(
            "/api/v1/echo",
            content=json.dumps(body),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == status.HTTP_200_OK

    @pytest.mark.asyncio
    async def test_excessive_depth_rejected(self, client):
        body = _nested_dict(MAX_JSON_DEPTH + 1)
        resp = await client.post(
            "/api/v1/echo",
            content=json.dumps(body),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "nesting depth" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_deeply_nested_list_rejected(self, client):
        obj: list = ["leaf"]
        for _ in range(MAX_JSON_DEPTH + 5):
            obj = [obj]
        resp = await client.post(
            "/api/v1/echo",
            content=json.dumps(obj),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.asyncio
    async def test_malformed_json_rejected(self, client):
        resp = await client.post(
            "/api/v1/echo",
            content="{not valid json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "Malformed JSON" in resp.json()["detail"]


# ===================================================================
# Request ID middleware
# ===================================================================


class TestRequestID:
    @pytest.mark.asyncio
    async def test_generates_request_id(self, client):
        resp = await client.get("/api/v1/items")
        rid = resp.headers.get("X-Request-ID")
        assert rid is not None
        # Should be a valid UUID.
        uuid.UUID(rid)

    @pytest.mark.asyncio
    async def test_passthrough_valid_uuid(self, client):
        custom_id = str(uuid.uuid4())
        resp = await client.get(
            "/api/v1/items",
            headers={"X-Request-ID": custom_id},
        )
        assert resp.headers["X-Request-ID"] == custom_id

    @pytest.mark.asyncio
    async def test_invalid_uuid_replaced(self, client):
        resp = await client.get(
            "/api/v1/items",
            headers={"X-Request-ID": "not-a-uuid"},
        )
        rid = resp.headers.get("X-Request-ID")
        assert rid is not None
        assert rid != "not-a-uuid"
        # Must be a valid UUID.
        uuid.UUID(rid)

    @pytest.mark.asyncio
    async def test_header_injection_prevented(self, client):
        # Attempt header injection via X-Request-ID value.
        resp = await client.get(
            "/api/v1/items",
            headers={"X-Request-ID": "abc\r\nX-Evil: injected"},
        )
        rid = resp.headers.get("X-Request-ID")
        assert rid is not None
        assert "X-Evil" not in rid
        uuid.UUID(rid)

    @pytest.mark.asyncio
    async def test_request_id_on_post(self, client):
        resp = await client.post(
            "/api/v1/echo",
            content=json.dumps({"test": True}),
            headers={"Content-Type": "application/json"},
        )
        rid = resp.headers.get("X-Request-ID")
        assert rid is not None
        uuid.UUID(rid)


# ===================================================================
# Security headers middleware
# ===================================================================


class TestSecurityHeaders:
    @pytest.mark.asyncio
    async def test_csp_header_present(self, client):
        resp = await client.get("/api/v1/items")
        csp = resp.headers.get("Content-Security-Policy")
        assert csp is not None
        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp

    @pytest.mark.asyncio
    async def test_xss_protection_headers(self, client):
        resp = await client.get("/api/v1/items")
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert resp.headers["X-Frame-Options"] == "DENY"
        assert resp.headers["X-XSS-Protection"] == "1; mode=block"
        assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
        assert resp.headers["X-Permitted-Cross-Domain-Policies"] == "none"

    @pytest.mark.asyncio
    async def test_csp_blocks_inline_scripts(self, client):
        resp = await client.get("/api/v1/items")
        csp = resp.headers["Content-Security-Policy"]
        assert "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]

    @pytest.mark.asyncio
    async def test_permissions_policy(self, client):
        resp = await client.get("/api/v1/items")
        pp = resp.headers.get("Permissions-Policy")
        assert pp is not None
        assert "camera=()" in pp
        assert "microphone=()" in pp
        assert "geolocation=()" in pp
