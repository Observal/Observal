"""Unit tests for observal-shim: Phase 3."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from observal_cli.shim import (
    ShimState,
    check_schema_compliance,
    classify_message,
    extract_span_name,
    extract_span_type,
)

# --- Message classification ---


class TestClassifyMessage:
    def test_request(self):
        assert classify_message({"method": "tools/call", "id": 1}) == "request"

    def test_response_result(self):
        assert classify_message({"id": 1, "result": {}}) == "response"

    def test_response_error(self):
        assert classify_message({"id": 1, "error": {"code": -1}}) == "response"

    def test_notification(self):
        assert classify_message({"method": "notifications/log"}) == "notification"

    def test_notification_no_id(self):
        assert classify_message({"method": "progress"}) == "notification"


# --- Span type mapping ---


class TestExtractSpanType:
    def test_tool_call(self):
        assert extract_span_type("tools/call") == "tool_call"

    def test_tool_list(self):
        assert extract_span_type("tools/list") == "tool_list"

    def test_resource_read(self):
        assert extract_span_type("resources/read") == "resource_read"

    def test_prompt_get(self):
        assert extract_span_type("prompts/get") == "prompt_get"

    def test_initialize(self):
        assert extract_span_type("initialize") == "initialize"

    def test_ping(self):
        assert extract_span_type("ping") == "ping"

    def test_unknown(self):
        assert extract_span_type("custom/method") == "other"


class TestExtractSpanName:
    def test_tool_call_name(self):
        assert extract_span_name("tools/call", {"name": "read_file"}) == "read_file"

    def test_resource_read_uri(self):
        assert extract_span_name("resources/read", {"uri": "file:///tmp/x"}) == "file:///tmp/x"

    def test_no_params(self):
        assert extract_span_name("tools/list", None) == "tools/list"

    def test_unknown_method(self):
        assert extract_span_name("custom/foo", {}) == "custom/foo"

    def test_missing_field(self):
        assert extract_span_name("tools/call", {"other": "val"}) == "tools/call"


# --- Schema compliance ---


class TestSchemaCompliance:
    def test_no_schemas(self):
        assert check_schema_compliance({"name": "x"}, {}) == (None, None)

    def test_tool_not_in_schema(self):
        schemas = {"read_file": {"properties": {"path": {}}}}
        valid, avail = check_schema_compliance({"name": "hallucinated_tool"}, schemas)
        assert valid == 0
        assert avail == 1

    def test_valid_call(self):
        schemas = {"read_file": {"properties": {"path": {}}, "required": ["path"]}}
        valid, avail = check_schema_compliance({"name": "read_file", "arguments": {"path": "/tmp"}}, schemas)
        assert valid == 1
        assert avail == 1

    def test_missing_required(self):
        schemas = {"read_file": {"properties": {"path": {}}, "required": ["path"]}}
        valid, avail = check_schema_compliance({"name": "read_file", "arguments": {}}, schemas)
        assert valid == 0

    def test_extra_property(self):
        schemas = {"read_file": {"properties": {"path": {}}}}
        valid, avail = check_schema_compliance(
            {"name": "read_file", "arguments": {"path": "/tmp", "extra": "bad"}}, schemas
        )
        assert valid == 0

    def test_empty_schema(self):
        schemas = {"simple_tool": {}}
        valid, avail = check_schema_compliance({"name": "simple_tool", "arguments": {"anything": "goes"}}, schemas)
        assert valid == 1

    def test_no_params(self):
        schemas = {"x": {}}
        valid, avail = check_schema_compliance(None, schemas)
        assert valid is None
        assert avail == 1

    def test_multiple_tools_available(self):
        schemas = {"a": {}, "b": {}, "c": {}}
        _, avail = check_schema_compliance({"name": "a"}, schemas)
        assert avail == 3


# --- ShimState request/response pairing ---


class TestShimState:
    def _make_state(self):
        return ShimState("mcp-1", "http://localhost:8000", "test-key")

    def test_on_request_tracks_pending(self):
        state = self._make_state()
        state.on_request({"method": "tools/call", "id": 1, "params": {"name": "x"}})
        assert 1 in state.pending

    def test_on_response_creates_span(self):
        state = self._make_state()
        state.on_request({"method": "tools/call", "id": 1, "params": {"name": "read_file"}})
        span = state.on_response({"id": 1, "result": {"content": "data"}})
        assert span is not None
        assert span["type"] == "tool_call"
        assert span["name"] == "read_file"
        assert span["status"] == "success"
        assert span["latency_ms"] >= 0
        assert span["output"] is not None

    def test_on_response_error(self):
        state = self._make_state()
        state.on_request({"method": "tools/call", "id": 2, "params": {"name": "x"}})
        span = state.on_response({"id": 2, "error": {"code": -32600, "message": "bad"}})
        assert span["status"] == "error"
        assert span["error"] is not None

    def test_on_response_unknown_id(self):
        state = self._make_state()
        span = state.on_response({"id": 999, "result": {}})
        assert span is None

    def test_on_response_no_id(self):
        state = self._make_state()
        span = state.on_response({"result": {}})
        assert span is None

    def test_tools_list_caches_schemas(self):
        state = self._make_state()
        state.on_request({"method": "tools/list", "id": 1})
        state.on_response(
            {
                "id": 1,
                "result": {
                    "tools": [
                        {"name": "read_file", "inputSchema": {"properties": {"path": {}}, "required": ["path"]}},
                        {"name": "write_file", "inputSchema": {"properties": {"path": {}, "content": {}}}},
                    ]
                },
            }
        )
        assert "read_file" in state.tool_schemas
        assert "write_file" in state.tool_schemas

    def test_tool_call_after_list_checks_schema(self):
        state = self._make_state()
        # First cache schemas
        state.on_request({"method": "tools/list", "id": 1})
        state.on_response(
            {
                "id": 1,
                "result": {
                    "tools": [{"name": "read_file", "inputSchema": {"properties": {"path": {}}, "required": ["path"]}}]
                },
            }
        )
        # Now make a valid tool call
        state.on_request(
            {"method": "tools/call", "id": 2, "params": {"name": "read_file", "arguments": {"path": "/tmp"}}}
        )
        span = state.on_response({"id": 2, "result": {"content": "ok"}})
        assert span["tool_schema_valid"] == 1
        assert span["tools_available"] == 1

    def test_tool_call_hallucinated_params(self):
        state = self._make_state()
        state.on_request({"method": "tools/list", "id": 1})
        state.on_response(
            {
                "id": 1,
                "result": {
                    "tools": [{"name": "read_file", "inputSchema": {"properties": {"path": {}}, "required": ["path"]}}]
                },
            }
        )
        state.on_request(
            {"method": "tools/call", "id": 2, "params": {"name": "read_file", "arguments": {"wrong_param": "x"}}}
        )
        span = state.on_response({"id": 2, "result": {}})
        assert span["tool_schema_valid"] == 0

    @pytest.mark.asyncio
    async def test_buffer_and_flush(self):
        state = self._make_state()
        with patch.object(state, "_send", new_callable=AsyncMock) as mock_send:
            span = {"span_id": "s1", "type": "tool_call"}
            await state.buffer_span(span)
            assert len(state.buffer) == 1
            await state.flush()
            mock_send.assert_called_once()
            assert len(state.buffer) == 0

    @pytest.mark.asyncio
    async def test_auto_flush_at_50(self):
        state = self._make_state()
        with patch.object(state, "_send", new_callable=AsyncMock) as mock_send:
            for i in range(50):
                await state.buffer_span({"span_id": f"s{i}"})
            mock_send.assert_called_once()
            assert len(state.buffer) == 0

    @pytest.mark.asyncio
    async def test_send_fire_and_forget(self):
        state = self._make_state()
        # Even if httpx fails, _send should not raise
        with patch("observal_cli.shim.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = Exception("network error")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client
            await state._send([{"span_id": "s1"}])  # should not raise


# --- Config generator tests ---


class TestConfigGenerator:
    def _make_listing(self, name="my-mcp", listing_id="abc-123", **kw):
        listing = MagicMock()
        listing.name = name
        listing.id = listing_id
        listing.docker_image = kw.get("docker_image")
        listing.framework = kw.get("framework")
        listing.environment_variables = kw.get("environment_variables", [])
        listing.command = kw.get("command")
        listing.args = kw.get("args")
        listing.url = kw.get("url")
        listing.transport = kw.get("transport")
        listing.auto_approve = kw.get("auto_approve")
        return listing

    def test_cursor_wraps_with_shim(self):
        from services.config_generator import generate_config

        cfg = generate_config(self._make_listing(), "cursor")
        server = cfg["mcpServers"]["my-mcp"]
        assert server["command"] == "observal-shim"
        assert "--mcp-id" in server["args"]
        assert "abc-123" in server["args"]
        assert "--" in server["args"]

    def test_no_api_key_in_config(self):
        from services.config_generator import generate_config

        cfg = generate_config(self._make_listing(), "cursor")
        server = cfg["mcpServers"]["my-mcp"]
        env = server.get("env", {})
        assert "OBSERVAL_KEY" not in env
        assert "api_key" not in json.dumps(cfg).lower()

    def test_claude_code_format(self):
        from services.config_generator import generate_config

        cfg = generate_config(self._make_listing(), "claude-code")
        assert cfg["type"] == "shell_command"
        assert "observal-shim" in cfg["command"]

    def test_gemini_cli_format(self):
        from services.config_generator import generate_config

        cfg = generate_config(self._make_listing(), "gemini-cli")
        server = cfg["mcpServers"]["my-mcp"]
        assert server["command"] == "observal-shim"


class TestAgentConfigGenerator:
    def _make_agent(self, name="test-agent", agent_id="agent-xyz"):
        agent = MagicMock()
        agent.name = name
        agent.id = agent_id
        agent.prompt = "You are a test agent."
        agent.mcp_links = []
        agent.external_mcps = [{"name": "ext-mcp", "command": "npx", "args": ["ext-mcp-server"], "id": "ext-1"}]
        return agent

    def test_injects_agent_id(self):
        from services.agent_config_generator import generate_agent_config

        cfg = generate_agent_config(self._make_agent(), "cursor")
        mcp_cfg = cfg["mcp_config"]["content"]["mcpServers"]["ext-mcp"]
        assert mcp_cfg["env"]["OBSERVAL_AGENT_ID"] == "agent-xyz"

    def test_external_mcp_wrapped_with_shim(self):
        from services.agent_config_generator import generate_agent_config

        cfg = generate_agent_config(self._make_agent(), "cursor")
        mcp_cfg = cfg["mcp_config"]["content"]["mcpServers"]["ext-mcp"]
        assert mcp_cfg["command"] == "observal-shim"
        assert "--mcp-id" in mcp_cfg["args"]

    def test_kiro_format(self):
        from services.agent_config_generator import generate_agent_config

        cfg = generate_agent_config(self._make_agent(), "kiro")
        assert "agent_file" in cfg
        agent = cfg["agent_file"]["content"]
        assert agent["name"] == "test-agent"
        assert agent["mcpServers"]["ext-mcp"]["env"]["OBSERVAL_AGENT_ID"] == "agent-xyz"
        assert "@ext-mcp" in agent["tools"]
