"""observal-shim: transparent stdio wrapper for MCP servers.

Sits on the stdio pipe between IDE and MCP, passes all JSON-RPC messages
through untouched, and async fire-and-forgets copies to the Observal server.
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

logger = logging.getLogger("observal-shim")

# --- JSON-RPC span type mapping ---

METHOD_TO_SPAN: dict[str, tuple[str, str | None]] = {
    "tools/call": ("tool_call", "params.name"),
    "tools/list": ("tool_list", None),
    "resources/read": ("resource_read", "params.uri"),
    "resources/list": ("resource_list", None),
    "resources/subscribe": ("resource_subscribe", "params.uri"),
    "prompts/get": ("prompt_get", "params.name"),
    "prompts/list": ("prompt_list", None),
    "initialize": ("initialize", None),
    "ping": ("ping", None),
    "completion/complete": ("completion", None),
    "logging/setLevel": ("config", None),
}


def classify_message(msg: dict) -> str:
    """Classify a JSON-RPC message as 'request', 'response', or 'notification'."""
    if "method" in msg and "id" in msg:
        return "request"
    if "result" in msg or "error" in msg:
        return "response"
    return "notification"


def extract_span_type(method: str) -> str:
    """Map a JSON-RPC method to a span type."""
    entry = METHOD_TO_SPAN.get(method)
    return entry[0] if entry else "other"


def extract_span_name(method: str, params: dict | None) -> str:
    """Extract a human-readable span name from a JSON-RPC request."""
    entry = METHOD_TO_SPAN.get(method)
    if entry and entry[1] and params:
        # Navigate dotted path like "params.name"
        parts = entry[1].split(".")
        val = params
        for p in parts:
            if p == "params":
                continue
            if isinstance(val, dict):
                val = val.get(p)
            else:
                val = None
                break
        if val and isinstance(val, str):
            return val
    return method or "unknown"


def check_schema_compliance(params: dict | None, tool_schemas: dict) -> tuple[int | None, int | None]:
    """Check if tool_call args match cached schema. Returns (tool_schema_valid, tools_available)."""
    if not tool_schemas:
        return None, None
    tools_available = len(tool_schemas)
    if not params or "name" not in params:
        return None, tools_available
    tool_name = params["name"]
    if tool_name not in tool_schemas:
        return 0, tools_available  # tool not in schema = hallucinated
    schema = tool_schemas[tool_name]
    args = params.get("arguments", {})
    if not schema:
        return 1, tools_available
    # Check required properties
    required = schema.get("required", [])
    properties = schema.get("properties", {})
    for r in required:
        if r not in args:
            return 0, tools_available
    # Check no extra properties if schema defines them
    if properties:
        for k in args:
            if k not in properties:
                return 0, tools_available
    return 1, tools_available


class ShimState:
    """Mutable state for the shim process."""

    def __init__(self, mcp_id: str, server_url: str, access_token: str, agent_id: str | None = None):
        self.mcp_id = mcp_id
        self.server_url = server_url.rstrip("/")
        self.access_token = access_token
        self.agent_id = agent_id
        self.trace_id = os.environ.get("OBSERVAL_TRACE_ID") or str(uuid.uuid4())
        self.parent_trace_id = os.environ.get("OBSERVAL_TRACE_ID")  # if set, we're a child
        self.session_id = os.environ.get("OBSERVAL_SESSION_ID", "")
        self.ide = os.environ.get("OBSERVAL_IDE", "")
        self.environment = os.environ.get("OBSERVAL_ENVIRONMENT", "default")
        self.trace_start = datetime.now(UTC)

        # Request tracking: id -> (method, params, start_time)
        self.pending: dict[str | int, tuple[str, dict | None, float]] = {}
        # Buffered spans for batch sending
        self.buffer: list[dict] = []
        self.tool_schemas: dict[str, dict] = {}  # tool_name -> inputSchema
        self.lock = asyncio.Lock()

    def _now_iso(self) -> str:
        return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    def on_request(self, msg: dict):
        """Track an outgoing request for later pairing."""
        msg_id = msg.get("id")
        method = msg.get("method", "")
        params = msg.get("params")
        if msg_id is not None:
            self.pending[msg_id] = (method, params, time.monotonic())

    def on_response(self, msg: dict) -> dict | None:
        """Pair a response with its request and create a span."""
        msg_id = msg.get("id")
        if msg_id is None or msg_id not in self.pending:
            return None
        method, params, start_mono = self.pending.pop(msg_id)
        latency_ms = int((time.monotonic() - start_mono) * 1000)
        now = self._now_iso()

        span_type = extract_span_type(method)
        span_name = extract_span_name(method, params)

        # Cache tool schemas from tools/list response
        if method == "tools/list" and "result" in msg:
            tools = msg["result"].get("tools", [])
            self.tool_schemas = {t["name"]: t.get("inputSchema", {}) for t in tools if "name" in t}

        # Schema compliance for tool_call
        tool_schema_valid = None
        tools_available = None
        if method == "tools/call":
            tool_schema_valid, tools_available = check_schema_compliance(params, self.tool_schemas)

        error_str = None
        status = "success"
        if "error" in msg:
            status = "error"
            error_str = json.dumps(msg["error"])

        return {
            "span_id": str(uuid.uuid4()),
            "trace_id": self.trace_id,
            "type": span_type,
            "name": span_name,
            "method": method,
            "input": json.dumps(params) if params else None,
            "output": json.dumps(msg.get("result")) if "result" in msg else None,
            "error": error_str,
            "start_time": now,  # approximate
            "end_time": now,
            "latency_ms": latency_ms,
            "status": status,
            "ide": self.ide,
            "metadata": {},
            "tool_schema_valid": tool_schema_valid,
            "tools_available": tools_available,
        }

    async def buffer_span(self, span: dict):
        async with self.lock:
            self.buffer.append(span)
            if len(self.buffer) >= 50:
                await self._flush_locked()

    async def flush(self):
        async with self.lock:
            await self._flush_locked()

    async def _flush_locked(self):
        if not self.buffer:
            return
        spans = self.buffer[:]
        self.buffer.clear()
        await self._send(spans)

    async def _send(self, spans: list[dict]):
        """Fire-and-forget send to Observal server."""
        payload = {
            "traces": [
                {
                    "trace_id": self.trace_id,
                    "parent_trace_id": self.parent_trace_id,
                    "trace_type": "mcp",
                    "mcp_id": self.mcp_id,
                    "agent_id": self.agent_id,
                    "session_id": self.session_id,
                    "ide": self.ide,
                    "name": f"shim:{self.mcp_id}",
                    "start_time": self.trace_start.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                    "tags": [],
                    "metadata": {},
                }
            ],
            "spans": spans,
            "scores": [],
        }
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                await client.post(
                    f"{self.server_url}/api/v1/telemetry/ingest",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.access_token}",
                        "X-Observal-Environment": self.environment,
                    },
                )
        except Exception:
            pass  # fire-and-forget: never block, never retry

    async def send_final(self):
        """Flush remaining buffer and send trace end_time."""
        await self.flush()


# --- Stdio relay ---


async def _read_messages(stream: asyncio.StreamReader) -> asyncio.Queue:
    """Read newline-delimited JSON-RPC messages from a stream into a queue."""
    queue: asyncio.Queue = asyncio.Queue()

    async def _reader():
        buf = b""
        while True:
            chunk = await stream.read(65536)
            if not chunk:
                await queue.put(None)  # EOF sentinel
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    await queue.put(msg)
                except json.JSONDecodeError:
                    pass  # skip malformed

    _task = asyncio.create_task(_reader())  # noqa: RUF006 - fire-and-forget by design
    return queue


async def _relay_ide_to_mcp(
    ide_queue: asyncio.Queue,
    mcp_stdin: asyncio.StreamWriter,
    state: ShimState,
):
    """Relay messages from IDE to MCP, tracking requests."""
    while True:
        msg = await ide_queue.get()
        if msg is None:
            mcp_stdin.close()
            break
        kind = classify_message(msg)
        if kind == "request":
            state.on_request(msg)
        raw = json.dumps(msg) + "\n"
        mcp_stdin.write(raw.encode())
        await mcp_stdin.drain()


async def _relay_mcp_to_ide(
    mcp_queue: asyncio.Queue,
    ide_stdout: asyncio.StreamWriter,
    state: ShimState,
):
    """Relay messages from MCP to IDE, pairing responses to create spans."""
    while True:
        msg = await mcp_queue.get()
        if msg is None:
            break
        kind = classify_message(msg)
        if kind == "response":
            span = state.on_response(msg)
            if span:
                await state.buffer_span(span)
        raw = json.dumps(msg) + "\n"
        ide_stdout.write(raw.encode())
        await ide_stdout.drain()


async def _periodic_flush(state: ShimState, interval: float = 5.0):
    """Flush buffered spans every `interval` seconds."""
    try:
        while True:
            await asyncio.sleep(interval)
            await state.flush()
    except asyncio.CancelledError:
        pass


async def run_shim(mcp_id: str, command: list[str]):
    """Main shim entry point: spawn MCP process and relay stdio."""
    # Resolve auth
    access_token = os.environ.get("OBSERVAL_KEY", "")
    server_url = os.environ.get("OBSERVAL_SERVER", "")
    if not access_token or not server_url:
        cfg = load_config()
        access_token = access_token or cfg.get("access_token", "")
        server_url = server_url or cfg.get("server_url", "")

    if not server_url or not access_token:
        # No config: pass through without capturing
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdin=sys.stdin,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
        sys.exit(await proc.wait())

    agent_id = os.environ.get("OBSERVAL_AGENT_ID")
    state = ShimState(mcp_id, server_url, access_token, agent_id)

    # Spawn the real MCP process
    proc = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    # Set up async readers
    ide_reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(ide_reader)
    await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)

    ide_writer_transport, ide_writer_protocol = await asyncio.get_event_loop().connect_write_pipe(
        asyncio.streams.FlowControlMixin, sys.stdout
    )
    ide_stdout = asyncio.StreamWriter(ide_writer_transport, ide_writer_protocol, None, asyncio.get_event_loop())

    ide_queue = await _read_messages(ide_reader)
    mcp_queue = await _read_messages(proc.stdout)

    # Forward stderr
    async def _forward_stderr():
        while True:
            data = await proc.stderr.read(65536)
            if not data:
                break
            sys.stderr.buffer.write(data)
            sys.stderr.buffer.flush()

    flush_task = asyncio.create_task(_periodic_flush(state))
    stderr_task = asyncio.create_task(_forward_stderr())

    try:
        await asyncio.gather(
            _relay_ide_to_mcp(ide_queue, proc.stdin, state),
            _relay_mcp_to_ide(mcp_queue, ide_stdout, state),
        )
    finally:
        flush_task.cancel()
        stderr_task.cancel()
        await state.send_final()

    return await proc.wait()


def main():
    """CLI entry point for observal-shim."""
    args = sys.argv[1:]

    # Parse --mcp-id <id> -- <command...>
    mcp_id = ""
    command = []
    i = 0
    while i < len(args):
        if args[i] == "--mcp-id" and i + 1 < len(args):
            mcp_id = args[i + 1]
            i += 2
        elif args[i] == "--":
            command = args[i + 1 :]
            break
        else:
            i += 1

    if not command:
        print("Usage: observal-shim --mcp-id <id> -- <command> [args...]", file=sys.stderr)
        sys.exit(1)

    exit_code = asyncio.run(run_shim(mcp_id, command))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
