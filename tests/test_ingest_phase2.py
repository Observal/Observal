"""Unit tests for POST /api/v1/telemetry/ingest: Phase 2."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# We need to test the route handler logic. Build a minimal FastAPI app
# that mounts just the telemetry router with auth mocked out.
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.routes.telemetry import router
from models.user import User


def _make_user(**kwargs):
    u = MagicMock(spec=User)
    u.id = kwargs.get("id", uuid.uuid4())
    u.role = kwargs.get("role", "admin")
    return u


def _app_with_user(user):
    """Create a test FastAPI app with auth overridden to return the given user."""
    from api.deps import get_current_user

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: user
    return app


@pytest.fixture
def user():
    return _make_user()


@pytest.fixture
def app(user):
    return _app_with_user(user)


# --- Schema validation tests ---


class TestIngestSchemas:
    def test_trace_ingest_minimal(self):
        from schemas.telemetry import TraceIngest

        t = TraceIngest(trace_id="t1", start_time="2026-01-01 00:00:00.000")
        assert t.trace_type == "mcp"
        assert t.tags == []
        assert t.metadata == {}

    def test_span_ingest_minimal(self):
        from schemas.telemetry import SpanIngest

        s = SpanIngest(
            span_id="s1",
            trace_id="t1",
            type="tool_call",
            name="my_tool",
            start_time="2026-01-01 00:00:00.000",
        )
        assert s.status == "success"
        assert s.tool_schema_valid is None

    def test_score_ingest_minimal(self):
        from schemas.telemetry import ScoreIngest

        sc = ScoreIngest(score_id="sc1", name="accuracy", value=0.9)
        assert sc.source == "api"
        assert sc.data_type == "numeric"

    def test_ingest_batch_empty(self):
        from schemas.telemetry import IngestBatch

        b = IngestBatch()
        assert b.traces == []
        assert b.spans == []
        assert b.scores == []

    def test_ingest_batch_full(self):
        from schemas.telemetry import IngestBatch, ScoreIngest, SpanIngest, TraceIngest

        b = IngestBatch(
            traces=[TraceIngest(trace_id="t1", start_time="2026-01-01 00:00:00.000")],
            spans=[
                SpanIngest(
                    span_id="s1", trace_id="t1", type="tool_call", name="x", start_time="2026-01-01 00:00:00.000"
                )
            ],
            scores=[ScoreIngest(score_id="sc1", name="acc", value=1.0)],
        )
        assert len(b.traces) == 1
        assert len(b.spans) == 1
        assert len(b.scores) == 1


# --- Route tests ---


class TestIngestEndpoint:
    @pytest.mark.asyncio
    async def test_empty_batch(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/v1/telemetry/ingest", json={})
        assert r.status_code == 200
        assert r.json() == {"ingested": 0, "errors": 0}

    @pytest.mark.asyncio
    async def test_ingest_traces(self, app):
        with patch("api.routes.telemetry.insert_traces", new_callable=AsyncMock) as mock_ins:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                r = await ac.post(
                    "/api/v1/telemetry/ingest",
                    json={
                        "traces": [
                            {"trace_id": "t1", "start_time": "2026-01-01 00:00:00.000"},
                            {"trace_id": "t2", "start_time": "2026-01-01 00:00:01.000"},
                        ]
                    },
                )
            assert r.status_code == 200
            assert r.json()["ingested"] == 2
            assert r.json()["errors"] == 0
            mock_ins.assert_called_once()
            rows = mock_ins.call_args[0][0]
            assert len(rows) == 2
            assert rows[0]["trace_id"] == "t1"
            # user_id injected server-side
            assert rows[0]["user_id"] != ""
            assert rows[0]["project_id"] == "default"

    @pytest.mark.asyncio
    async def test_ingest_spans(self, app):
        with patch("api.routes.telemetry.insert_spans", new_callable=AsyncMock) as mock_ins:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                r = await ac.post(
                    "/api/v1/telemetry/ingest",
                    json={
                        "spans": [
                            {
                                "span_id": "s1",
                                "trace_id": "t1",
                                "type": "tool_call",
                                "name": "my_tool",
                                "start_time": "2026-01-01 00:00:00.000",
                            }
                        ]
                    },
                )
            assert r.status_code == 200
            assert r.json()["ingested"] == 1
            rows = mock_ins.call_args[0][0]
            assert rows[0]["type"] == "tool_call"

    @pytest.mark.asyncio
    async def test_ingest_scores(self, app):
        with patch("api.routes.telemetry.insert_scores", new_callable=AsyncMock) as mock_ins:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                r = await ac.post(
                    "/api/v1/telemetry/ingest",
                    json={
                        "scores": [
                            {
                                "score_id": "sc1",
                                "name": "accuracy",
                                "value": 0.95,
                                "source": "eval",
                            }
                        ]
                    },
                )
            assert r.status_code == 200
            assert r.json()["ingested"] == 1
            rows = mock_ins.call_args[0][0]
            assert rows[0]["source"] == "eval"
            assert rows[0]["value"] == 0.95
            # timestamp injected server-side
            assert rows[0]["timestamp"] != ""

    @pytest.mark.asyncio
    async def test_ingest_mixed_batch(self, app):
        with (
            patch("api.routes.telemetry.insert_traces", new_callable=AsyncMock),
            patch("api.routes.telemetry.insert_spans", new_callable=AsyncMock),
            patch("api.routes.telemetry.insert_scores", new_callable=AsyncMock),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                r = await ac.post(
                    "/api/v1/telemetry/ingest",
                    json={
                        "traces": [{"trace_id": "t1", "start_time": "2026-01-01 00:00:00.000"}],
                        "spans": [
                            {
                                "span_id": "s1",
                                "trace_id": "t1",
                                "type": "tool_call",
                                "name": "x",
                                "start_time": "2026-01-01 00:00:00.000",
                            }
                        ],
                        "scores": [{"score_id": "sc1", "name": "acc", "value": 1.0}],
                    },
                )
            assert r.json() == {"ingested": 3, "errors": 0}

    @pytest.mark.asyncio
    async def test_trace_failure_doesnt_block_spans(self, app):
        with (
            patch("api.routes.telemetry.insert_traces", new_callable=AsyncMock, side_effect=Exception("ch down")),
            patch("api.routes.telemetry.insert_spans", new_callable=AsyncMock) as mock_spans,
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                r = await ac.post(
                    "/api/v1/telemetry/ingest",
                    json={
                        "traces": [{"trace_id": "t1", "start_time": "2026-01-01 00:00:00.000"}],
                        "spans": [
                            {
                                "span_id": "s1",
                                "trace_id": "t1",
                                "type": "tool_call",
                                "name": "x",
                                "start_time": "2026-01-01 00:00:00.000",
                            }
                        ],
                    },
                )
            data = r.json()
            assert data["errors"] == 1  # trace failed
            assert data["ingested"] == 1  # span succeeded
            mock_spans.assert_called_once()

    @pytest.mark.asyncio
    async def test_environment_header(self, app):
        with patch("api.routes.telemetry.insert_traces", new_callable=AsyncMock) as mock_ins:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                r = await ac.post(
                    "/api/v1/telemetry/ingest",
                    json={"traces": [{"trace_id": "t1", "start_time": "2026-01-01 00:00:00.000"}]},
                    headers={"X-Observal-Environment": "staging"},
                )
            rows = mock_ins.call_args[0][0]
            assert rows[0]["environment"] == "staging"

    @pytest.mark.asyncio
    async def test_tool_schema_valid_bool_to_int(self, app):
        with patch("api.routes.telemetry.insert_spans", new_callable=AsyncMock) as mock_ins:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                r = await ac.post(
                    "/api/v1/telemetry/ingest",
                    json={
                        "spans": [
                            {
                                "span_id": "s1",
                                "trace_id": "t1",
                                "type": "tool_call",
                                "name": "x",
                                "start_time": "2026-01-01 00:00:00.000",
                                "tool_schema_valid": True,
                            }
                        ]
                    },
                )
            rows = mock_ins.call_args[0][0]
            assert rows[0]["tool_schema_valid"] == 1  # bool → int for ClickHouse UInt8

    @pytest.mark.asyncio
    async def test_validation_error_returns_422(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(
                "/api/v1/telemetry/ingest",
                json={
                    "spans": [{"span_id": "s1"}]  # missing required fields
                },
            )
        assert r.status_code == 422


class TestLegacyEventsEndpoint:
    """Verify the old /events endpoint still works."""

    @pytest.mark.asyncio
    async def test_still_exists(self, app):
        with (
            patch("api.routes.telemetry.insert_tool_call", new_callable=AsyncMock),
            patch("api.routes.telemetry.insert_agent_interaction", new_callable=AsyncMock),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                r = await ac.post("/api/v1/telemetry/events", json={})
            assert r.status_code == 200
            assert r.json() == {"ingested": 0, "errors": 0}
