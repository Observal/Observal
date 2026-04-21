# Data model

Everything Observal stores in ClickHouse fits into four shapes: **traces**, **spans**, **sessions**, and **scores**. This page is the authoritative reference for the fields each carries.

Schemas live in `observal-server/schemas/telemetry.py`.

## Trace

A top-level operation. Most traces are a single agent turn — one user prompt through to the agent's response — but they can be anything logically at the top of a tree.

| Field | Type | Notes |
| --- | --- | --- |
| `trace_id` | UUID | Primary identifier |
| `parent_trace_id` | UUID | Nullable — only set for trace-of-traces hierarchies |
| `trace_type` | string | Classifier: `agent`, `mcp`, `eval`, etc. |
| `agent_id` | UUID | Nullable; set when the trace belongs to a registered agent |
| `session_id` | UUID | Nullable; groups traces from the same IDE session |
| `mcp_id` | UUID | Nullable; set when the trace is bound to one MCP server |
| `start_time` | timestamp | Trace start |
| `end_time` | timestamp | Trace end |
| `input` | JSON | Input payload (user prompt, or input to the top-level call) |
| `output` | JSON | Final output |
| `metadata` | JSON | Free-form key/value — IDE, model, user, tags |
| `tags` | array of strings | Searchable tags |

## Span

A sub-operation within a trace. Typically one MCP tool call. Spans can nest.

| Field | Type | Notes |
| --- | --- | --- |
| `span_id` | UUID | Primary identifier |
| `trace_id` | UUID | Parent trace |
| `parent_span_id` | UUID | Nullable — set for nested spans |
| `type` | string | `tool_call`, `llm_call`, `retrieval`, `hook`, etc. |
| `name` | string | Human-readable span name |
| `method` | string | For tool calls: the tool or method name |
| `input` | JSON | Input payload |
| `output` | JSON | Output payload |
| `error` | JSON | Nullable; error details if the span failed |
| `latency_ms` | int | Wall-clock duration |
| `status` | string | `ok`, `error`, `cancelled`, `timeout` |
| `token_counts` | JSON | `{input, output, cache_read, cache_write}` when available |
| `cost` | float | USD, when the IDE exposes it |
| `retry_count` | int | Number of retries the span went through |

Spans are the unit that most of the UI and eval engine operate on.

## Session

Not a separate table — a logical grouping identified by `session_id` in `traces.metadata`. One IDE session (a user opening Claude Code, working for 30 minutes, closing it) produces many traces that all share the same `session_id`.

The web UI surfaces sessions as the grouping in the trace list.

## Score

The output of evaluation. Attached to a trace or a specific span.

| Field | Type | Notes |
| --- | --- | --- |
| `score_id` | UUID | Primary identifier |
| `trace_id` | UUID | The trace being scored |
| `span_id` | UUID | Nullable; set if the score targets one span |
| `name` | string | Dimension name: `goal_completion`, `tool_efficiency`, `factual_grounding`, etc. |
| `source` | string | `eval_engine`, `user_feedback`, `canary_detector`, etc. |
| `value` | float | Numeric score (0–10 on standard dimensions) |
| `string_value` | string | Nullable; for non-numeric scores |
| `comment` | string | Free-form explanation from the judge |
| `metadata` | JSON | Source-specific extras (model name, prompt, canary type) |
| `timestamp` | timestamp | When the score was recorded |

Multiple scores per trace are the norm — one per dimension, plus any user feedback and canary detections.

## Storage

* **Postgres** holds the *registry* — users, agents, MCP configs, scorecards (summaries).
* **ClickHouse** holds *every* trace, span, and individual dimension score.

ClickHouse tables use `ReplacingMergeTree` with `is_deleted` + `event_ts` for soft-delete and deduplication. Queries should use `FINAL` to force dedup; the API does this for you. Details: [Self-Hosting → Databases](../self-hosting/databases.md).

## IDs and aliases

IDs are UUIDs everywhere. Wherever `<id-or-name>` is accepted, the CLI also accepts:

* The object's **name** (`github-mcp`, `code-reviewer`)
* A **row number** from the last `list` command (`1`, `2`, …)
* An **alias** you defined via `observal config alias` (`@my-mcp`)

Aliases are client-side only — not shared with the server.

## Schema evolution

ClickHouse tables are auto-created with `CREATE TABLE IF NOT EXISTS` on API startup. New columns are added via the same path. Breaking changes would require an explicit migration and are called out in the CHANGELOG when they happen.

Postgres tables migrate through Alembic — see `observal-server/alembic/versions/`.

## Related

* [Evaluation engine](evaluation.md) — what produces scores
* [Shim vs proxy](shim-vs-proxy.md) — what produces spans
* [Self-Hosting → Databases](../self-hosting/databases.md) — where all of this lives
