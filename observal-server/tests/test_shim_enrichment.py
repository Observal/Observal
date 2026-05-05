"""Tests for services/insights/shim_enrichment.py.

TDD: these tests define the expected behavior before implementation.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from services.insights.shim_enrichment import (
    compute_mcp_metrics,
    enrich_session_with_shim,
    get_shim_spans_for_sessions,
)

# ---------------------------------------------------------------------------
# enrich_session_with_shim — pure logic, no I/O
# ---------------------------------------------------------------------------


class TestEnrichSessionWithShim:
    @pytest.mark.asyncio
    async def test_returns_events_unchanged_when_no_shim_spans(self):
        events = [{"tool_name": "Read", "timestamp": "2026-01-01 00:00:01.000", "latency_ms": 50}]
        result = await enrich_session_with_shim("sess-1", events, [])
        assert result == events

    @pytest.mark.asyncio
    async def test_enriches_matching_event_with_shim_latency(self):
        events = [{"tool_name": "Read", "timestamp": "2026-01-01 00:00:01.000", "latency_ms": 50}]
        spans = [
            {
                "tool_name": "Read",
                "start_time": "2026-01-01 00:00:01.100",
                "latency_ms": 42,
                "tool_schema_valid": 1,
                "input": "full input text",
                "output": "full output text",
                "mcp_id": "mcp-abc",
            }
        ]
        result = await enrich_session_with_shim("sess-1", events, spans)
        assert len(result) == 1
        assert result[0]["mcp_latency_ms"] == 42
        assert result[0]["tool_schema_valid"] == 1
        assert result[0]["full_tool_input"] == "full input text"
        assert result[0]["full_tool_response"] == "full output text"

    @pytest.mark.asyncio
    async def test_does_not_match_events_outside_2_second_window(self):
        events = [{"tool_name": "Read", "timestamp": "2026-01-01 00:00:01.000", "latency_ms": 50}]
        spans = [
            {
                "tool_name": "Read",
                "start_time": "2026-01-01 00:00:05.000",  # 4 seconds away
                "latency_ms": 42,
                "tool_schema_valid": 1,
                "input": "input",
                "output": "output",
                "mcp_id": "mcp-abc",
            }
        ]
        result = await enrich_session_with_shim("sess-1", events, spans)
        assert "mcp_latency_ms" not in result[0]

    @pytest.mark.asyncio
    async def test_does_not_match_different_tool_name(self):
        events = [{"tool_name": "Read", "timestamp": "2026-01-01 00:00:01.000", "latency_ms": 50}]
        spans = [
            {
                "tool_name": "Write",
                "start_time": "2026-01-01 00:00:01.100",
                "latency_ms": 42,
                "tool_schema_valid": 1,
                "input": "input",
                "output": "output",
                "mcp_id": "mcp-abc",
            }
        ]
        result = await enrich_session_with_shim("sess-1", events, spans)
        assert "mcp_latency_ms" not in result[0]

    @pytest.mark.asyncio
    async def test_each_span_matches_at_most_one_event(self):
        """A shim span should not be applied to two events."""
        events = [
            {"tool_name": "Read", "timestamp": "2026-01-01 00:00:01.000", "latency_ms": 50},
            {"tool_name": "Read", "timestamp": "2026-01-01 00:00:01.200", "latency_ms": 50},
        ]
        spans = [
            {
                "tool_name": "Read",
                "start_time": "2026-01-01 00:00:01.100",
                "latency_ms": 99,
                "tool_schema_valid": 1,
                "input": "x",
                "output": "y",
                "mcp_id": "mcp-1",
            }
        ]
        result = await enrich_session_with_shim("sess-1", events, spans)
        enriched = [e for e in result if "mcp_latency_ms" in e]
        assert len(enriched) == 1

    @pytest.mark.asyncio
    async def test_handles_missing_timestamp_fields_gracefully(self):
        events = [{"tool_name": "Read"}]  # no timestamp
        spans = [
            {
                "tool_name": "Read",
                "start_time": "2026-01-01 00:00:01.000",
                "latency_ms": 10,
                "tool_schema_valid": 1,
                "input": "",
                "output": "",
                "mcp_id": "",
            }
        ]
        # Should not raise
        result = await enrich_session_with_shim("sess-1", events, spans)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# get_shim_spans_for_sessions — ClickHouse I/O
# ---------------------------------------------------------------------------


class TestGetShimSpansForSessions:
    @pytest.mark.asyncio
    async def test_returns_empty_dict_when_no_sessions(self):
        result = await get_shim_spans_for_sessions("my-agent", [], "2026-01-01", "2026-01-31")
        assert result == {}

    @pytest.mark.asyncio
    async def test_groups_spans_by_session_id(self):
        mock_rows = [
            {
                "tool_name": "Read",
                "input": "inp",
                "output": "out",
                "latency_ms": 10,
                "tool_schema_valid": 1,
                "start_time": "2026-01-01 00:00:01.000",
                "mcp_id": "mcp-1",
                "session_id": "sess-a",
            },
            {
                "tool_name": "Write",
                "input": "inp2",
                "output": "out2",
                "latency_ms": 20,
                "tool_schema_valid": 1,
                "start_time": "2026-01-01 00:00:02.000",
                "mcp_id": "mcp-2",
                "session_id": "sess-b",
            },
        ]

        mock_response = AsyncMock()
        mock_response.raise_for_status = lambda: None
        mock_response.json = lambda: {"data": mock_rows}

        with patch("services.insights.shim_enrichment._query", new=AsyncMock(return_value=mock_response)):
            result = await get_shim_spans_for_sessions("my-agent", ["sess-a", "sess-b"], "2026-01-01", "2026-01-31")

        assert set(result.keys()) == {"sess-a", "sess-b"}
        assert len(result["sess-a"]) == 1
        assert result["sess-a"][0]["tool_name"] == "Read"
        assert len(result["sess-b"]) == 1

    @pytest.mark.asyncio
    async def test_returns_empty_dict_on_query_failure(self):
        with patch("services.insights.shim_enrichment._query", new=AsyncMock(side_effect=Exception("db error"))):
            result = await get_shim_spans_for_sessions("my-agent", ["sess-x"], "2026-01-01", "2026-01-31")
        assert result == {}


# ---------------------------------------------------------------------------
# compute_mcp_metrics — ClickHouse I/O
# ---------------------------------------------------------------------------


class TestComputeMcpMetrics:
    @pytest.mark.asyncio
    async def test_returns_zero_metrics_when_no_spans(self):
        mock_response = AsyncMock()
        mock_response.raise_for_status = lambda: None
        mock_response.json = lambda: {"data": []}

        with patch("services.insights.shim_enrichment._query", new=AsyncMock(return_value=mock_response)):
            result = await compute_mcp_metrics("my-agent", "2026-01-01", "2026-01-31")

        assert result["total_mcp_calls"] == 0
        assert result["schema_violations"] == 0
        assert result["schema_violation_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_computes_schema_violation_rate(self):
        def make_mock(data):
            m = AsyncMock()
            m.raise_for_status = lambda: None
            m.json = lambda: {"data": data}
            return m

        mock_agg = make_mock(
            [
                {
                    "total_mcp_calls": "10",
                    "latency_p50_ms": "50",
                    "latency_p95_ms": "200",
                    "latency_p99_ms": "500",
                    "schema_violations": "2",
                    "tools_available_count": "15",
                }
            ]
        )
        mock_slowest = make_mock([])
        mock_errors = make_mock([])

        responses = [mock_agg, mock_slowest, mock_errors]
        call_idx = [0]

        async def fake_query(sql, params=None):
            r = responses[call_idx[0]]
            call_idx[0] += 1
            return r

        with patch("services.insights.shim_enrichment._query", side_effect=fake_query):
            result = await compute_mcp_metrics("my-agent", "2026-01-01", "2026-01-31")

        assert result["total_mcp_calls"] == 10
        assert result["schema_violations"] == 2
        assert abs(result["schema_violation_rate"] - 0.2) < 0.001
        assert result["latency_p50_ms"] == 50
        assert result["latency_p95_ms"] == 200
        assert result["latency_p99_ms"] == 500
        assert result["tools_available_count"] == 15

    @pytest.mark.asyncio
    async def test_returns_safe_defaults_on_query_error(self):
        with patch("services.insights.shim_enrichment._query", new=AsyncMock(side_effect=Exception("fail"))):
            result = await compute_mcp_metrics("my-agent", "2026-01-01", "2026-01-31")

        assert result["total_mcp_calls"] == 0
        assert result["schema_violation_rate"] == 0.0
        assert result["slowest_tools"] == []
        assert result["error_tools"] == []
