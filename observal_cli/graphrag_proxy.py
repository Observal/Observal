"""observal-graphrag-proxy: HTTP reverse proxy for GraphRAG endpoints.

Sits between agent and GraphRAG endpoint, forwards all requests untouched,
captures query/response pairs as retrieval spans with telemetry.
"""

import asyncio
import json
import logging
import os
import sys
import time
import uuid
from datetime import UTC, datetime

import httpx

from observal_cli.config import load as load_config

logger = logging.getLogger("observal-graphrag-proxy")

MAX_BODY_BYTES = 64 * 1024  # 64KB truncation


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _truncate(text: str, limit: int = MAX_BODY_BYTES) -> str:
    if len(text) > limit:
        return text[:limit] + "\n... [truncated]"
    return text


def _detect_query_interface(path: str, content_type: str, body: bytes) -> str:
    if "/graphql" in path or content_type == "application/graphql":
        return "graphql"
    if "/sparql" in path:
        return "sparql"
    if "/cypher" in path:
        return "cypher"
    try:
        parsed = json.loads(body)
        if isinstance(parsed, dict) and "query" in parsed:
            q = parsed["query"].strip().lower()
            if q.startswith("{") or q.startswith("query") or q.startswith("mutation"):
                return "graphql"
            if q.startswith("select") or q.startswith("ask") or q.startswith("construct"):
                return "sparql"
            if q.startswith("match") or q.startswith("create"):
                return "cypher"
    except Exception:
        pass
    return "rest"


def _parse_response_counts(body: bytes) -> tuple[int | None, float | None]:
    """Try to extract entity count and relevance score from response."""
    try:
        parsed = json.loads(body)
        if isinstance(parsed, dict):
            # Common patterns: results, data, nodes, entities, chunks
            chunks = None
            relevance = None
            for key in ("results", "data", "nodes", "entities", "chunks", "hits"):
                if key in parsed and isinstance(parsed[key], list):
                    chunks = len(parsed[key])
                    break
            if "score" in parsed:
                relevance = float(parsed["score"])
            elif "relevance" in parsed:
                relevance = float(parsed["relevance"])
            return chunks, relevance
    except Exception:
        pass
    return None, None


class GraphRagProxyState:
    def __init__(self, graphrag_id: str, target_url: str, server_url: str, api_key: str):
        self.graphrag_id = graphrag_id
        self.target_url = target_url.rstrip("/")
        self.server_url = server_url.rstrip("/") if server_url else ""
        self.api_key = api_key
        self._buffer: list[dict] = []
        self._lock = asyncio.Lock()

    async def buffer_span(self, span: dict):
        async with self._lock:
            self._buffer.append(span)
            if len(self._buffer) >= 10:
                await self._flush_locked()

    async def flush(self):
        async with self._lock:
            await self._flush_locked()

    async def _flush_locked(self):
        if not self._buffer or not self.server_url or not self.api_key:
            self._buffer.clear()
            return
        spans = self._buffer[:]
        self._buffer.clear()
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                await client.post(
                    f"{self.server_url}/api/v1/telemetry/ingest",
                    json={"traces": [], "spans": spans, "scores": []},
                    headers={"X-API-Key": self.api_key},
                )
        except Exception:
            pass


async def _handle_request(
    state: GraphRagProxyState, method: str, path: str, headers: dict, body: bytes
) -> tuple[int, dict, bytes]:
    url = f"{state.target_url}{path}"
    fwd_headers = {k: v for k, v in headers.items() if k.lower() not in ("host", "transfer-encoding")}

    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.request(method, url, headers=fwd_headers, content=body)
        latency_ms = int((time.monotonic() - start) * 1000)
        resp_body = resp.content

        content_type = headers.get("content-type", "")
        query_interface = _detect_query_interface(path, content_type, body)
        chunks, relevance = _parse_response_counts(resp_body)

        input_text = body.decode("utf-8", errors="replace") if body else ""
        output_text = resp_body.decode("utf-8", errors="replace") if resp_body else ""

        span = {
            "span_id": str(uuid.uuid4()),
            "trace_id": str(uuid.uuid4()),
            "parent_span_id": None,
            "type": "retrieval",
            "name": f"graphrag:{path or '/'}",
            "method": method,
            "input": _truncate(input_text),
            "output": _truncate(output_text),
            "error": None if resp.status_code < 400 else f"HTTP {resp.status_code}",
            "start_time": _now_iso(),
            "end_time": _now_iso(),
            "latency_ms": latency_ms,
            "status": "success" if resp.status_code < 400 else "error",
            "ide": "",
            "metadata": {"graphrag_id": state.graphrag_id},
            "query_interface": query_interface,
            "chunks_returned": chunks,
            "relevance_score": relevance,
        }
        await state.buffer_span(span)

        return resp.status_code, dict(resp.headers), resp_body
    except Exception as e:
        latency_ms = int((time.monotonic() - start) * 1000)
        return 502, {"content-type": "application/json"}, json.dumps({"error": str(e)}).encode()


async def run_proxy(graphrag_id: str, target_url: str, port: int = 0):
    api_key = os.environ.get("OBSERVAL_KEY", "")
    server_url = os.environ.get("OBSERVAL_SERVER", "")
    if not api_key or not server_url:
        cfg = load_config()
        api_key = api_key or cfg.get("api_key", "")
        server_url = server_url or cfg.get("server_url", "")

    state = GraphRagProxyState(graphrag_id, target_url, server_url or "", api_key or "")

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            request_line = await reader.readline()
            if not request_line:
                writer.close()
                return
            parts = request_line.decode().strip().split(" ")
            if len(parts) < 3:
                writer.close()
                return
            method, path = parts[0], parts[1]

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

            body = b""
            if content_length > 0:
                body = await reader.readexactly(content_length)

            status, resp_headers, resp_body = await _handle_request(state, method, path, headers, body)

            status_text = {200: "OK", 201: "Created", 400: "Bad Request", 404: "Not Found", 500: "Internal Server Error", 502: "Bad Gateway"}.get(status, "OK")
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
    print(json.dumps({"proxy_port": actual_port, "target": target_url, "graphrag_id": graphrag_id}), flush=True)

    async def periodic_flush():
        try:
            while True:
                await asyncio.sleep(5.0)
                await state.flush()
        except asyncio.CancelledError:
            pass

    flush_task = asyncio.create_task(periodic_flush())
    try:
        async with server:
            await server.serve_forever()
    finally:
        flush_task.cancel()
        await state.flush()


def main():
    args = sys.argv[1:]
    graphrag_id = ""
    target_url = ""
    port = 0

    i = 0
    while i < len(args):
        if args[i] == "--graphrag-id" and i + 1 < len(args):
            graphrag_id = args[i + 1]
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
        print("Usage: observal-graphrag-proxy --graphrag-id <id> --target <url> [--port <port>]", file=sys.stderr)
        sys.exit(1)

    asyncio.run(run_proxy(graphrag_id, target_url, port))


if __name__ == "__main__":
    main()
