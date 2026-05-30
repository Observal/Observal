<!-- SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 tsitu0 <tomsitu0102@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# Telemetry pipeline

How trace data gets from an agent session to ClickHouse.

## Two paths

```
┌──────────────┐
│   Your IDE   │
└──────┬───────┘
       │
   (MCP call)                (hook event)
       │                         │
       ▼                         ▼
┌──────────────┐          ┌────────────────┐
│ observal-shim│          │    IDE hook    │
│ /proxy       │          │  (shell / HTTP)│
└──────┬───────┘          └────────┬───────┘
       │                           │
       ▼                           ▼
┌──────────────┐          ┌────────────────┐
│  /api/v1/    │          │ /api/v1/       │
│  telemetry/  │          │ telemetry/     │
│  ingest      │          │ hooks          │
└──────┬───────┘          └────────┬───────┘
       │                           │
       └──────────┬────────────────┘
                  ▼
          ┌───────────────┐
          │   ClickHouse  │
          │  (traces,     │
          │   spans)      │
          └───────────────┘
```

Two channels, one destination. **MCP tool calls** go through `observal-shim` (stdio) or `observal-proxy` (HTTP). **Lifecycle events** (session start, user prompt, session end, etc.) go through IDE hooks (native HTTP hooks for Claude Code, shell-command hooks for Kiro).

## Channel 1 - MCP traffic

The shim and proxy are transparent interceptors that forward MCP traffic unchanged while recording spans asynchronously.

Operational knobs:

* **Server address**: `OBSERVAL_SERVER_URL` on the CLI user's machine. The shim picks this up from `~/.observal/config.json` or the env var.
* **API key**: the shim uses the user's stored credentials. No extra setup.
* **Offline behavior**: if the server is unreachable, telemetry is buffered at `~/.observal/telemetry_buffer.db` and flushed later. Flush manually with `observal ops sync`. Check the buffer size with `observal auth status`.

## Channel 2 - IDE hooks

Events sent per lifecycle event:

* `SessionStart` / `Stop`: session boundaries
* `UserPromptSubmit`: the user's prompt
* `PreToolUse` / `PostToolUse`: tool calls (Claude Code has these even without the shim, for tools that don't go through MCP)
* `SubagentStop`: Claude Code sub-agent lifecycle
* `Notification`: IDE notifications

Full schema and handler types: [Hooks specification](../reference/hooks-spec.md).

`observal agent pull` and `observal doctor patch --hook` wire hooks into the appropriate file:

* Claude Code: `~/.claude/settings.json`
* Kiro: agent JSON at `.kiro/agents/<name>.json` or `~/.kiro/agents/<name>.json`

## High-volume tuning

At high telemetry volume, two hot spots:

1. **ClickHouse writes.** Observal batches inserts already. If you see ingest backpressure, bump `CLICKHOUSE_*` memory limits, consider external ClickHouse.
2. **Redis queue.** `arq` uses Redis for the background job queue. Redis at 256 MB is fine for most deployments.

## Alert on degraded ingest

Create an alert rule that fires when telemetry volume drops unexpectedly:

* "Spans/minute < 10% of last 24h average for 15 minutes"

Configure in the web UI at `/settings/alerts` or via `POST /api/v1/alerts`.

## Legacy event endpoints

`/api/v1/telemetry/events` is retained for backward compatibility with earlier hook formats. New integrations should use `/api/v1/telemetry/ingest` (batch traces + spans + scores) and `/api/v1/telemetry/hooks` (hook events).

## Verifying the pipeline

```bash
# Fire a test event from the CLI
observal ops telemetry test

# Confirm arrival
observal ops telemetry status
observal ops traces --limit 5
```

End-to-end smoke test done.

## Next

→ [Upgrades](upgrades.md)
