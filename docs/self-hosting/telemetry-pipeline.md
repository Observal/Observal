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
│  telemetry/  │          │ otel/hooks     │
│  ingest      │          │                │
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

Two channels, one destination. **MCP tool calls** go through `observal-shim` (stdio) or `observal-proxy` (HTTP). **Lifecycle events** (session start, user prompt, session end, etc.) go through IDE hooks — native HTTP hooks for Claude Code, shell-command hooks for Kiro.

## Channel 1 — MCP traffic

Full architecture in [Concepts → Shim vs proxy](../concepts/shim-vs-proxy.md).

Operational knobs:

* **Server address** — `OBSERVAL_SERVER_URL` on the CLI user's machine. The shim picks this up from `~/.observal/config.json` or the env var.
* **API key** — the shim uses the user's stored credentials. No extra setup.
* **Offline behavior** — if the server is unreachable, telemetry is buffered at `~/.observal/telemetry_buffer.db` and flushed later. Flush manually with `observal ops sync`. Check the buffer size with `observal auth status`.

## Channel 2 — IDE hooks

Events sent per lifecycle event:

* `SessionStart` / `Stop` — session boundaries
* `UserPromptSubmit` — the user's prompt
* `PreToolUse` / `PostToolUse` — tool calls (Claude Code has these even without the shim, for tools that don't go through MCP)
* `SubagentStop` — Claude Code sub-agent lifecycle
* `Notification` — IDE notifications

Full schema and handler types: [Hooks specification](../reference/hooks-spec.md).

`observal pull` and `observal scan --home` wire hooks into the appropriate file:

* Claude Code: `~/.claude/settings.json`
* Kiro: agent JSON at `.kiro/agents/<name>.json` or `~/.kiro/agents/<name>.json`

## The OTEL Collector

`observal-otel-collector` (port 4317 gRPC, 4318 HTTP) accepts native OpenTelemetry traces and logs. It is used by:

* **Claude Code** — via `OTEL_EXPORTER_OTLP_ENDPOINT`. Claude Code exports native OTLP traces and logs including token counts and cost.
* **Any OTEL-instrumented tool** — anything that speaks OTLP can send to port 4317/4318.

Kiro does not yet export OTLP natively ([kirodotdev/Kiro#6319](https://github.com/kirodotdev/Kiro/issues/6319)), so Kiro telemetry flows through hooks instead of the collector.

Collector config lives at `otel-collector-config.yaml` at the repo root. It forwards traces to the Observal API's OTLP ingest path.

## High-volume tuning

At high telemetry volume, three hot spots:

1. **ClickHouse writes.** Observal batches inserts already. If you see ingest backpressure, bump `CLICKHOUSE_*` memory limits, consider external ClickHouse.
2. **OTEL collector memory.** Default is 256 MB. Raise if you see drop metrics in the collector logs.
3. **Redis queue.** `arq` uses Redis for the eval job queue. Redis at 256 MB is fine for most deployments; bump for heavier eval workloads.

## Alert on degraded ingest

Create an alert rule that fires when telemetry volume drops unexpectedly:

* "Spans/minute < 10% of last 24h average for 15 minutes"

Configure in the web UI at `/settings/alerts` or via `POST /api/v1/alerts`.

## Legacy event endpoints

`/api/v1/telemetry/events` is retained for backward compatibility with earlier hook formats. New integrations should use `/api/v1/telemetry/ingest` (batch traces + spans + scores) and `/api/v1/otel/hooks` (hook events).

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
