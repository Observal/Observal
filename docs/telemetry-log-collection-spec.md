# Telemetry Log Collection Spec

How Observal captures real logs/output for every registry type. This is the implementation spec — not aspirational, but what we build.

## Core Principle

Every registry type must produce a span with real `input` and `output` fields containing actual content from the tool/service. No stubs, no placeholders.

## Per-Type Collection

### 1. MCP Servers (existing, working)
- **Mechanism**: `observal-shim` (stdio) / `observal-proxy` (HTTP)
- **Logs captured**: JSON-RPC request/response pairs
- **Span fields**: `input` = request params, `output` = response result, `error` = JSON-RPC error
- **Status**: ✅ Done

### 2. Sandbox Exec
- **Mechanism**: `observal-sandbox-run` Python entry point using Docker SDK
- **How it works**:
  1. `docker.from_env().containers.run(image, command, detach=True, ...)`
  2. `container.wait()` → get `StatusCode`
  3. `container.logs(stdout=True, stderr=True)` → full stdout/stderr output (this IS the log)
  4. `container.attrs['State']['OOMKilled']` → OOM detection
  5. POST span to `/api/v1/telemetry/ingest`
- **Span fields**:
  - `type`: `sandbox_exec`
  - `input`: the command/entrypoint that was run
  - `output`: stdout/stderr from `container.logs()` (truncated to 64KB)
  - `exit_code`: from `container.wait()`
  - `oom_killed`: from container state
  - `container_id`: short container ID
  - `latency_ms`: wall-clock time from run to wait completion
- **Why `container.logs()` not `container.stats()`**: Stats give cgroup metrics (CPU/memory numbers). Logs give you what actually happened — the commands, their output, errors, stack traces. That's what developers need to debug.

### 3. GraphRAG
- **Mechanism**: `observal-graphrag-proxy` HTTP reverse proxy
- **How it works**:
  1. Sits between agent and GraphRAG endpoint_url
  2. Forwards every HTTP request untouched to the target
  3. Captures request body (the query) and response body (the results)
  4. Detects query_interface from Content-Type or URL path
  5. POST span to `/api/v1/telemetry/ingest`
- **Span fields**:
  - `type`: `retrieval`
  - `input`: request body (the query)
  - `output`: response body (truncated to 64KB)
  - `query_interface`: detected from request
  - `latency_ms`: round-trip time
  - `chunks_returned`: parsed from response if possible
  - `relevance_score`: parsed from response if available

### 4. Tool Calls (standalone, non-MCP)
- **Mechanism**: Depends on tool type
  - HTTP tools: `observal-proxy` wraps the endpoint_url (same as MCP HTTP transport)
  - Non-HTTP tools: Config generator emits a PostToolUse hook pointing at `/api/v1/telemetry/hooks`
- **Span fields**:
  - `type`: `tool_invoke`
  - `input`: tool input/params
  - `output`: tool response
  - `latency_ms`: round-trip time

### 5. Hooks
- **Mechanism**: The hook IS the telemetry. Config generator emits an HTTP hook config that POSTs to our `/api/v1/telemetry/hooks` endpoint.
- **How it works**:
  1. IDE fires hook (e.g., PostToolUse in Claude Code)
  2. IDE sends hook JSON to our endpoint
  3. We parse it into a span and insert into ClickHouse
- **Span fields**:
  - `type`: `hook_exec`
  - `input`: `tool_input` from hook JSON
  - `output`: `tool_response` from hook JSON
  - `hook_event`: event name (PostToolUse, SessionStart, etc.)
  - `name`: tool_name from hook JSON

### 6. Skills
- **Mechanism**: No runtime proxy (skills are instruction files). Telemetry via hooks.
- **How it works**:
  1. Config generator emits SessionStart + SessionEnd hooks
  2. Hooks report which skills are loaded/active
  3. Correlation with PostToolUse hooks shows skill impact
- **Span fields**:
  - `type`: `skill_activate`
  - `input`: skill metadata (name, triggers, task_type)
  - `output`: session context showing skill was active

### 7. Prompts
- **Mechanism**: Server-side. The `/api/v1/prompts/{id}/render` endpoint emits a span.
- **Already implemented**: The render route creates a `prompt_render` span with template/rendered tokens.
- **Span fields**:
  - `type`: `prompt_render`
  - `input`: template + variables
  - `output`: rendered text
  - `template_tokens`, `rendered_tokens`, `variables_provided`

### 8. Agents
- **Mechanism**: Existing agent config generator wraps linked MCPs with shim. Agent-level telemetry comes from aggregating MCP spans + hook spans.
- **Status**: ✅ Done (via shim wrapping)

## Config Generator Output

Each install route must return a real, usable IDE config snippet.

### Sandbox → `observal-sandbox-run`
```json
{
  "sandbox": {
    "command": "observal-sandbox-run",
    "args": ["--sandbox-id", "<uuid>", "--image", "<image>", "--timeout", "300"],
    "env": {"OBSERVAL_KEY": "$OBSERVAL_API_KEY", "OBSERVAL_SERVER": "http://localhost:8000"}
  }
}
```

### GraphRAG → `observal-graphrag-proxy`
```json
{
  "graphrag": {
    "proxy_url": "http://localhost:<port>",
    "original_endpoint": "<endpoint_url>",
    "start_command": "observal-graphrag-proxy --graphrag-id <uuid> --target <endpoint_url>"
  }
}
```

### Tool (HTTP) → `observal-proxy`
```json
{
  "tool": {
    "proxy_url": "http://localhost:<port>",
    "original_endpoint": "<endpoint_url>",
    "start_command": "observal-proxy --mcp-id <uuid> --target <endpoint_url>"
  }
}
```

### Tool (non-HTTP) → PostToolUse hook
```json
{
  "hooks": {
    "PostToolUse": [{
      "matcher": "<tool_name>",
      "hooks": [{"type": "http", "url": "http://localhost:8000/api/v1/telemetry/hooks"}]
    }]
  }
}
```

### Skill → SessionStart/End hooks
```json
{
  "hooks": {
    "SessionStart": [{
      "matcher": "*",
      "hooks": [{"type": "http", "url": "http://localhost:8000/api/v1/telemetry/hooks",
                  "headers": {"X-Observal-Skill-Id": "<uuid>"}}]
    }]
  }
}
```

### Hook → HTTP hook config (already implemented in `hook_config_generator.py`)

## Entry Points (pyproject.toml)
```
observal-sandbox-run = "observal_cli.sandbox_runner:main"
observal-graphrag-proxy = "observal_cli.graphrag_proxy:main"
```

## Implementation Order
1. Sandbox runner (most complex, proves the pattern)
2. GraphRAG proxy (reuses proxy.py pattern)
3. Config generators for sandbox, graphrag, tool, skill
4. Wire install routes to call config generators
5. Integration test with real Docker container
