#!/usr/bin/env bash
set -euo pipefail

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${CYAN}[info]${NC}  $*"; }
ok()    { echo -e "${GREEN}[ok]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC}  $*"; }
fail()  { echo -e "${RED}[fail]${NC}  $*"; }
header(){ echo -e "\n${BOLD}=== $* ===${NC}\n"; }

DEMO_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$DEMO_DIR")"

OBSERVAL_SERVER="${OBSERVAL_SERVER:-http://localhost:8000}"
OBSERVAL_IDE="${OBSERVAL_IDE:-demo}"
export OBSERVAL_SERVER OBSERVAL_IDE

# --- Helpers ---

die() { fail "$@"; exit 1; }

check_cmd() {
    command -v "$1" &>/dev/null || die "'$1' not found in PATH"
}

send_jsonrpc() {
    # Usage: send_jsonrpc <mcp_id> <script> <messages_json_array>
    local mcp_id="$1" script="$2" messages="$3"
    info "Running observal-shim --mcp-id $mcp_id: python3 $script"
    echo "$messages" | jq -c '.[]' | observal-shim --mcp-id "$mcp_id": python3 "$script" > /dev/null 2>&1 || true
    sleep 1
}

# --- Preflight ---

header "Preflight Checks"

check_cmd observal-shim
check_cmd jq
check_cmd curl
ok "Required commands found"

# Check Docker stack
if curl -sf "${OBSERVAL_SERVER}/docs" > /dev/null 2>&1; then
    ok "API server reachable at ${OBSERVAL_SERVER}"
else
    die "API server not reachable at ${OBSERVAL_SERVER}. Is the Docker stack running?"
fi

if curl -sf "http://localhost:8123/?user=default&password=clickhouse&query=SELECT%201&user=default&password=clickhouse" > /dev/null 2>&1; then
    ok "ClickHouse reachable"
else
    die "ClickHouse not reachable on :8123"
fi

# --- Auth ---

header "Authentication"

if [ -n "${OBSERVAL_KEY:-}" ]; then
    ok "Using OBSERVAL_KEY from environment"
elif [ -f "$HOME/.observal/config.json" ]; then
    OBSERVAL_KEY="$(jq -r '.api_key // empty' "$HOME/.observal/config.json")"
    if [ -n "$OBSERVAL_KEY" ]; then
        ok "Loaded API key from ~/.observal/config.json"
    fi
fi

if [ -z "${OBSERVAL_KEY:-}" ]; then
    info "No API key found, running 'observal init'..."
    INIT_OUT="$(observal init 2>&1)" || die "observal init failed: $INIT_OUT"
    OBSERVAL_KEY="$(jq -r '.api_key // empty' "$HOME/.observal/config.json" 2>/dev/null)"
    [ -n "$OBSERVAL_KEY" ] || die "Could not extract API key after init"
    ok "Created admin account"
fi

export OBSERVAL_KEY

# --- Demo: General MCP ---

header "Demo 1: General MCP Server (mock_mcp.py)"

MESSAGES='[
  {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{}}},
  {"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}},
  {"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"echo","arguments":{"text":"hello observal"}}},
  {"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"add","arguments":{"a":17,"b":25}}},
  {"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"read_file","arguments":{"path":"/etc/hostname"}}},
  {"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"search","arguments":{"query":"telemetry"}}},
  {"jsonrpc":"2.0","id":7,"method":"resources/read","params":{"uri":"file:///demo/config.json"}},
  {"jsonrpc":"2.0","id":8,"method":"prompts/get","params":{"name":"summarize","arguments":{"text":"Observal demo"}}},
  {"jsonrpc":"2.0","id":9,"method":"ping","params":{}}
]'

send_jsonrpc "demo-mcp" "$DEMO_DIR/mock_mcp.py" "$MESSAGES"
ok "General MCP demo complete"

# --- Demo: GraphRAG MCP ---

header "Demo 2: GraphRAG MCP Server (mock_graphrag_mcp.py)"

MESSAGES='[
  {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{}}},
  {"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}},
  {"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"graph_query","arguments":{"query":"How does AuthService connect to UserDB?","max_hops":3}}},
  {"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"graph_traverse","arguments":{"entity_id":"e-003","depth":2,"relationship_types":["routes_to","publishes_to"]}}},
  {"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"entity_lookup","arguments":{"name":"Cache"}}},
  {"jsonrpc":"2.0","id":6,"method":"ping","params":{}}
]'

send_jsonrpc "demo-graphrag" "$DEMO_DIR/mock_graphrag_mcp.py" "$MESSAGES"
ok "GraphRAG MCP demo complete"

# --- Demo: Agent MCP ---

header "Demo 3: Multi-Agent MCP Server (mock_agent_mcp.py)"

MESSAGES='[
  {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{}}},
  {"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}},
  {"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"memory_store","arguments":{"key":"project","value":"Observal demo run"}}},
  {"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"memory_retrieve","arguments":{"key":"project"}}},
  {"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"delegate_task","arguments":{"agent_name":"researcher","task":"Find best practices for MCP telemetry"}}},
  {"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"reasoning_step","arguments":{"step":"Evaluate findings","premises":["MCP is JSON-RPC","Shim is transparent","Telemetry is async"]}}},
  {"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"delegate_task","arguments":{"agent_name":"coder","task":"Implement telemetry pipeline","context":"Based on researcher findings"}}},
  {"jsonrpc":"2.0","id":8,"method":"ping","params":{}}
]'

send_jsonrpc "demo-agent" "$DEMO_DIR/mock_agent_mcp.py" "$MESSAGES"
ok "Multi-Agent MCP demo complete"

# --- Query ClickHouse ---

header "Captured Telemetry"

info "Querying ClickHouse for recent spans..."
sleep 2

CH="http://localhost:8123/?user=default&password=clickhouse&database=observal"

SPAN_COUNT="$(curl -sf "${CH}&query=SELECT+count()+FROM+spans+FINAL+WHERE+is_deleted%3D0+FORMAT+TabSeparated" 2>/dev/null || echo '?')"
echo -e "  Total spans in ClickHouse: ${BOLD}${SPAN_COUNT}${NC}"

info "Recent spans by type:"
curl -sf "${CH}" --data "SELECT type, count() as cnt FROM spans FINAL WHERE is_deleted=0 GROUP BY type ORDER BY cnt DESC FORMAT PrettyCompact" \
  2>/dev/null || warn "Could not query ClickHouse"

echo ""
info "Recent spans by MCP:"
curl -sf "${CH}" --data "SELECT t.mcp_id, count() as spans FROM traces t FINAL JOIN spans s FINAL ON t.trace_id = s.trace_id WHERE t.is_deleted=0 AND s.is_deleted=0 GROUP BY t.mcp_id ORDER BY spans DESC FORMAT PrettyCompact" \
  2>/dev/null || warn "Could not query ClickHouse"

# --- Query GraphQL ---

header "GraphQL Trace Query"

info "Querying traces via GraphQL..."
GQL_QUERY='{"query":"{ traces(limit: 5) { items { traceId name mcpId metrics { totalSpans errorCount toolCallCount } } } }"}'
GQL_RESULT="$(curl -sf -X POST "${OBSERVAL_SERVER}/api/v1/graphql" \
  -H "Content-Type: application/json" \
  -d "$GQL_QUERY" 2>/dev/null || echo '{"error":"GraphQL query failed"}')"

echo "$GQL_RESULT" | jq '.' 2>/dev/null || echo "$GQL_RESULT"

# --- Summary ---

header "Demo Summary"

ok "3 mock MCP servers exercised through observal-shim"
ok "Spans captured: initialize, tools/list, tools/call, resources/read, prompts/get, ping"
ok "Graph-specific fields: hop_count, entities_retrieved, relationships_used"
ok "Agent-specific tools: delegate_task, reasoning_step, memory_store, memory_retrieve"
echo ""
info "IDE configs available in demo/:"
echo "  - kiro_agent.json       (Kiro agent with hooks)"
echo "  - claude_code_hooks.json (Claude Code hooks)"
echo "  - cursor_mcp.json       (Cursor/VS Code MCP config)"
echo "  - gemini_cli_mcp.json   (Gemini CLI MCP config)"
echo ""
ok "Demo complete!"
