"""Unit tests for ClickHouse service: Phase 1 (traces, spans, scores)."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.clickhouse import (
    INIT_SQL,
    init_clickhouse,
    insert_scores,
    insert_spans,
    insert_traces,
    query_scores,
    query_span_by_id,
    query_spans,
    query_trace_by_id,
    query_traces,
)

# --- DDL tests ---


class TestInitSQL:
    def test_has_new_tables(self):
        ddl_text = " ".join(INIT_SQL)
        assert "CREATE TABLE IF NOT EXISTS traces" in ddl_text
        assert "CREATE TABLE IF NOT EXISTS spans" in ddl_text
        assert "CREATE TABLE IF NOT EXISTS scores" in ddl_text

    def test_project_id_on_all_new_tables(self):
        new_tables = INIT_SQL[0:3]
        assert len(new_tables) == 3
        for ddl in new_tables:
            assert "project_id" in ddl

    def test_replacing_merge_tree(self):
        new_tables = INIT_SQL[0:3]
        for ddl in new_tables:
            assert "ReplacingMergeTree" in ddl

    def test_bloom_filter_indexes(self):
        new_tables = INIT_SQL[0:3]
        for ddl in new_tables:
            assert "bloom_filter" in ddl

    def test_monthly_partitioning(self):
        new_tables = INIT_SQL[0:3]
        for ddl in new_tables:
            assert "PARTITION BY toYYYYMM" in ddl

    def test_traces_columns(self):
        traces_ddl = INIT_SQL[0]
        for col in [
            "trace_id",
            "parent_trace_id",
            "trace_type",
            "mcp_id",
            "agent_id",
            "user_id",
            "session_id",
            "ide",
            "environment",
            "start_time",
            "end_time",
            "event_ts",
            "is_deleted",
            "tags",
        ]:
            assert col in traces_ddl

    def test_spans_columns(self):
        spans_ddl = INIT_SQL[1]
        for col in [
            "span_id",
            "trace_id",
            "parent_span_id",
            "type",
            "name",
            "method",
            "input",
            "output",
            "error",
            "latency_ms",
            "status",
            "token_count_input",
            "token_count_output",
            "cost",
            "cpu_ms",
            "memory_mb",
            "hop_count",
            "entities_retrieved",
            "tool_schema_valid",
            "tools_available",
        ]:
            assert col in spans_ddl

    def test_scores_columns(self):
        scores_ddl = INIT_SQL[2]
        for col in [
            "score_id",
            "trace_id",
            "span_id",
            "name",
            "source",
            "data_type",
            "value",
            "string_value",
            "comment",
            "eval_template_id",
            "eval_config_id",
            "eval_run_id",
        ]:
            assert col in scores_ddl


# --- Mock helpers ---


def _mock_response(status_code=200, data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    if data is not None:
        resp.json.return_value = {"data": data}
    return resp


# --- Init tests ---


class TestInitClickhouse:
    @pytest.mark.asyncio
    async def test_calls_all_ddl(self):
        with patch("services.clickhouse._query", new_callable=AsyncMock) as mock_q:
            mock_q.return_value = _mock_response()
            await init_clickhouse()
            # +1 health check
            # +6 conditional materialize checks (3 checks + up to 3 materializations)
            # +5 TTL ALTER statements (traces, spans, scores, otel_logs, session_events)
            # The exact count depends on mock behavior; verify at minimum
            # INIT_SQL + health + TTL are all called.
            assert mock_q.call_count >= len(INIT_SQL) + 1 + 5


# --- Insert tests (JSONEachRow format) ---


class TestInsertTraces:
    @pytest.mark.asyncio
    async def test_empty_list(self):
        with patch("services.clickhouse._query", new_callable=AsyncMock) as mock_q:
            await insert_traces([])
            mock_q.assert_not_called()

    @pytest.mark.asyncio
    async def test_single_trace(self):
        trace = {
            "trace_id": "t1",
            "project_id": "proj1",
            "user_id": "u1",
            "start_time": "2026-01-01 00:00:00.000",
            "trace_type": "mcp",
        }
        with patch("services.clickhouse._query", new_callable=AsyncMock) as mock_q:
            mock_q.return_value = _mock_response()
            await insert_traces([trace])
            mock_q.assert_called_once()
            call_kwargs = mock_q.call_args
            sql = call_kwargs[0][0]
            assert "INSERT INTO traces" in sql
            assert "FORMAT JSONEachRow" in sql
            # Data is passed via the data keyword
            data = call_kwargs[1].get("data", "")
            row = json.loads(data)
            assert row["trace_id"] == "t1"
            assert row["project_id"] == "proj1"

    @pytest.mark.asyncio
    async def test_batch_traces(self):
        traces = [
            {"trace_id": f"t{i}", "project_id": "p1", "user_id": "u1", "start_time": "2026-01-01 00:00:00.000"}
            for i in range(3)
        ]
        with patch("services.clickhouse._query", new_callable=AsyncMock) as mock_q:
            mock_q.return_value = _mock_response()
            await insert_traces(traces)
            data = mock_q.call_args[1].get("data", "")
            lines = data.strip().split("\n")
            assert len(lines) == 3
            assert json.loads(lines[0])["trace_id"] == "t0"
            assert json.loads(lines[1])["trace_id"] == "t1"
            assert json.loads(lines[2])["trace_id"] == "t2"

    @pytest.mark.asyncio
    async def test_raises_on_error(self):
        with patch("services.clickhouse._query", new_callable=AsyncMock) as mock_q:
            mock_q.side_effect = Exception("connection refused")
            with pytest.raises(Exception, match="connection refused"):
                await insert_traces(
                    [
                        {
                            "trace_id": "t1",
                            "project_id": "p1",
                            "user_id": "u1",
                            "start_time": "2026-01-01 00:00:00.000",
                        }
                    ]
                )


class TestInsertSpans:
    @pytest.mark.asyncio
    async def test_empty_list(self):
        with patch("services.clickhouse._query", new_callable=AsyncMock) as mock_q:
            await insert_spans([])
            mock_q.assert_not_called()

    @pytest.mark.asyncio
    async def test_single_span(self):
        span = {
            "span_id": "s1",
            "trace_id": "t1",
            "project_id": "p1",
            "user_id": "u1",
            "type": "tool_call",
            "name": "my_tool",
            "start_time": "2026-01-01 00:00:00.000",
        }
        with patch("services.clickhouse._query", new_callable=AsyncMock) as mock_q:
            mock_q.return_value = _mock_response()
            await insert_spans([span])
            sql = mock_q.call_args[0][0]
            assert "INSERT INTO spans" in sql
            assert "FORMAT JSONEachRow" in sql
            data = mock_q.call_args[1].get("data", "")
            row = json.loads(data)
            assert row["span_id"] == "s1"
            assert row["type"] == "tool_call"

    @pytest.mark.asyncio
    async def test_domain_specific_fields(self):
        span = {
            "span_id": "s1",
            "trace_id": "t1",
            "project_id": "p1",
            "user_id": "u1",
            "type": "graph_traverse",
            "name": "query",
            "start_time": "2026-01-01 00:00:00.000",
            "hop_count": 3,
            "entities_retrieved": 12,
            "relationships_used": 8,
            "tool_schema_valid": 1,
        }
        with patch("services.clickhouse._query", new_callable=AsyncMock) as mock_q:
            mock_q.return_value = _mock_response()
            await insert_spans([span])
            data = mock_q.call_args[1].get("data", "")
            row = json.loads(data)
            assert row["type"] == "graph_traverse"
            assert row["hop_count"] == 3
            assert row["entities_retrieved"] == 12
            assert row["tool_schema_valid"] == 1


class TestInsertScores:
    @pytest.mark.asyncio
    async def test_empty_list(self):
        with patch("services.clickhouse._query", new_callable=AsyncMock) as mock_q:
            await insert_scores([])
            mock_q.assert_not_called()

    @pytest.mark.asyncio
    async def test_single_score(self):
        score = {
            "score_id": "sc1",
            "project_id": "p1",
            "user_id": "u1",
            "name": "accuracy",
            "source": "eval",
            "data_type": "numeric",
            "value": 0.95,
            "timestamp": "2026-01-01 00:00:00.000",
        }
        with patch("services.clickhouse._query", new_callable=AsyncMock) as mock_q:
            mock_q.return_value = _mock_response()
            await insert_scores([score])
            sql = mock_q.call_args[0][0]
            assert "INSERT INTO scores" in sql
            assert "FORMAT JSONEachRow" in sql
            data = mock_q.call_args[1].get("data", "")
            row = json.loads(data)
            assert row["score_id"] == "sc1"
            assert row["source"] == "eval"
            assert row["value"] == 0.95


# --- Query tests (parameterized) ---


class TestQueryTraces:
    @pytest.mark.asyncio
    async def test_basic_query(self):
        with patch("services.clickhouse._query", new_callable=AsyncMock) as mock_q:
            mock_q.return_value = _mock_response(data=[{"trace_id": "t1"}])
            result = await query_traces("proj1")
            assert len(result) == 1
            sql = mock_q.call_args[0][0]
            assert "project_id = {pid:String}" in sql
            assert "is_deleted = 0" in sql
            assert "FINAL" in sql
            # Check params
            params = mock_q.call_args[0][1]
            assert params["param_pid"] == "proj1"

    @pytest.mark.asyncio
    async def test_with_filters(self):
        with patch("services.clickhouse._query", new_callable=AsyncMock) as mock_q:
            mock_q.return_value = _mock_response(data=[])
            await query_traces("p1", trace_type="mcp", mcp_id="m1", user_id="u1")
            sql = mock_q.call_args[0][0]
            assert "trace_type = {tt:String}" in sql
            assert "mcp_id = {mid:String}" in sql
            assert "user_id = {uid:String}" in sql
            params = mock_q.call_args[0][1]
            assert params["param_tt"] == "mcp"
            assert params["param_mid"] == "m1"
            assert params["param_uid"] == "u1"

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self):
        with patch("services.clickhouse._query", new_callable=AsyncMock) as mock_q:
            mock_q.side_effect = Exception("timeout")
            result = await query_traces("p1")
            assert result == []


class TestQueryTraceById:
    @pytest.mark.asyncio
    async def test_found(self):
        with patch("services.clickhouse._query", new_callable=AsyncMock) as mock_q:
            mock_q.return_value = _mock_response(data=[{"trace_id": "t1"}])
            result = await query_trace_by_id("p1", "t1")
            assert result == {"trace_id": "t1"}
            params = mock_q.call_args[0][1]
            assert params["param_tid"] == "t1"

    @pytest.mark.asyncio
    async def test_not_found(self):
        with patch("services.clickhouse._query", new_callable=AsyncMock) as mock_q:
            mock_q.return_value = _mock_response(data=[])
            result = await query_trace_by_id("p1", "t999")
            assert result is None


class TestQuerySpans:
    @pytest.mark.asyncio
    async def test_basic_query(self):
        with patch("services.clickhouse._query", new_callable=AsyncMock) as mock_q:
            mock_q.return_value = _mock_response(data=[{"span_id": "s1"}])
            result = await query_spans("p1", "t1")
            assert len(result) == 1
            sql = mock_q.call_args[0][0]
            assert "trace_id = {tid:String}" in sql
            params = mock_q.call_args[0][1]
            assert params["param_tid"] == "t1"

    @pytest.mark.asyncio
    async def test_with_type_filter(self):
        with patch("services.clickhouse._query", new_callable=AsyncMock) as mock_q:
            mock_q.return_value = _mock_response(data=[])
            await query_spans("p1", "t1", span_type="tool_call", status="error")
            sql = mock_q.call_args[0][0]
            assert "type = {st:String}" in sql
            assert "status = {status:String}" in sql


class TestQuerySpanById:
    @pytest.mark.asyncio
    async def test_found(self):
        with patch("services.clickhouse._query", new_callable=AsyncMock) as mock_q:
            mock_q.return_value = _mock_response(data=[{"span_id": "s1"}])
            result = await query_span_by_id("p1", "s1")
            assert result == {"span_id": "s1"}


class TestQueryScores:
    @pytest.mark.asyncio
    async def test_basic_query(self):
        with patch("services.clickhouse._query", new_callable=AsyncMock) as mock_q:
            mock_q.return_value = _mock_response(data=[{"score_id": "sc1"}])
            result = await query_scores("p1")
            assert len(result) == 1

    @pytest.mark.asyncio
    async def test_with_filters(self):
        with patch("services.clickhouse._query", new_callable=AsyncMock) as mock_q:
            mock_q.return_value = _mock_response(data=[])
            await query_scores("p1", trace_id="t1", source="eval", name="accuracy")
            sql = mock_q.call_args[0][0]
            assert "trace_id = {tid:String}" in sql
            assert "source = {src:String}" in sql
            assert "name = {name:String}" in sql
