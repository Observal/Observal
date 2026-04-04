# Design Spec: New Registry Types

**Date:** 2026-04-04
**Status:** Draft

## Overview

Expand Observal from 2 registry types (MCP Servers, Agents) to 8 by adding:

1. **Tool Calls** — standalone tools exposed to agents
2. **Sandbox Exec** — Docker/LXC execution environments
3. **GraphRAGs** — knowledge graph + RAG system endpoints
4. **Hooks** — lifecycle callbacks for agent sessions
5. **Skills** — reusable instruction/script bundles for coding agents
6. **Prompts** — managed prompt templates

All 6 new types go through the existing admin review workflow. Feedback and metrics extend to all types.

---

## 1. Tool Calls

Standalone tool definitions that agents can invoke directly, without requiring a full MCP server.

### Model: `ToolListing`

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| name | String(255) | |
| version | String(50) | |
| description | Text | |
| owner | String(255) | |
| category | String(100) | e.g. "code-generation", "data-retrieval" |
| function_schema | JSON | OpenAI-style function schema (`name`, `description`, `parameters`) |
| auth_type | String(50) | "none", "api_key", "oauth2", "bearer" |
| auth_config | JSON | Nullable. Credential field names, OAuth URLs, etc. |
| endpoint_url | String(500) | Nullable. For HTTP-callable tools |
| rate_limit | JSON | Nullable. `{requests_per_minute: int, burst: int}` |
| supported_ides | JSON | List of IDE identifiers |
| status | ListingStatus | Reuse existing enum (pending/approved/rejected) |
| rejection_reason | Text | Nullable |
| submitted_by | UUID FK → users | |
| created_at | DateTime | |
| updated_at | DateTime | |

### API

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/tools` | Submit a tool for review |
| GET | `/api/v1/tools` | List approved tools (`search`, `category`) |
| GET | `/api/v1/tools/{id}` | Tool details |
| POST | `/api/v1/tools/{id}/install` | Get IDE config snippet + record download |
| DELETE | `/api/v1/tools/{id}` | Delete |

### CLI

```
observal tool submit          # interactive or --from-file
observal tool list [--category] [--search]
observal tool show <id>
observal tool install <id> --ide <ide>
observal tool delete <id>
```

### Validation

No git clone needed. Schema validation only:
- `function_schema` must be valid JSON Schema
- If `endpoint_url` is set, HTTP HEAD check for reachability
- `auth_type` and `auth_config` must be consistent (e.g. oauth2 requires token_url)

---

## 2. Sandbox Exec

Docker or LXC execution environments that agents can use for code execution, testing, and builds.

### Model: `SandboxListing`

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| name | String(255) | |
| version | String(50) | |
| description | Text | |
| owner | String(255) | |
| runtime_type | String(20) | "docker" or "lxc" |
| image | String(500) | Docker image ref or LXC template |
| dockerfile_url | String(500) | Nullable. Git URL to Dockerfile for audit |
| resource_limits | JSON | `{cpu: str, memory: str, disk: str, timeout_seconds: int}` |
| network_policy | String(20) | "none", "host", "restricted" |
| allowed_mounts | JSON | List of allowed mount paths/patterns |
| env_vars | JSON | Default env vars injected into sandbox |
| entrypoint | String(500) | Nullable. Override entrypoint |
| supported_ides | JSON | |
| status | ListingStatus | |
| rejection_reason | Text | Nullable |
| submitted_by | UUID FK → users | |
| created_at | DateTime | |
| updated_at | DateTime | |

### API

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/sandboxes` | Submit a sandbox for review |
| GET | `/api/v1/sandboxes` | List approved sandboxes |
| GET | `/api/v1/sandboxes/{id}` | Sandbox details |
| POST | `/api/v1/sandboxes/{id}/install` | Get config snippet |
| DELETE | `/api/v1/sandboxes/{id}` | Delete |

### CLI

```
observal sandbox submit
observal sandbox list [--runtime docker|lxc]
observal sandbox show <id>
observal sandbox install <id> --ide <ide>
observal sandbox delete <id>
```

### Validation

2-stage pipeline (similar to MCP validation):
1. **Image inspection**: Pull image (or clone Dockerfile repo), check it exists and is pullable. Extract labels/metadata.
2. **Security scan**: Run `docker scout` or `trivy` on the image. Flag critical CVEs. Store scan results as validation output.

---

## 3. GraphRAGs

Knowledge graph and RAG system endpoints that agents can query for domain-specific context.

### Model: `GraphRagListing`

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| name | String(255) | |
| version | String(50) | |
| description | Text | |
| owner | String(255) | |
| endpoint_url | String(500) | User-hosted query endpoint |
| auth_type | String(50) | "none", "api_key", "bearer", "oauth2" |
| auth_config | JSON | Nullable |
| query_interface | String(50) | "graphql", "rest", "cypher", "sparql" |
| graph_schema | JSON | Nullable. Node/edge types, properties |
| data_sources | JSON | List of source descriptions |
| embedding_model | String(255) | Nullable. e.g. "text-embedding-3-small" |
| chunk_strategy | String(100) | Nullable. e.g. "recursive-512", "semantic" |
| supported_ides | JSON | |
| status | ListingStatus | |
| rejection_reason | Text | Nullable |
| submitted_by | UUID FK → users | |
| created_at | DateTime | |
| updated_at | DateTime | |

### API

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/graphrags` | Submit a GraphRAG for review |
| GET | `/api/v1/graphrags` | List approved GraphRAGs |
| GET | `/api/v1/graphrags/{id}` | Details |
| POST | `/api/v1/graphrags/{id}/install` | Get config snippet |
| DELETE | `/api/v1/graphrags/{id}` | Delete |

### CLI

```
observal graphrag submit
observal graphrag list [--query-interface graphql|rest|cypher|sparql]
observal graphrag show <id>
observal graphrag install <id> --ide <ide>
observal graphrag delete <id>
```

### Validation

- HTTP reachability check on `endpoint_url`
- If `query_interface` is "graphql", introspection query to verify schema
- If `graph_schema` is provided, validate it's well-formed JSON
- No git clone needed

---

## 4. Hooks

Lifecycle callbacks that execute at predefined points during an agent session.

### Lifecycle Events

Union of Claude Code, Cursor, and Kiro hook systems:

| Event | Claude Code | Cursor | Kiro | Description |
|-------|:-----------:|:------:|:----:|-------------|
| `prompt_submit` | ✓ | ✓ | ✓ | User submits a prompt |
| `pre_tool_use` | ✓ (PreToolUse) | ✓ | ✓ | Before any tool call |
| `post_tool_use` | ✓ (PostToolUse) | ✓ | ✓ | After any tool call completes |
| `session_start` | ✓ (SessionStart) | ✓ | — | Agent session begins |
| `agent_stop` | ✓ (Stop) | ✓ | ✓ (Agent Stop) | Agent finishes its turn |
| `file_create` | — | — | ✓ | New file created in workspace |
| `file_save` | — | — | ✓ | File saved (matches glob pattern) |
| `file_delete` | — | — | ✓ | File deleted |
| `pre_task_exec` | — | — | ✓ | Before a spec task begins (Kiro-specific) |
| `post_task_exec` | — | — | ✓ | After a spec task completes (Kiro-specific) |
| `manual` | — | — | ✓ | On-demand manual trigger |
| `error` | ✓ | — | — | When an error occurs |

Kiro hooks additionally support tool name filtering with categories (`read`, `write`, `shell`, `web`, `spec`, `*`) and prefix filters (`@mcp`, `@powers`, `@builtin`) with regex matching (e.g. `@mcp.*sql.*`).

### Model: `HookListing`

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| name | String(255) | |
| version | String(50) | |
| description | Text | |
| owner | String(255) | |
| event | String(50) | One of the lifecycle events above |
| execution_mode | String(10) | "sync" or "async" |
| priority | Integer | Execution order (lower = first). Default 100 |
| handler_type | String(20) | "shell", "http", "script", "agent_prompt" |
| handler_config | JSON | `{command: str}` or `{url: str}` or `{script: str, runtime: str}` or `{prompt: str}` |
| input_schema | JSON | Nullable. JSON Schema for the event payload the hook receives |
| output_schema | JSON | Nullable. JSON Schema for what the hook returns (for sync hooks that modify) |
| scope | String(20) | "agent" (default), "global", "org" |
| tool_filter | JSON | Nullable. Tool names/categories/prefixes (e.g. `["write", "@mcp.*sql.*", "specific_tool"]`) |
| file_pattern | JSON | Nullable. Glob patterns for file_create/file_save/file_delete events |
| supported_ides | JSON | |
| status | ListingStatus | |
| rejection_reason | Text | Nullable |
| submitted_by | UUID FK → users | |
| created_at | DateTime | |
| updated_at | DateTime | |

### Agent-Hook Link: `AgentHookLink`

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| agent_id | UUID FK → agents | |
| hook_id | UUID FK → hook_listings | |
| order | Integer | Execution order within the agent |
| config_override | JSON | Nullable. Per-agent config overrides |

Hooks with `scope=agent` must be linked to agents via this table. `scope=global` hooks apply to all agents in the org. `scope=org` hooks apply to all agents owned by the hook owner's org.

### API

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/hooks` | Submit a hook for review |
| GET | `/api/v1/hooks` | List approved hooks (`event`, `scope`) |
| GET | `/api/v1/hooks/{id}` | Hook details |
| POST | `/api/v1/hooks/{id}/install` | Get config snippet |
| DELETE | `/api/v1/hooks/{id}` | Delete |
| POST | `/api/v1/agents/{id}/hooks` | Link a hook to an agent |
| DELETE | `/api/v1/agents/{id}/hooks/{hook_id}` | Unlink |

### CLI

```
observal hook submit
observal hook list [--event pre_tool_use] [--scope agent|global|org]
observal hook show <id>
observal hook install <id> --ide <ide>
observal hook delete <id>
observal agent link-hook <agent-id> <hook-id> [--order 10]
```

### Validation

- If `handler_type=http`: reachability check on URL
- If `handler_type=shell`: syntax check on command (no execution)
- If `handler_type=script`: validate runtime is supported (node, python, bash)
- If `handler_type=agent_prompt`: validate prompt is non-empty, check for template variable syntax
- `input_schema` and `output_schema` must be valid JSON Schema if provided
- If `event` is `file_create`/`file_save`/`file_delete`, `file_pattern` is required
- If `event` is `pre_tool_use`/`post_tool_use`, `tool_filter` is recommended (warn if missing)

### Hook Config Generation per IDE

| IDE | Hook config format | Notes |
|-----|-------------------|-------|
| Claude Code | `.claude/settings.json` hooks array | `PreToolUse`, `PostToolUse`, `Stop`, etc. Shell commands |
| Cursor | `.cursor/hooks/` directory | JSON hook definitions |
| Kiro IDE | `.kiro/hooks/` directory | YAML/JSON hook files with trigger type, tool name filters, file patterns |
| Kiro CLI | `.kiro/hooks/` directory | Same as IDE |

---

## 5. Skills

Reusable instruction/script bundles that coding agents load for specialized tasks. All major IDEs have converged on the open [Agent Skills](https://agentskills.io) standard: a `SKILL.md` file with YAML frontmatter in a named directory, plus optional scripts/templates/references.

### IDE Support Matrix

| IDE | Workspace location | Global location | Activation | Slash commands |
|-----|-------------------|----------------|------------|----------------|
| Claude Code | `.claude/skills/<name>/` | `~/.claude/skills/<name>/` | Auto + `/skill-name` | ✓ |
| GitHub Copilot | `.github/skills/<name>/` | `~/.github/skills/<name>/` | Auto + `/skill-name` | ✓ |
| Cursor | `.cursor/skills/<name>/` | `~/.cursor/skills/<name>/` | Auto + `/skill-name` | ✓ |
| Gemini CLI | `.gemini/skills/<name>/` | `~/.agents/skills/<name>/` | Auto + `/skill-name` | ✓ |
| Kiro IDE | `.kiro/skills/<name>/` | `~/.kiro/skills/<name>/` | Auto (description match) + `/` menu | ✓ |
| Kiro CLI | `.kiro/skills/<name>/` | `~/.kiro/skills/<name>/` | Auto (description match) | — |

Kiro additionally has **Powers** — bundles of MCP server config + POWER.md steering + optional hooks that activate dynamically based on conversation keywords. Powers are a superset of skills for MCP-backed workflows. Observal should support Powers as a variant of skills (see Powers section below).

### Skill Structure (what gets submitted)

```
my-skill/
├── SKILL.md          # Required. YAML frontmatter (name, description, triggers) + Markdown instructions
├── templates/        # Optional. Code/config templates
├── scripts/          # Optional. Executable scripts
└── data/             # Optional. Reference data files
```

Skills are submitted as git repos (like MCPs) or as zip archives.

### Model: `SkillListing`

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| name | String(255) | From SKILL.md frontmatter |
| version | String(50) | |
| description | Text | From SKILL.md frontmatter |
| owner | String(255) | |
| git_url | String(500) | Nullable. Git repo containing the skill |
| skill_path | String(500) | Path within repo to skill directory (default "/") |
| archive_url | String(500) | Nullable. URL to zip archive (alternative to git) |
| target_agents | JSON | List: "claude_code", "copilot", "cursor", "gemini_cli", "kiro", "kiro_cli" |
| task_type | String(100) | e.g. "testing", "code-review", "documentation", "refactoring" |
| triggers | JSON | Nullable. Auto-activation keywords/patterns from SKILL.md |
| slash_command | String(100) | Nullable. e.g. "/my-skill" |
| has_scripts | Boolean | Whether the skill includes executable scripts |
| has_templates | Boolean | Whether the skill includes templates |
| supported_ides | JSON | Derived from target_agents but may differ |
| status | ListingStatus | |
| rejection_reason | Text | Nullable |
| submitted_by | UUID FK → users | |
| created_at | DateTime | |
| updated_at | DateTime | |

### Agent-Skill Link: `AgentSkillLink`

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| agent_id | UUID FK → agents | |
| skill_id | UUID FK → skill_listings | |
| order | Integer | Priority order |

Skills can be standalone (installed directly into an IDE's skill directory) or linked to agents (bundled when the agent is installed).

### API

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/skills` | Submit a skill for review |
| GET | `/api/v1/skills` | List approved skills (`search`, `task_type`, `target_agent`) |
| GET | `/api/v1/skills/{id}` | Skill details |
| POST | `/api/v1/skills/{id}/install` | Get install instructions + record download |
| DELETE | `/api/v1/skills/{id}` | Delete |
| POST | `/api/v1/agents/{id}/skills` | Link a skill to an agent |
| DELETE | `/api/v1/agents/{id}/skills/{skill_id}` | Unlink |

### CLI

```
observal skill submit <git-url-or-path>
observal skill list [--task-type testing] [--target-agent cursor]
observal skill show <id>
observal skill install <id> --ide <ide>
observal skill delete <id>
observal agent link-skill <agent-id> <skill-id>
```

### Validation

2-stage pipeline (like MCPs):
1. **Clone/extract + inspect**: Clone repo or extract archive. Verify `SKILL.md` exists. Parse YAML frontmatter for required fields (name, description).
2. **Content validation**: Check that referenced templates/scripts exist. If `has_scripts=true`, verify scripts are executable. Validate SKILL.md frontmatter schema.

### Install Config Generation

Skills install differently per IDE:

| IDE | Workspace location | Global location | Notes |
|-----|-------------------|----------------|-------|
| Claude Code | `.claude/skills/<name>/` | `~/.claude/skills/<name>/` | Copy SKILL.md + assets |
| GitHub Copilot | `.github/skills/<name>/` | `~/.github/skills/<name>/` | Copy SKILL.md + assets |
| Cursor | `.cursor/skills/<name>/` | `~/.cursor/skills/<name>/` | Copy SKILL.md + assets |
| Gemini CLI | `.gemini/skills/<name>/` | `~/.agents/skills/<name>/` | Copy SKILL.md + assets |
| Kiro IDE | `.kiro/skills/<name>/` | `~/.kiro/skills/<name>/` | Copy SKILL.md + assets. For custom agents, also add `skill://` URI to agent's `resources` field |
| Kiro CLI | `.kiro/skills/<name>/` | `~/.kiro/skills/<name>/` | Same as IDE. Default agent auto-loads; custom agents need explicit `skill://` resource URIs |

The install endpoint returns a script or instructions to clone/copy the skill into the correct directory.

---

## 5a. Powers (Kiro-specific)

Powers are a Kiro-specific concept: bundles of MCP server config + POWER.md steering + optional hooks that activate dynamically based on conversation keywords. They solve context overload by loading MCP tools on-demand rather than all at once.

Powers are stored in Observal as a skill variant with `is_power=true` and additional fields.

### Additional columns on `SkillListing` for Powers

| Column | Type | Notes |
|--------|------|-------|
| is_power | Boolean | Default false. True for Kiro Powers |
| power_md | Text | Nullable. POWER.md content (steering for MCP tools) |
| mcp_server_config | JSON | Nullable. MCP server connection details for the power |
| activation_keywords | JSON | Nullable. Keywords that trigger power activation |

When `is_power=true`:
- Install generates Kiro power config (POWER.md + MCP config + optional hooks)
- `target_agents` is implicitly `["kiro", "kiro_cli"]`
- The power is listed in both skill and power browse views in the web UI

### CLI

```
observal skill submit <git-url-or-path> --power   # submit as a Kiro Power
observal power list                                 # alias for skill list --power
observal power show <id>
observal power install <id>                         # Kiro-only
```

---

## 6. Prompts

Managed prompt templates for use in agent configurations, eval pipelines, or direct invocation.

### Model: `PromptListing`

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| name | String(255) | |
| version | String(50) | |
| description | Text | |
| owner | String(255) | |
| category | String(100) | e.g. "system", "evaluation", "task", "few-shot" |
| template | Text | The prompt text. Supports `{{variable}}` placeholders |
| variables | JSON | List of `{name, type, description, required, default}` |
| model_hints | JSON | Nullable. `{recommended_models: [], max_tokens: int, temperature: float}` |
| tags | JSON | Searchable tags |
| supported_ides | JSON | |
| status | ListingStatus | |
| rejection_reason | Text | Nullable |
| submitted_by | UUID FK → users | |
| created_at | DateTime | |
| updated_at | DateTime | |

### API

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/prompts` | Submit a prompt for review |
| GET | `/api/v1/prompts` | List approved prompts (`search`, `category`, `tag`) |
| GET | `/api/v1/prompts/{id}` | Prompt details |
| POST | `/api/v1/prompts/{id}/render` | Render template with provided variables |
| DELETE | `/api/v1/prompts/{id}` | Delete |

### CLI

```
observal prompt submit [--from-file]
observal prompt list [--category system] [--tag coding]
observal prompt show <id>
observal prompt render <id> --var key=value
observal prompt delete <id>
```

### Validation

- Template must contain valid `{{variable}}` syntax (no unclosed braces)
- All variables declared in `variables` must appear in `template`
- All `{{placeholders}}` in template must be declared in `variables`
- `category` must be one of the allowed values

---

## Unified Review Workflow

The current review system only handles `McpListing`. It needs to become polymorphic.

### Option: Unified Submissions Table

Add a `submissions` table that wraps all reviewable types:

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| listing_type | String(20) | "mcp", "tool", "sandbox", "graphrag", "hook", "skill", "prompt" |
| listing_id | UUID | FK to the specific listing table |
| status | ListingStatus | |
| rejection_reason | Text | Nullable |
| submitted_by | UUID FK → users | |
| reviewed_by | UUID FK → users | Nullable |
| created_at | DateTime | |
| reviewed_at | DateTime | Nullable |

This lets the review endpoints stay the same:

```
GET    /api/v1/review              # list pending (all types, or ?type=skill)
GET    /api/v1/review/{id}         # submission details (resolves to underlying listing)
POST   /api/v1/review/{id}/approve
POST   /api/v1/review/{id}/reject
```

The `status` field on individual listing tables becomes a denormalized copy synced on approve/reject. This avoids changing every listing query to join through submissions.

### CLI

```
observal review list [--type mcp|tool|sandbox|graphrag|hook|skill|prompt]
observal review show <id>
observal review approve <id>
observal review reject <id> --reason "..."
```

---

## Feedback Extension

The `Feedback` model already uses a polymorphic `listing_type` string. Extend the allowed values:

**Current:** `"mcp"`, `"agent"`
**New:** `"mcp"`, `"agent"`, `"tool"`, `"sandbox"`, `"graphrag"`, `"hook"`, `"skill"`, `"prompt"`

Add a check constraint or application-level validation. The feedback API and CLI commands already accept `--type`, so they just need the new values whitelisted.

---

## Metrics Extension

Each new type gets a metrics endpoint:

```
GET /api/v1/tools/{id}/metrics
GET /api/v1/sandboxes/{id}/metrics
GET /api/v1/graphrags/{id}/metrics
GET /api/v1/hooks/{id}/metrics
GET /api/v1/skills/{id}/metrics
GET /api/v1/prompts/{id}/metrics
```

Standard metrics per type: downloads, installs, error rate, latency percentiles. Hooks and tools additionally track invocation counts. Prompts track render counts.

---

## Download Tracking

Each type gets a download table following the `McpDownload` / `AgentDownload` pattern:

- `ToolDownload`
- `SandboxDownload`
- `GraphRagDownload`
- `HookDownload`
- `SkillDownload`
- `PromptDownload`

All have the same schema: `id`, `listing_id` (FK), `user_id` (FK), `ide` (String), `created_at`.

---

## Database Migrations

New tables (14 total):
- `tool_listings`
- `sandbox_listings`
- `graphrag_listings`
- `hook_listings`
- `skill_listings`
- `prompt_listings`
- `agent_hook_links`
- `agent_skill_links`
- `tool_downloads`
- `sandbox_downloads`
- `graphrag_downloads`
- `hook_downloads`
- `skill_downloads`
- `prompt_downloads`

Plus the `submissions` table for unified review.

Existing tables modified:
- `feedback`: update check constraint to allow new listing_type values

---

## File Changes Summary

### New files

| File | Purpose |
|------|---------|
| `models/tool.py` | ToolListing, ToolDownload |
| `models/sandbox.py` | SandboxListing, SandboxDownload |
| `models/graphrag.py` | GraphRagListing, GraphRagDownload |
| `models/hook.py` | HookListing, HookDownload, AgentHookLink |
| `models/skill.py` | SkillListing, SkillDownload, AgentSkillLink |
| `models/prompt.py` | PromptListing, PromptDownload |
| `models/submission.py` | Submission (unified review) |
| `schemas/tool.py` | Request/response schemas |
| `schemas/sandbox.py` | Request/response schemas |
| `schemas/graphrag.py` | Request/response schemas |
| `schemas/hook.py` | Request/response schemas |
| `schemas/skill.py` | Request/response schemas |
| `schemas/prompt.py` | Request/response schemas |
| `api/routes/tool.py` | Tool CRUD + install |
| `api/routes/sandbox.py` | Sandbox CRUD + install |
| `api/routes/graphrag.py` | GraphRAG CRUD + install |
| `api/routes/hook.py` | Hook CRUD + install + agent linking |
| `api/routes/skill.py` | Skill CRUD + install + agent linking |
| `api/routes/prompt.py` | Prompt CRUD + install + render |
| `services/tool_validator.py` | Schema + endpoint validation |
| `services/sandbox_validator.py` | Image pull + security scan |
| `services/skill_validator.py` | Clone + SKILL.md parsing |
| `services/graphrag_validator.py` | Endpoint + schema validation |
| `services/hook_validator.py` | Handler validation |
| `services/prompt_validator.py` | Template + variable validation |
| `services/skill_config_generator.py` | IDE-specific skill install configs |
| `services/power_config_generator.py` | Kiro Power install configs (POWER.md + MCP + hooks) |
| `services/hook_config_generator.py` | IDE-specific hook config generation |
| `services/tool_shim.py` | Standalone tool telemetry shim (non-MCP) |
| `services/graphrag_proxy.py` | GraphRAG HTTP proxy with retrieval/embedding telemetry |
| `services/sandbox_wrapper.py` | Container metrics collection wrapper |
| `observal_cli/cmd_tool.py` | CLI commands |
| `observal_cli/cmd_sandbox.py` | CLI commands |
| `observal_cli/cmd_graphrag.py` | CLI commands |
| `observal_cli/cmd_hook.py` | CLI commands |
| `observal_cli/cmd_skill.py` | CLI commands |
| `observal_cli/cmd_prompt.py` | CLI commands |

### Modified files

| File | Change |
|------|--------|
| `models/__init__.py` | Import all new models |
| `api/routes/review.py` | Query `submissions` table instead of `mcp_listings` directly |
| `api/routes/feedback.py` | Whitelist new listing_type values |
| `api/routes/dashboard.py` | Add metrics endpoints for new types |
| `observal_cli/main.py` | Register new command groups |
| `main.py` | Mount new route modules |
| `services/clickhouse.py` | Add new columns to INIT_SQL, extend insert_spans/insert_traces |
| `schemas/telemetry.py` | Extend TraceIngest and SpanIngest with new fields |
| `api/graphql.py` | Add new metrics types, extend Span type, add subscription filters |
| `observal_cli/shim.py` | Support new env vars (OBSERVAL_TOOL_ID, OBSERVAL_SKILL_ID, etc.) |
| `observal_cli/proxy.py` | Support new trace types |
| `observal-web/` | New browse/detail pages for each type |

---

## Telemetry, Tracing, and Observability

### Current Architecture

Observal has a 3-layer telemetry stack:

1. **Collection**: The `observal-shim` (stdio) and `observal-proxy` (HTTP) sit between IDE and MCP server, transparently observing JSON-RPC messages. They pair requests/responses into spans and batch-POST them to the ingest endpoint. Fire-and-forget — if the server is down, spans are silently dropped.

2. **Storage**: ClickHouse with 5 tables:
   - `mcp_tool_calls` (legacy) — flat tool call events
   - `agent_interactions` (legacy) — flat agent interaction events
   - `traces` — ReplacingMergeTree, bloom filter indexes, parent/child trace linking
   - `spans` — ReplacingMergeTree, typed spans with latency, tokens, cost, error, schema compliance fields
   - `scores` — ReplacingMergeTree, quality metrics attached to traces/spans (from eval engine or feedback dual-write)

3. **Query**: GraphQL API with DataLoaders for batch ClickHouse queries. REST dashboard endpoints for aggregate metrics. WebSocket subscriptions for live trace/span events via Redis pub/sub.

### What Exists Today

The `spans` table already has fields that anticipate the new registry types:

| Field | Current use | New type relevance |
|-------|------------|-------------------|
| `type` | `"tool_call"`, `"request"`, `"response"`, `"notification"` | Extend with new span types |
| `hop_count` | Nullable | GraphRAG traversal depth |
| `entities_retrieved` | Nullable | GraphRAG entity count |
| `relationships_used` | Nullable | GraphRAG relationship count |
| `cpu_ms` | Nullable | Sandbox CPU time |
| `memory_mb` | Nullable | Sandbox memory usage |
| `retry_count` | Nullable | Tool/GraphRAG retry tracking |
| `tools_available` | Nullable | Tool schema compliance |
| `tool_schema_valid` | Nullable | Tool schema compliance |

The `traces` table has `trace_type` (currently `"mcp"`) and nullable `mcp_id`/`agent_id` foreign keys.

### New Span Types

Extend the `type` LowCardinality column with new values. Aligned with [OpenTelemetry GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/) (v1.40.0):

| Span type | OTel `gen_ai.operation.name` | Source | Description |
|-----------|------------------------------|--------|-------------|
| `tool_call` | `execute_tool` | Shim/proxy (existing) | MCP tool invocation |
| `tool_invoke` | `execute_tool` | Tool shim (new) | Standalone tool invocation (non-MCP) |
| `sandbox_exec` | — (custom) | Sandbox wrapper | Code execution in Docker/LXC |
| `retrieval` | `retrieval` | GraphRAG proxy | Knowledge graph query |
| `hook_exec` | — (custom) | Hook runner | Lifecycle hook execution |
| `skill_activate` | — (custom) | IDE telemetry | Skill activation event |
| `prompt_render` | — (custom) | API/CLI | Prompt template rendering |
| `inference` | `chat` / `generate_content` | Shim (existing, from LLM calls) | LLM inference call |
| `embeddings` | `embeddings` | GraphRAG proxy | Embedding generation for RAG |

### New Trace Types

Extend `trace_type` LowCardinality:

| Trace type | Description |
|-----------|-------------|
| `mcp` | MCP server session (existing) |
| `agent` | Agent session (existing) |
| `tool` | Standalone tool invocation session |
| `sandbox` | Sandbox execution session |
| `graphrag` | GraphRAG query session |
| `hook` | Hook execution chain |
| `skill` | Skill activation session |
| `prompt` | Prompt render + downstream calls |

### New Span Attributes

Add columns to the `spans` table for type-specific telemetry:

```sql
-- Sandbox execution fields
ALTER TABLE spans ADD COLUMN IF NOT EXISTS container_id Nullable(String);
ALTER TABLE spans ADD COLUMN IF NOT EXISTS exit_code Nullable(Int16);
ALTER TABLE spans ADD COLUMN IF NOT EXISTS network_bytes_in Nullable(UInt64);
ALTER TABLE spans ADD COLUMN IF NOT EXISTS network_bytes_out Nullable(UInt64);
ALTER TABLE spans ADD COLUMN IF NOT EXISTS disk_read_bytes Nullable(UInt64);
ALTER TABLE spans ADD COLUMN IF NOT EXISTS disk_write_bytes Nullable(UInt64);
ALTER TABLE spans ADD COLUMN IF NOT EXISTS oom_killed Nullable(UInt8);

-- GraphRAG fields (hop_count, entities_retrieved, relationships_used already exist)
ALTER TABLE spans ADD COLUMN IF NOT EXISTS query_interface Nullable(String);
ALTER TABLE spans ADD COLUMN IF NOT EXISTS relevance_score Nullable(Float32);
ALTER TABLE spans ADD COLUMN IF NOT EXISTS chunks_returned Nullable(UInt16);
ALTER TABLE spans ADD COLUMN IF NOT EXISTS embedding_latency_ms Nullable(UInt32);

-- Hook fields
ALTER TABLE spans ADD COLUMN IF NOT EXISTS hook_event Nullable(String);
ALTER TABLE spans ADD COLUMN IF NOT EXISTS hook_scope Nullable(String);
ALTER TABLE spans ADD COLUMN IF NOT EXISTS hook_action Nullable(String);
ALTER TABLE spans ADD COLUMN IF NOT EXISTS hook_blocked Nullable(UInt8);

-- Prompt fields
ALTER TABLE spans ADD COLUMN IF NOT EXISTS variables_provided Nullable(UInt8);
ALTER TABLE spans ADD COLUMN IF NOT EXISTS template_tokens Nullable(UInt32);
ALTER TABLE spans ADD COLUMN IF NOT EXISTS rendered_tokens Nullable(UInt32);
```

Add foreign key columns to `traces`:

```sql
ALTER TABLE traces ADD COLUMN IF NOT EXISTS tool_id Nullable(String);
ALTER TABLE traces ADD COLUMN IF NOT EXISTS sandbox_id Nullable(String);
ALTER TABLE traces ADD COLUMN IF NOT EXISTS graphrag_id Nullable(String);
ALTER TABLE traces ADD COLUMN IF NOT EXISTS hook_id Nullable(String);
ALTER TABLE traces ADD COLUMN IF NOT EXISTS skill_id Nullable(String);
ALTER TABLE traces ADD COLUMN IF NOT EXISTS prompt_id Nullable(String);
```

With bloom filter indexes on each.

### Telemetry Collection Per Type

#### Tool Calls (standalone)

Collection mechanism: **Tool shim** — a new variant of `observal-shim` for non-MCP tools.

For HTTP tools, the config generator wraps the `endpoint_url` with `observal-proxy`, which intercepts the HTTP request/response and emits a `tool_invoke` span. For function-schema tools invoked by the IDE natively, telemetry comes from the IDE's hook system (pre_tool_use / post_tool_use hooks that POST to the ingest endpoint).

Span attributes captured:
- `name`: tool name from `function_schema`
- `input`: serialized arguments
- `output`: serialized response
- `latency_ms`: end-to-end
- `status`: success/error
- `tool_schema_valid`: validated against `function_schema.parameters`
- `retry_count`: if the tool was retried

#### Sandbox Exec

Collection mechanism: **Sandbox wrapper** — a lightweight sidecar or wrapper script that runs inside or alongside the container.

Two approaches depending on runtime:
1. **Docker**: Use `docker stats` API streaming + container events API. The wrapper script captures resource metrics and exit status, then POSTs a `sandbox_exec` span to the ingest endpoint.
2. **LXC**: Similar approach using `lxc info` for resource metrics.

Span attributes captured (aligned with [OTel container semantic conventions](https://opentelemetry.io/docs/specs/semconv/system/container-metrics/)):
- `container_id`: Docker/LXC container ID
- `cpu_ms`: CPU time consumed
- `memory_mb`: peak memory usage
- `disk_read_bytes` / `disk_write_bytes`: I/O
- `network_bytes_in` / `network_bytes_out`: network I/O
- `exit_code`: process exit code
- `oom_killed`: whether the container was OOM-killed
- `latency_ms`: wall-clock execution time
- `status`: success (exit 0) / error (non-zero) / timeout / oom

Dashboard metrics:
- Execution count, error rate, OOM rate
- CPU/memory/disk/network percentiles (p50, p90, p99)
- Average execution time
- Timeout rate

#### GraphRAGs

Collection mechanism: **GraphRAG proxy** — an HTTP reverse proxy (like `observal-proxy`) that sits between the agent and the GraphRAG endpoint.

The proxy intercepts queries and responses, emitting two span types:
1. `embeddings` span — if the query involves embedding generation (captures embedding latency, token count)
2. `retrieval` span — the actual knowledge graph query (captures entities, relationships, relevance)

This aligns with the [OTel GenAI retrieval span](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/#retrievals) convention which defines `gen_ai.operation.name = "retrieval"` with `gen_ai.data_source.id`.

Span attributes captured:
- `query_interface`: graphql/rest/cypher/sparql
- `entities_retrieved`: number of entities/nodes returned
- `relationships_used`: number of edges traversed
- `hop_count`: graph traversal depth
- `chunks_returned`: number of text chunks returned (for RAG)
- `relevance_score`: average relevance/similarity score
- `embedding_latency_ms`: time spent generating embeddings (if applicable)
- `latency_ms`: total query time
- `status`: success/error/timeout
- `input`: query text
- `output`: result summary (truncated)

Dashboard metrics (aligned with [Langfuse RAG observability](https://langfuse.com/blog/2025-10-28-rag-observability-and-evals) patterns):
- Query count, error rate
- Avg entities retrieved, avg relationships used
- Latency percentiles (total, embedding-only)
- Relevance score distribution
- Chunks returned distribution

#### Hooks

Collection mechanism: **Hook runner telemetry** — the hook execution runtime (whether shell, HTTP, script, or agent_prompt) emits a `hook_exec` span.

For hooks installed via Observal, the config generator wraps the hook handler with a telemetry wrapper that:
1. Records the hook event trigger (pre_tool_use, file_save, etc.)
2. Captures input payload and output
3. Records whether the hook blocked the action (for sync pre-hooks)
4. POSTs the span to the ingest endpoint

Span attributes captured:
- `hook_event`: the lifecycle event that triggered it
- `hook_scope`: agent/global/org
- `hook_action`: allow/block/modify (for sync hooks)
- `hook_blocked`: 1 if the hook blocked the action, 0 otherwise
- `latency_ms`: hook execution time
- `status`: success/error/timeout
- `error`: error message if hook failed

Dashboard metrics:
- Execution count per event type
- Block rate (how often hooks prevent actions)
- Error rate, timeout rate
- Latency percentiles per event type
- Most-triggered hooks

#### Skills

Collection mechanism: **IDE telemetry events** — skills don't have a runtime proxy. Telemetry comes from the IDE reporting skill activation events.

The shim/proxy already captures `OBSERVAL_AGENT_ID` from env vars. Extend this to capture `OBSERVAL_SKILL_ID` when a skill is active. The IDE (or the skill's scripts, if they call external tools) can POST `skill_activate` spans.

Span attributes captured:
- `name`: skill name
- `latency_ms`: time the skill was active in the session
- `status`: success/error
- `metadata.trigger`: auto-activated vs slash-command vs linked-to-agent

Dashboard metrics:
- Activation count (auto vs manual)
- Which agents trigger which skills
- Error rate when skill is active vs inactive
- Session duration with skill active

#### Prompts

Collection mechanism: **API-level telemetry** — the `/render` endpoint emits a `prompt_render` span directly.

When a prompt is rendered (via API or CLI), the server creates a span with:
- `variables_provided`: number of variables filled
- `template_tokens`: estimated token count of the raw template
- `rendered_tokens`: estimated token count after variable substitution
- `latency_ms`: render time (usually <1ms, but relevant for complex templates)

If the rendered prompt is then used in an LLM call, the downstream `inference` span links back via `parent_span_id`.

Dashboard metrics:
- Render count
- Most-used prompts
- Variable fill rate (how many variables are typically provided)
- Token expansion ratio (rendered / template)
- Downstream LLM call success rate when using this prompt

### Ingest Schema Changes

Extend `TraceIngest` to accept new foreign keys:

```python
class TraceIngest(BaseModel):
    # ... existing fields ...
    tool_id: str | None = None
    sandbox_id: str | None = None
    graphrag_id: str | None = None
    hook_id: str | None = None
    skill_id: str | None = None
    prompt_id: str | None = None
```

Extend `SpanIngest` with new optional fields:

```python
class SpanIngest(BaseModel):
    # ... existing fields ...
    # Sandbox
    container_id: str | None = None
    exit_code: int | None = None
    network_bytes_in: int | None = None
    network_bytes_out: int | None = None
    disk_read_bytes: int | None = None
    disk_write_bytes: int | None = None
    oom_killed: bool | None = None
    # GraphRAG
    query_interface: str | None = None
    relevance_score: float | None = None
    chunks_returned: int | None = None
    embedding_latency_ms: int | None = None
    # Hook
    hook_event: str | None = None
    hook_scope: str | None = None
    hook_action: str | None = None
    hook_blocked: bool | None = None
    # Prompt
    variables_provided: int | None = None
    template_tokens: int | None = None
    rendered_tokens: int | None = None
```

All new fields are nullable and optional — existing shim/proxy clients continue working without changes.

### GraphQL Schema Extensions

New query fields:

```graphql
type Query {
  # Existing
  traces(...): TraceConnection!
  mcpMetrics(mcpId: String!, start: String!, end: String!): McpMetrics!

  # New
  toolMetrics(toolId: String!, start: String!, end: String!): ToolMetrics!
  sandboxMetrics(sandboxId: String!, start: String!, end: String!): SandboxMetrics!
  graphragMetrics(graphragId: String!, start: String!, end: String!): GraphRagMetrics!
  hookMetrics(hookId: String!, start: String!, end: String!): HookMetrics!
  skillMetrics(skillId: String!, start: String!, end: String!): SkillMetrics!
  promptMetrics(promptId: String!, start: String!, end: String!): PromptMetrics!
}

type ToolMetrics {
  invocationCount: Int!
  errorRate: Float!
  avgLatencyMs: Float!
  p50LatencyMs: Float!
  p90LatencyMs: Float!
  p99LatencyMs: Float!
  schemaComplianceRate: Float!
  retryRate: Float!
}

type SandboxMetrics {
  executionCount: Int!
  errorRate: Float!
  oomRate: Float!
  timeoutRate: Float!
  avgCpuMs: Float!
  avgMemoryMb: Float!
  avgLatencyMs: Float!
  p90LatencyMs: Float!
  avgNetworkBytesIn: Float!
  avgNetworkBytesOut: Float!
}

type GraphRagMetrics {
  queryCount: Int!
  errorRate: Float!
  avgLatencyMs: Float!
  p90LatencyMs: Float!
  avgEntitiesRetrieved: Float!
  avgRelationshipsUsed: Float!
  avgRelevanceScore: Float!
  avgChunksReturned: Float!
  avgEmbeddingLatencyMs: Float!
}

type HookMetrics {
  executionCount: Int!
  errorRate: Float!
  blockRate: Float!
  avgLatencyMs: Float!
  executionsByEvent: [EventCount!]!
}

type EventCount {
  event: String!
  count: Int!
}

type SkillMetrics {
  activationCount: Int!
  autoActivations: Int!
  manualActivations: Int!
  errorRate: Float!
  avgSessionDurationMs: Float!
}

type PromptMetrics {
  renderCount: Int!
  avgTemplateTokens: Float!
  avgRenderedTokens: Float!
  tokenExpansionRatio: Float!
  variableFillRate: Float!
}
```

### GraphQL Subscriptions

Extend existing subscriptions to support new trace types:

```graphql
type Subscription {
  traceCreated(traceType: String): Trace!    # filter by type
  spanCreated(spanType: String): Span!       # filter by type
}
```

### OTel Alignment Summary

Observal's span model maps to OTel GenAI semantic conventions as follows:

| Observal field | OTel attribute | Notes |
|---------------|---------------|-------|
| `type` | `gen_ai.operation.name` | Maps to `execute_tool`, `retrieval`, `chat`, `embeddings` |
| `name` | `gen_ai.tool.name` / span name | |
| `input` | `gen_ai.tool.call.arguments` / `gen_ai.input.messages` | |
| `output` | `gen_ai.tool.call.result` / `gen_ai.output.messages` | |
| `latency_ms` | Derived from span start/end time | |
| `status` | `error.type` (on error) | |
| `token_count_input` | `gen_ai.usage.input_tokens` | |
| `token_count_output` | `gen_ai.usage.output_tokens` | |
| `tool_schema_valid` | Custom (no OTel equivalent) | |
| `entities_retrieved` | Custom (retrieval-specific) | |
| `hop_count` | Custom (graph-specific) | |
| `container_id` | `container.id` (OTel resource convention) | |
| `cpu_ms` | `container.cpu.time` (OTel system convention) | |
| `memory_mb` | `container.memory.usage` (OTel system convention) | |

This alignment means Observal telemetry can be exported to any OTel-compatible backend (Datadog, Langfuse, Jaeger) with minimal transformation.

---

## Implementation Order

1. **Submissions table + review refactor** — unblock everything else
2. **Prompts** — simplest new type, no validation pipeline, good to prove the pattern
3. **Telemetry schema extensions** — ALTER TABLE for new span/trace columns, extend ingest schemas
4. **Tool Calls** — schema validation only, no git clone; includes tool shim for telemetry
5. **Hooks** — introduces agent linking pattern; includes hook runner telemetry wrapper
6. **Skills** — git clone + SKILL.md parsing, reuses MCP validator patterns; includes Powers variant
7. **GraphRAGs** — endpoint validation; includes GraphRAG proxy for retrieval/embedding telemetry
8. **Sandbox Exec** — most complex validation (image pull + security scan); includes container metrics collection
9. **Feedback + metrics extension** — wire up all types
10. **GraphQL + dashboard extension** — new metrics types, subscription filters, web UI pages
