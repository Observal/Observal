# Core Concepts

The vocabulary you need to be productive with Observal. Read once — every other page in these docs assumes you know these terms.

## The big picture

```
┌─────────────┐     ┌───────────────┐     ┌──────────────┐
│   Your IDE  │ ◄─► │ observal-shim │ ◄─► │  MCP Server  │
└─────────────┘     └───────┬───────┘     └──────────────┘
                            │
                            ▼  fire-and-forget
                   ┌────────────────┐
                   │   Observal API │
                   └────────┬───────┘
                            │
              ┌─────────────┴──────────────┐
              ▼                            ▼
      ┌──────────────┐             ┌───────────────┐
      │  PostgreSQL  │             │   ClickHouse  │
      │ (registry,   │             │ (traces,      │
      │  users, RBAC)│             │  spans, scores)│
      └──────────────┘             └───────────────┘
```

Two data stores, two concerns:

* **Postgres** holds the *registry* — users, accounts, agent configs, MCP listings, review state, alert rules. Transactional, relational.
* **ClickHouse** holds the *telemetry* — traces, spans, and eval scores. High-volume, time-series, fast analytical queries.

## The registry

Six component types. Agents bundle the other five.

| Type | What it is |
| --- | --- |
| **Agent** | A complete, installable AI agent. Bundles MCP servers, skills, hooks, prompts, and sandboxes into one YAML. |
| **MCP Server** | A [Model Context Protocol](https://modelcontextprotocol.io/) server — the tools an agent can call. |
| **Skill** | A portable instruction package agents load on demand. |
| **Hook** | A lifecycle callback — runs on session start, tool use, session end, etc. |
| **Prompt** | A named, parameterized prompt template with variable substitution. |
| **Sandbox** | A Docker execution environment for running code the agent generates. |

Anyone can publish. Admin review controls what appears in the public listing, but your own items are usable immediately without approval.

## Telemetry: traces, spans, sessions, scores

### Span

A single operation. Typically one MCP tool call — includes the tool name, input, output, latency, status, and any error. Spans can nest via `parent_span_id`.

### Trace

A top-level operation that can contain many spans. Most traces are a single agent turn (one user prompt → the agent's response). Identified by `trace_id`.

### Session

A logical grouping of related traces — typically one IDE session or one user task. Identified by `session_id` in trace metadata. A long Claude Code session produces many traces that all share a `session_id`.

### Score

An evaluation result attached to a trace or span. Produced by the eval engine or added manually. Each score has a dimension (goal completion, tool efficiency, etc.), a numeric value, and an optional comment.

## The shim and the proxy

Observal intercepts MCP traffic without modifying it. Two flavors:

| Component | Transport | When it's used |
| --- | --- | --- |
| `observal-shim` | stdio | The default for most MCP servers. Wraps the MCP server process and forwards stdin/stdout. |
| `observal-proxy` | HTTP / SSE / streamable-HTTP | Used when an MCP server speaks HTTP instead of stdio. |

You rarely call either one directly. `observal scan` rewrites your IDE config to route MCP servers through the appropriate one.

Interception is **transparent**: nothing is changed on the wire. If Observal is unreachable, the tool call still succeeds — the telemetry is queued locally (see [Telemetry buffer](#telemetry-buffer) below) and flushed later.

For more on this, see [Shim vs proxy](../concepts/shim-vs-proxy.md).

## Hooks (a different kind)

Confusingly, "hook" means two things in this ecosystem:

1. **Registry hooks** — packaged, reusable hook definitions you publish and install via `observal registry hook`.
2. **IDE hooks** — the underlying lifecycle mechanism your IDE exposes (`PreToolUse`, `PostToolUse`, `SessionStart`, `Stop`, etc.). Observal's installer wires hooks into `~/.claude/settings.json` for Claude Code and into agent JSON for Kiro.

Both use the same event vocabulary (`PreToolUse`, `PostToolUse`, `SessionStart`, `Stop`, `SubagentStop`, `UserPromptSubmit`, `Notification`). See the [Hooks spec](../reference/hooks-spec.md) for the full schema.

## Telemetry buffer

When the Observal server is unreachable, the CLI and shim don't drop telemetry. Events are queued in a local SQLite buffer at `~/.observal/telemetry_buffer.db` and flushed the next time the server is reachable.

Check the buffer:

```bash
observal auth status
observal ops telemetry status
```

Flush manually:

```bash
observal ops sync
```

## Deployment mode

Two server-side modes, controlled by the `DEPLOYMENT_MODE` environment variable:

| Mode | Self-registration | Bootstrap | Auth |
| --- | --- | --- | --- |
| `local` (default) | Yes | Yes (fresh server creates admin on first login) | Email + password or API key |
| `enterprise` | No | No | SSO / OIDC only; SCIM provisioning |

You pick this when you set up the server. Most self-hosters use `local`.

## Evaluation: the six dimensions

The eval engine scores each session on six dimensions:

| Dimension | Scorer |
| --- | --- |
| Goal completion | LLM-as-judge |
| Tool call efficiency | Rule-based (duplicates, retries, unused results) |
| Tool call failures | Rule-based (error rate) |
| Factual grounding | LLM-as-judge (claims vs tool output) |
| Thought process | LLM-as-judge |
| Adversarial robustness | Rule-based (injection detection, canary parroting) |

Dimensions are weighted, penalties applied, and mapped to a letter grade (A–F). Weights and penalties are tunable via `observal admin weights` and `observal admin penalties`. Deep dive: [Evaluation engine](../concepts/evaluation.md).

## Next

→ [Use Cases](../use-cases/README.md) to see what you can actually do with all of this.
