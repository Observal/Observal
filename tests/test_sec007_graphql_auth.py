# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for the GraphQL endpoint authentication requirement.

Verifies that the /api/v1/graphql endpoint rejects unauthenticated requests
and that authenticated requests are allowed through to the resolvers.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_client():
    from httpx import ASGITransport, AsyncClient

    from api.ratelimit import limiter
    from main import app

    limiter.enabled = False
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    )


GQL_TRACES = '{ "query": "{ traces { edges { node { trace_id } } } }" }'
GQL_SPAN = '{ "query": "{ span(spanId: \\"abc\\") { span_id } }" }'


@pytest.mark.asyncio
async def test_graphql_rejects_unauthenticated():
    """Anonymous POST to /api/v1/graphql must return 401."""
    from main import app

    app.dependency_overrides.clear()
    async with _make_client() as client:
        r = await client.post(
            "/api/v1/graphql",
            content=GQL_TRACES,
            headers={"Content-Type": "application/json"},
        )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_graphql_rejects_invalid_token():
    """A request with a malformed Bearer token must return 401."""
    from main import app

    app.dependency_overrides.clear()
    async with _make_client() as client:
        r = await client.post(
            "/api/v1/graphql",
            content=GQL_TRACES,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer not-a-real-token",
            },
        )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_graphql_allows_authenticated_user():
    """A valid authenticated context reaches the resolver (no 401/403)."""
    from api.graphql import get_context_dep
    from main import app

    async def _fake_ctx():
        return {
            "project_id": "default",
            "user_id": str(uuid.uuid4()),
            "user_role": "user",
            "trace_privacy": False,
            "span_loader": MagicMock(),
            "score_by_trace_loader": MagicMock(),
            "score_by_span_loader": MagicMock(),
        }

    app.dependency_overrides[get_context_dep] = _fake_ctx
    try:
        with patch("api.graphql.query_traces", new_callable=AsyncMock, return_value=[]):
            async with _make_client() as client:
                r = await client.post(
                    "/api/v1/graphql",
                    content=GQL_TRACES,
                    headers={"Content-Type": "application/json"},
                )
        assert r.status_code == 200
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_graphql_get_rejects_unauthenticated():
    """GraphQL introspection via GET also requires auth."""
    from main import app

    app.dependency_overrides.clear()
    async with _make_client() as client:
        r = await client.get("/api/v1/graphql?query={__typename}")
    assert r.status_code == 401
