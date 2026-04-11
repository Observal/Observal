# Observal End-to-End Integration Test

You are testing Observal, a self-hosted AI agent registry. Your job is to set it up from scratch, register real components from the local `~/.claude` setup, compose agents, and verify the full workflow end-to-end. **No mocking.** Everything runs for real against a live local instance.

If anything fails or is broken, create a GitHub issue for it using `gh issue create --repo BlazeUp-AI/Observal` with appropriate labels. Keep going past failures — document all of them.

---

## Phase 0: Setup

### 0a. Clone and configure

```bash
cd /tmp
git clone https://github.com/BlazeUp-AI/Observal.git
cd Observal
cp .env.example .env
```

Edit `.env` — set real values:
```
DATABASE_URL=postgresql+asyncpg://postgres:observal-test@observal-db:5432/observal
CLICKHOUSE_URL=clickhouse://default:clickhouse@observal-clickhouse:8123/observal
POSTGRES_USER=postgres
POSTGRES_PASSWORD=observal-test
SECRET_KEY=test-secret-key-change-me-in-prod
CLICKHOUSE_USER=default
CLICKHOUSE_PASSWORD=clickhouse
```

### 0b. Start services

```bash
cd docker && docker compose up --build -d && cd ..
```

Wait for services to be healthy:
```bash
docker compose -f docker/docker-compose.yml ps
```

Retry for up to 2 minutes if services are still starting. The API must respond before proceeding:
```bash
curl -sf http://localhost:8000/health
```

### 0c. Install CLI

```bash
uv tool install --editable .
```

### 0d. Authenticate

```bash
observal auth login
```

On a fresh server, this auto-detects that no users exist and bootstraps an admin account automatically — no prompts, no API key dance. Your credentials are saved to `~/.observal/config.json`.

Verify:
```bash
observal auth whoami  # verify you're logged in
observal auth status  # verify server connectivity
```

**If any step in Phase 0 fails, create a GitHub issue and stop.**

---

## Phase 1: Discover Real MCP Servers

Read the local Claude Code setup to discover what's installed:

```bash
# Check what plugins are enabled
cat ~/.claude/settings.json | python3 -c "
import json, sys
settings = json.load(sys.stdin)
for name, enabled in settings.get('enabledPlugins', {}).items():
    if enabled:
        print(name.split('@')[0])
"
```

This should show plugins like: context7, playwright, github, telegram, frontend-design, superpowers, skill-creator, typescript-lsp, impeccable.

Read the plugin descriptions:
```bash
find ~/.claude/plugins/cache/ -name "plugin.json" -path "*/.claude-plugin/*" | while read f; do
    echo "=== $(python3 -c "import json; print(json.load(open('$f'))['name'])") ==="
    python3 -c "import json; print(json.load(open('$f'))['description'])"
done
```

Also check for agent definitions:
```bash
ls ~/.claude/agents/
```

---

## Phase 2: Register MCP Servers

Register the MCP servers discovered from `~/.claude`. These are real servers the user actually uses.

For each MCP server (context7, playwright, github, telegram, typescript-lsp), register it:

```bash
# Example for context7
observal registry mcp submit https://github.com/upstash/context7 \
    --name context7 \
    --category documentation \
    --yes

# Example for playwright
observal registry mcp submit https://github.com/microsoft/playwright-mcp \
    --name playwright \
    --category testing \
    --yes
```

If `registry mcp submit` doesn't accept a git URL, use the API directly:
```bash
curl -X POST http://localhost:8000/api/v1/mcps \
    -H "Content-Type: application/json" \
    -H "X-API-Key: $(jq -r .api_key ~/.observal/config.json)" \
    -d '{"name":"context7","description":"Up-to-date documentation lookup","git_url":"https://github.com/upstash/context7","category":"documentation","transport":"stdio"}'
```

Record each server's ID.

---

## Phase 3: Register Skills

Register the skill-type plugins: frontend-design, superpowers, skill-creator, impeccable.

```bash
# Via API
curl -X POST http://localhost:8000/api/v1/skills \
    -H "Content-Type: application/json" \
    -H "X-API-Key: $(jq -r .api_key ~/.observal/config.json)" \
    -d '{"name":"frontend-design","description":"Frontend design skill for UI/UX implementation","content":"Skill plugin from claude-plugins-official","category":"general"}'
```

Or via CLI if available:
```bash
observal registry skill submit --name frontend-design --yes
```

---

## Phase 4: Admin Review — Approve Everything

List all pending submissions and approve them:

```bash
observal admin review list
```

For each pending item, approve it:
```bash
observal admin review approve <id>
```

Verify they're now visible in the public listing:
```bash
observal registry mcp list
observal registry skill list
```

---

## Phase 5: Compose an Agent

Create an agent that bundles the registered MCP servers and skills together.

### 5a. Initialize agent YAML

```bash
mkdir -p /tmp/test-agent && cd /tmp/test-agent
observal agent init
```

This creates `observal-agent.yaml`. Edit it:
- name: `full-stack-dev`
- version: `1.0.0`
- description: `Full-stack development agent with docs lookup, browser testing, GitHub integration, and frontend design skills`
- model: `claude-sonnet-4-6`

### 5b. Add components

Add each registered MCP server and skill by their IDs:
```bash
observal agent add mcp <context7-id>
observal agent add mcp <playwright-id>
observal agent add mcp <github-id>
observal agent add mcp <telegram-id>
observal agent add skill <frontend-design-id>
observal agent add skill <superpowers-id>
```

### 5c. Validate and publish

```bash
observal agent build          # dry-run validation
observal agent publish        # submit to registry
```

Record the agent ID.

### 5d. Approve the agent

```bash
observal admin review list
observal admin review approve <agent-id>
```

---

## Phase 6: Verify Registry

### 6a. CLI verification

```bash
observal agent list
observal agent show <agent-id>
```

The agent should appear with all its components listed.

### 6b. Web UI verification (if Playwright MCP is available)

Navigate to `http://localhost:3000` and verify:
- Home page loads and shows the agent in "Recently Added" or "Trending"
- `/agents` page lists the agent with download count and rating columns
- `/agents/<id>` detail page shows all components under the Components tab
- `/agents/builder` page loads (requires auth — check if it prompts for login)
- `/agents/leaderboard` page loads

### 6c. API verification

```bash
curl -s http://localhost:8000/api/v1/agents | python3 -m json.tool
curl -s http://localhost:8000/api/v1/overview/stats | python3 -m json.tool
curl -s http://localhost:8000/api/v1/overview/top-agents | python3 -m json.tool
```

---

## Phase 7: Pull Agent Locally

Test pulling the agent into different IDE formats:

```bash
mkdir -p /tmp/pull-test-cursor /tmp/pull-test-vscode /tmp/pull-test-claude

observal pull <agent-id> --ide cursor --dir /tmp/pull-test-cursor
observal pull <agent-id> --ide vscode --dir /tmp/pull-test-vscode
observal pull <agent-id> --ide claude-code --dir /tmp/pull-test-claude
```

For each, verify the output:
```bash
# Cursor
cat /tmp/pull-test-cursor/.cursor/mcp.json 2>/dev/null

# VSCode
cat /tmp/pull-test-vscode/.vscode/mcp.json 2>/dev/null

# Claude Code
ls /tmp/pull-test-claude/.claude/ 2>/dev/null
```

The pulled configs should contain the MCP server definitions from the agent's components.

---

## Phase 8: Download Stats & Feedback

```bash
# Check download was tracked
observal ops metrics <agent-id> --type agent

# Rate the agent
observal ops rate <agent-id> --stars 5 --type agent --comment "Works great"

# Check feedback
observal ops feedback <agent-id> --type agent
```

---

## Phase 9: Scan Existing IDE Config

Test `observal scan` against the real `~/.claude` directory. This should detect existing MCP servers and wrap them with the observal shim for telemetry.

```bash
# Scan real Claude Code config
observal scan --ide claude-code
```

Verify:
- It detected your real MCP servers
- It registered or recognized them
- Check if a backup was created

If scan modifies config files, verify they were backed up:
```bash
ls ~/.claude/*.bak 2>/dev/null || ls ~/.claude/*.pre-observal.* 2>/dev/null
```

---

## Phase 10: Issue Creation for Failures

For every failure you encountered, create a GitHub issue:

```bash
gh issue create --repo BlazeUp-AI/Observal \
  --title "<concise title>" \
  --body "$(cat <<'ISSUE_EOF'
## What happened
<description of the failure>

## Steps to reproduce
<exact commands that failed>

## Expected behavior
<what should have happened>

## Actual behavior
<error message or incorrect output>

## Environment
- OS: <your OS>
- Python: <version>
- Docker: <version>
- Observal: latest main
ISSUE_EOF
)" \
  --label "bug"
```

Also create issues for:
- Any CLI commands that have confusing help text or missing `--help`
- Any API endpoints that return unexpected errors
- Any web UI pages that don't load or show wrong data
- Missing features that the README advertises but don't work

---

## Summary Checklist

At the end, report on each item — PASS or FAIL (with issue number):

- [ ] Docker services start and API is healthy
- [ ] CLI installs and `auth login` auto-bootstraps admin
- [ ] Real MCP servers discovered from `~/.claude/settings.json`
- [ ] MCP server registration works (context7, playwright, github, telegram)
- [ ] Skill registration works (frontend-design, superpowers, skill-creator)
- [ ] Admin review approve flow works
- [ ] Approved items appear in public listings
- [ ] Agent init/add/build/publish workflow completes
- [ ] Agent appears in registry with correct components
- [ ] `observal pull` generates correct IDE configs for cursor
- [ ] `observal pull` generates correct IDE configs for vscode
- [ ] `observal pull` generates correct IDE configs for claude-code
- [ ] Download stats are tracked after pull
- [ ] Feedback/rating submission works
- [ ] `observal scan` detects real IDE configs
- [ ] Web UI home page loads and shows data
- [ ] Web UI agent detail page shows components
- [ ] API endpoints return expected data
