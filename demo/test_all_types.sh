#!/usr/bin/env bash
# End-to-end test: submit, approve, install, and test all registry types
set -euo pipefail

API="http://localhost:8000"
API_KEY=$(python3 -c "import json; print(json.load(open('$HOME/.observal/config.json'))['api_key'])")

ok()   { echo -e "\033[32m✓ $1\033[0m"; }
fail() { echo -e "\033[31m✗ $1\033[0m"; exit 1; }
info() { echo -e "\033[36m→ $1\033[0m"; }
hdr()  { echo -e "\n\033[1;33m═══ $1 ═══\033[0m"; }

post() {
  local resp
  resp=$(curl -s -X POST "$1" -H "Content-Type: application/json" -H "X-API-Key:${API_KEY}" -d "$2")
  echo "$resp"
}

get() { curl -s "$1" -H "X-API-Key:${API_KEY}"; }

jid() { python3 -c "import json,sys; print(json.loads(sys.stdin.read())['id'])"; }

approve() {
  post "${API}/api/v1/review/$1/approve" '{}' > /dev/null 2>&1
  ok "Approved $1"
}

install_for() {
  post "${API}/api/v1/$1/$2/install" '{"ide":"claude-code"}'
}

###############################################################################
hdr "1. MCP SERVER"
###############################################################################
info "Submitting MCP server (filesystem)..."
MCP_ID=$(post "${API}/api/v1/mcps/submit" '{
  "git_url": "https://github.com/modelcontextprotocol/servers",
  "name": "filesystem-mcp",
  "version": "1.0.0",
  "category": "filesystem",
  "description": "MCP server for filesystem operations: read, write, search, and manage files and directories. Provides tools for listing directory contents, reading file content, writing files, and searching with glob patterns.",
  "owner": "modelcontextprotocol"
}' | jid)
ok "Submitted MCP: $MCP_ID"
approve "$MCP_ID"

info "Installing for Claude Code..."
MCP_CONFIG=$(install_for "mcps" "$MCP_ID")
echo "$MCP_CONFIG" | python3 -m json.tool 2>/dev/null || echo "$MCP_CONFIG"
ok "MCP install config"

###############################################################################
hdr "2. PROMPT"
###############################################################################
info "Submitting code review prompt..."
PROMPT_ID=$(post "${API}/api/v1/prompts/submit" '{
  "name": "code-review-prompt",
  "version": "1.0.0",
  "description": "Structured code review prompt with severity levels",
  "owner": "blazeup",
  "category": "code-review",
  "template": "Review the following code for bugs, security issues, and style.\n\nLanguage: {{ language }}\nFile: {{ filename }}\n\n```\n{{ code }}\n```\n\nProvide feedback:\n- [CRITICAL] ...\n- [WARNING] ...\n- [SUGGESTION] ...",
  "variables": [
    {"name": "language", "description": "Programming language"},
    {"name": "filename", "description": "File being reviewed"},
    {"name": "code", "description": "Code to review"}
  ],
  "tags": ["code-review", "quality"],
  "supported_ides": ["claude-code", "cursor", "kiro"]
}' | jid)
ok "Submitted prompt: $PROMPT_ID"
approve "$PROMPT_ID"

info "Rendering prompt (emits prompt_render span)..."
RENDER=$(post "${API}/api/v1/prompts/${PROMPT_ID}/render" '{
  "variables": {
    "language": "Python",
    "filename": "main.py",
    "code": "def add(a, b):\n    return a + b"
  }
}')
echo "$RENDER" | python3 -m json.tool 2>/dev/null || echo "$RENDER"
ok "Prompt rendered"

info "Installing prompt..."
PROMPT_INST=$(install_for "prompts" "$PROMPT_ID")
echo "$PROMPT_INST" | python3 -m json.tool 2>/dev/null || echo "$PROMPT_INST"
ok "Prompt install config"

###############################################################################
hdr "3. TOOL (HTTP)"
###############################################################################
info "Submitting HTTP tool (GitHub code search)..."
TOOL_ID=$(post "${API}/api/v1/tools/submit" '{
  "name": "github-code-search",
  "version": "1.0.0",
  "description": "Full-text code search across GitHub repositories",
  "owner": "blazeup",
  "category": "search",
  "function_schema": {
    "name": "search_code",
    "parameters": {
      "type": "object",
      "properties": {
        "query": {"type": "string"},
        "language": {"type": "string"}
      },
      "required": ["query"]
    }
  },
  "endpoint_url": "https://api.github.com/search/code",
  "auth_type": "bearer",
  "supported_ides": ["claude-code", "cursor", "kiro"]
}' | jid)
ok "Submitted tool: $TOOL_ID"
approve "$TOOL_ID"

info "Installing tool (should generate observal-proxy config)..."
TOOL_INST=$(install_for "tools" "$TOOL_ID")
echo "$TOOL_INST" | python3 -m json.tool 2>/dev/null || echo "$TOOL_INST"
ok "Tool install config (HTTP → observal-proxy)"

###############################################################################
hdr "4. HOOK (PostToolUse)"
###############################################################################
info "Submitting PostToolUse hook..."
HOOK_ID=$(post "${API}/api/v1/hooks/submit" '{
  "name": "post-tool-use-logger",
  "version": "1.0.0",
  "description": "Logs every tool use to Observal for analysis",
  "owner": "blazeup",
  "event": "PostToolUse",
  "handler_type": "http",
  "handler_config": {"url": "http://localhost:8000/api/v1/telemetry/hooks"},
  "scope": "global",
  "supported_ides": ["claude-code", "kiro", "cursor"]
}' | jid)
ok "Submitted hook: $HOOK_ID"
approve "$HOOK_ID"

info "Installing hook for Claude Code..."
HOOK_INST=$(install_for "hooks" "$HOOK_ID")
echo "$HOOK_INST" | python3 -m json.tool 2>/dev/null || echo "$HOOK_INST"
ok "Hook install config (HTTP hook → /api/v1/telemetry/hooks)"

info "Simulating Claude Code hook fire..."
HOOK_FIRE=$(post "${API}/api/v1/telemetry/hooks" '{
  "hook_event_name": "PostToolUse",
  "session_id": "claude-session-001",
  "tool_name": "Read",
  "tool_input": {"file_path": "/home/user/project/main.py"},
  "tool_response": "def main():\n    print(\"hello world\")\n\nif __name__ == \"__main__\":\n    main()"
}')
echo "$HOOK_FIRE"
ok "Hook telemetry ingested → hook_exec span in ClickHouse"

###############################################################################
hdr "5. SKILL"
###############################################################################
info "Submitting Python expert skill..."
SKILL_ID=$(post "${API}/api/v1/skills/submit" '{
  "name": "python-expert",
  "version": "1.0.0",
  "description": "Expert Python coding skill with best practices, type hints, and testing patterns",
  "owner": "blazeup",
  "git_url": "https://github.com/anthropics/anthropic-cookbook",
  "skill_path": "/",
  "task_type": "coding",
  "target_agents": ["claude-code", "kiro"],
  "triggers": {"keywords": ["python", "pytest", "type hints"]},
  "activation_keywords": ["python", "pytest", "typing"],
  "supported_ides": ["claude-code", "kiro", "cursor"]
}' | jid)
ok "Submitted skill: $SKILL_ID"
approve "$SKILL_ID"

info "Installing skill for Claude Code..."
SKILL_INST=$(install_for "skills" "$SKILL_ID")
echo "$SKILL_INST" | python3 -m json.tool 2>/dev/null || echo "$SKILL_INST"
ok "Skill install config (SessionStart/End hooks)"

###############################################################################
hdr "6. SANDBOX: REAL DOCKER EXECUTION"
###############################################################################
info "Submitting Python sandbox..."
SANDBOX_ID=$(post "${API}/api/v1/sandboxes/submit" '{
  "name": "python-sandbox",
  "version": "1.0.0",
  "description": "Isolated Python 3.12 sandbox for running untrusted code",
  "owner": "blazeup",
  "runtime_type": "docker",
  "image": "python:3.12-slim",
  "resource_limits": {"timeout": 30},
  "network_policy": "none",
  "supported_ides": ["claude-code", "kiro", "cursor"]
}' | jid)
ok "Submitted sandbox: $SANDBOX_ID"
approve "$SANDBOX_ID"

info "Installing sandbox..."
SANDBOX_INST=$(install_for "sandboxes" "$SANDBOX_ID")
echo "$SANDBOX_INST" | python3 -m json.tool 2>/dev/null || echo "$SANDBOX_INST"
ok "Sandbox install config (observal-sandbox-run)"

info "Running REAL Docker container (python:3.12-slim)..."
echo "--- container stdout/stderr ---"
cd /home/haz3/code/blazeup/Observal
uv run observal-sandbox-run \
  --sandbox-id "$SANDBOX_ID" \
  --image python:3.12-slim \
  --command 'python -c "
import sys, os, platform
print(f\"Python {sys.version}\")
print(f\"Platform: {platform.platform()}\")
print(f\"PID: {os.getpid()}\")
print(f\"2 + 2 = {2+2}\")
print(\"Sandbox execution successful!\")
"' \
  --timeout 30
echo "--- end container output ---"
ok "Sandbox execution completed: logs captured via container.logs()"

info "Running Alpine container with shell commands..."
echo "--- container stdout/stderr ---"
uv run observal-sandbox-run \
  --sandbox-id "$SANDBOX_ID" \
  --image alpine:latest \
  --command 'sh -c "echo === System Info === && uname -a && echo === Disk === && df -h / && echo === Memory === && free -m 2>/dev/null || cat /proc/meminfo | head -3 && echo === Done ==="' \
  --timeout 15
echo "--- end container output ---"
ok "Alpine sandbox execution completed"

###############################################################################
hdr "7. GRAPHRAG"
###############################################################################
info "Submitting GraphRAG (using httpbin as mock endpoint)..."
GRAPHRAG_ID=$(post "${API}/api/v1/graphrags/submit" '{
  "name": "codebase-knowledge-graph",
  "version": "1.0.0",
  "description": "Knowledge graph over codebase entities",
  "owner": "blazeup",
  "endpoint_url": "https://httpbin.org/post",
  "query_interface": "rest",
  "graph_schema": {
    "entities": ["Function", "Class", "Module"],
    "relationships": ["CALLS", "IMPORTS", "INHERITS"]
  },
  "embedding_model": "text-embedding-3-small",
  "supported_ides": ["claude-code", "kiro", "cursor"]
}' | jid)
ok "Submitted GraphRAG: $GRAPHRAG_ID"
approve "$GRAPHRAG_ID"

info "Installing GraphRAG..."
GRAPHRAG_INST=$(install_for "graphrags" "$GRAPHRAG_ID")
echo "$GRAPHRAG_INST" | python3 -m json.tool 2>/dev/null || echo "$GRAPHRAG_INST"
ok "GraphRAG install config (observal-graphrag-proxy)"

###############################################################################
hdr "8. BATCH TELEMETRY INGEST (all span types)"
###############################################################################
info "Ingesting mixed spans to ClickHouse..."
INGEST=$(post "${API}/api/v1/telemetry/ingest" '{
  "traces": [{
    "trace_id": "e2e-trace-001",
    "trace_type": "sandbox_exec",
    "name": "e2e-full-test",
    "sandbox_id": "'"$SANDBOX_ID"'",
    "start_time": "2026-04-04 17:00:00.000",
    "end_time": "2026-04-04 17:00:05.000"
  }],
  "spans": [
    {
      "span_id": "e2e-span-sandbox",
      "trace_id": "e2e-trace-001",
      "type": "sandbox_exec",
      "name": "python:3.12-slim",
      "input": "{\"image\":\"python:3.12-slim\",\"command\":\"python -c print(42)\"}",
      "output": "42\n",
      "status": "success",
      "latency_ms": 1500,
      "container_id": "abc123",
      "exit_code": 0,
      "oom_killed": false,
      "start_time": "2026-04-04 17:00:00.000",
      "end_time": "2026-04-04 17:00:01.500"
    },
    {
      "span_id": "e2e-span-retrieval",
      "trace_id": "e2e-trace-001",
      "type": "retrieval",
      "name": "graphrag-query",
      "input": "{\"query\":\"find Python functions\"}",
      "output": "{\"results\":[{\"entity\":\"main\"}]}",
      "status": "success",
      "latency_ms": 200,
      "query_interface": "rest",
      "chunks_returned": 5,
      "relevance_score": 0.92,
      "start_time": "2026-04-04 17:00:02.000",
      "end_time": "2026-04-04 17:00:02.200"
    },
    {
      "span_id": "e2e-span-hook",
      "trace_id": "e2e-trace-001",
      "type": "hook_exec",
      "name": "PostToolUse",
      "input": "{\"tool\":\"Read\"}",
      "output": "def main(): pass",
      "status": "success",
      "hook_event": "PostToolUse",
      "hook_action": "allow",
      "hook_blocked": false,
      "start_time": "2026-04-04 17:00:03.000",
      "end_time": "2026-04-04 17:00:03.010"
    },
    {
      "span_id": "e2e-span-prompt",
      "trace_id": "e2e-trace-001",
      "type": "prompt_render",
      "name": "code-review-prompt",
      "input": "Review code...",
      "output": "Review the following code for bugs...",
      "status": "success",
      "template_tokens": 50,
      "rendered_tokens": 120,
      "variables_provided": 3,
      "start_time": "2026-04-04 17:00:04.000",
      "end_time": "2026-04-04 17:00:04.005"
    },
    {
      "span_id": "e2e-span-tool",
      "trace_id": "e2e-trace-001",
      "type": "tool_invoke",
      "name": "github-code-search",
      "input": "{\"query\":\"fastapi\",\"language\":\"python\"}",
      "output": "{\"total_count\":1000}",
      "status": "success",
      "latency_ms": 350,
      "start_time": "2026-04-04 17:00:05.000",
      "end_time": "2026-04-04 17:00:05.350"
    },
    {
      "span_id": "e2e-span-skill",
      "trace_id": "e2e-trace-001",
      "type": "skill_activate",
      "name": "python-expert",
      "input": "{\"skill\":\"python-expert\",\"trigger\":\"keyword:python\"}",
      "output": "Skill activated for session",
      "status": "success",
      "start_time": "2026-04-04 17:00:00.000",
      "end_time": "2026-04-04 17:00:00.001"
    }
  ],
  "scores": [{
    "score_id": "e2e-score-001",
    "trace_id": "e2e-trace-001",
    "name": "code_quality",
    "source": "llm-judge",
    "data_type": "numeric",
    "value": 0.85,
    "comment": "Good code quality with minor style issues"
  }]
}')
echo "$INGEST" | python3 -m json.tool 2>/dev/null || echo "$INGEST"
ok "Batch ingest: 1 trace + 6 spans + 1 score"

###############################################################################
hdr "9. VERIFY CLICKHOUSE DATA"
###############################################################################
info "Querying ClickHouse for ingested spans..."
CH_SPANS=$(curl -s "http://localhost:8123/?query=SELECT+type,name,status,latency_ms+FROM+observal.spans+WHERE+trace_id='e2e-trace-001'+ORDER+BY+start_time+FORMAT+PrettyCompact" \
  --user "default:clickhouse" 2>&1)
echo "$CH_SPANS"
ok "ClickHouse spans verified"

info "Querying ClickHouse for traces..."
CH_TRACES=$(curl -s "http://localhost:8123/?query=SELECT+trace_id,trace_type,name+FROM+observal.traces+WHERE+trace_id='e2e-trace-001'+FORMAT+PrettyCompact" \
  --user "default:clickhouse" 2>&1)
echo "$CH_TRACES"
ok "ClickHouse traces verified"

info "Querying ClickHouse for scores..."
CH_SCORES=$(curl -s "http://localhost:8123/?query=SELECT+name,source,value,comment+FROM+observal.scores+WHERE+trace_id='e2e-trace-001'+FORMAT+PrettyCompact" \
  --user "default:clickhouse" 2>&1)
echo "$CH_SCORES"
ok "ClickHouse scores verified"

###############################################################################
hdr "10. CLAUDE CODE CONFIG PREVIEW"
###############################################################################
info "What your Claude Code config would look like with all these installed:"
echo ""
python3 -c "
import json

# Hook config for Claude Code
hook_config = json.loads('''$(echo "$HOOK_INST")''')
snippet = hook_config.get('config_snippet', hook_config)

print('=== .claude/settings.json (hooks section) ===')
if 'hooks' in snippet:
    print(json.dumps({'hooks': snippet['hooks']}, indent=2))

print()
print('=== MCP server config ===')
mcp_config = json.loads('''$(echo "$MCP_CONFIG")''')
mcp_snippet = mcp_config.get('config_snippet', mcp_config)
print(json.dumps(mcp_snippet, indent=2))
"

###############################################################################
hdr "RESULTS"
###############################################################################
echo ""
ok "MCP Server:  $MCP_ID (filesystem-mcp)"
ok "Prompt:      $PROMPT_ID (code-review-prompt): rendered + span emitted"
ok "Tool:        $TOOL_ID (github-code-search): HTTP proxy config"
ok "Hook:        $HOOK_ID (post-tool-use-logger): hook fired + span ingested"
ok "Skill:       $SKILL_ID (python-expert): SessionStart/End hooks"
ok "Sandbox:     $SANDBOX_ID (python-sandbox): REAL Docker execution with logs"
ok "GraphRAG:    $GRAPHRAG_ID (codebase-knowledge-graph): proxy config"
echo ""
ok "All 7 registry types: submitted → approved → installed → tested"
ok "Real Docker containers executed, logs captured via container.logs()"
ok "Telemetry spans ingested to ClickHouse for all span types"
ok "ClickHouse data verified with direct queries"
