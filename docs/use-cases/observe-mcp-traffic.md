# Observe MCP traffic

Your agents are making tool calls every session. You have no idea how many, which ones fail, which ones are slow, or which ones are never used. This is the first and cheapest thing Observal does for you.

## What you get

Every MCP tool call becomes a span with:

* Tool name and input parameters
* Response payload
* Latency (ms)
* Status (success / error) and error message
* Token counts and cost (where the IDE exposes them — Claude Code does, Kiro gives credits only)
* A `trace_id` that groups calls from the same agent turn, and a `session_id` that groups calls across an IDE session

Spans stream into ClickHouse in near real-time. You query them from the web UI or the CLI.

## Instrument an existing setup in one command

If you already have MCP servers configured in Claude Code, Kiro, Cursor, VS Code, or Gemini CLI:

```bash
observal scan
```

This:

1. Finds every MCP config file on your machine (`~/.claude/settings.json`, `.kiro/settings/mcp.json`, `.cursor/mcp.json`, `.vscode/mcp.json`, `.gemini/settings.json`).
2. Registers each MCP server with Observal (you'll see them in `observal registry mcp list`).
3. Rewrites each config so every server runs through `observal-shim`.
4. Saves a timestamped `.bak` next to every file it modified.

Scope the scan if you only want certain IDEs:

```bash
observal scan --ide claude-code
observal scan --ide kiro
observal scan --all-ides        # every IDE Observal knows about
```

Project vs global Kiro config:

```bash
observal scan --ide kiro           # project (.kiro/settings/mcp.json)
observal scan --ide kiro --home    # global (~/.kiro/settings/mcp.json)
```

## Observability at zero cost to your agents

The shim is transparent — it forwards every byte unchanged. If it can't reach the Observal server, the tool call **still succeeds** and telemetry is buffered locally in `~/.observal/telemetry_buffer.db`, flushed on the next successful contact. See [Core Concepts → Telemetry buffer](../getting-started/core-concepts.md#telemetry-buffer).

Restart your IDE after `scan`. The next MCP call produces a trace.

## Query what you collected

**Web UI** — open `http://localhost:3000/traces`. Filter by IDE, agent, MCP, or time range.

**CLI** — list recent traces and drill into spans:

```bash
# Last 20 traces
observal ops traces --limit 20

# Last 20 from a specific MCP server
observal ops traces --mcp github-mcp

# Dive into a specific trace
observal ops spans <trace-id>

# Ranking dashboard — which MCP servers are hottest?
observal ops top --type mcp

# Metrics for one MCP (live-updating)
observal ops metrics github-mcp --type mcp --watch
```

## What this unlocks

Once traces are flowing you can:

* **Find the bottleneck.** `observal ops top --type mcp` → which servers are called most and which are slowest.
* **Spot errors early.** Alert rules fire on error-rate spikes — see the Alerts page in the web UI.
* **Plan removals.** A tool nobody uses after a week is a tool you can delete from the agent config.
* **Feed the eval engine.** Traces are the raw material evaluators score against.

## Caveats

* Token counts and cost are only as good as what the IDE exposes. Claude Code provides both. Kiro exposes billing credits instead of token counts; Observal shows credits for Kiro sessions.
* HTTP/SSE MCP servers route through `observal-proxy`, not `observal-shim`. `scan` picks the right one automatically based on the transport field.

## Next

→ [Debug agent failures](debug-agent-failures.md) — now that you have traces, here's how to actually use them when something breaks.
