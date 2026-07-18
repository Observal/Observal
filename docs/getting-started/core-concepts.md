<!-- SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Core Concepts

The vocabulary you need to be productive with Observal. Read once; every other page in these docs assumes you know these terms.

## The big picture

```mermaid
flowchart TB
    harness["AI coding harness: Claude Code, Kiro, Cursor, Pi"]
    sessions["Harness session sources - JSONL or native message APIs"]
    hooks["harness hooks - session + lifecycle events"]
    shim["observal-shim / proxy - MCP request + response capture"]
    mcp[MCP servers]
    cli["observal CLI - reconcile + push"]
    api[Observal API]
    pg["PostgreSQL - registry + users + review state"]
    ch["ClickHouse - traces + spans + session events"]

    harness --> sessions
    harness --> hooks
    harness <--> shim
    shim <--> mcp
    hooks --> api
    shim --> api
    sessions --> cli
    cli --> api
    api --> pg
    api --> ch
```

Observal collects agent activity through three complementary paths:

* **Session capture** reads harness JSONL transcripts or native message APIs and delivers indexed raw records for server-side parsing.
* **harness hooks** capture lifecycle events such as session start, user prompt, tool use, stop, and notifications when the harness exposes them.
* **MCP shims and proxies** capture MCP requests and responses without modifying the traffic.

Two data stores, two concerns:

* **Postgres** holds the *registry*: users, accounts, agent configs, MCP listings, review state, and alert rules. Transactional, relational.
* **ClickHouse** holds the *telemetry*: traces, spans, and session events. High-volume, time-series, fast analytical queries.

## The registry

Six component types. Agents bundle the other five.

| Type | What it is |
| --- | --- |
| **Agent** | A complete, installable AI agent. Bundles MCP servers, skills, hooks, prompts, and sandboxes into one YAML. |
| **MCP Server** | A [Model Context Protocol](https://modelcontextprotocol.io/) server, the tools an agent can call. |
| **Skill** | A portable instruction package agents load on demand. |
| **Hook** | A lifecycle callback that runs on session start, tool use, session end, etc. |
| **Prompt** | A named, parameterized prompt template with variable substitution. |
| **Sandbox** | A Docker execution environment for running code the agent generates. |

Anyone can publish. Admin review controls what appears in the public listing, but your own items are usable immediately without approval.

## Telemetry: traces, spans, sessions

### Span

A single operation. Typically one MCP tool call or lifecycle event. Includes the name, input/output metadata, latency, status, and any error. Spans can nest via `parent_span_id`.

### Trace

A top-level operation that can contain many spans. Most traces are a single agent turn (one user prompt → the agent's response). Identified by `trace_id`.

### Session

A logical grouping of related traces, typically one harness session or one user task. Identified by `session_id` in trace metadata. A long Claude Code session produces many traces that all share a `session_id`.

## The shim and the proxy

Observal intercepts MCP traffic without modifying it. Two flavors:

| Component | Transport | When it's used |
| --- | --- | --- |
| `observal-shim` | stdio | The default for most MCP servers. Wraps the MCP server process and forwards stdin/stdout. |
| `observal-proxy` | HTTP / SSE / streamable-HTTP | Used when an MCP server speaks HTTP instead of stdio. |

You rarely call either one directly. `observal doctor patch --shim` (or `--all`) rewrites your harness config to route MCP servers through the appropriate one.

Interception is **transparent**: nothing is changed on the wire, and an unreachable Observal server does not block the MCP tool call. Reliable session delivery is handled separately by the harness exporter.

## Durable session outboxes

Session traces use **eventual at-least-once delivery with effectively-once storage**. Python exporters persist records in `~/.observal/telemetry_buffer.db` before upload. OpenCode and Pi use native durable outboxes under `~/.observal/`. Failed attempts remain pending across process restarts. A batch is removed, and its source line advances, only after the server acknowledges a contiguous checkpoint that covers it.

The server identifies a source record by project, user, harness, session ID, and source line index. Retries and overlapping batches therefore converge to one canonical record. If local cursor state is missing, corrupt, or stale, recovery reads the authenticated server checkpoint before resuming. Finalization performs a stable-file pass and SHA-256 audit; a mismatch rewinds to the affected range for idempotent replay. Full-history hashing does not run on normal hook uploads.

The guarantee begins when Observal observes and durably spools a record. It cannot recover a source record that the harness deletes before any installed hook or extension runs.

Check Python exporter outbox status:

```bash
observal auth status
observal ops telemetry status
```

Drain happens automatically on the next exporter wake-up after the server is reachable.

## Deployment mode

SSO-only access is controlled by `deployment.sso_only`:

| Mode | Self-registration | Bootstrap | Auth |
| --- | --- | --- | --- |
| `deployment.sso_only=false` (default) | Yes | Yes (fresh server creates admin on first login) | Email + password or API key |
| `deployment.sso_only=true` | No | No | SSO only |

You pick this when you set up the server. Most self-hosters use `deployment.sso_only=false`.

## Next

→ [Use Cases](../use-cases/README.md) to see what you can actually do with all of this.
