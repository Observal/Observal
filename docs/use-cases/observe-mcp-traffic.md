<!-- SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# Observe MCP traffic

Your agents are making tool calls every session. You have no idea how many, which ones fail, which ones are slow, or which ones are never used. This is the first and cheapest thing Observal does for you.

## What you get

Every MCP tool call becomes a span with:

* Tool name and input parameters
* Response payload
* Latency (ms)
* Status (success / error) and error message
* Token counts and cost (where the IDE exposes them; Claude Code does, Kiro gives credits only)
* A `trace_id` that groups calls from the same agent turn, and a `session_id` that groups calls across an IDE session

Spans stream into ClickHouse in near real-time. You query them from the web UI or the CLI.

## Discover and instrument an existing setup

If you already have MCP servers configured in Claude Code, Kiro, Cursor, VS Code, or Gemini CLI, first see what's there:

```bash
observal scan
```

`scan` is read-only -- it lists your MCP servers without modifying anything. Then instrument them:

```bash
observal doctor patch --all --all-ides
```

This:

1. Finds every MCP config file on your machine (`~/.claude/settings.json`, `.kiro/settings/mcp.json`, `.cursor/mcp.json`, `.vscode/mcp.json`, `.gemini/settings.json`).
2. Rewrites each config so every server runs through `observal-shim`.
3. Installs telemetry hooks for session lifecycle events.
4. Saves a timestamped `.bak` next to every file it modified.

Scope to specific IDEs:

```bash
observal doctor patch --all --ide claude-code
observal doctor patch --all --ide kiro
observal doctor patch --all --ide gemini-cli
```

## Observability at zero cost to your agents

The shim is transparent - it forwards every byte unchanged. If it can't reach the Observal server, the tool call **still succeeds** and telemetry is buffered locally in `~/.observal/telemetry_buffer.db`, flushed on the next successful contact. See [Core Concepts → Telemetry buffer](../getting-started/core-concepts.md#telemetry-buffer).

Restart your IDE after `doctor patch`. The next MCP call produces a trace.

## Query what you collected

**Web UI**: open `http://localhost/traces`. Filter by IDE, agent, MCP, or time range.

**CLI**: list recent traces and drill into spans:

```bash
# Last 20 traces
observal ops traces --limit 20

# Last 20 from a specific MCP server
observal ops traces --mcp github-mcp

# Dive into a specific trace
observal ops spans <trace-id>

# Ranking dashboard - which MCP servers are hottest?
observal ops top --type mcp

# Metrics for one MCP (live-updating)
observal ops metrics github-mcp --type mcp --watch
```

## What this unlocks

Once traces are flowing you can:

* **Find the bottleneck.** `observal ops top --type mcp` → which servers are called most and which are slowest.
* **Spot errors early.** Alert rules fire on error-rate spikes. See the Alerts page in the web UI.
* **Plan removals.** A tool nobody uses after a week is a tool you can delete from the agent config.

## Caveats

* Token counts and cost are only as good as what the IDE exposes. Claude Code provides both. Kiro exposes billing credits instead of token counts; Observal shows credits for Kiro sessions.
* HTTP/SSE MCP servers route through `observal-proxy`, not `observal-shim`. `doctor patch` picks the right one automatically based on the transport field.

## Next

→ [Debug agent failures](debug-agent-failures.md): now that you have traces, here's how to actually use them when something breaks.
