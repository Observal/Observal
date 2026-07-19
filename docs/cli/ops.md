<!-- SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# observal ops

Operational and observability commands for dashboards, sessions, events, metrics, and feedback.

## Subcommands

| Command | Description |
| --- | --- |
| [`ops metrics`](#observal-ops-metrics) | Metrics for one MCP or agent |
| [`ops top`](#observal-ops-top) | Top items by usage |
| [`ops traces`](#observal-ops-traces) | List recent traces |
| [`ops spans`](#observal-ops-spans) | Detailed events for one session |
| [`ops rate`](#observal-ops-rate) | Rate an MCP or agent (1–5 stars) |
| [`ops feedback`](#observal-ops-feedback) | View feedback for an MCP or agent |
| [`ops telemetry status`](#observal-ops-telemetry-status) | Telemetry pipeline status |
| [`ops telemetry test`](#observal-ops-telemetry-test) | Send a test telemetry event |

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

List recent sessions. By default shows a summary table. Use `--turn` to unfold prompts and tool calls, or `--span` for full event detail.

### Synopsis

```bash
observal ops traces [--platform <harness>] [--days N] [--limit N] [--turn] [--span] [--output table|json]
```

### Examples

```bash
observal ops traces --limit 20
observal ops traces --turn --limit 5
observal ops traces --span --limit 3
observal ops traces --platform kiro --days 7
observal ops traces --output json | jq
```

---

## `observal ops spans`

Inspect detailed parsed events inside a session. The command name is retained as part of the CLI trace-view vocabulary.

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
# Test event sent. View at http://localhost/traces
```

## Related

* [Use Cases → Observe MCP traffic](../use-cases/observe-mcp-traffic.md)
* [Use Cases → Debug agent failures](../use-cases/debug-agent-failures.md)
