# Kiro CLI Research Notes

**Research date:** 2026-04-11
**Kiro CLI version:** 1.28.1
**Installation:** `curl -fsSL https://cli.kiro.dev/install | bash`
**Binary location:** `/home/haz3/.local/bin/kiro-cli`
**Binary type:** Native ELF (~112 MB, Rust)

---

## 1. Kiro CLI Architecture

Kiro is an AI-powered development platform by Amazon/AWS with two forms:
- **Desktop IDE** — based on Code OSS, compatible with VS Code extensions
- **Standalone CLI** (`kiro-cli`) — fully independent terminal AI coding assistant

Authentication: AWS IAM Identity Center, GitHub, Google, or AWS Builder ID.

### CLI Subcommands

| Command | Purpose |
|---------|---------|
| `chat` | Interactive AI chat (`--no-interactive` for headless, `--trust-all-tools` for auto-approve) |
| `agent` | Manage custom agents (list, create, edit, validate) |
| `mcp` | Manage MCP servers (add, remove, list, import, status) |
| `acp` | Agent Client Protocol support |
| `translate` | Natural language → shell command |
| `doctor` | Diagnose installation issues |
| `login` / `logout` / `whoami` | Authentication |
| `settings` | Appearance and behavior |
| `inline` | Inline shell completions |

### Available Models

Credit-based pricing. Models include:
- Claude Opus 4.6, Sonnet 4.6, Opus 4.5, Sonnet 4.5, Sonnet 4, Haiku 4.5
- DeepSeek 3.2, MiniMax M2.5/M2.1, GLM-5, Qwen3 Coder Next
- `auto` (default) — dynamic model selection per task

---

## 2. Config File Structure

```
~/.kiro/
├── settings/
│   ├── cli.json          # CLI settings (telemetry, appearance, behavior)
│   ├── mcp.json          # MCP server configs (global)
│   └── telemetry.json    # (proposed, not yet implemented)
├── steering/             # Global steering files (markdown + YAML frontmatter)
├── agents/               # Agent configs (JSON)
│   ├── coder.json
│   ├── frontend.json
│   ├── backend.json
│   ├── fullstack.json
│   ├── devops.json
│   ├── debugger.json
│   ├── reviewer.json
│   ├── researcher.json
│   ├── tester.json
│   ├── docs.json
│   ├── database.json
│   └── api-designer.json
├── skills/               # Global skills
└── hooks/                # Global hooks (IDE format)

.kiro/                    # Project-level
├── settings/
│   └── mcp.json          # Project MCP servers
├── steering/             # Project steering files
│   ├── product.md        # Auto-generated
│   ├── tech.md           # Auto-generated
│   └── structure.md      # Auto-generated
├── specs/                # Structured planning
│   └── [feature-name]/
│       ├── requirements.md (or bugfix.md)
│       ├── design.md
│       └── tasks.md
├── skills/               # Project skills
│   └── [skill-name]/
│       ├── SKILL.md      # Required
│       ├── scripts/
│       ├── references/
│       └── assets/
└── hooks/                # Project hooks
```

---

## 3. MCP Configuration Format

File: `.kiro/settings/mcp.json`

```json
{
  "mcpServers": {
    "local-server": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-bravesearch"],
      "env": {
        "BRAVE_API_KEY": "${BRAVE_API_KEY}"
      },
      "disabled": false,
      "autoApprove": ["tool1"],
      "disabledTools": ["tool2"]
    },
    "remote-server": {
      "url": "https://mcp.example.com/mcp",
      "headers": {
        "Authorization": "Bearer $TOKEN"
      }
    }
  }
}
```

Transport is inferred: `command` → stdio, `url` → HTTP/streamable-HTTP. No explicit `transport` field.

---

## 4. Hook System

### CLI Hook Events

| Event | Description | STDIN Fields |
|-------|-------------|--------------|
| `agentSpawn` | Agent initialization | `hook_event_name`, `cwd` |
| `userPromptSubmit` | User submits message | `hook_event_name`, `cwd`; env `USER_PROMPT` |
| `preToolUse` | Before tool execution | `hook_event_name`, `tool_name`, `tool_input`, `cwd` |
| `postToolUse` | After tool execution | `hook_event_name`, `tool_name`, `tool_input`, `tool_response`, `cwd` |
| `stop` | Agent finishes responding | `hook_event_name`, `cwd` |

### IDE Hook Events (additional)

| Event | Description |
|-------|-------------|
| `fileEdited` | File saved/modified (supports glob patterns) |
| `fileCreated` | File created |
| `fileDeleted` | File deleted |
| `userTriggered` | Manual trigger |
| `promptSubmit` | User submits prompt |
| `agentStop` | Agent finishes |
| `preSpecTask` / `postSpecTask` | Before/after spec task |

### CLI Hook Config (in agent JSON)

```json
{
  "hooks": {
    "preToolUse": [
      { "matcher": "execute_bash", "command": "echo 'checking...'" }
    ],
    "postToolUse": [
      { "matcher": "fs_write", "command": "cargo fmt --all" }
    ],
    "agentSpawn": [
      { "command": "git status" }
    ],
    "stop": [
      { "command": "npm test" }
    ]
  }
}
```

### IDE Hook Config (JSON files in .kiro/hooks/)

```json
{
  "id": "optional-id",
  "name": "Hook Name",
  "comment": "Description",
  "when": {
    "type": "fileEdited|fileCreated|fileDeleted|userTriggered|promptSubmit|agentStop|preToolUse|postToolUse",
    "pattern": "**/*.ts"
  },
  "then": {
    "type": "askAgent|runCommand|alert",
    "prompt": "string (for askAgent)",
    "command": "string (for runCommand)",
    "message": "string (for alert)"
  }
}
```

### Hook Blocking

- CLI: Exit code 2 on `preToolUse` blocks the tool
- Claude Code: Return JSON `{"decision": "block"}`

### Tool Matchers (CLI)

- Canonical names: `fs_read`, `fs_write`, `execute_bash`, `use_aws`
- Aliases: `read`, `write`, `shell`, `aws`
- MCP tool refs: `@git`, `@postgres/query`
- Patterns: `@builtin`, `*`

### Claude Code ↔ Kiro Event Mapping

| Claude Code | Kiro CLI | Kiro IDE |
|-------------|----------|----------|
| `SessionStart` | `agentSpawn` | N/A |
| `UserPromptSubmit` | `userPromptSubmit` | `promptSubmit` |
| `PreToolUse` | `preToolUse` | `preToolUse` |
| `PostToolUse` | `postToolUse` | `postToolUse` |
| `Stop` | `stop` | `agentStop` |
| `SubagentStart` | — (not available) | — |
| `SubagentStop` | — (not available) | — |
| `PreCompact` | — (not available) | — |
| `PostCompact` | — (not available) | — |
| `Notification` | — (not available) | — |
| `TaskCreated` | — (not available) | — |
| `TaskCompleted` | — (not available) | — |

---

## 5. Telemetry / OTEL Status

### Current State: No Native OTEL Export

Kiro does **not** emit OpenTelemetry data. Relevant upstream issues:
- [kirodotdev/Kiro#6319](https://github.com/kirodotdev/Kiro/issues/6319) — Native OTLP trace export (feature request)
- [kirodotdev/Kiro#7226](https://github.com/kirodotdev/Kiro/issues/7226) — Configurable telemetry endpoint for enterprise
- [kirodotdev/Kiro#7347](https://github.com/kirodotdev/Kiro/issues/7347) — Expose session telemetry as exportable metadata

### What Kiro Tracks Internally

- Estimated credits used (per-turn)
- Elapsed time (per-turn)
- Model name
- Token counts (input/output, for context management)
- Credit consumption (model-specific rates)
- Turn count per session

**None of this is accessible via hooks or export.** Only visible in UI and via `/usage` CLI command.

### Workaround: Hook-Based Telemetry

Community members use `runCommand` hooks to send data to external systems:
- `agentSpawn` hook → log session start
- `preToolUse` / `postToolUse` hooks → log tool usage
- `stop` hook → log session end
- `promptSubmit` hook → log user prompts (example: sending to Grafana Loki via curl)

This is the recommended integration path for Observal until Kiro implements native OTEL export.

---

## 6. Steering Files (Agent Instructions)

Kiro's equivalent of CLAUDE.md / AGENTS.md. Stored in `.kiro/steering/`.

### Format

```markdown
---
inclusion: always | fileMatch | manual | auto
globs:
  - "**/*.tsx"
  - "src/components/**"
name: component-patterns
description: React component patterns for this project
---

# Steering Content

Instructions for the AI agent...
```

### Inclusion Modes

| Mode | Behavior |
|------|----------|
| `always` | Loaded every interaction |
| `fileMatch` | Loaded when working with matching files |
| `manual` | Loaded when user types `#name` |
| `auto` | Loaded when description matches user intent |

### Auto-Generated Files

Kiro auto-generates three baseline steering files:
- `product.md` — Product overview
- `tech.md` — Technology stack
- `structure.md` — Project structure

### AGENTS.md Compatibility

Kiro recognizes AGENTS.md files but treats them as "always included" (no inclusion modes). They serve as a simpler, always-active instruction format.

---

## 7. Skills System

Skills live in `.kiro/skills/` (project) or `~/.kiro/skills/` (global).

### Structure

```
.kiro/skills/
└── my-skill/
    ├── SKILL.md        # Required — instructions + metadata
    ├── scripts/        # Optional — executable scripts
    ├── references/     # Optional — reference docs
    └── assets/         # Optional — images, templates
```

### SKILL.md Format

```markdown
---
name: my-skill
description: What this skill does
license: MIT
compatibility:
  kiro: ">=1.20.0"
metadata:
  author: user
---

# Skill Instructions

Instructions loaded when skill is activated...
```

Skills use progressive disclosure: only name/description loaded at startup, full content on activation. Invoked via `/skill-name` slash command.

---

## 8. Agent Config Format

File: `~/.kiro/agents/<name>.json` or `.kiro/agents/<name>.json`

```json
{
  "name": "my-agent",
  "description": "Agent description",
  "prompt": "System prompt / instructions",
  "mcpServers": {
    "server-name": {
      "command": "npx",
      "args": ["-y", "some-server"]
    }
  },
  "tools": ["@git", "@builtin", "read", "write", "shell"],
  "hooks": {
    "preToolUse": [
      { "matcher": "*", "command": "echo checking" }
    ],
    "postToolUse": [
      { "matcher": "*", "command": "echo done" }
    ]
  },
  "includeMcpJson": true,
  "model": "claude-sonnet-4"
}
```

### Observal's Current Agent Generation (for comparison)

```python
# From agent_config_generator.py
{
    "agent_file": {
        "path": f"~/.kiro/agents/{safe_name}.json",
        "content": {
            "name": safe_name,
            "description": agent.description[:200],
            "prompt": agent.prompt,
            "mcpServers": mcp_configs,
            "tools": [f"@{n}" for n in mcp_configs] + ["read", "write", "shell"],
            "hooks": {},
            "includeMcpJson": True,
            "model": agent.model_name,
        },
    },
}
```

This is already compatible with Kiro's expected format.

---

## 9. Powers System

Powers = bundled extensions (MCP tools + steering + hooks in one package). 50+ available including AWS, Firebase, Stripe, etc. Powers load dynamically based on conversation context.

No Observal equivalent currently. Low priority for integration.

---

## 10. Integration Strategy

### Recommended Approach

Since Kiro lacks native OTEL, the telemetry bridge must use hooks:

1. **Create an Observal telemetry hook script** that Kiro hooks call via `runCommand`
2. **The hook script** receives STDIN JSON, enriches it (adds session ID, timestamps), and POSTs to Observal's `/api/v1/telemetry/hooks` endpoint
3. **Install hooks** into Kiro agent configs for `agentSpawn`, `preToolUse`, `postToolUse`, `stop`, and `userPromptSubmit`
4. **Generate Steering files** instead of (or in addition to) AGENTS.md for richer agent instructions

### What This Gives Us

- Tool usage tracking (which tools, success/failure, timing)
- Session lifecycle (start/stop)
- User prompts
- **Missing:** Token counts, model name, cost data (blocked on Kiro upstream)

### What We Won't Get Until Kiro Adds OTEL

- Token counts per request
- Model name per request
- Cost/credit data
- Cache hit rates
- API request latency
