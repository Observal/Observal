<!-- SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

---
name: observal
command: observal
description: Use the Observal agent registry and component platform. Handles creating, updating, versioning, and pulling agents. Browse and submit MCPs, skills, and prompts. Use when the user asks to interact with their Observal server.
version: 1.1.0
owner: observal
---

# Observal — Agent Registry & Component Platform

You have the Observal CLI installed. Use it to manage agents and components on the registry server.

## Critical Rules

1. **EXECUTE commands** — run them in your shell, do not just display them
2. **Set timeout to 60 seconds** — commands make HTTP calls
3. **Use single quotes** for `--prompt` and `--description` values to avoid shell quoting issues
4. **Do NOT run `observal auth status` before other commands** — they error clearly if auth is broken
5. **Name conflict (409)?** → use `observal agent publish --update` or `observal agent release --bump`
6. **Only fall back to local mode** if a command returns "Connection failed" or "Not configured"

---

## Agent Commands

### Create a New Agent

```bash
observal agent create --name AGENT_NAME --description 'DESCRIPTION' --prompt 'SYSTEM PROMPT' --model claude-sonnet-4 --ide kiro --ide claude-code --ide cursor
```

Flags:
- `--name` / `-n` — required. Lowercase `[a-z0-9_-]`, max 64 chars
- `--prompt` / `-p` — required. System prompt text (supports multiline)
- `--description` / `-d` — required by server. Short summary
- `--model` / `-m` — default: `claude-sonnet-4`. Options: `claude-opus-4`, `claude-haiku-4-5`, `gemini-2.5-pro`, `gpt-4o`
- `--owner` — auto-detected from auth if omitted
- `--version` / `-v` — default: `1.0.0`
- `--ide` — repeat for multiple. Omit for all IDEs
- `--prompt-file` — read prompt from a file instead of inline
- `--from-file` / `-f` — pass a complete JSON definition

### Update an Existing Agent

Two options when the name already exists (409 error):

**Option A: Direct update (skips review queue, updates in-place):**

```bash
observal agent publish --update --dir /path/to/yaml/dir
```

**Option B: New version (goes to review queue):**

```bash
observal agent release <name> --bump patch --dir /path/to/yaml/dir
```

Use Option B when the user wants changes reviewed. Use Option A for quick edits.

Both require an `observal-agent.yaml`. Write it like this:

```bash
# 1. Write observal-agent.yaml (anywhere, e.g. /tmp/myagent/)
mkdir -p /tmp/myagent && cat > /tmp/myagent/observal-agent.yaml << 'EOF'
name: existing-agent-name
version: "1.0.0"
description: "Updated description"
owner: "team-name"
model_name: claude-sonnet-4
model_config_json: {}
models_by_ide: {}
external_mcps: []
prompt: |
  Your updated system prompt here.
  Can be multiline.
supported_ides:
  - kiro
  - claude-code
  - cursor
components: []
EOF

# 2. Push the update
observal agent publish --update --dir /tmp/myagent
```

### Release a New Version

To bump the version of an existing agent:

```bash
# 1. Write the YAML with updated prompt/config
mkdir -p /tmp/myagent && cat > /tmp/myagent/observal-agent.yaml << 'EOF'
name: agent-name
description: "What it does"
model_name: claude-sonnet-4
model_config_json: {}
models_by_ide: {}
external_mcps: []
prompt: |
  Your updated system prompt.
supported_ides:
  - kiro
  - claude-code
components: []
EOF

# 2. Release with version bump
observal agent release agent-name --bump patch --dir /tmp/myagent
```

Bump types: `patch` (1.0.0→1.0.1), `minor` (1.0.0→1.1.0), `major` (1.0.0→2.0.0)

### observal-agent.yaml Schema

All fields:

```yaml
name: my-agent                    # required, [a-z0-9_-]
description: "What this agent does"  # required
version: "1.0.0"                  # semver, auto-bumped by release
owner: "team-name"                # required
model_name: claude-sonnet-4       # required
model_config_json: {}             # MUST be {} not omitted
models_by_ide: {}                 # optional per-IDE overrides e.g. {kiro: claude-haiku-4-5}
external_mcps: []                 # MUST be [] not omitted
prompt: |                         # required, multiline supported
  System prompt text here.
supported_ides:                   # list of IDE slugs
  - kiro
  - claude-code
  - cursor
  - gemini-cli
  - vscode
  - codex
  - copilot
  - opencode
components: []                    # component refs, empty for prompt-only agents
```

**Critical**: `model_config_json` MUST be `{}` and `external_mcps` MUST be `[]` — never omit them or set to null, or the API returns 422.

### Pull an Agent

```bash
observal agent pull <name> --ide <ide> --no-prompt --dir .
```

Flags: `--model`, `--scope user|project`, `--dry-run`

### Browse Agents

```bash
observal agent list --output json
observal agent list --search "keyword" --output json
observal agent my --output json
observal agent show <name> --output json
observal agent versions <name> --output json
```

### Delete / Archive

```bash
observal agent delete <name> --yes
observal agent unarchive <name> --yes
```

---

## Component Commands (MCPs, Skills, Prompts)

### Browse Components

```bash
# MCPs
observal mcp list --output json
observal mcp list --search "github" --output json
observal mcp list --category developer-tools --output json
observal mcp show <name-or-id> --output json

# Skills
observal skill list --output json
observal skill list --task-type code-review --output json
observal skill show <name-or-id> --output json

# Prompts
observal prompt list --output json
observal prompt show <name-or-id> --output json
```

MCP categories: `browser-automation`, `cloud-platforms`, `code-execution`, `communication`, `databases`, `developer-tools`, `devops`, `file-systems`, `finance`, `knowledge-memory`, `monitoring`, `multimedia`, `productivity`, `search`, `security`, `version-control`, `ai-ml`, `data-analytics`, `general`

Skill task types: `code-review`, `code-generation`, `testing`, `documentation`, `debugging`, `refactoring`, `deployment`, `security-audit`, `performance`, `general`

### Submit an MCP Server

From a git repo (recommended):

```bash
observal mcp submit --git https://github.com/org/mcp-server --name my-mcp --category developer-tools --yes
```

From a JSON file:

```bash
observal mcp submit --from-file mcp.json
```

### Submit a Skill

```bash
observal skill submit --skill-md ./SKILL.md --git-url https://github.com/org/repo --git-ref main
```

### Submit a Prompt

```bash
observal prompt submit --from-file prompt.json
```

---

## Supported IDEs

| IDE Flag | Accepts `--model` | Accepts `--scope` |
|----------|---|---|
| `cursor` | No | Yes |
| `kiro` | Yes | Yes |
| `claude-code` | Yes | Yes |
| `gemini-cli` | Yes | Yes |
| `vscode` | No | No |
| `codex` | Yes | No |
| `copilot` | No | No |
| `copilot-cli` | No | No |
| `opencode` | Yes | Yes |

---

## Local Fallback Mode

If commands fail with "Connection failed", write configs directly:

**Kiro** → `~/.kiro/agents/<name>.json`:
```json
{"name":"<name>","description":"<desc>","prompt":"<prompt>","model":"claude-sonnet-4-20250514","mcpServers":{},"tools":["*"],"resources":["skill://~/.kiro/skills/*/SKILL.md"]}
```

**Claude Code** → `.claude/agents/<name>.md`:
```markdown
---
name: <name>
description: <desc>
---
<prompt>
```

**Cursor** → `.cursor/rules/<name>.mdc`:
```markdown
---
name: <name>
description: <desc>
---
<prompt>
```

---

## Error Reference

| Error | Fix |
|-------|-----|
| 409 "already have an agent named X" | Use `observal agent publish --update` or `agent release --bump` |
| 422 model_config_json/external_mcps | Ensure YAML has `model_config_json: {}` and `external_mcps: []` |
| "Not configured" | User must run `observal auth login` |
| "Connection failed" | Use Local Fallback Mode |
| 404 Not found | Check name with `observal agent list --output json` |
| "system prompt is required" | Add `--prompt` or `prompt:` in YAML |
