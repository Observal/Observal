# Telemetry Collection Architecture

How Observal collects telemetry for each registry type. No wrapper binaries needed.

## Collection Mechanisms

### MCP Servers (existing)
- `observal-shim` (stdio): transparent JSON-RPC proxy between IDE and MCP server
- `observal-proxy` (HTTP): reverse proxy for HTTP-transport MCPs
- Pairs request/response into spans, fire-and-forget POST to `/api/v1/telemetry/ingest`

### Tool Calls (standalone, non-MCP)
- For HTTP tools: `observal-proxy` wraps the `endpoint_url`
- For IDE-native tools: config generator emits a PostToolUse HTTP hook that POSTs to ingest
- Span type: `tool_invoke`

### Hooks
- Config generator emits an HTTP hook (`type: "http"`) pointing at our ingest endpoint
- Claude Code hooks receive JSON on stdin: `session_id`, `tool_name`, `tool_input`, `tool_response`
- Kiro hooks work similarly with their own JSON format
- The hook itself IS the telemetry - we just need to receive and store it
- Span type: `hook_exec`

### Skills
- No runtime proxy possible (skills are instruction files, not services)
- Telemetry via SessionStart hook: detect loaded skills from session context
- Correlate with PostToolUse hooks to measure impact when skill is active
- Config generator emits SessionStart + Stop hooks that report skill activation
- Span type: `skill_activate`

### Prompts
- Server-side only: `/api/v1/prompts/{id}/render` endpoint emits span to ClickHouse
- Tracks: template tokens, rendered tokens, variables provided, render latency
- Span type: `prompt_render`

### Sandbox Exec
- Docker Python SDK: `docker.from_env().containers.run()` then `container.stats(stream=False)`
- Reads cgroup metrics: CPU usage, memory usage/limit, network I/O, block I/O
- Captures stdout, stderr, exit code, OOM kill status
- No wrapper binary - Python calls Docker API directly
- Span type: `sandbox_exec`

### GraphRAGs
- `observal-proxy` variant: HTTP reverse proxy between agent and GraphRAG endpoint
- Intercepts query/response, measures latency, parses response for entity/relationship counts
- For GraphQL endpoints: can introspect response structure
- Span type: `retrieval`

## Config Generator Output

When a user runs `observal install <id> --ide <ide>`, the config generator returns:

### For MCP Servers
```json
{"mcpServers": {"name": {"command": "observal-shim", "args": ["--mcp-id", "uuid", "--", "original-command"]}}}
```

### For Tools (HTTP)
```json
{"mcpServers": {"name": {"url": "http://localhost:<proxy-port>"}}}
```

### For Hooks (Claude Code)
```json
{
  "hooks": {
    "PostToolUse": [{
      "matcher": "*",
      "hooks": [{
        "type": "http",
        "url": "http://localhost:8000/api/v1/telemetry/hooks",
        "headers": {"X-API-Key": "$OBSERVAL_API_KEY"},
        "allowedEnvVars": ["OBSERVAL_API_KEY"]
      }]
    }]
  }
}
```

### For Hooks (Kiro)
Hook YAML file in `.kiro/hooks/` with equivalent configuration.

### For Skills
SessionStart + Stop hooks that report skill activation/deactivation to ingest endpoint.

### For Sandboxes
Docker run command wrapped with telemetry collection:
```json
{"sandbox": {"command": "observal-sandbox-run", "args": ["--sandbox-id", "uuid", "--", "docker", "run", "image"]}}
```
Where `observal-sandbox-run` is a Python entry point (not a separate binary) that:
1. Runs the docker command
2. Collects stats via Docker SDK
3. POSTs span to ingest

### For GraphRAGs
```json
{"graphrag": {"proxy_url": "http://localhost:<proxy-port>", "target": "original-endpoint"}}
```

## New Ingest Endpoint

`POST /api/v1/telemetry/hooks` - dedicated endpoint for hook telemetry that accepts the raw hook JSON from Claude Code/Kiro and transforms it into spans.

Input: raw hook JSON (as sent by the IDE)
Output: transforms to SpanIngest and inserts into ClickHouse

## ClickHouse Schema Extensions

New span columns (all Nullable, added via ALTER TABLE):
- `container_id` String - Docker container ID
- `exit_code` Int16 - process exit code
- `network_bytes_in` UInt64 - network I/O
- `network_bytes_out` UInt64 - network I/O
- `disk_read_bytes` UInt64 - block I/O
- `disk_write_bytes` UInt64 - block I/O
- `oom_killed` UInt8 - OOM kill flag
- `query_interface` String - graphql/rest/cypher/sparql
- `relevance_score` Float32 - RAG relevance
- `chunks_returned` UInt16 - RAG chunks
- `embedding_latency_ms` UInt32 - embedding time
- `hook_event` String - lifecycle event name
- `hook_scope` String - agent/global/org
- `hook_action` String - allow/block/modify
- `hook_blocked` UInt8 - whether hook blocked
- `variables_provided` UInt8 - prompt variables filled
- `template_tokens` UInt32 - raw template tokens
- `rendered_tokens` UInt32 - rendered tokens

New trace columns:
- `tool_id` String
- `sandbox_id` String
- `graphrag_id` String
- `hook_id` String
- `skill_id` String
- `prompt_id` String
