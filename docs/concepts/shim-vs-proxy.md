# Shim vs proxy

How Observal intercepts MCP traffic without modifying it. Two components, different transports, same job.

## What they do

Both are transparent interceptors. An MCP request enters on one side, is forwarded unchanged to the other side, and a copy is fire-and-forgotten to the Observal API as a span.

```
IDE  ──►  shim/proxy  ──►  MCP server
           │
           ▼ (async, non-blocking)
      Observal API  ──►  ClickHouse
```

"Transparent" here is strict: **bytes are not altered.** If the shim or proxy is unreachable to the server, the MCP call still succeeds — telemetry is queued in `~/.observal/telemetry_buffer.db` for later.

## The split

Two transports, two binaries:

| Component | Transport | Used when |
| --- | --- | --- |
| `observal-shim` | stdio | The MCP server is invoked as a subprocess (most Python / Node MCPs) |
| `observal-proxy` | HTTP, SSE, streamable-HTTP | The MCP server speaks HTTP |

Both are installed as entry points when you install the CLI. You rarely invoke them by hand — `observal scan` rewrites IDE configs to route through the appropriate one based on the transport field.

## Why two

MCP has multiple transport specs:

* **stdio** — the default. A subprocess with stdin/stdout as the protocol bus. Cheap, local, and what most MCP servers use.
* **HTTP / SSE / streamable-HTTP** — long-lived connections for remote MCP servers. Lets you run MCP services over a network rather than as a subprocess.

stdio and HTTP need completely different interception mechanics. A stdio shim can't hook HTTP traffic and vice versa. So Observal ships both.

## What the shim does (stdio)

1. The IDE spawns `observal-shim` as a subprocess (instead of the MCP server directly).
2. The shim parses its argv, learns which real MCP server it's wrapping, and spawns *that* server.
3. Every JSON-RPC message on stdin is forwarded to the child's stdin. Every response on the child's stdout is forwarded to the shim's stdout.
4. As messages pass through, the shim builds a span (tool name, input, output, latency, status) and POSTs it to the Observal API.

Rewritten config example:

```json
// Before:
"github-mcp": {
  "command": "npx",
  "args": ["@modelcontextprotocol/server-github"]
}

// After:
"github-mcp": {
  "command": "observal-shim",
  "args": ["--", "npx", "@modelcontextprotocol/server-github"]
}
```

## What the proxy does (HTTP)

1. `observal-proxy` runs as a local HTTP server on a chosen port.
2. The IDE is configured to talk to the proxy instead of the upstream MCP.
3. The proxy forwards each request to the upstream, streams the response back, and builds spans from observed JSON-RPC traffic.

For SSE / streamable-HTTP, spans include streaming details — every chunk contributes to the span.

## Classification: tool vs transport vs control

Inside the shim and proxy, spans are classified by message type. See `observal_cli/shim.py:26-38` for the exact mapping.

* `tool_call` — the agent invoked a tool (`tools/call`)
* `tool_list` — listing available tools (`tools/list`)
* `resource_read` — reading a resource (`resources/read`)
* `control` — initialization, shutdown, handshake messages

Most UI and eval work operates on `tool_call` spans. The others are useful for debugging MCP protocol issues.

## Failure modes

**The shim can't reach the Observal server.** The tool call still succeeds. Telemetry is queued locally (`~/.observal/telemetry_buffer.db`) and flushed on the next successful contact. Check with `observal auth status`.

**The MCP server crashes.** The shim detects the child process exit and surfaces the failure to the IDE. A span is still recorded with `status: error` and the child's stderr attached.

**The shim itself crashes.** Extremely rare, and the IDE surfaces it as an MCP server crash. The shim is a thin wrapper — most of its bugs are config parsing issues, which show up at startup, not mid-session.

## Why not modify the IDE?

We could. But:

* IDEs release on their own schedule. Observal would lag.
* Every IDE is different. A per-IDE integration multiplies the surface area.
* The shim works everywhere MCP works, today. One code path covers Claude Code, Kiro, Cursor, VS Code, Gemini CLI, any future MCP consumer.

The tradeoff: we can't observe things that don't go through MCP. For those, Observal uses IDE-native hooks (see [Telemetry pipeline](../self-hosting/telemetry-pipeline.md)).

## Security notes

* The shim and proxy never send credentials to Observal unless they were in the MCP tool *output* itself. Request payloads often contain secrets (API keys in headers, tokens in args); those are logged. **Don't ship production API keys to a shared Observal server if you haven't vetted the retention policy.**
* For sensitive MCPs, consider running a private Observal instance. Everything works the same against a private server — just point `OBSERVAL_SERVER_URL` elsewhere.

## Related

* [`observal scan`](../cli/scan.md) — the command that wires the shim/proxy in
* [Data model](data-model.md) — what a span looks like after the shim records it
* [Telemetry pipeline](../self-hosting/telemetry-pipeline.md) — the rest of the path from span to ClickHouse
