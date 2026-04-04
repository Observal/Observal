"""Unit tests for observal-proxy: Phase 4."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from observal_cli.proxy import ProxyState, _handle_request, _parse_jsonrpc_body

# --- JSON-RPC body parsing ---


class TestParseJsonrpcBody:
    def test_valid_json(self):
        body = json.dumps({"method": "tools/call", "id": 1}).encode()
        assert _parse_jsonrpc_body(body) == {"method": "tools/call", "id": 1}

    def test_invalid_json(self):
        assert _parse_jsonrpc_body(b"not json") is None

    def test_empty(self):
        assert _parse_jsonrpc_body(b"") is None

    def test_binary(self):
        assert _parse_jsonrpc_body(b"\x00\x01\x02") is None


# --- ProxyState ---


class TestProxyState:
    def test_inherits_shim_state(self):
        state = ProxyState("mcp-1", "http://target:3000", "http://server:8000", "key")
        assert state.target_url == "http://target:3000"
        assert state.mcp_id == "mcp-1"
        assert state.server_url == "http://server:8000"
        assert state.trace_id  # auto-generated


# --- Request handling ---


class TestHandleRequest:
    @pytest.mark.asyncio
    async def test_forwards_request(self):
        state = ProxyState("mcp-1", "http://target:3000", "http://server:8000", "key")
        req_body = json.dumps({"method": "tools/call", "id": 1, "params": {"name": "x"}}).encode()
        resp_body = json.dumps({"id": 1, "result": {"content": "ok"}}).encode()

        with patch("observal_cli.proxy.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = resp_body
            mock_resp.headers = {"content-type": "application/json"}
            mock_client.request.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            with patch.object(state, "buffer_span", new_callable=AsyncMock) as mock_buf:
                status, headers, body = await _handle_request(state, "POST", "/", {}, req_body)

            assert status == 200
            assert body == resp_body
            mock_buf.assert_called_once()
            span = mock_buf.call_args[0][0]
            assert span["type"] == "tool_call"
            assert span["latency_ms"] >= 0

    @pytest.mark.asyncio
    async def test_returns_502_on_target_error(self):
        state = ProxyState("mcp-1", "http://target:3000", "http://server:8000", "key")

        with patch("observal_cli.proxy.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.request.side_effect = Exception("connection refused")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            status, headers, body = await _handle_request(state, "POST", "/", {}, b"{}")

        assert status == 502
        assert b"connection refused" in body

    @pytest.mark.asyncio
    async def test_non_jsonrpc_passthrough(self):
        state = ProxyState("mcp-1", "http://target:3000", "http://server:8000", "key")

        with patch("observal_cli.proxy.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = b"plain text"
            mock_resp.headers = {"content-type": "text/plain"}
            mock_client.request.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            with patch.object(state, "buffer_span", new_callable=AsyncMock) as mock_buf:
                status, _, body = await _handle_request(state, "GET", "/health", {}, b"")

            assert status == 200
            assert body == b"plain text"
            mock_buf.assert_not_called()  # no JSON-RPC, no span

    @pytest.mark.asyncio
    async def test_error_response_creates_error_span(self):
        state = ProxyState("mcp-1", "http://target:3000", "http://server:8000", "key")
        req_body = json.dumps({"method": "tools/call", "id": 1, "params": {"name": "x"}}).encode()
        resp_body = json.dumps({"id": 1, "error": {"code": -32600, "message": "bad"}}).encode()

        with patch("observal_cli.proxy.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = resp_body
            mock_resp.headers = {}
            mock_client.request.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            with patch.object(state, "buffer_span", new_callable=AsyncMock) as mock_buf:
                await _handle_request(state, "POST", "/", {}, req_body)

            span = mock_buf.call_args[0][0]
            assert span["status"] == "error"


# --- Config generator HTTP transport ---


class TestConfigGeneratorHTTP:
    def _make_listing(self, name="my-http-mcp", listing_id="http-123"):
        listing = MagicMock()
        listing.name = name
        listing.id = listing_id
        return listing

    def test_proxy_port_cursor(self):
        from services.config_generator import generate_config

        cfg = generate_config(self._make_listing(), "cursor", proxy_port=9999)
        server = cfg["mcpServers"]["my-http-mcp"]
        assert server["url"] == "http://localhost:9999"
        assert "command" not in server

    def test_proxy_port_claude_code(self):
        from services.config_generator import generate_config

        cfg = generate_config(self._make_listing(), "claude-code", proxy_port=9999)
        assert "http://localhost:9999" in str(cfg["command"])

    def test_proxy_port_kiro(self):
        from services.config_generator import generate_config

        cfg = generate_config(self._make_listing(), "kiro", proxy_port=8888)
        server = cfg["mcpServers"]["my-http-mcp"]
        assert server["url"] == "http://localhost:8888"

    def test_stdio_still_works(self):
        from services.config_generator import generate_config

        cfg = generate_config(self._make_listing(), "cursor")
        server = cfg["mcpServers"]["my-http-mcp"]
        assert server["command"] == "observal-shim"
