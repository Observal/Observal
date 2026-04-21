# observal ops

Operational and observability commands — dashboards, traces, spans, metrics, feedback.

## Subcommands

| Command | Description |
| --- | --- |
| [`ops overview`](#observal-ops-overview) | Dashboard summary stats |
| [`ops metrics`](#observal-ops-metrics) | Metrics for one MCP or agent |
| [`ops top`](#observal-ops-top) | Top items by usage |
| [`ops traces`](#observal-ops-traces) | List recent traces |
| [`ops spans`](#observal-ops-spans) | Spans for one trace |
| [`ops rate`](#observal-ops-rate) | Rate an MCP or agent (1–5 stars) |
| [`ops feedback`](#observal-ops-feedback) | View feedback for an MCP or agent |
| [`ops sync`](#observal-ops-sync) | Flush locally buffered telemetry |
| [`ops telemetry status`](#observal-ops-telemetry-status) | Telemetry pipeline status |
| [`ops telemetry test`](#observal-ops-telemetry-test) | Send a test telemetry event |

---

## `observal ops overview`

Summary stats across your server — total traces, active agents, error rate, top MCPs.

```bash
observal ops overview
```

---

## `observal ops metrics`

Metrics for a single MCP or agent. Pair with `--watch` for live updates.

### Synopsis

```bash
observal ops metrics <id-or-name> [--type mcp|agent] [--watch] [--window <duration>]
```

### Example

```bash
observal ops metrics github-mcp --type mcp --watch
observal ops metrics @reviewer --type agent --window 7d
```

---

## `observal ops top`

Ranking dashboard. By default shows MCPs; pass `--type agent` for agents.

```bash
observal ops top
observal ops top --type agent --limit 20
```

---

## `observal ops traces`

List recent traces. Filter by agent, MCP, or type.

### Synopsis

```bash
observal ops traces [--type <type>] [--agent <id>] [--mcp <id>] [--limit N] [--session <id>] [--output table|json]
```

### Examples

```bash
observal ops traces --limit 20
observal ops traces --agent code-reviewer --limit 50
observal ops traces --mcp github-mcp
observal ops traces --session <session-id>
observal ops traces --output json | jq
```

---

## `observal ops spans`

Walk the spans inside a trace. Output is hierarchical (parent → children).

```bash
observal ops spans <trace-id>
observal ops spans <trace-id> --output json
```

Each line shows name, duration, status, and any error. See [Debug agent failures](../use-cases/debug-agent-failures.md) for a worked example.

---

## `observal ops rate`

Rate an MCP server or agent on a 1–5 star scale, optionally with a comment.

```bash
observal ops rate <id-or-name> --stars 5 [--type mcp|agent] [--comment "saved me hours"]
```

---

## `observal ops feedback`

View aggregate feedback (average stars, comments).

```bash
observal ops feedback <id-or-name> [--type mcp|agent]
```

---

## `observal ops sync`

Flush the local telemetry buffer. When the Observal server is unreachable, hook events accumulate in `~/.observal/telemetry_buffer.db`. This command sends them in batches.

```bash
observal ops sync
```

Auto-flush also happens on the next successful CLI invocation — you rarely need to run this manually.

---

## `observal ops telemetry status`

Telemetry pipeline health and local buffer stats.

```bash
observal ops telemetry status
# Telemetry:   OK
# Local buffer: 0 events pending
# Last flush:   12 seconds ago
```

---

## `observal ops telemetry test`

Send a test telemetry event. Useful for verifying instrumentation end-to-end.

```bash
observal ops telemetry test
# Test event sent — view at http://localhost:3000/traces
```

## Related

* [Use Cases → Observe MCP traffic](../use-cases/observe-mcp-traffic.md)
* [Use Cases → Debug agent failures](../use-cases/debug-agent-failures.md)
* [Data model](../concepts/data-model.md)
