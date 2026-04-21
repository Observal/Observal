# Cursor

Cursor is supported at the MCP and rules level. Telemetry is MCP-traffic-only — Cursor doesn't expose session lifecycle hooks, so tool calls are the unit of observation.

## What you get

* **MCP server instrumentation** — `observal scan --ide cursor` wraps MCPs via `observal-shim`
* **Rules files** — Cursor reads `AGENTS.md` / `.cursor/rules` for system instructions

## What you don't get

* No hook bridge — no session start/stop, user prompt, or subagent events
* No native OTLP

If these matter, use Claude Code or Kiro instead.

## Setup

```bash
uv tool install observal-cli
observal auth login

observal scan --ide cursor
observal doctor --ide cursor
```

Restart Cursor.

## Config file

`.cursor/mcp.json` in your project directory. After `scan`, every MCP entry routes through `observal-shim`. A timestamped `.bak` is saved next to the file.

## Install an agent

```bash
observal pull <agent-id> --ide cursor
```

What gets written:

* MCP servers appended to `.cursor/mcp.json`
* `AGENTS.md` (or `.cursor/rules` if configured) with the agent's rules

Cursor reloads MCP on the next prompt — you may need to restart Cursor for a cleaner state.

## Caveats

* Cursor's MCP config is currently per-project. For global config, repeat `scan` per project or use `observal use` with a profile that applies to multiple directories.
* Because there are no lifecycle hooks, traces are tool-call-level. You won't see "user prompt X produced tool calls Y and Z" — only Y and Z.

## Related

* [`observal scan`](../cli/scan.md)
* [Use Cases → Observe MCP traffic](../use-cases/observe-mcp-traffic.md)
