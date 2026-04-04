# Telemetry Overhaul: Design Document

## Vision

Observal is a universal observability layer for the entire AI agent stack. It captures traces, spans, and metrics from MCP servers, multi-agent frameworks, memory systems, sandbox execution, knowledge graphs, and individual agent reasoning: all without requiring code changes to any of these systems.

When a user installs any tool via Observal, a lightweight shim wraps the process and silently captures all traffic. For HTTP-based services, an HTTP proxy does the same. Neither the IDE, the agent, nor the tool knows Observal is there.

All captured data flows back to the org's Observal server for storage, dashboards, evals, and scoring.

---

## Architecture

### Stdio Transport (most MCP servers)

```
IDE / Agent Framework
    ↕ stdio (JSON-RPC)
observal-shim (transparent wrapper)
    ├── passes all messages through untouched
    ├── async fire-and-forget copies to Observal server
    ↕ stdio (JSON-RPC)
Actual MCP Server / Tool (unchanged, unaware)
```

### HTTP Transport (SSE / Streamable HTTP)

```
IDE / Agent Framework
    ↕ HTTP
observal-proxy (HTTP reverse proxy)
    ├── forwards all requests/responses untouched
    ├── async copies to Observal server
    ↕ HTTP
Actual MCP Server / Service (unchanged, unaware)
```

### Multi-Agent / Framework-Level

```
Agent Framework (CrewAI, LangGraph, etc.)
    ↕ inter-agent messages, tool calls, memory ops
observal-shim wrapping each tool/MCP
    ├── captures per-tool spans
    ├── parent trace groups all spans for one agent turn
    ↕
Individual MCP Servers / Tools / Memory / Sandbox
```

Each MCP server gets its own shim. An agent-level parent trace groups all MCP traces for one agent interaction via a shared `OBSERVAL_TRACE_ID` env var.

---

## Shim & Proxy

### Shim (stdio)

Location: `observal_cli/shim.py`, entry point: `observal-shim`

Behavior:
- Parse args: extract `--mcp-id` and everything after `--` as the real command
- Read `OBSERVAL_SERVER`, `OBSERVAL_KEY`, `OBSERVAL_TRACE_ID` (optional parent), `OBSERVAL_AGENT_ID` (optional) from env
- Spawn real process with `subprocess.Popen(stdin=PIPE, stdout=PIPE, stderr=PIPE)`
- Two async reader loops: IDE→MCP and MCP→IDE
- Parse JSON-RPC messages, pair requests with responses by `id`
- Buffer spans, flush to server every 5s or 50 spans (whichever first)
- On child exit, flush remaining buffer, send trace end_time
- Exit with same exit code as child

### Proxy (HTTP)

Location: `observal_cli/proxy.py`, entry point: `observal-proxy`

Behavior:
- Starts a local HTTP server on a random port
- Forwards all requests to the real MCP server URL
- Captures request/response bodies
- Same async fire-and-forget telemetry shipping as the shim
- Install config points IDE at `http://localhost:{port}` instead of the real URL

### Resilience (both)

- All telemetry sending is fire-and-forget with 5s timeout
- Failed sends silently dropped: never retry, never block
- If `OBSERVAL_SERVER` not set, passes through without capturing
- Child process stderr forwarded to own stderr
- MCP works identically whether Observal server is up or down

### Upgrade

`observal upgrade` updates the CLI package (and with it the shim/proxy binaries).

---

## Install Config Generation

### Before (current)

```json
{
  "mcpServers": {
    "my-mcp": {
      "command": "python",
      "args": ["-m", "my_mcp"]
    }
  }
}
```

### After: Stdio MCP

```json
{
  "mcpServers": {
    "my-mcp": {
      "command": "observal-shim",
      "args": ["--mcp-id", "abc123", "--", "python", "-m", "my_mcp"],
      "env": {
        "OBSERVAL_SERVER": "https://observal.internal:8000",
        "OBSERVAL_KEY": "user-api-key"
      }
    }
  }
}
```

### After: HTTP MCP

```json
{
  "mcpServers": {
    "my-mcp": {
      "url": "http://localhost:{proxy_port}",
      "env": {
        "OBSERVAL_SERVER": "https://observal.internal:8000",
        "OBSERVAL_KEY": "user-api-key"
      }
    }
  }
}
```

### After: Agent (bundles multiple MCPs)

Each linked MCP gets its own shim. All share a common `OBSERVAL_AGENT_ID`:

```json
{
  "mcpServers": {
    "mcp-a": {
      "command": "observal-shim",
      "args": ["--mcp-id", "aaa", "--", "python", "-m", "mcp_a"],
      "env": {
        "OBSERVAL_SERVER": "https://observal.internal:8000",
        "OBSERVAL_KEY": "user-api-key",
        "OBSERVAL_AGENT_ID": "agent-xyz"
      }
    },
    "mcp-b": {
      "command": "observal-shim",
      "args": ["--mcp-id", "bbb", "--", "npx", "mcp-b"],
      "env": {
        "OBSERVAL_SERVER": "https://observal.internal:8000",
        "OBSERVAL_KEY": "user-api-key",
        "OBSERVAL_AGENT_ID": "agent-xyz"
      }
    }
  }
}
```

---

## ClickHouse Schema

### `traces`

One row per session (shim start → shim exit) or per agent interaction turn.

```sql
CREATE TABLE traces (
    trace_id        String,
    parent_trace_id Nullable(String),          -- for agent-level grouping
    mcp_id          Nullable(String),
    agent_id        Nullable(String),
    user_id         String,
    session_id      Nullable(String),
    ide             LowCardinality(String),
    environment     LowCardinality(String) DEFAULT 'default',

   -- Timing
    start_time      DateTime64(3),
    end_time        Nullable(DateTime64(3)),

   -- Classification
    trace_type      LowCardinality(String) DEFAULT 'mcp',  -- 'mcp', 'agent', 'memory', 'sandbox', 'graph', 'framework'
    name            String DEFAULT '',
    metadata        Map(LowCardinality(String), String),
    tags            Array(String),

   -- Input/output summary (optional, for top-level trace context)
    input           Nullable(String) CODEC(ZSTD(3)),
    output          Nullable(String) CODEC(ZSTD(3)),

    created_at      DateTime64(3) DEFAULT now(),
    event_ts        DateTime64(3),
    is_deleted      UInt8 DEFAULT 0,

    INDEX idx_trace_id trace_id TYPE bloom_filter(0.001) GRANULARITY 1,
    INDEX idx_parent_trace_id parent_trace_id TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_mcp_id mcp_id TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_agent_id agent_id TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_user_id user_id TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_session_id session_id TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_trace_type trace_type TYPE bloom_filter(0.01) GRANULARITY 1
)
ENGINE = ReplacingMergeTree(event_ts, is_deleted)
PARTITION BY toYYYYMM(start_time)
PRIMARY KEY (user_id, toDate(start_time))
ORDER BY (user_id, toDate(start_time), trace_id);
```

### `spans`

One row per operation within a trace. Covers tool calls, memory retrievals, graph traversals, sandbox executions, agent handoffs: everything.

```sql
CREATE TABLE spans (
    span_id                 String,
    trace_id                String,
    parent_span_id          Nullable(String),
    mcp_id                  Nullable(String),
    agent_id                Nullable(String),
    user_id                 String,

   -- Classification
    type                    LowCardinality(String),
   -- MCP:       'tool_call', 'resource_read', 'prompt_get', 'initialize', 'tool_list', 'ping'
   -- Agent:     'agent_turn', 'agent_handoff', 'reasoning_step', 'fallback'
   -- Memory:    'memory_store', 'memory_retrieve', 'memory_consolidate'
   -- Sandbox:   'sandbox_exec', 'sandbox_retry'
   -- Graph:     'graph_traverse', 'graph_query'
   -- Framework: 'orchestration', 'delegation'
   -- Generic:   'other'

    name                    String,            -- tool name, agent name, memory key, etc.
    method                  String DEFAULT '', -- raw protocol method (e.g. 'tools/call')

   -- Full payloads
    input                   Nullable(String) CODEC(ZSTD(3)),
    output                  Nullable(String) CODEC(ZSTD(3)),
    error                   Nullable(String) CODEC(ZSTD(3)),

   -- Timing
    start_time              DateTime64(3),
    end_time                Nullable(DateTime64(3)),
    latency_ms              Nullable(UInt32),

   -- Status
    status                  LowCardinality(String) DEFAULT 'success', -- 'success', 'error', 'timeout', 'cancelled'
    level                   LowCardinality(String) DEFAULT 'DEFAULT',

   -- Resource usage (for sandbox, LLM calls)
    token_count_input       Nullable(UInt32),
    token_count_output      Nullable(UInt32),
    token_count_total       Nullable(UInt32),
    cost                    Nullable(Float64),
    cpu_ms                  Nullable(UInt32),
    memory_mb               Nullable(Float32),

   -- Graph-specific
    hop_count               Nullable(UInt8),
    entities_retrieved      Nullable(UInt16),
    relationships_used      Nullable(UInt16),

   -- Agent-specific
    retry_count             Nullable(UInt8),
    tools_available         Nullable(UInt16),   -- how many tools were available at decision time
    tool_schema_valid       Nullable(UInt8),    -- 1 = args matched schema, 0 = hallucinated params

   -- Context
    ide                     LowCardinality(String) DEFAULT '',
    environment             LowCardinality(String) DEFAULT 'default',
    metadata                Map(LowCardinality(String), String),

    created_at              DateTime64(3) DEFAULT now(),
    event_ts                DateTime64(3),
    is_deleted              UInt8 DEFAULT 0,

    INDEX idx_span_id span_id TYPE bloom_filter(0.001) GRANULARITY 1,
    INDEX idx_trace_id trace_id TYPE bloom_filter(0.001) GRANULARITY 1,
    INDEX idx_name name TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_type type TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_status status TYPE bloom_filter(0.01) GRANULARITY 1
)
ENGINE = ReplacingMergeTree(event_ts, is_deleted)
PARTITION BY toYYYYMM(start_time)
PRIMARY KEY (user_id, type, toDate(start_time))
ORDER BY (user_id, type, toDate(start_time), span_id);
```

### `scores`

Unified scoring. All quality signals in one table.

```sql
CREATE TABLE scores (
    score_id        String,
    trace_id        Nullable(String),
    span_id         Nullable(String),
    mcp_id          Nullable(String),
    agent_id        Nullable(String),
    user_id         String,

   -- Score identity
    name            String,
    source          LowCardinality(String),    -- 'api', 'eval', 'annotation', 'computed'
    data_type       LowCardinality(String),    -- 'numeric', 'boolean', 'categorical'

   -- Score value
    value           Float64,
    string_value    Nullable(String),
    comment         Nullable(String) CODEC(ZSTD(1)),

   -- Eval linkage
    eval_template_id Nullable(String),
    eval_config_id  Nullable(String),
    eval_run_id     Nullable(String),

   -- Context
    environment     LowCardinality(String) DEFAULT 'default',
    metadata        Map(LowCardinality(String), String),

    timestamp       DateTime64(3),
    created_at      DateTime64(3) DEFAULT now(),
    event_ts        DateTime64(3),
    is_deleted      UInt8 DEFAULT 0,

    INDEX idx_score_id score_id TYPE bloom_filter(0.001) GRANULARITY 1,
    INDEX idx_trace_id trace_id TYPE bloom_filter(0.001) GRANULARITY 1,
    INDEX idx_span_id span_id TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_name name TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_source source TYPE bloom_filter(0.01) GRANULARITY 1
)
ENGINE = ReplacingMergeTree(event_ts, is_deleted)
PARTITION BY toYYYYMM(timestamp)
PRIMARY KEY (user_id, toDate(timestamp), name)
ORDER BY (user_id, toDate(timestamp), name, score_id);
```

### Data Retention

No automatic TTL. Data is retained indefinitely. Only an admin can trigger deletion via explicit API call or enterprise setting.

---

## Metrics Catalog

Everything below is derived from the traces, spans, and scores tables. No additional storage needed: these are computed at query time or via materialized views.

### 1. MCP (Model Context Protocol)

| Metric | Source | Computation |
|--------|--------|-------------|
| Tool Discovery Latency | spans where `type = 'tool_list'` | `latency_ms` |
| Tool Call Latency (p50/p90/p99) | spans where `type = 'tool_call'` | percentiles on `latency_ms` |
| Transport Failures | spans where `status = 'error'` | count, group by `error` |
| Timeout Rate | spans where `status = 'timeout'` | count / total |
| Schema Compliance | spans where `type = 'tool_call'` | `tool_schema_valid` = 1 ratio |
| Error Rate by Tool | spans where `type = 'tool_call'` | count(status='error') / count(*) group by `name` |
| Calls per Session | spans per `trace_id` | count group by trace_id |

### 2. Multi-Agent Frameworks (CrewAI, LangGraph, etc.)

| Metric | Source | Computation |
|--------|--------|-------------|
| Handoff Latency | spans where `type = 'agent_handoff'` | `latency_ms` or gap between consecutive agent_turn spans |
| Orchestration Overhead | spans where `type = 'orchestration'` or `'delegation'` | sum(`token_count_total`) vs total tokens in trace |
| Loop Detection | spans within a trace | detect repeated (name, input) pairs with no output change |
| Agent Turn Count | spans where `type = 'agent_turn'` per trace | count |
| Delegation Ratio | orchestration tokens / total tokens per trace | ratio |

### 3. Memory Systems

| Metric | Source | Computation |
|--------|--------|-------------|
| Recall Accuracy | eval score `name = 'recall_accuracy'` | LLM-as-judge on memory_retrieve spans |
| Context Window Saturation | spans where `type = 'memory_retrieve'` | `token_count_total` / context window size |
| Memory Consolidation Efficiency | eval score `name = 'information_loss'` | LLM-as-judge comparing pre/post consolidation |
| Retrieval Latency | spans where `type = 'memory_retrieve'` | `latency_ms` |
| Store Latency | spans where `type = 'memory_store'` | `latency_ms` |

### 4. Sandbox Execution

| Metric | Source | Computation |
|--------|--------|-------------|
| Execution Success Rate | spans where `type = 'sandbox_exec'` | count(status='success') / count(*) |
| Self-Correction Cycles | spans where `type = 'sandbox_retry'` per trace | count |
| Resource Consumption | spans where `type = 'sandbox_exec'` | `cpu_ms`, `memory_mb` |
| Security Violations | spans where `type = 'sandbox_exec'` and metadata has `security_violation` | count |
| Avg Retries to Success | sandbox_retry spans before a successful sandbox_exec | avg count |

### 5. GraphRAG (Knowledge Graphs)

| Metric | Source | Computation |
|--------|--------|-------------|
| Hop Count / Traversal Depth | spans where `type = 'graph_traverse'` | `hop_count` |
| Relationship Density | spans where `type = 'graph_traverse'` | `relationships_used` / `entities_retrieved` |
| Faithfulness to Graph | eval score `name = 'graph_faithfulness'` | LLM-as-judge comparing output vs graph triples |
| Query Latency | spans where `type = 'graph_query'` | `latency_ms` |
| Entities per Query | spans where `type = 'graph_traverse'` | `entities_retrieved` |

### 6. Skills & Tool-Calling

| Metric | Source | Computation |
|--------|--------|-------------|
| Selection Accuracy | eval score `name = 'tool_selection_accuracy'` | LLM-as-judge: was the right tool picked? |
| Parameter Hallucination Rate | spans where `type = 'tool_call'` | count(tool_schema_valid=0) / count(*) |
| Tool Output Utility | eval score `name = 'tool_output_utility'` | LLM-as-judge: did the output help? |
| Tools Available vs Used | spans per trace | distinct tools used / `tools_available` |
| Unused Tool Ratio | per trace | tools_available - distinct tools used |

### 7. Agents (Individual Logic)

| Metric | Source | Computation |
|--------|--------|-------------|
| Reasoning Trace Clarity | eval score `name = 'reasoning_clarity'` | LLM-as-judge on reasoning_step spans |
| Token Efficiency | spans per trace | sum(token_count_total) for traces where goal was completed |
| Fallback Rate | spans where `type = 'fallback'` | count / total agent_turn count |
| Goal Completion Rate | traces with metadata `goal_completed = true` | count / total |
| Avg Tokens per Goal | traces where goal completed | avg(sum of token_count_total across spans) |
| Max Iterations Hit | traces with metadata `max_iterations_hit = true` | count / total |

---

## Eval-Computed Metrics

Several metrics above require LLM-as-judge evaluation. These map to eval templates:

| Eval Template | Applies To | Dimensions |
|---------------|-----------|------------|
| `recall_accuracy` | memory_retrieve spans | relevance of retrieved memory to current turn |
| `information_loss` | memory_consolidate spans | what was lost in summarization |
| `graph_faithfulness` | graph_traverse spans | does output contradict graph relationships |
| `tool_selection_accuracy` | tool_call spans | was the correct tool chosen |
| `tool_output_utility` | tool_call spans | did the tool output advance the goal |
| `reasoning_clarity` | reasoning_step spans | logical soundness of CoT steps |
| `role_alignment` | agent_turn spans | did the agent stay in its assigned role |
| `schema_compliance` | tool_call spans | do args match the tool's schema |
| `response_quality` | agent_turn spans | overall quality of agent response |
| `hallucination` | agent_turn spans | factual grounding of claims |

These templates are stored in PostgreSQL (eval_templates table) and executed by the eval engine against spans/traces from ClickHouse. Results write back to the `scores` table with `source = 'eval'`.

---

## Ingestion API

### `POST /api/v1/telemetry/ingest`

```python
class SpanIngest(BaseModel):
    span_id: str
    trace_id: str
    parent_span_id: str | None = None
    type: str
    name: str
    method: str = ""
    input: str | None = None
    output: str | None = None
    error: str | None = None
    start_time: str
    end_time: str | None = None
    latency_ms: int | None = None
    status: str = "success"
    ide: str = ""
    metadata: dict[str, str] = {}
    # Resource usage (optional)
    token_count_input: int | None = None
    token_count_output: int | None = None
    token_count_total: int | None = None
    cost: float | None = None
    cpu_ms: int | None = None
    memory_mb: float | None = None
    # Domain-specific (optional)
    hop_count: int | None = None
    entities_retrieved: int | None = None
    relationships_used: int | None = None
    retry_count: int | None = None
    tools_available: int | None = None
    tool_schema_valid: bool | None = None

class TraceIngest(BaseModel):
    trace_id: str
    parent_trace_id: str | None = None
    trace_type: str = "mcp"
    mcp_id: str | None = None
    agent_id: str | None = None
    session_id: str | None = None
    ide: str = ""
    name: str = ""
    start_time: str
    end_time: str | None = None
    input: str | None = None
    output: str | None = None
    metadata: dict[str, str] = {}
    tags: list[str] = []

class ScoreIngest(BaseModel):
    score_id: str
    trace_id: str | None = None
    span_id: str | None = None
    mcp_id: str | None = None
    agent_id: str | None = None
    name: str
    source: str = "api"
    data_type: str = "numeric"
    value: float
    string_value: str | None = None
    comment: str | None = None
    metadata: dict[str, str] = {}

class IngestBatch(BaseModel):
    traces: list[TraceIngest] = []
    spans: list[SpanIngest] = []
    scores: list[ScoreIngest] = []
```

The endpoint:
- Authenticates via `X-API-Key` header
- Sets `user_id` server-side from authenticated user
- Sets `environment` from header or default
- Generates `event_ts` server-side
- Inserts into ClickHouse
- Returns `{"ingested": N, "errors": N}`
- Never fails the batch for individual event errors

### `POST /api/v1/telemetry/events` (existing, backward compat)

Stays as-is. Old format still works.

---

## Shim JSON-RPC Parsing

### Message Classification

```
Has "method" + has "id"     → Request  (IDE → MCP)
Has "result" or "error"     → Response (MCP → IDE)
Has "method" + no "id"      → Notification (log, don't pair)
```

### Span Type Mapping

| JSON-RPC method | Span type | Span name |
|----------------|-----------|-----------|
| `tools/call` | `tool_call` | `params.name` |
| `tools/list` | `tool_list` | `tools/list` |
| `resources/read` | `resource_read` | `params.uri` |
| `resources/list` | `resource_list` | `resources/list` |
| `resources/subscribe` | `resource_subscribe` | `params.uri` |
| `prompts/get` | `prompt_get` | `params.name` |
| `prompts/list` | `prompt_list` | `prompts/list` |
| `initialize` | `initialize` | `initialize` |
| `ping` | `ping` | `ping` |
| `completion/complete` | `completion` | `completion/complete` |
| `logging/setLevel` | `config` | `logging/setLevel` |
| anything else | `other` | method name |

### Schema Compliance Detection

For `tools/call` spans, the shim can optionally:
1. Cache the tool schemas from the most recent `tools/list` response
2. On each `tools/call`, validate `params.arguments` against the cached schema
3. Set `tool_schema_valid = 1` or `0` on the span
4. Set `tools_available` from the cached tool count

This gives you Parameter Hallucination Rate and Selection Accuracy data for free.

---

## Migration Plan

### Phase 1: ClickHouse Schema
- Create `traces`, `spans`, `scores` tables with `project_id` on all
- Existing `mcp_tool_calls` and `agent_interactions` stay untouched
- Update `init_clickhouse()` with new DDL
- Single node, cluster-ready schema (`ReplacingMergeTree`)

### Phase 2: Ingestion Endpoint
- Add `POST /api/v1/telemetry/ingest` with new schemas
- Existing `POST /api/v1/telemetry/events` stays for backward compat

### Phase 3: Shim (stdio)
- Implement `observal_cli/shim.py`
- Register `observal-shim` entry point in `pyproject.toml`
- Shim reads auth from `~/.observal/config.json`, env var override
- Update `config_generator.py` and `agent_config_generator.py` (no key in IDE config)

### Phase 4: Proxy (HTTP)
- Implement `observal_cli/proxy.py`
- Register `observal-proxy` entry point
- Update config generators for HTTP transport MCPs

### Phase 5: Redis + Worker
- Add Redis container to Docker stack
- Implement arq worker for background eval jobs
- Wire up pub/sub for GraphQL subscriptions

### Phase 6: GraphQL Layer
- Add Strawberry GraphQL dependency
- Mount `/api/v1/graphql` on FastAPI app
- Implement types, resolvers, DataLoaders for traces, spans, scores
- Implement aggregated metric resolvers (MCP, agent, memory, sandbox, graph)
- Implement WebSocket subscriptions (backed by Redis pub/sub)
- Kill REST dashboard endpoints

### Phase 7: Dashboard Rewrite
- Replace Next.js with Vite + React
- urql as GraphQL client
- Trace explorer view (span tree, live updates via subscriptions)
- Metrics dashboards per category
- Remove `observal-web` Next.js app entirely

### Phase 8: Eval Engine (LLM-as-judge stopgap)
- Managed eval templates (no custom authoring)
- Background eval jobs via arq worker
- Scores write to unified ClickHouse `scores` table with `source = 'eval'`
- Designed as pluggable backend: swap to ITJ later without changing the interface

### Phase 9: Score Unification
- Migrate existing `feedback` data to ClickHouse `scores` table
- Update feedback endpoints to write to `scores`
- Deprecate old ClickHouse tables and PostgreSQL feedback/scorecard tables

### Phase 10: CLI Updates
- `observal upgrade` command
- Updated `observal metrics` with new metric categories
- `observal traces` / `observal spans` commands for debugging
- Set up `justfile` for monorepo task running

### Phase 11: Testing & CI
- pytest for server unit tests, integration tests, and E2E
- pytest + httpx test client for GraphQL and REST endpoint testing
- pytest E2E: shim → ingestion → ClickHouse → GraphQL query → verify data
- Playwright for critical dashboard flows (login, trace explorer, metrics)
- Kill all bash test scripts
- GitHub Actions with `just` targets and path filters
- `justfile` targets: `test-server`, `test-cli`, `test-e2e`, `test-web`, `test` (all)

### Phase 12: Auth / SSO
- **Keycloak** as identity gateway (Docker container in the stack)
- Keycloak handles all upstream protocols: OIDC, SAML 2.0, LDAP, Kerberos, social login
- Observal only speaks OIDC to Keycloak via **Authlib**
- Enterprise admin configures their IdP in Keycloak admin UI: Observal code never changes
- Web sessions: short-lived JWT (15min) + refresh token rotation in httpOnly cookie
- CLI auth: device code flow (`observal login`) + API key fallback for CI/automation
- Shim auth: reads from CLI config, env var override, ingestion-scoped
- API key scopes: `ingestion`, `read`, `write`, `admin`
- Per-project RBAC: user ↔ project ↔ role in PostgreSQL
- Kill localStorage API key auth in web UI

### Phase 13: TUI Overhaul
- Replace current Typer + Rich CLI with a full interactive TUI (Textual)
- Claude Code / Kiro level polish: not a CLI that prints tables, a real terminal application
- Live trace viewer: watch spans stream in real-time (WebSocket → terminal)
- Interactive dashboards: metrics, charts, sparklines rendered in terminal
- MCP/agent browser: search, filter, install with keyboard navigation
- Eval results viewer: scores, confidence intervals, drill into spans
- Split panes: trace tree on left, span detail on right
- Syntax-highlighted JSON for input/output payloads
- Autocomplete for commands, MCP names, agent names
- Theming (dark/light, customizable colors)
- Responsive layout (adapts to terminal width)
- Still supports non-interactive mode (`observal install xyz --ide cursor` works without TUI)

### Phase 14: ITJ Integration (future)
- Replace LLM-as-judge backend with Information-Theoretic Judge
- f-mutual information scoring (Shannon MI white-box, TVD-MI black-box)
- Bayesian calibration + conformal prediction intervals
- Same interface: traces/spans in → scores with confidence intervals out
- Verification loop with drift detection

### Phase 15: Release Engineering (future)
- Compiled binary for shim/proxy (Go or Rust)
- GitHub releases with versioned binaries
- Package registry publishing: npm, apt, pacman, brew, yarn
- Stable release cadence

---

## API Layer Split

### Protocol by Concern

| Layer | Protocol | Why |
|-------|----------|-----|
| Dashboard / Web UI queries | GraphQL (Strawberry) | Flexible nested queries on traces→spans→scores, exact field selection, real-time subscriptions |
| Telemetry ingestion (shim → server) | REST | Simple fire-and-forget POST, no query flexibility needed |
| CLI operations (submit, install, review, admin) | REST | CRUD, straightforward request/response |
| Auth / SSO | **TBD: deferred to auth/SSO review** | |

### GraphQL Endpoint

`POST /api/v1/graphql`: single endpoint, Strawberry + FastAPI integration.

### Stack

- **Strawberry GraphQL**: async, native FastAPI mount, type-safe Python schema
- **DataLoaders**: batch ClickHouse queries to avoid N+1 (e.g., loading scores for 50 spans in one query)
- **Subscriptions**: WebSocket-based, for live trace/span streaming in the dashboard

### Schema

```graphql
type Trace {
  traceId: ID!
  parentTraceId: ID
  traceType: String!
  mcpId: String
  agentId: String
  userId: String!
  sessionId: String
  ide: String
  name: String
  startTime: DateTime!
  endTime: DateTime
  latencyMs: Int
  input: JSON
  output: JSON
  metadata: JSON
  tags: [String!]!
  spans(type: String, status: String, limit: Int): [Span!]!
  scores(source: String, name: String): [Score!]!
  childTraces: [Trace!]!
  metrics: TraceMetrics!
}

type Span {
  spanId: ID!
  traceId: ID!
  parentSpanId: ID
  type: String!
  name: String!
  method: String
  input: JSON
  output: JSON
  error: JSON
  startTime: DateTime!
  endTime: DateTime
  latencyMs: Int
  status: String!
  level: String
  tokenCountInput: Int
  tokenCountOutput: Int
  tokenCountTotal: Int
  cost: Float
  cpuMs: Int
  memoryMb: Float
  hopCount: Int
  entitiesRetrieved: Int
  relationshipsUsed: Int
  retryCount: Int
  toolsAvailable: Int
  toolSchemaValid: Boolean
  metadata: JSON
  children: [Span!]!
  scores(source: String): [Score!]!
}

type Score {
  scoreId: ID!
  traceId: ID
  spanId: ID
  name: String!
  source: String!
  dataType: String!
  value: Float!
  stringValue: String
  comment: String
  evalTemplateId: ID
  evalRunId: ID
  metadata: JSON
  timestamp: DateTime!
}

type TraceMetrics {
  totalSpans: Int!
  totalLatencyMs: Int
  errorCount: Int!
  toolCallCount: Int!
  tokenCountTotal: Int
}

# --- Aggregated Metrics ---

type McpMetrics {
  toolCallCount: Int!
  errorRate: Float!
  avgLatencyMs: Float!
  p50LatencyMs: Float!
  p90LatencyMs: Float!
  p99LatencyMs: Float!
  transportFailures: Int!
  timeoutRate: Float!
  schemaComplianceRate: Float!
  toolDiscoveryLatencyMs: Float
  topTools: [ToolUsage!]!
}

type AgentMetrics {
  turnCount: Int!
  handoffLatencyMs: Float
  orchestrationOverheadRatio: Float
  loopDetectionCount: Int!
  fallbackRate: Float!
  tokenEfficiency: Float
  goalCompletionRate: Float
  avgTokensPerGoal: Float
}

type MemoryMetrics {
  retrievalLatencyMs: Float!
  storeLatencyMs: Float!
  retrievalCount: Int!
  consolidationCount: Int!
}

type SandboxMetrics {
  executionSuccessRate: Float!
  avgSelfCorrectionCycles: Float!
  avgCpuMs: Float
  avgMemoryMb: Float
  securityViolationCount: Int!
}

type GraphMetrics {
  avgHopCount: Float!
  avgRelationshipDensity: Float!
  queryLatencyMs: Float!
  avgEntitiesPerQuery: Float!
}

type ToolUsage {
  name: String!
  callCount: Int!
  errorRate: Float!
  avgLatencyMs: Float!
}

type OverviewStats {
  totalTraces: Int!
  totalSpans: Int!
  totalMcps: Int!
  totalAgents: Int!
  totalUsers: Int!
  toolCallsToday: Int!
  errorsToday: Int!
}

type TrendPoint {
  date: String!
  traces: Int!
  spans: Int!
  errors: Int!
}

# --- Filters ---

input TraceFilter {
  traceType: String
  mcpId: ID
  agentId: ID
  userId: ID
  sessionId: String
  ide: String
  status: String
  startTimeGte: DateTime
  startTimeLte: DateTime
  tags: [String!]
}

input SpanFilter {
  type: String
  name: String
  status: String
  minLatencyMs: Int
  maxLatencyMs: Int
}

input TimeWindow {
  start: DateTime!
  end: DateTime!
}

enum Granularity {
  HOUR
  DAY
  WEEK
  MONTH
}

# --- Queries ---

type TraceConnection {
  items: [Trace!]!
  totalCount: Int!
  hasMore: Boolean!
}

type Query {
  # Trace exploration
  traces(filter: TraceFilter, limit: Int, offset: Int): TraceConnection!
  trace(traceId: ID!): Trace
  spans(traceId: ID!, filter: SpanFilter): [Span!]!
  span(spanId: ID!): Span

  # Aggregated metrics
  mcpMetrics(mcpId: ID!, window: TimeWindow!): McpMetrics!
  agentMetrics(agentId: ID!, window: TimeWindow!): AgentMetrics!
  memoryMetrics(agentId: ID!, window: TimeWindow!): MemoryMetrics!
  sandboxMetrics(window: TimeWindow!): SandboxMetrics!
  graphMetrics(window: TimeWindow!): GraphMetrics!

  # Overview
  overview(window: TimeWindow!): OverviewStats!
  trends(window: TimeWindow!, granularity: Granularity!): [TrendPoint!]!

  # Scores
  scores(traceId: ID, spanId: ID, source: String, name: String, limit: Int): [Score!]!
}

type Subscription {
  traceCreated(mcpId: ID, agentId: ID): Trace!
  spanCreated(traceId: ID!): Span!
  scoreCreated(traceId: ID!): Score!
}
```

### DataLoader Strategy

Each nested field uses a DataLoader to batch ClickHouse queries:

| Parent → Child | DataLoader | ClickHouse Query |
|---------------|------------|-----------------|
| Trace → Spans | `SpansByTraceIdLoader` | `SELECT * FROM spans WHERE trace_id IN ({ids})` |
| Trace → Scores | `ScoresByTraceIdLoader` | `SELECT * FROM scores WHERE trace_id IN ({ids})` |
| Trace → Child Traces | `TracesByParentIdLoader` | `SELECT * FROM traces WHERE parent_trace_id IN ({ids})` |
| Span → Children | `SpansByParentIdLoader` | `SELECT * FROM spans WHERE parent_span_id IN ({ids})` |
| Span → Scores | `ScoresBySpanIdLoader` | `SELECT * FROM scores WHERE span_id IN ({ids})` |

### REST Endpoints That Stay

All existing REST endpoints remain for CLI and non-dashboard operations:

- `POST /api/v1/telemetry/ingest`: shim/proxy ingestion
- `POST /api/v1/telemetry/events`: backward compat
- `/api/v1/auth/*`: **TBD pending SSO review**
- `/api/v1/mcps/*`: registry CRUD
- `/api/v1/agents/*`: agent CRUD
- `/api/v1/review/*`: admin review workflow
- `/api/v1/admin/*`: settings, user management
- `/api/v1/feedback/*`: migrates to scores eventually
- `/api/v1/eval/*`: eval engine operations
- `/health`: health check

The existing REST dashboard endpoints (`/api/v1/mcps/{id}/metrics`, `/api/v1/overview/*`, etc.) get deprecated once the GraphQL layer is live. The web UI switches to GraphQL queries.

---

## Auth / SSO

**Status: DEFERRED**

Current auth is API-key-only (SHA-256 hashed, stored in PostgreSQL `users` table, passed via `X-API-Key` header). This covers CLI and shim auth.

Full auth/SSO design (OIDC, SAML, session management, RBAC overhaul, token refresh, etc.) is pending review with the auth/SSO specialist. The design should cover:

- Web UI session auth (currently API key in localStorage: not ideal)
- SSO provider integration (Okta, Azure AD, Google Workspace, etc.)
- CLI auth flow (device code flow? browser redirect?)
- Shim auth (needs to be lightweight: env var based, no interactive login)
- API key scoping (read-only keys, ingestion-only keys, admin keys)
- RBAC model (current admin/developer/user may need refinement)
- Multi-tenancy / org isolation

**Do not design or implement auth changes until after the SSO review.**

---

## Resolved Decisions

### Architecture & Infrastructure

| # | Question | Decision | Rationale |
|---|----------|----------|-----------|
| 1 | Web UI framework | **Vite + React** (replace Next.js) | Simpler, faster, no SSR baggage. Dashboard is a pure SPA. |
| 2 | GraphQL client | **urql** | Built-in subscription support, lightweight (~15KB), simpler than Apollo. |
| 3 | Background worker | **Redis + arq** | Async-native, fits FastAPI. Redis doubles as pub/sub backend for GraphQL subscriptions. One new container, two purposes. |
| 4 | Eval engine | **Managed LLM-as-judge (temporary fallback)**. No custom authoring. Will be replaced by ITJ (Information-Theoretic Judge) when ready. | ITJ replaces LLM-as-judge with f-mutual information scoring, Bayesian calibration, and conformal prediction intervals. LLM-as-judge is a stopgap. Same interface: traces in, scores out. |
| 5 | Multi-tenancy | **Single instance, multi-project**. `project_id` on every table, every query, every API call from day one. | Enterprise customers need team isolation within one deployment. Retrofitting later is brutal. |
| 6 | ClickHouse deployment | **Single node, cluster-ready schema**. `ReplacingMergeTree` now, one-line swap to `ReplicatedReplacingMergeTree` later. | KISS. No Keeper dependency. |
| 7 | Shim distribution | **Python now** (part of `observal-cli`), **compiled binary later** for GA. Future: GitHub releases + npm, apt, pacman, brew, yarn. Versioned stable releases. | Ship fast. Binary comes with proper release engineering later. |
| 8 | API key in config | **Shim reads from `~/.observal/config.json` automatically**, env var `OBSERVAL_KEY` override. No key in IDE config files. | No keys in project files. No accidental git commits. Security teams happy. |
| 9 | REST dashboard endpoints | **Kill immediately** when GraphQL ships. No deprecation period. | Product doesn't exist yet. No consumers. Clean cut. |
| 10 | Repo structure | **Monorepo with `just`** as task runner. Scoped CI via path filters in GitHub Actions. | Atomic cross-component changes. `just` is simple, CI path filters handle scoped builds. |
| 11 | Testing | **pytest** (server unit/integration/E2E) + **Playwright** (dashboard UI). Kill bash scripts. | pytest covers the full backend pipeline including shim E2E. Playwright for critical UI flows only. |
| 12 | CLI UX | **Full TUI with Textual** (Phase 13). Claude Code / Kiro level polish. Non-interactive mode preserved. | The CLI is the primary interface for developers. It should be beautiful, not just functional. |
| 13 | Auth / SSO | **Keycloak** as identity gateway container. Observal only speaks OIDC (via Authlib). Keycloak brokers SAML, LDAP, Kerberos, OIDC: whatever the enterprise has. | Enterprise customers use different IdPs. One gateway, infinite protocols. Observal code never changes. |
| 14 | Web sessions | **Short-lived JWT (15min) + refresh token rotation in httpOnly cookie**. Kill localStorage auth. | Secure, standard, works with Keycloak OIDC flow. |
| 15 | CLI auth | **Device code flow + API key fallback**. Scoped keys: `ingestion`, `read`, `write`, `admin`. | Device code for humans, API keys for CI/automation. Least privilege via scopes. |
| 16 | Project access | **Per-project RBAC** (user ↔ project ↔ role in PostgreSQL). | Fine-grained: admin of project A, viewer of project B. |

### Transport & Telemetry

| Question | Decision |
|----------|----------|
| HTTP transport | HTTP proxy (`observal-proxy`), same fire-and-forget pattern |
| Agent-level tracing | Parent trace groups all MCP traces via `OBSERVAL_AGENT_ID` + `parent_trace_id` |
| Rate limiting | Not in scope: not our concern |
| Data retention | Indefinite. No TTL. Admin-only deletion via API |
| Shim updates | `observal upgrade` command updates CLI + shim + proxy |
| Schema compliance | Shim caches `tools/list` response and validates `tools/call` args against it |

### Supported Systems

| System | Span Types |
|--------|-----------|
| MCP servers | `tool_call`, `resource_read`, `prompt_get`, `initialize`, `tool_list`, `ping` |
| Multi-agent frameworks | `agent_turn`, `agent_handoff`, `orchestration`, `delegation`, `reasoning_step`, `fallback` |
| Memory systems | `memory_store`, `memory_retrieve`, `memory_consolidate` |
| Sandbox execution | `sandbox_exec`, `sandbox_retry` (with `cpu_ms`/`memory_mb`) |
| Knowledge graphs | `graph_traverse`, `graph_query` (with `hop_count`/`entities_retrieved`/`relationships_used`) |

### API Layer

| Concern | Protocol | Status |
|---------|----------|--------|
| Dashboard / Web UI queries | GraphQL (Strawberry) at `/api/v1/graphql` | New |
| Real-time trace streaming | GraphQL subscriptions over WebSocket (Redis pub/sub) | New |
| Telemetry ingestion | REST `POST /api/v1/telemetry/ingest` | New |
| CLI operations | REST | Existing (keep) |
| Auth / SSO | **Keycloak** as identity gateway. Observal speaks OIDC only (via Authlib). Keycloak brokers to whatever the enterprise uses (SAML, LDAP, Kerberos, OIDC, etc.). | Do not design or implement until after review |
