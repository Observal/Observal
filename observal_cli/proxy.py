"""observal-proxy: transparent HTTP reverse proxy for MCP servers.

Sits between IDE and an HTTP-transport MCP server, forwards all requests
untouched, and async fire-and-forgets copies to the Observal server.
"""

import asyncio
import json
import logging
import os
import sys
import time

import httpx

from observal_cli.config import load as load_config
from observal_cli.shim import ShimState

logger = logging.getLogger("observal-proxy")


def _parse_jsonrpc_body(body: bytes) -> dict | None:
    """Try to parse a JSON-RPC message from an HTTP body."""
    try:
        return json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


class ProxyState(ShimState):
    """Extends ShimState for HTTP proxy use."""

    def __init__(self, mcp_id: str, target_url: str, server_url: str, access_token: str, agent_id: str | None = None):
        super().__init__(mcp_id, server_url, access_token, agent_id)
        self.target_url = target_url.rstrip("/")


async def _handle_request(
    state: ProxyState, method: str, path: str, headers: dict, body: bytes
) -> tuple[int, dict, bytes]:
    """Forward a request to the target MCP server and capture telemetry."""
    url = f"{state.target_url}{path}"

    # Forward headers, skip hop-by-hop
    fwd_headers = {k: v for k, v in headers.items() if k.lower() not in ("host", "transfer-encoding")}

    max_attempts = 2
    for attempt in range(max_attempts):
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.request(method, url, headers=fwd_headers, content=body)
            latency_ms = int((time.monotonic() - start) * 1000)
            resp_body = resp.content
            resp_headers = dict(resp.headers)

            # Try to capture JSON-RPC telemetry
            req_msg = _parse_jsonrpc_body(body)
            resp_msg = _parse_jsonrpc_body(resp_body)

            if req_msg and isinstance(req_msg, dict) and "method" in req_msg:
                state.on_request(req_msg)
            if resp_msg and isinstance(resp_msg, dict):
                span = state.on_response(resp_msg)
                if span:
                    span["latency_ms"] = latency_ms
                    await state.buffer_span(span)

            return resp.status_code, resp_headers, resp_body
        except httpx.ConnectError:
            if attempt < max_attempts - 1:
                await asyncio.sleep(1)
                continue
            return (
                502,
                {"content-type": "application/json"},
                json.dumps({"error": "upstream connection failed"}).encode(),
            )
        except Exception as e:
            return 502, {"content-type": "application/json"}, json.dumps({"error": str(e)}).encode()


async def run_proxy(mcp_id: str, target_url: str, port: int = 0):
    """Start the HTTP proxy server."""
    # Resolve auth
    access_token = os.environ.get("OBSERVAL_KEY", "")
    server_url = os.environ.get("OBSERVAL_SERVER", "")
    if not access_token or not server_url:
        cfg = load_config()
        access_token = access_token or cfg.get("access_token", "")
        server_url = server_url or cfg.get("server_url", "")

    state = ProxyState(mcp_id, target_url, server_url or "", access_token or "", os.environ.get("OBSERVAL_AGENT_ID"))

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            # Read HTTP request line
            request_line = await reader.readline()
            if not request_line:
                writer.close()
                return
            parts = request_line.decode().strip().split(" ")
            if len(parts) < 3:
                writer.close()
                return
            method, path, _ = parts[0], parts[1], parts[2]

            # Read headers
            headers = {}
            content_length = 0
            while True:
                line = await reader.readline()
                if line in (b"\r\n", b"\n", b""):
                    break
                decoded = line.decode().strip()
                if ":" in decoded:
                    k, v = decoded.split(":", 1)
                    headers[k.strip().lower()] = v.strip()
                    if k.strip().lower() == "content-length":
                        content_length = int(v.strip())

            # Read body
            body = b""
            if content_length > 0:
                body = await reader.readexactly(content_length)

            # Forward
            status, resp_headers, resp_body = await _handle_request(state, method, path, headers, body)

            # Write response
            status_text = {
                200: "OK",
                201: "Created",
                204: "No Content",
                400: "Bad Request",
                404: "Not Found",
                500: "Internal Server Error",
                502: "Bad Gateway",
            }.get(status, "OK")
            writer.write(f"HTTP/1.1 {status} {status_text}\r\n".encode())
            resp_headers["content-length"] = str(len(resp_body))
            for k, v in resp_headers.items():
                if k.lower() not in ("transfer-encoding",):
                    writer.write(f"{k}: {v}\r\n".encode())
            writer.write(b"\r\n")
            writer.write(resp_body)
            await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", port)
    actual_port = server.sockets[0].getsockname()[1]
    print(json.dumps({"proxy_port": actual_port, "target": target_url}), flush=True)

    # Periodic flush
    flush_task = asyncio.create_task(_periodic_flush(state))
    try:
        async with server:
            await server.serve_forever()
    finally:
        flush_task.cancel()
        await state.send_final()


async def _periodic_flush(state: ShimState, interval: float = 5.0):
    try:
        while True:
            await asyncio.sleep(interval)
            await state.flush()
    except asyncio.CancelledError:
        pass


def main():
    """CLI entry point for observal-proxy."""
    args = sys.argv[1:]

    mcp_id = ""
    target_url = ""
    port = 0
    i = 0
    while i < len(args):
        if args[i] == "--mcp-id" and i + 1 < len(args):
            mcp_id = args[i + 1]
            i += 2
        elif args[i] == "--target" and i + 1 < len(args):
            target_url = args[i + 1]
            i += 2
        elif args[i] == "--port" and i + 1 < len(args):
            port = int(args[i + 1])
            i += 2
        else:
            i += 1

    if not target_url:
        print("Usage: observal-proxy --mcp-id <id> --target <url> [--port <port>]", file=sys.stderr)
        sys.exit(1)

    asyncio.run(run_proxy(mcp_id, target_url, port))


if __name__ == "__main__":
    main()
