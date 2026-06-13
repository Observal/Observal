<!-- SPDX-FileCopyrightText: 2026 Rajat <rajattempest8736@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# Kiro

Kiro is a first-class Observal IDE integration. Observal can install Kiro agents,
configure MCP servers, add hooks, expose skills, and collect Kiro session
telemetry.

---

## Overview

Kiro agents are JSON files. Project agents live in `.kiro/agents/`. User agents
live in `~/.kiro/agents/`.

When Observal installs a Kiro agent, it adds two hooks to the agent JSON:
`userPromptSubmit` and `stop`. Both hooks run
`observal_cli.hooks.kiro_session_push`.

The hook reads Kiro session JSONL files from `~/.kiro/sessions/cli/`. It reads
only new lines since the last push and sends them to Observal.

---

## Supported Features

| Feature | Support |
|---|---|
| Agents | Project and user scope |
| Hook bridge | `userPromptSubmit` and `stop` by default |
| Custom hooks | `agentSpawn`, `userPromptSubmit`, `preToolUse`, `postToolUse`, `stop` |
| MCP servers | `.kiro/settings/mcp.json` and `~/.kiro/settings/mcp.json` |
| Agent prompt | Registry prompts are embedded in the generated Kiro agent JSON |
| Resources | Generated agents can reference `AGENTS.md`, `README.md`, and Kiro skills |
| Skills | `.kiro/skills/{name}/SKILL.md` and `~/.kiro/skills/{name}/SKILL.md` |
| Session parsing | Kiro JSONL parser |
| Telemetry | MCP telemetry through `observal-shim`; session telemetry through hooks |
| Model selection | Supported |

---

## Setup

### 1. Install the Observal CLI

```bash
uv tool install observal-cli
# or: pipx install observal-cli
```

### 2. Authenticate

```bash
observal auth login
```

This writes credentials to `~/.observal/config.json`.

### 3. Pull an agent into Kiro

```bash
observal pull <agent-name> --ide kiro
```

Kiro's default scope is user scope. By default, the agent is written to
`~/.kiro/agents/{name}.json`.

To install into the current project:

```bash
observal pull <agent-name> --ide kiro --scope project
```

Project agents are written to `.kiro/agents/{name}.json`.

### 4. Patch existing Kiro agents

To add or refresh Observal hooks in existing Kiro agents:

```bash
observal doctor patch --all --ide kiro
```

This updates Observal hook entries and keeps other hook entries unchanged.

---

## Config Paths

| Purpose | Project scope | User scope |
|---|---|---|
| Agent definition | `.kiro/agents/{name}.json` | `~/.kiro/agents/{name}.json` |
| MCP config | `.kiro/settings/mcp.json` | `~/.kiro/settings/mcp.json` |
| Skill definition | `.kiro/skills/{name}/SKILL.md` | `~/.kiro/skills/{name}/SKILL.md` |
| Hook config | Inside `.kiro/agents/{name}.json` | Inside `~/.kiro/agents/{name}.json` |
| Hook scripts | `.kiro/hooks/` | `~/.kiro/hooks/` |
| Session JSONL | `~/.kiro/sessions/cli/{session_id}.jsonl` | `~/.kiro/sessions/cli/{session_id}.jsonl` |
| Credit metadata | `~/.kiro/sessions/cli/{session_id}.json` | `~/.kiro/sessions/cli/{session_id}.json` |
| Observal credentials | `~/.observal/config.json` | `~/.observal/config.json` |
| Last session cache | `~/.observal/.kiro-session` | `~/.observal/.kiro-session` |

Kiro MCP configs use the `mcpServers` key.

---

## Hook Spec

Kiro hooks are stored inside each agent JSON file. Observal adds these default hooks:

```json
{
  "hooks": {
    "userPromptSubmit": [
      {
        "command": "python -m observal_cli.hooks.kiro_session_push"
      }
    ],
    "stop": [
      {
        "command": "python -m observal_cli.hooks.kiro_session_push"
      }
    ]
  }
}
```

On non-Windows platforms, generated server config may use `python3` instead of
`python`. During `observal pull`, the CLI rewrites Observal hook commands to use
the active Python interpreter.

When an agent name is available, the hook command sets `OBSERVAL_AGENT_NAME` for
agent attribution.

### Event Map

| Observal event | Kiro event |
|---|---|
| `SessionStart` | `agentSpawn` |
| `UserPromptSubmit` | `userPromptSubmit` |
| `PreToolUse` | `preToolUse` |
| `PostToolUse` | `postToolUse` |
| `Stop` | `stop` |

`preToolUse` and `postToolUse` hooks can include a `matcher`. Observal uses `*`
when no matcher is set.

---

## Session Push Behavior

`kiro_session_push` works as follows:

1. Resolve the Kiro session ID from the hook payload or `~/.observal/.kiro-session`.
2. Find `~/.kiro/sessions/cli/{session_id}.jsonl`.
3. Read the saved byte cursor for the session.
4. Read only new JSONL lines.
5. Send the lines to Observal with `ide` set to `kiro`.
6. Advance the cursor after a successful push.

On `stop`, the hook finalizes the cursor. It also reads
`~/.kiro/sessions/cli/{session_id}.json` when present and sends Kiro credit
usage.

---

## Agent File Format

Kiro agents are JSON files. Observal generates fields like these:

```json
{
  "name": "my-agent",
  "prompt": "You are a Kiro agent with the following specialization....",
  "mcpServers": {
    "my-mcp-server": {
      "command": "observal-shim",
      "args": ["--mcp-id", "example", "--", "npx", "-y", "example-server"]
    }
  },
  "tools": ["*"],
  "toolAliases": {},
  "allowedTools": [],
  "resources": [
    "file://AGENTS.md",
    "file://README.md",
    "skill://.kiro/skills/*/SKILL.md",
    "skill://~/.kiro/skills/*/SKILL.md"
  ],
  "hooks": {
    "userPromptSubmit": [
      {
        "command": "python -m observal_cli.hooks.kiro_session_push"
      }
    ],
    "stop": [
      {
        "command": "python -m observal_cli.hooks.kiro_session_push"
      }
    ]
  },
  "toolsSettings": {},
  "includeMcpJson": true,
  "model": "claude-sonnet-4"
}
```

The `model` field is present when a model is resolved for the agent.

---

## Skill File Format

Kiro skills live at:

| Scope | Path |
|---|---|
| Project | `.kiro/skills/{name}/SKILL.md` |
| User | `~/.kiro/skills/{name}/SKILL.md` |

Example:

```markdown
---
description: "Runs the project test suite"
task_type: testing
---

# Run Tests

Run `pytest -q` from the project root.
```

---

## Caveats

**Hooks are per agent.** Kiro stores Observal hooks inside each agent JSON file.

**Existing agents need patching.** Pulling a new agent includes hooks
automatically. Existing agents can be patched with
`observal doctor patch --all --ide kiro`.

**Default scope is user.** `observal pull <agent-name> --ide kiro` writes to
`~/.kiro/agents/` unless `--scope project` is set.

**No Claude Code subagent layout.** Kiro reads
`~/.kiro/sessions/cli/{session_id}.jsonl`. It does not scan Claude Code's
`subagents/` directory.

**MCP config is Kiro-specific.** Kiro uses `.kiro/settings/mcp.json` and
`~/.kiro/settings/mcp.json`, not Claude Code MCP paths.
