# Observal Demo Framework

End-to-end demos showing Observal's telemetry capture across different MCP server types and IDE configurations.

## Prerequisites

- Docker stack running (`cd docker && docker compose up -d`)
- `observal-shim` installed (`uv tool install --editable .`)
- `jq` and `curl` available
- An Observal API key (via `observal init` or `OBSERVAL_KEY` env var)

## Quick Start

```bash
cd demo
./run_demo.sh
```

The script checks the Docker stack, authenticates, runs all 3 mock MCPs through `observal-shim`, then queries ClickHouse and GraphQL to show captured telemetry.

## Mock MCP Servers

### mock_mcp.py: General Purpose

Tools: `echo`, `add`, `read_file`, `write_file`, `search`

Also responds to `resources/read`, `prompts/get`, and `ping`. Generates diverse span types: `tool_call`, `resource_read`, `prompt_get`, `initialize`, `tool_list`, `ping`.

### mock_graphrag_mcp.py: Knowledge Graph

Tools: `graph_query`, `graph_traverse`, `entity_lookup`

Returns fake knowledge graph data with entities (AuthService, UserDB, APIGateway, etc.) and relationships (reads_from, routes_to, caches_in). Exercises graph-specific span columns: `hop_count`, `entities_retrieved`, `relationships_used`.

### mock_agent_mcp.py: Multi-Agent

Tools: `delegate_task`, `reasoning_step`, `memory_store`, `memory_retrieve`

Simulates multi-agent coordination with task delegation, chain-of-thought reasoning, and key-value memory. Tests agent-specific span types.

## IDE Configs

| File | IDE | Description |
|------|-----|-------------|
| `kiro_agent.json` | Kiro | Agent config with hooks (PreToolUse, PostToolUse, Stop) |
| `claude_code_hooks.json` | Claude Code | Settings with hooks and MCP configs |
| `cursor_mcp.json` | Cursor / VS Code | MCP server config |
| `gemini_cli_mcp.json` | Gemini CLI | MCP server config |

### Using with Kiro

```bash
mkdir -p .kiro/agents
cp demo/kiro_agent.json .kiro/agents/observal-demo.json
```

### Using with Claude Code

```bash
cp demo/claude_code_hooks.json .claude/settings.json
```

### Using with Cursor / VS Code

Copy `demo/cursor_mcp.json` to `.cursor/mcp.json` or `.vscode/mcp.json`.

### Using with Gemini CLI

Copy `demo/gemini_cli_mcp.json` to `.gemini/settings.json`.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OBSERVAL_SERVER` | `http://localhost:8000` | API server URL |
| `OBSERVAL_KEY` | from `~/.observal/config.json` | API key |
| `OBSERVAL_IDE` | `demo` | IDE identifier for telemetry |

## What Gets Captured

After running the demo, you can verify telemetry in ClickHouse:

```sql
-- Span counts by type
SELECT type, count() FROM spans FINAL WHERE is_deleted=0 GROUP BY type ORDER BY count() DESC;

-- Spans by MCP server
SELECT t.mcp_id, count() FROM traces t FINAL JOIN spans s FINAL ON t.trace_id = s.trace_id WHERE t.is_deleted=0 AND s.is_deleted=0 GROUP BY t.mcp_id;

-- Graph-specific columns
SELECT name, hop_count, entities_retrieved, relationships_used FROM spans FINAL WHERE hop_count IS NOT NULL;
```
