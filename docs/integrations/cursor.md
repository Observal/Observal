<!-- SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 tsitu0 <tomsitu0102@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# Cursor

Cursor is supported at the MCP and rules level. Telemetry is MCP-traffic-only — Cursor doesn't expose session lifecycle hooks, so tool calls are the unit of observation.

## What you get

* **MCP server instrumentation** — `observal doctor patch --shim --ide cursor` wraps MCPs via `observal-shim`
* **Rules files** — Cursor reads `AGENTS.md` / `.cursor/rules` for system instructions

## What you don't get

* No hook bridge — no session start/stop, user prompt, or subagent events
* No native OTLP

If these matter, use Claude Code or Kiro instead.

## Setup

```bash
curl -fsSL https://raw.githubusercontent.com/BlazeUp-AI/Observal/main/install.sh | bash
observal auth login

observal scan --ide cursor                         # see what's there
observal doctor patch --all --ide cursor            # instrument it
observal doctor --ide cursor                        # verify
```

Restart Cursor.

## Config file

`.cursor/mcp.json` in your project directory. After `doctor patch --shim`, every MCP entry routes through `observal-shim`. A timestamped `.bak` is saved next to the file.

## Install an agent

```bash
observal agent pull <agent-id> --ide cursor
```

What gets written:

* MCP servers appended to `.cursor/mcp.json`
* `AGENTS.md` (or `.cursor/rules` if configured) with the agent's rules

Cursor reloads MCP on the next prompt — you may need to restart Cursor for a cleaner state.

## Caveats

* Cursor's MCP config is currently per-project. For global config, repeat `doctor patch` per project or use `observal use` with a profile that applies to multiple directories.
* Because there are no lifecycle hooks, traces are tool-call-level. You won't see "user prompt X produced tool calls Y and Z" — only Y and Z.

## Related

* [`observal scan`](../cli/scan.md)
* [Use Cases → Observe MCP traffic](../use-cases/observe-mcp-traffic.md)
