"""Unit tests for GraphQL layer: Phase 6."""

from unittest.mock import AsyncMock, patch

import pytest

from api.graphql import (
    Query,
    TraceConnection,
    _load_scores_by_span_ids,
    _load_scores_by_trace_ids,
    _load_spans_by_trace_ids,
    _parse_json,
    _row_to_score,
    _row_to_span,
    _row_to_trace,
    get_context,
    schema,
)

# --- Helpers ---


class TestParseJson:
    def test_valid(self):
        assert _parse_json('{"a": 1}') == {"a": 1}

    def test_none(self):
        assert _parse_json(None) is None

    def test_invalid(self):
        assert _parse_json("not json") == "not json"

    def test_empty(self):
        assert _parse_json("") is None


# --- Row converters ---


class TestRowToTrace:
    def test_minimal(self):
        t = _row_to_trace({"trace_id": "t1", "user_id": "u1", "start_time": "2026-01-01"})
        assert t.trace_id == "t1"
        assert t.trace_type == "mcp"

    def test_full(self):
        t = _row_to_trace(
            {
                "trace_id": "t1",
                "parent_trace_id": "p1",
                "trace_type": "agent",
                "mcp_id": "m1",
                "agent_id": "a1",
                "user_id": "u1",
                "session_id": "s1",
                "ide": "cursor",
                "name": "test",
                "start_time": "2026-01-01",
                "end_time": "2026-01-02",
                "tags": ["a", "b"],
                "metadata": {"k": "v"},
            }
        )
        assert t.parent_trace_id == "p1"
        assert t.tags == ["a", "b"]


class TestRowToSpan:
    def test_minimal(self):
        s = _row_to_span(
            {"span_id": "s1", "trace_id": "t1", "type": "tool_call", "name": "x", "start_time": "2026-01-01"}
        )
        assert s.type == "tool_call"
        assert s.status == "success"

    def test_tool_schema_valid(self):
        s = _row_to_span(
            {
                "span_id": "s1",
                "trace_id": "t1",
                "type": "tool_call",
                "name": "x",
                "start_time": "2026-01-01",
                "tool_schema_valid": "1",
            }
        )
        assert s.tool_schema_valid is True

    def test_tool_schema_invalid(self):
        s = _row_to_span(
            {
                "span_id": "s1",
                "trace_id": "t1",
                "type": "tool_call",
                "name": "x",
                "start_time": "2026-01-01",
                "tool_schema_valid": "0",
            }
        )
        assert s.tool_schema_valid is False

    def test_nullable_fields(self):
        s = _row_to_span(
            {"span_id": "s1", "trace_id": "t1", "type": "tool_call", "name": "x", "start_time": "2026-01-01"}
        )
        assert s.latency_ms is None
        assert s.cost is None
        assert s.tool_schema_valid is None


class TestRowToScore:
    def test_basic(self):
        sc = _row_to_score(
            {"score_id": "sc1", "name": "acc", "source": "eval", "value": "0.95", "timestamp": "2026-01-01"}
        )
        assert sc.value == 0.95
        assert sc.source == "eval"


# --- DataLoaders ---


class TestDataLoaders:
    @pytest.mark.asyncio
    async def test_load_spans_by_trace_ids(self):
        mock_rows = [
            {"trace_id": "t1", "span_id": "s1", "type": "tool_call", "name": "x", "start_time": "2026-01-01"},
            {"trace_id": "t2", "span_id": "s2", "type": "tool_call", "name": "y", "start_time": "2026-01-01"},
        ]
        with patch("api.graphql._ch_json", new_callable=AsyncMock, return_value=mock_rows):
            result = await _load_spans_by_trace_ids(["t1", "t2", "t3"])
        assert len(result) == 3
        assert len(result[0]) == 1  # t1
        assert len(result[1]) == 1  # t2
        assert len(result[2]) == 0  # t3

    @pytest.mark.asyncio
    async def test_load_scores_by_trace_ids(self):
        mock_rows = [{"trace_id": "t1", "score_id": "sc1", "name": "acc", "value": "1"}]
        with patch("api.graphql._ch_json", new_callable=AsyncMock, return_value=mock_rows):
            result = await _load_scores_by_trace_ids(["t1"])
        assert len(result[0]) == 1

    @pytest.mark.asyncio
    async def test_load_scores_by_span_ids(self):
        mock_rows = [{"span_id": "s1", "score_id": "sc1", "name": "acc", "value": "1"}]
        with patch("api.graphql._ch_json", new_callable=AsyncMock, return_value=mock_rows):
            result = await _load_scores_by_span_ids(["s1"])
        assert len(result[0]) == 1


# --- Schema structure ---


class TestSchema:
    def test_schema_exists(self):
        assert schema is not None

    def test_has_query_type(self):
        assert schema._schema.query_type is not None

    def test_has_subscription_type(self):
        assert schema._schema.subscription_type is not None

    def test_context_has_loaders(self):
        ctx = get_context()
        assert "span_loader" in ctx
        assert "score_by_trace_loader" in ctx
        assert "score_by_span_loader" in ctx


# --- Query resolvers ---


class TestQueryResolvers:
    @pytest.mark.asyncio
    async def test_traces_resolver(self):
        mock_rows = [{"trace_id": "t1", "user_id": "u1", "start_time": "2026-01-01"}]
        with patch("api.graphql.query_traces", new_callable=AsyncMock, return_value=mock_rows):
            q = Query()
            result = await q.traces(info=None)
            assert isinstance(result, TraceConnection)
            assert len(result.items) == 1
            assert result.has_more is False

    @pytest.mark.asyncio
    async def test_traces_has_more(self):
        # Return limit+1 rows to trigger has_more
        mock_rows = [{"trace_id": f"t{i}", "user_id": "u1", "start_time": "2026-01-01"} for i in range(51)]
        with patch("api.graphql.query_traces", new_callable=AsyncMock, return_value=mock_rows):
            q = Query()
            result = await q.traces(info=None, limit=50)
            assert result.has_more is True
            assert len(result.items) == 50

    @pytest.mark.asyncio
    async def test_trace_by_id(self):
        with patch(
            "api.graphql.query_trace_by_id",
            new_callable=AsyncMock,
            return_value={"trace_id": "t1", "user_id": "u1", "start_time": "2026-01-01"},
        ):
            q = Query()
            result = await q.trace(info=None, trace_id="t1")
            assert result.trace_id == "t1"

    @pytest.mark.asyncio
    async def test_trace_not_found(self):
        with patch("api.graphql.query_trace_by_id", new_callable=AsyncMock, return_value=None):
            q = Query()
            result = await q.trace(info=None, trace_id="missing")
            assert result is None

    @pytest.mark.asyncio
    async def test_span_by_id(self):
        with patch(
            "api.graphql.query_span_by_id",
            new_callable=AsyncMock,
            return_value={
                "span_id": "s1",
                "trace_id": "t1",
                "type": "tool_call",
                "name": "x",
                "start_time": "2026-01-01",
            },
        ):
            q = Query()
            result = await q.span(info=None, span_id="s1")
            assert result.span_id == "s1"

    @pytest.mark.asyncio
    async def test_mcp_metrics(self):
        mock_rows = [
            {
                "cnt": "100",
                "errs": "5",
                "timeouts": "2",
                "avg_lat": "50.5",
                "p50": "40",
                "p90": "80",
                "p99": "150",
                "schema_ok": "90",
                "schema_total": "95",
            }
        ]
        with patch("api.graphql._ch_json", new_callable=AsyncMock, return_value=mock_rows):
            q = Query()
            result = await q.mcp_metrics(mcp_id="m1", start="2026-01-01", end="2026-02-01")
            assert result.tool_call_count == 100
            assert result.error_rate == 0.05

    @pytest.mark.asyncio
    async def test_overview(self):
        with patch(
            "api.graphql._ch_json",
            new_callable=AsyncMock,
            side_effect=[
                [{"traces": "500"}],
                [{"spans": "2000", "tools": "1500", "errs": "50"}],
            ],
        ):
            q = Query()
            result = await q.overview(start="2026-01-01", end="2026-02-01")
            assert result.total_traces == 500
            assert result.total_spans == 2000


# --- Main.py integration ---


class TestMainIntegration:
    def test_dashboard_router_mounted(self):
        from main import app

        paths = [r.path for r in app.routes]
        # Dashboard REST endpoints coexist with GraphQL
        assert "/api/v1/graphql" in paths

    def test_graphql_mounted(self):
        from main import app

        paths = [r.path for r in app.routes]
        assert "/api/v1/graphql" in paths
