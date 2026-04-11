#!/usr/bin/env bash
set -euo pipefail

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

info()  { echo -e "${CYAN}[info]${NC}  $*"; }
ok()    { echo -e "${GREEN}[ok]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC}  $*"; }
fail()  { echo -e "${RED}[fail]${NC}  $*"; }
header(){ echo -e "\n${BOLD}=== $* ===${NC}\n"; }

DEMO_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$DEMO_DIR")"

OBSERVAL_SERVER="${OBSERVAL_SERVER:-http://localhost:8000}"
export OBSERVAL_SERVER

CLAUDE_DIR="$HOME/.claude"
PLUGINS_CACHE="$CLAUDE_DIR/plugins/cache/claude-plugins-official"
AGENTS_DIR="$CLAUDE_DIR/agents"
SETTINGS_FILE="$CLAUDE_DIR/settings.json"

# Track registered IDs for agent composition
declare -A MCP_IDS
declare -A SKILL_IDS
AGENT_ID=""
PASS=0
FAIL_COUNT=0

# --- Helpers ---

die() { fail "$@"; exit 1; }

check_cmd() {
    command -v "$1" &>/dev/null || die "'$1' not found in PATH"
}

api_get() {
    curl -sf "$1" -H "X-API-Key:${OBSERVAL_KEY}" 2>/dev/null
}

api_post() {
    curl -sf -X POST "$1" -H "Content-Type: application/json" -H "X-API-Key:${OBSERVAL_KEY}" -d "$2" 2>/dev/null
}

track_result() {
    if [ $? -eq 0 ]; then
        ok "$1"
        PASS=$((PASS + 1))
    else
        fail "$1"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
}

# ─── Phase 0: Preflight ──────────────────────────────────────

header "Phase 0: Preflight Checks"

check_cmd observal
check_cmd jq
check_cmd curl
check_cmd python3
ok "Required commands found"

# Check Docker stack
if curl -sf "${OBSERVAL_SERVER}/health" > /dev/null 2>&1; then
    ok "API server reachable at ${OBSERVAL_SERVER}"
else
    die "API server not reachable at ${OBSERVAL_SERVER}. Is the Docker stack running?"
fi

# Check Claude Code setup exists
if [ ! -d "$CLAUDE_DIR" ]; then
    die "~/.claude directory not found. This demo requires a real Claude Code setup."
fi

if [ ! -f "$SETTINGS_FILE" ]; then
    die "~/.claude/settings.json not found. Configure Claude Code first."
fi

ok "~/.claude setup detected"

# Discover enabled plugins
ENABLED_PLUGINS=$(python3 -c "
import json, sys
with open('$SETTINGS_FILE') as f:
    settings = json.load(f)
plugins = settings.get('enabledPlugins', {})
for name, enabled in plugins.items():
    if enabled:
        # Extract plugin name from 'name@source' format
        print(name.split('@')[0])
" 2>/dev/null || true)

if [ -z "$ENABLED_PLUGINS" ]; then
    die "No enabled plugins found in ~/.claude/settings.json"
fi

info "Discovered enabled plugins:"
echo "$ENABLED_PLUGINS" | while read -r p; do echo "  - $p"; done

# Categorize plugins as MCP servers or skills by checking plugin.json
MCP_PLUGINS=""
SKILL_PLUGINS=""

for plugin in $ENABLED_PLUGINS; do
    # Find the plugin.json to check type
    PJSON=$(find "$HOME/.claude/plugins/cache/" -path "*/$plugin/*/.claude-plugin/plugin.json" 2>/dev/null | head -1)
    if [ -z "$PJSON" ]; then
        PJSON=$(find "$HOME/.claude/plugins/cache/" -path "*/$plugin/*/plugin.json" 2>/dev/null | head -1)
    fi

    if [ -z "$PJSON" ]; then
        warn "No plugin.json found for $plugin — skipping"
        continue
    fi

    DESC=$(python3 -c "import json; print(json.load(open('$PJSON')).get('description',''))" 2>/dev/null || echo "")

    # Heuristic: MCP servers mention "MCP" or "server" in description, or are known MCP types
    case "$plugin" in
        context7|playwright|github|telegram|typescript-lsp)
            MCP_PLUGINS="$MCP_PLUGINS $plugin"
            ;;
        frontend-design|superpowers|skill-creator|impeccable)
            SKILL_PLUGINS="$SKILL_PLUGINS $plugin"
            ;;
        *)
            # Fall back to description heuristic
            if echo "$DESC" | grep -qi "mcp\|server\|automation"; then
                MCP_PLUGINS="$MCP_PLUGINS $plugin"
            else
                SKILL_PLUGINS="$SKILL_PLUGINS $plugin"
            fi
            ;;
    esac
done

info "MCP servers:${MCP_PLUGINS:-  (none)}"
info "Skills:${SKILL_PLUGINS:-  (none)}"

# Count agents
AGENT_COUNT=0
if [ -d "$AGENTS_DIR" ]; then
    AGENT_COUNT=$(ls "$AGENTS_DIR"/*.md 2>/dev/null | wc -l)
fi
info "Agent definitions: $AGENT_COUNT in ~/.claude/agents/"

# ─── Phase 1: Authentication ─────────────────────────────────

header "Phase 1: Authentication"

if [ -n "${OBSERVAL_KEY:-}" ]; then
    ok "Using OBSERVAL_KEY from environment"
elif [ -f "$HOME/.observal/config.json" ]; then
    OBSERVAL_KEY="$(jq -r '.api_key // empty' "$HOME/.observal/config.json" 2>/dev/null)"
    if [ -n "$OBSERVAL_KEY" ]; then
        ok "Loaded API key from ~/.observal/config.json"
    fi
fi

if [ -z "${OBSERVAL_KEY:-}" ]; then
    info "No API key found. Checking if server needs bootstrap..."
    INITIALIZED=$(curl -sf "${OBSERVAL_SERVER}/health" | python3 -c "import json,sys; print(json.load(sys.stdin).get('initialized', True))" 2>/dev/null || echo "True")

    if [ "$INITIALIZED" = "False" ]; then
        info "Fresh server — auto-bootstrapping admin..."
        BOOT_RESP=$(curl -sf -X POST "${OBSERVAL_SERVER}/api/v1/auth/bootstrap" 2>/dev/null)
        OBSERVAL_KEY=$(echo "$BOOT_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['api_key'])" 2>/dev/null)
        if [ -n "$OBSERVAL_KEY" ]; then
            # Save to config
            mkdir -p "$HOME/.observal"
            echo "{\"server_url\": \"${OBSERVAL_SERVER}\", \"api_key\": \"${OBSERVAL_KEY}\"}" > "$HOME/.observal/config.json"
            ok "Admin account bootstrapped"
        else
            die "Bootstrap failed — could not extract API key"
        fi
    else
        die "Server is initialized but no API key found. Run: observal auth login"
    fi
fi

export OBSERVAL_KEY

# Verify auth works
WHOAMI=$(api_get "${OBSERVAL_SERVER}/api/v1/auth/whoami")
if [ -n "$WHOAMI" ]; then
    USER_NAME=$(echo "$WHOAMI" | python3 -c "import json,sys; print(json.load(sys.stdin).get('name','?'))" 2>/dev/null)
    ok "Authenticated as: $USER_NAME"
    PASS=$((PASS + 1))
else
    fail "Auth verification failed"
    FAIL_COUNT=$((FAIL_COUNT + 1))
fi

# ─── Phase 2: Register MCP Servers ───────────────────────────

header "Phase 2: Register MCP Servers"

# Known GitHub URLs for common MCP servers
declare -A MCP_URLS
MCP_URLS[context7]="https://github.com/nicepkg/context7"
MCP_URLS[playwright]="https://github.com/nicepkg/context7"
MCP_URLS[github]="https://github.com/nicepkg/context7"
MCP_URLS[telegram]="https://github.com/nicepkg/context7"
MCP_URLS[typescript-lsp]="https://github.com/nicepkg/context7"

declare -A MCP_CATEGORIES
MCP_CATEGORIES[context7]="documentation"
MCP_CATEGORIES[playwright]="testing"
MCP_CATEGORIES[github]="development"
MCP_CATEGORIES[telegram]="communication"
MCP_CATEGORIES[typescript-lsp]="development"

for plugin in $MCP_PLUGINS; do
    plugin=$(echo "$plugin" | xargs)  # trim whitespace
    [ -z "$plugin" ] && continue

    # Get description from plugin.json
    PJSON=$(find "$HOME/.claude/plugins/cache/" -path "*/$plugin/*/.claude-plugin/plugin.json" 2>/dev/null | head -1)
    DESC="MCP server: $plugin"
    if [ -n "$PJSON" ]; then
        DESC=$(python3 -c "import json; print(json.load(open('$PJSON')).get('description','MCP server: $plugin'))" 2>/dev/null || echo "MCP server: $plugin")
    fi

    GIT_URL="${MCP_URLS[$plugin]:-}"
    CATEGORY="${MCP_CATEGORIES[$plugin]:-general}"

    info "Registering MCP: $plugin (category: $CATEGORY)"

    PAYLOAD=$(python3 -c "
import json
print(json.dumps({
    'name': '$plugin',
    'description': $(python3 -c "import json; print(json.dumps('$DESC'))" 2>/dev/null),
    'git_url': '$GIT_URL',
    'category': '$CATEGORY',
    'transport': 'stdio'
}))
" 2>/dev/null)

    RESP=$(api_post "${OBSERVAL_SERVER}/api/v1/mcps" "$PAYLOAD" || echo "")
    if [ -n "$RESP" ]; then
        MCP_ID=$(echo "$RESP" | python3 -c "import json,sys; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo "")
        if [ -n "$MCP_ID" ]; then
            MCP_IDS[$plugin]="$MCP_ID"
            ok "Registered $plugin -> $MCP_ID"
            PASS=$((PASS + 1))
        else
            warn "Registered $plugin but could not extract ID"
        fi
    else
        # Might already exist — try to find it
        EXISTING=$(api_get "${OBSERVAL_SERVER}/api/v1/mcps/$plugin" || echo "")
        if [ -n "$EXISTING" ]; then
            MCP_ID=$(echo "$EXISTING" | python3 -c "import json,sys; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo "")
            MCP_IDS[$plugin]="$MCP_ID"
            ok "$plugin already registered -> $MCP_ID"
            PASS=$((PASS + 1))
        else
            fail "Failed to register MCP: $plugin"
            FAIL_COUNT=$((FAIL_COUNT + 1))
        fi
    fi
done

# ─── Phase 3: Register Skills ────────────────────────────────

header "Phase 3: Register Skills"

for plugin in $SKILL_PLUGINS; do
    plugin=$(echo "$plugin" | xargs)
    [ -z "$plugin" ] && continue

    PJSON=$(find "$HOME/.claude/plugins/cache/" -path "*/$plugin/*/.claude-plugin/plugin.json" 2>/dev/null | head -1)
    DESC="Skill: $plugin"
    if [ -n "$PJSON" ]; then
        DESC=$(python3 -c "import json; print(json.load(open('$PJSON')).get('description','Skill: $plugin'))" 2>/dev/null || echo "Skill: $plugin")
    fi

    info "Registering skill: $plugin"

    PAYLOAD=$(python3 -c "
import json
print(json.dumps({
    'name': '$plugin',
    'description': $(python3 -c "import json; print(json.dumps('$DESC'))" 2>/dev/null),
    'content': 'Skill plugin from claude-plugins-official',
    'category': 'general'
}))
" 2>/dev/null)

    RESP=$(api_post "${OBSERVAL_SERVER}/api/v1/skills" "$PAYLOAD" || echo "")
    if [ -n "$RESP" ]; then
        SKILL_ID=$(echo "$RESP" | python3 -c "import json,sys; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo "")
        if [ -n "$SKILL_ID" ]; then
            SKILL_IDS[$plugin]="$SKILL_ID"
            ok "Registered $plugin -> $SKILL_ID"
            PASS=$((PASS + 1))
        else
            warn "Registered $plugin but could not extract ID"
        fi
    else
        EXISTING=$(api_get "${OBSERVAL_SERVER}/api/v1/skills/$plugin" || echo "")
        if [ -n "$EXISTING" ]; then
            SKILL_ID=$(echo "$EXISTING" | python3 -c "import json,sys; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo "")
            SKILL_IDS[$plugin]="$SKILL_ID"
            ok "$plugin already registered -> $SKILL_ID"
            PASS=$((PASS + 1))
        else
            fail "Failed to register skill: $plugin"
            FAIL_COUNT=$((FAIL_COUNT + 1))
        fi
    fi
done

# ─── Phase 4: Approve All Pending ────────────────────────────

header "Phase 4: Admin Review — Approve All"

PENDING=$(api_get "${OBSERVAL_SERVER}/api/v1/review" || echo "[]")
PENDING_COUNT=$(echo "$PENDING" | python3 -c "import json,sys; items=json.load(sys.stdin); print(len(items) if isinstance(items, list) else 0)" 2>/dev/null || echo "0")

if [ "$PENDING_COUNT" -gt 0 ]; then
    info "$PENDING_COUNT items pending review"
    echo "$PENDING" | python3 -c "
import json, sys
items = json.load(sys.stdin)
if isinstance(items, list):
    for item in items:
        print(item.get('id', ''))
" 2>/dev/null | while read -r item_id; do
        [ -z "$item_id" ] && continue
        api_post "${OBSERVAL_SERVER}/api/v1/review/${item_id}/approve" '{}' > /dev/null 2>&1
        ok "Approved $item_id"
    done
    PASS=$((PASS + 1))
else
    info "No items pending review (all already approved)"
    PASS=$((PASS + 1))
fi

# Verify approved items are visible
MCP_LIST=$(api_get "${OBSERVAL_SERVER}/api/v1/mcps" || echo "[]")
MCP_COUNT=$(echo "$MCP_LIST" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d) if isinstance(d,list) else d.get('total',0))" 2>/dev/null || echo "0")
info "MCP servers in registry: $MCP_COUNT"

SKILL_LIST=$(api_get "${OBSERVAL_SERVER}/api/v1/skills" || echo "[]")
SKILL_COUNT=$(echo "$SKILL_LIST" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d) if isinstance(d,list) else d.get('total',0))" 2>/dev/null || echo "0")
info "Skills in registry: $SKILL_COUNT"

# ─── Phase 5: Compose Agent ──────────────────────────────────

header "Phase 5: Compose Agent from Real Components"

# Build component_links from registered IDs
COMPONENTS="[]"
COMP_ARRAY="["
FIRST=true

for plugin in "${!MCP_IDS[@]}"; do
    id="${MCP_IDS[$plugin]}"
    [ -z "$id" ] && continue
    if [ "$FIRST" = true ]; then FIRST=false; else COMP_ARRAY="$COMP_ARRAY,"; fi
    COMP_ARRAY="$COMP_ARRAY{\"type\":\"mcp\",\"id\":\"$id\"}"
done

for plugin in "${!SKILL_IDS[@]}"; do
    id="${SKILL_IDS[$plugin]}"
    [ -z "$id" ] && continue
    if [ "$FIRST" = true ]; then FIRST=false; else COMP_ARRAY="$COMP_ARRAY,"; fi
    COMP_ARRAY="$COMP_ARRAY{\"type\":\"skill\",\"id\":\"$id\"}"
done

COMP_ARRAY="$COMP_ARRAY]"

info "Creating agent with components: $COMP_ARRAY"

AGENT_PAYLOAD=$(python3 -c "
import json
print(json.dumps({
    'name': 'e2e-test-agent',
    'description': 'End-to-end test agent built from real local Claude Code setup',
    'version': '1.0.0',
    'model': 'claude-sonnet-4-6',
    'component_links': json.loads('$COMP_ARRAY')
}))
" 2>/dev/null)

AGENT_RESP=$(api_post "${OBSERVAL_SERVER}/api/v1/agents" "$AGENT_PAYLOAD" || echo "")
if [ -n "$AGENT_RESP" ]; then
    AGENT_ID=$(echo "$AGENT_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo "")
    if [ -n "$AGENT_ID" ]; then
        ok "Agent created -> $AGENT_ID"
        PASS=$((PASS + 1))
    else
        fail "Agent created but could not extract ID"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
else
    # Try to find existing
    EXISTING=$(api_get "${OBSERVAL_SERVER}/api/v1/agents/e2e-test-agent" || echo "")
    if [ -n "$EXISTING" ]; then
        AGENT_ID=$(echo "$EXISTING" | python3 -c "import json,sys; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo "")
        ok "Agent already exists -> $AGENT_ID"
        PASS=$((PASS + 1))
    else
        fail "Failed to create agent"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
fi

# Approve agent if pending
if [ -n "$AGENT_ID" ]; then
    PENDING2=$(api_get "${OBSERVAL_SERVER}/api/v1/review" || echo "[]")
    echo "$PENDING2" | python3 -c "
import json, sys
items = json.load(sys.stdin)
if isinstance(items, list):
    for item in items:
        print(item.get('id', ''))
" 2>/dev/null | while read -r item_id; do
        [ -z "$item_id" ] && continue
        api_post "${OBSERVAL_SERVER}/api/v1/review/${item_id}/approve" '{}' > /dev/null 2>&1
    done
    ok "Approved agent (if pending)"
fi

# ─── Phase 6: Pull Agent ─────────────────────────────────────

header "Phase 6: Pull Agent"

if [ -n "$AGENT_ID" ]; then
    PULL_DIR=$(mktemp -d)

    for ide in cursor vscode claude-code; do
        TARGET="$PULL_DIR/$ide"
        mkdir -p "$TARGET"

        info "Pulling agent for $ide -> $TARGET"
        if observal pull "$AGENT_ID" --ide "$ide" --dir "$TARGET" 2>/dev/null; then
            ok "Pull succeeded for $ide"
            PASS=$((PASS + 1))

            # Verify output files exist
            case "$ide" in
                cursor)
                    if [ -f "$TARGET/.cursor/mcp.json" ]; then
                        ok "  .cursor/mcp.json exists"
                    else
                        warn "  .cursor/mcp.json not found"
                    fi
                    ;;
                vscode)
                    if [ -f "$TARGET/.vscode/mcp.json" ]; then
                        ok "  .vscode/mcp.json exists"
                    else
                        warn "  .vscode/mcp.json not found"
                    fi
                    ;;
                claude-code)
                    if [ -d "$TARGET/.claude" ]; then
                        ok "  .claude/ directory exists"
                    else
                        warn "  .claude/ directory not found"
                    fi
                    ;;
            esac
        else
            fail "Pull failed for $ide"
            FAIL_COUNT=$((FAIL_COUNT + 1))
        fi
    done

    # Clean up
    rm -rf "$PULL_DIR"
else
    warn "Skipping pull — no agent ID"
fi

# ─── Phase 7: Feedback ───────────────────────────────────────

header "Phase 7: Feedback & Rating"

if [ -n "$AGENT_ID" ]; then
    RATE_RESP=$(api_post "${OBSERVAL_SERVER}/api/v1/feedback" "{\"target_id\":\"$AGENT_ID\",\"target_type\":\"agent\",\"stars\":5,\"comment\":\"E2E test — works great\"}" || echo "")
    if [ -n "$RATE_RESP" ]; then
        ok "Rating submitted (5 stars)"
        PASS=$((PASS + 1))
    else
        fail "Failed to submit rating"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi

    FEEDBACK=$(api_get "${OBSERVAL_SERVER}/api/v1/feedback/agent/$AGENT_ID" || echo "")
    if [ -n "$FEEDBACK" ]; then
        ok "Feedback retrieved"
        PASS=$((PASS + 1))
    else
        fail "Failed to retrieve feedback"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
fi

# ─── Phase 8: API Verification ───────────────────────────────

header "Phase 8: API Verification"

# Overview stats
STATS=$(api_get "${OBSERVAL_SERVER}/api/v1/overview/stats" || echo "")
if [ -n "$STATS" ]; then
    ok "GET /overview/stats returned data"
    echo -e "  ${DIM}$(echo "$STATS" | python3 -m json.tool 2>/dev/null | head -10)${NC}"
    PASS=$((PASS + 1))
else
    fail "GET /overview/stats failed"
    FAIL_COUNT=$((FAIL_COUNT + 1))
fi

# Top agents
TOP=$(api_get "${OBSERVAL_SERVER}/api/v1/overview/top-agents" || echo "")
if [ -n "$TOP" ]; then
    ok "GET /overview/top-agents returned data"
    PASS=$((PASS + 1))
else
    fail "GET /overview/top-agents failed"
    FAIL_COUNT=$((FAIL_COUNT + 1))
fi

# Agent list
AGENTS=$(api_get "${OBSERVAL_SERVER}/api/v1/agents" || echo "")
if [ -n "$AGENTS" ]; then
    ok "GET /agents returned data"
    PASS=$((PASS + 1))
else
    fail "GET /agents failed"
    FAIL_COUNT=$((FAIL_COUNT + 1))
fi

# Health
HEALTH=$(curl -sf "${OBSERVAL_SERVER}/health" || echo "")
if [ -n "$HEALTH" ]; then
    ok "GET /health returned data"
    PASS=$((PASS + 1))
else
    fail "GET /health failed"
    FAIL_COUNT=$((FAIL_COUNT + 1))
fi

# ─── Summary ─────────────────────────────────────────────────

header "Summary"

TOTAL=$((PASS + FAIL_COUNT))
echo -e "  Results: ${GREEN}${PASS} passed${NC} / ${RED}${FAIL_COUNT} failed${NC} / ${BOLD}${TOTAL} total${NC}"
echo ""

if [ "$FAIL_COUNT" -eq 0 ]; then
    ok "All checks passed!"
else
    fail "$FAIL_COUNT check(s) failed"
    exit 1
fi
