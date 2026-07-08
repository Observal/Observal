#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Observal Contributor
# SPDX-License-Identifier: AGPL-3.0-only

# E2E test: Agent CLI authoring flow (init + add + build + publish)
# This test validates the full CLI workflow for creating and publishing agents.
# Run with: bash demo/test_agent_authoring.sh
# Prerequisites: Docker stack running, CLI installed, user logged in
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

###############################################################################
hdr "Step 0: Prerequisite - Create MCP and Skill for agent components"
###############################################################################

info "Submitting MCP server..."
MCP_ID=$(post "${API}/api/v1/mcps/submit" '{
  "git_url": "https://github.com/modelcontextprotocol/servers",
  "name": "test-filesystem-mcp",
  "version": "1.0.0",
  "category": "filesystem",
  "description": "Test MCP server for filesystem operations",
  "owner": "test-owner"
}' | jid)
ok "Submitted MCP: $MCP_ID"
approve "$MCP_ID"

info "Submitting Skill..."
SKILL_ID=$(post "${API}/api/v1/skills/submit" '{
  "name": "test-python-skill",
  "version": "1.0.0",
  "description": "Test Python skill for agent",
  "owner": "test-owner",
  "git_url": "https://github.com/anthropics/anthropic-cookbook",
  "skill_path": "/",
  "task_type": "coding",
  "target_ides": ["claude-code", "kiro"],
  "supported_ides": ["claude-code", "kiro", "cursor"]
}' | jid)
ok "Submitted Skill: $SKILL_ID"
approve "$SKILL_ID"

###############################################################################
hdr "Step 1: Agent Init - Create observal-agent.yaml locally"
###############################################################################

TEST_DIR=$(mktemp -d)
cd "$TEST_DIR"

info "Running observal agent init..."
echo -e "test-agent\n1.0.0\nTest agent description\ntest-owner\nclaude-sonnet-4\nYou are a helpful coding agent." | \
  uv run observal agent init --dir "$TEST_DIR" 2>/dev/null || true

if [ -f "$TEST_DIR/observal-agent.yaml" ]; then
  ok "observal-agent.yaml created"
  cat "$TEST_DIR/observal-agent.yaml"
else
  fail "observal-agent.yaml not created"
fi

###############################################################################
hdr "Step 2: Agent Add - Add MCP and Skill components"
###############################################################################

info "Adding MCP component..."
uv run observal agent add mcp "$MCP_ID" --dir "$TEST_DIR" > /dev/null 2>&1 || true

info "Adding Skill component..."
uv run observal agent add skill "$SKILL_ID" --dir "$TEST_DIR" > /dev/null 2>&1 || true

COMPONENT_COUNT=$(python3 -c "import yaml; data = yaml.safe_load(open('$TEST_DIR/observal-agent.yaml')); print(len(data.get('components', [])))")
if [ "$COMPONENT_COUNT" -eq 2 ]; then
  ok "Added 2 components to YAML"
else
  fail "Expected 2 components, found $COMPONENT_COUNT"
fi

cat "$TEST_DIR/observal-agent.yaml"

###############################################################################
hdr "Step 3: Agent Build - Validate components against server"
###############################################################################

info "Running observal agent build..."
BUILD_OUTPUT=$(uv run observal agent build --dir "$TEST_DIR" 2>&1 || true)
echo "$BUILD_OUTPUT"

if echo "$BUILD_OUTPUT" | grep -q "All components valid"; then
  ok "Build validation passed"
else
  fail "Build validation failed"
fi

###############################################################################
hdr "Step 4: Agent Publish - Submit to server"
###############################################################################

info "Running observal agent publish..."
PUBLISH_OUTPUT=$(uv run observal agent publish --dir "$TEST_DIR" 2>&1 || true)
echo "$PUBLISH_OUTPUT"

AGENT_ID=$(echo "$PUBLISH_OUTPUT" | grep -oE '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' | head -1)

if [ -n "$AGENT_ID" ]; then
  ok "Agent published with ID: $AGENT_ID"
else
  # Try alternative pattern
  AGENT_ID=$(echo "$PUBLISH_OUTPUT" | grep -oE 'ID: [0-9a-f-]+' | awk '{print $2}' | head -1)
  if [ -n "$AGENT_ID" ]; then
    ok "Agent published with ID: $AGENT_ID"
  else
    fail "Could not extract agent ID from output"
  fi
fi

###############################################################################
hdr "Step 5: Verify agent exists on server"
###############################################################################

info "Fetching agent from server..."
AGENT_DATA=$(get "${API}/api/v1/agents/${AGENT_ID}")
AGENT_NAME=$(python3 -c "import json,sys; print(json.load(sys.stdin)['name'])" <<< "$AGENT_DATA")

if [ "$AGENT_NAME" = "test-agent" ]; then
  ok "Agent retrieved from server: $AGENT_NAME"
else
  fail "Agent name mismatch"
fi

echo "$AGENT_DATA" | python3 -m json.tool 2>/dev/null || echo "$AGENT_DATA"

###############################################################################
hdr "Step 6: Agent Install - Generate IDE config"
###############################################################################

info "Installing agent for Claude Code..."
INSTALL_DATA=$(post "${API}/api/v1/agents/${AGENT_ID}/install" '{"ide":"claude-code"}')
echo "$INSTALL_DATA" | python3 -m json.tool 2>/dev/null || echo "$INSTALL_DATA"
ok "Agent install config generated"

###############################################################################
hdr "Step 7: Update existing agent (--update flag)"
###############################################################################

# Modify the YAML
python3 -c "
import yaml
with open('$TEST_DIR/observal-agent.yaml', 'r') as f:
    data = yaml.safe_load(f)
data['description'] = 'Updated description for testing update flow'
data['version'] = '1.0.1'
with open('$TEST_DIR/observal-agent.yaml', 'w') as f:
    yaml.dump(data, f, default_flow_style=False, sort_keys=False)
"

info "Running observal agent publish --update..."
UPDATE_OUTPUT=$(uv run observal agent publish --dir "$TEST_DIR" --update 2>&1 || true)
echo "$UPDATE_OUTPUT"

if echo "$UPDATE_OUTPUT" | grep -q "Agent updated"; then
  ok "Agent updated successfully"
else
  fail "Agent update failed"
fi

###############################################################################
hdr "Step 8: Create draft agent"
###############################################################################

info "Creating draft agent..."
DRAFT_OUTPUT=$(uv run observal agent publish --dir "$TEST_DIR" --draft 2>&1 || true)
echo "$DRAFT_OUTPUT"

DRAFT_ID=$(echo "$DRAFT_OUTPUT" | grep -oE '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' | head -1)

if [ -n "$DRAFT_ID" ]; then
  ok "Draft agent created: $DRAFT_ID"
else
  fail "Could not extract draft ID"
fi

###############################################################################
hdr "Step 9: Submit draft for review"
###############################################################################

info "Submitting draft for review..."
SUBMIT_OUTPUT=$(uv run observal agent publish --submit "$DRAFT_ID" 2>&1 || true)
echo "$SUBMIT_OUTPUT"

if echo "$SUBMIT_OUTPUT" | grep -q "Draft submitted for review"; then
  ok "Draft submitted for review"
else
  fail "Draft submission failed"
fi

###############################################################################
hdr "RESULTS"
###############################################################################

echo ""
ok "Agent Init:        observal-agent.yaml created locally"
ok "Agent Add:         MCP and Skill added to YAML"
ok "Agent Build:       Components validated against server"
ok "Agent Publish:     New agent submitted for review"
ok "Agent Retrieve:    Agent fetched from server"
ok "Agent Install:     IDE config generated"
ok "Agent Update:      Existing agent updated (--update)"
ok "Agent Draft:       Draft agent created (--draft)"
ok "Draft Submit:      Draft submitted for review"
echo ""
ok "Full authoring flow tested!"
info "Test directory: $TEST_DIR"