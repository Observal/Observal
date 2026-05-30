# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.deps import get_current_user
from api.routes.telemetry import router
from models.user import User, UserRole


@pytest.fixture(autouse=True)
def _disable_rate_limiter():
    from api.ratelimit import limiter

    old_enabled = limiter.enabled
    limiter.enabled = False
    try:
        yield
    finally:
        limiter.enabled = old_enabled


def _make_user(org_id: uuid.UUID | None = None):
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.org_id = org_id
    user.role = UserRole.user
    return user


def _app_with_user(user):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: user
    return app


@pytest.mark.asyncio
async def test_client_score_sources_are_namespaced_and_marked_untrusted():
    app = _app_with_user(_make_user())

    with patch("api.routes.telemetry.insert_scores", new_callable=AsyncMock) as insert_scores:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/telemetry/ingest",
                json={
                    "scores": [
                        {
                            "score_id": "score-1",
                            "name": "accuracy",
                            "source": "manual",
                            "value": 0.97,
                            "metadata": {"team": "quality"},
                        }
                    ]
                },
            )

    assert response.status_code == 200
    rows = insert_scores.call_args.args[0]
    assert rows[0]["source"] == "client:manual"
    assert rows[0]["metadata"] == {
        "team": "quality",
        "score_original_source": "manual",
        "score_trust": "untrusted_client",
        "score_writer": "telemetry_api",
    }


@pytest.mark.asyncio
async def test_client_prefixed_score_source_is_preserved():
    app = _app_with_user(_make_user())

    with patch("api.routes.telemetry.insert_scores", new_callable=AsyncMock) as insert_scores:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/telemetry/ingest",
                json={"scores": [{"score_id": "score-1", "name": "accuracy", "source": "client:manual", "value": 1}]},
            )

    assert response.status_code == 200
    rows = insert_scores.call_args.args[0]
    assert rows[0]["source"] == "client:manual"


@pytest.mark.asyncio
async def test_reserved_internal_score_source_is_rejected():
    app = _app_with_user(_make_user())

    with patch("api.routes.telemetry.insert_scores", new_callable=AsyncMock) as insert_scores:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/telemetry/ingest",
                json={"scores": [{"score_id": "score-1", "name": "accuracy", "source": "server", "value": 0.5}]},
            )

    assert response.status_code == 422
    assert "reserved" in response.text
    insert_scores.assert_not_called()


@pytest.mark.asyncio
async def test_score_references_in_same_batch_do_not_require_clickhouse_lookup():
    app = _app_with_user(_make_user())

    with (
        patch("api.routes.telemetry.insert_traces", new_callable=AsyncMock),
        patch("api.routes.telemetry.insert_spans", new_callable=AsyncMock),
        patch("api.routes.telemetry.insert_scores", new_callable=AsyncMock) as insert_scores,
        patch("api.routes.telemetry.query_trace_by_id", new_callable=AsyncMock) as query_trace_by_id,
        patch("api.routes.telemetry.query_span_by_id", new_callable=AsyncMock) as query_span_by_id,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/telemetry/ingest",
                json={
                    "traces": [{"trace_id": "trace-1", "start_time": "2026-01-01 00:00:00.000"}],
                    "spans": [
                        {
                            "span_id": "span-1",
                            "trace_id": "trace-1",
                            "type": "tool_call",
                            "name": "tool",
                            "start_time": "2026-01-01 00:00:00.000",
                        }
                    ],
                    "scores": [
                        {
                            "score_id": "score-1",
                            "trace_id": "trace-1",
                            "span_id": "span-1",
                            "name": "accuracy",
                            "value": 1,
                        }
                    ],
                },
            )

    assert response.status_code == 200
    assert response.json() == {"ingested": 3, "errors": 0}
    insert_scores.assert_called_once()
    query_trace_by_id.assert_not_called()
    query_span_by_id.assert_not_called()


@pytest.mark.asyncio
async def test_existing_score_references_are_checked_with_org_project_id():
    org_id = uuid.uuid4()
    app = _app_with_user(_make_user(org_id=org_id))

    with (
        patch("api.routes.telemetry.insert_scores", new_callable=AsyncMock),
        patch("api.routes.telemetry.query_trace_by_id", new_callable=AsyncMock) as query_trace_by_id,
        patch("api.routes.telemetry.query_span_by_id", new_callable=AsyncMock) as query_span_by_id,
    ):
        query_trace_by_id.return_value = {"trace_id": "trace-1"}
        query_span_by_id.return_value = {"span_id": "span-1", "trace_id": "trace-1"}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/telemetry/ingest",
                json={
                    "scores": [
                        {
                            "score_id": "score-1",
                            "trace_id": "trace-1",
                            "span_id": "span-1",
                            "name": "accuracy",
                            "value": 1,
                        }
                    ]
                },
            )

    assert response.status_code == 200
    query_trace_by_id.assert_awaited_once_with(str(org_id), "trace-1")
    query_span_by_id.assert_awaited_once_with(str(org_id), "span-1")


@pytest.mark.asyncio
async def test_missing_referenced_span_is_rejected():
    app = _app_with_user(_make_user())

    with (
        patch("api.routes.telemetry.insert_scores", new_callable=AsyncMock) as insert_scores,
        patch("api.routes.telemetry.query_span_by_id", new_callable=AsyncMock, return_value=None),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/telemetry/ingest",
                json={"scores": [{"score_id": "score-1", "span_id": "span-1", "name": "accuracy", "value": 1}]},
            )

    assert response.status_code == 404
    assert "Referenced span not found" in response.text
    insert_scores.assert_not_called()


@pytest.mark.asyncio
async def test_referenced_span_must_match_referenced_trace():
    app = _app_with_user(_make_user())

    with (
        patch("api.routes.telemetry.insert_scores", new_callable=AsyncMock) as insert_scores,
        patch("api.routes.telemetry.query_trace_by_id", new_callable=AsyncMock, return_value={"trace_id": "trace-1"}),
        patch(
            "api.routes.telemetry.query_span_by_id",
            new_callable=AsyncMock,
            return_value={"span_id": "span-1", "trace_id": "trace-2"},
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/telemetry/ingest",
                json={
                    "scores": [
                        {
                            "score_id": "score-1",
                            "trace_id": "trace-1",
                            "span_id": "span-1",
                            "name": "accuracy",
                            "value": 1,
                        }
                    ]
                },
            )

    assert response.status_code == 422
    assert "does not belong" in response.text
    insert_scores.assert_not_called()


@pytest.mark.asyncio
async def test_missing_referenced_trace_is_rejected():
    """Score referencing a trace not owned by the submitter's org (or not present) must 404."""
    app = _app_with_user(_make_user())

    with (
        patch("api.routes.telemetry.insert_scores", new_callable=AsyncMock) as insert_scores,
        patch("api.routes.telemetry.query_trace_by_id", new_callable=AsyncMock, return_value=None),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/telemetry/ingest",
                json={
                    "scores": [
                        {
                            "score_id": "score-1",
                            "trace_id": "trace-from-other-org",
                            "name": "accuracy",
                            "value": 1,
                        }
                    ]
                },
            )

    assert response.status_code == 404
    assert "Referenced trace not found" in response.text
    insert_scores.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("reserved", ["SERVER", "Internal", "System", "TRUSTED"])
async def test_reserved_score_source_check_is_case_insensitive(reserved):
    """Reserved-name check must lowercase to prevent trivial bypass via casing."""
    app = _app_with_user(_make_user())

    with patch("api.routes.telemetry.insert_scores", new_callable=AsyncMock) as insert_scores:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/telemetry/ingest",
                json={"scores": [{"score_id": "score-1", "name": "accuracy", "source": reserved, "value": 0.5}]},
            )

    assert response.status_code == 422
    assert "reserved" in response.text
    insert_scores.assert_not_called()


@pytest.mark.asyncio
async def test_client_cannot_override_score_trust_metadata():
    """Trust markers injected by the server must overwrite any client-supplied values."""
    app = _app_with_user(_make_user())

    with patch("api.routes.telemetry.insert_scores", new_callable=AsyncMock) as insert_scores:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/telemetry/ingest",
                json={
                    "scores": [
                        {
                            "score_id": "score-1",
                            "name": "accuracy",
                            "source": "manual",
                            "value": 1,
                            "metadata": {
                                "score_trust": "trusted_server",
                                "score_writer": "server",
                                "score_original_source": "trusted",
                                "user_tag": "keepme",
                            },
                        }
                    ]
                },
            )

    assert response.status_code == 200
    rows = insert_scores.call_args.args[0]
    assert rows[0]["metadata"]["score_trust"] == "untrusted_client"
    assert rows[0]["metadata"]["score_writer"] == "telemetry_api"
    # Original-source field tracks what the client *said* it was, not their forged claim
    assert rows[0]["metadata"]["score_original_source"] == "manual"
    # Untouched user metadata is preserved
    assert rows[0]["metadata"]["user_tag"] == "keepme"


@pytest.mark.asyncio
async def test_in_batch_span_with_mismatched_trace_id_is_rejected():
    """Fast-path check: span in same batch but with a different trace_id must 422 without a DB hit."""
    app = _app_with_user(_make_user())

    with (
        patch("api.routes.telemetry.insert_traces", new_callable=AsyncMock),
        patch("api.routes.telemetry.insert_spans", new_callable=AsyncMock),
        patch("api.routes.telemetry.insert_scores", new_callable=AsyncMock) as insert_scores,
        patch("api.routes.telemetry.query_trace_by_id", new_callable=AsyncMock) as query_trace_by_id,
        patch("api.routes.telemetry.query_span_by_id", new_callable=AsyncMock) as query_span_by_id,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/telemetry/ingest",
                json={
                    "traces": [{"trace_id": "trace-1", "start_time": "2026-01-01 00:00:00.000"}],
                    "spans": [
                        {
                            "span_id": "span-1",
                            "trace_id": "trace-1",
                            "type": "tool_call",
                            "name": "tool",
                            "start_time": "2026-01-01 00:00:00.000",
                        }
                    ],
                    "scores": [
                        {
                            "score_id": "score-1",
                            "trace_id": "trace-1",
                            "span_id": "span-1",
                            "name": "accuracy",
                            "value": 1,
                        },
                        {
                            "score_id": "score-2",
                            "trace_id": "trace-1",
                            "span_id": "span-1",
                            "name": "latency",
                            "value": 1,
                        },
                    ],
                },
            )

    # Score-2 keeps the same trace_id, so this batch is fine, switch one to force a mismatch.
    assert response.status_code == 200  # sanity-check the helper batch
    insert_scores.assert_called_once()
    query_trace_by_id.assert_not_called()
    query_span_by_id.assert_not_called()

    insert_scores.reset_mock()
    with (
        patch("api.routes.telemetry.insert_traces", new_callable=AsyncMock),
        patch("api.routes.telemetry.insert_spans", new_callable=AsyncMock),
        patch("api.routes.telemetry.insert_scores", new_callable=AsyncMock) as insert_scores,
        patch("api.routes.telemetry.query_trace_by_id", new_callable=AsyncMock) as query_trace_by_id,
        patch("api.routes.telemetry.query_span_by_id", new_callable=AsyncMock) as query_span_by_id,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/telemetry/ingest",
                json={
                    "traces": [
                        {"trace_id": "trace-1", "start_time": "2026-01-01 00:00:00.000"},
                        {"trace_id": "trace-2", "start_time": "2026-01-01 00:00:00.000"},
                    ],
                    "spans": [
                        {
                            "span_id": "span-1",
                            "trace_id": "trace-1",
                            "type": "tool_call",
                            "name": "tool",
                            "start_time": "2026-01-01 00:00:00.000",
                        }
                    ],
                    "scores": [
                        {
                            "score_id": "score-1",
                            "trace_id": "trace-2",  # mismatch: span-1 is on trace-1
                            "span_id": "span-1",
                            "name": "accuracy",
                            "value": 1,
                        }
                    ],
                },
            )

    assert response.status_code == 422
    assert "does not belong" in response.text
    insert_scores.assert_not_called()
    query_trace_by_id.assert_not_called()
    query_span_by_id.assert_not_called()


@pytest.mark.asyncio
async def test_default_score_source_is_namespaced_to_client_api():
    """source=None and source='' both fall back to 'api' and namespace to 'client:api'."""
    app = _app_with_user(_make_user())

    for payload_source in (None, ""):
        with patch("api.routes.telemetry.insert_scores", new_callable=AsyncMock) as insert_scores:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                score = {"score_id": "score-1", "name": "accuracy", "value": 0.5}
                if payload_source is not None:
                    score["source"] = payload_source
                response = await ac.post(
                    "/api/v1/telemetry/ingest",
                    json={"scores": [score]},
                )

        assert response.status_code == 200, payload_source
        rows = insert_scores.call_args.args[0]
        assert rows[0]["source"] == "client:api"
        assert rows[0]["metadata"]["score_original_source"] == "api"
