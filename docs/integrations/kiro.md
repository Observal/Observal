<!-- SPDX-FileCopyrightText: 2026 Rajat <rajattempest8736@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Kiro

Kiro is a first-class Observal harness integration. Observal can install Kiro agents,
configure MCP servers, add hooks, expose skills, and collect Kiro session telemetry.

---

## Overview

Kiro agent profiles are JSON files. Project agents live in `.kiro/agents/`.
User agents live in `~/.kiro/agents/`.

When Observal installs a Kiro agent, it writes attributed hook commands into that agent JSON. The default hooks run the shared `observal_cli.hooks.session_push --harness kiro` exporter for `userPromptSubmit` and `stop`.

Current Kiro CLI conversations are read from `~/.local/share/kiro-cli/data.sqlite3` (with platform-equivalent application-data paths). The Kiro adapter converts each stored prompt, assistant response, tool call, and tool result into the stable Kiro record format used by the server parser. Legacy `~/.kiro/sessions/cli/*.jsonl` sessions remain readable as a fallback.

---

## Supported capabilities

| Capability | Support |
|---|---|
| Agent profiles | Project and user scope |
| Hook bridge | `userPromptSubmit` and `stop` by default |
| Custom hooks | `agentSpawn`, `userPromptSubmit`, `preToolUse`, `postToolUse`, `stop` |
| MCP servers | `.kiro/settings/mcp.json` and `~/.kiro/settings/mcp.json` |
| Agent prompt | Registry prompts are embedded in the generated Kiro agent profile |
| Guidance files | Scanned from steering files and `AGENTS.md`, not overwritten |
| Skills | `.kiro/skills/{name}/SKILL.md` and `~/.kiro/skills/{name}/SKILL.md` |
| Session parsing | Kiro SQLite/legacy JSONL source adapter and Kiro record parser |
| Telemetry | MCP telemetry through `observal-shim`; session telemetry through hooks |
| Model selection | Registry-backed Kiro model catalog |

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
observal agent pull <agent-name> --harness kiro
```

Kiro's default scope is user scope. By default, the agent is written to
`~/.kiro/agents/{name}.json`.

To install into the current project:

```bash
observal agent pull <agent-name> --harness kiro --scope project
```

Project agents are written to `.kiro/agents/{name}.json`.

### 4. Refresh Kiro hooks

Pull the agent again to refresh its Observal hook commands.

Kiro attribution is installed per pulled agent because each hook command carries
that agent's Observal UUID. `doctor patch` does not install generic Kiro hooks.

---

## Config paths

| Purpose | Project scope | User scope |
|---|---|---|
| Agent profile | `.kiro/agents/{name}.json` | `~/.kiro/agents/{name}.json` |
| Guidance files | `.kiro/steering/*.md`, `AGENTS.md` | `~/.kiro/steering/*.md` |
| MCP config | `.kiro/settings/mcp.json` | `~/.kiro/settings/mcp.json` |
| Skill definition | `.kiro/skills/{name}/SKILL.md` | `~/.kiro/skills/{name}/SKILL.md` |
| Hook config | Embedded in `.kiro/agents/{name}.json` | Embedded in `~/.kiro/agents/{name}.json` |
| Custom hook scripts | `.kiro/hooks/` | `~/.kiro/hooks/` |
| Current session store | `~/.local/share/kiro-cli/data.sqlite3` | `~/.local/share/kiro-cli/data.sqlite3` |
| Legacy session store | `~/.kiro/sessions/cli/{session_id}.jsonl` | `~/.kiro/sessions/cli/{session_id}.jsonl` |
| Observal credentials | `~/.observal/config.json` | `~/.observal/config.json` |
| Last session cache | `~/.observal/.kiro-session` | `~/.observal/.kiro-session` |

Kiro MCP configs use the `mcpServers` key.

---

## Hook spec

Observal writes the telemetry hooks inside each Kiro agent JSON:

```json
{
  "hooks": {
    "userPromptSubmit": [
      {
        "command": "OBSERVAL_AGENT_ID=<agent-uuid> python -m observal_cli.hooks.session_push --harness kiro"
      }
    ],
    "stop": [
      {
        "command": "OBSERVAL_AGENT_ID=<agent-uuid> python -m observal_cli.hooks.session_push --harness kiro"
      }
    ]
  }
}
```

On non-Windows platforms, generated server config may use `python3` instead of
`python`. During `observal pull`, the CLI rewrites Observal hook commands to use
the active Python interpreter.

### Attribution

Kiro's local conversation store identifies the Kiro conversation, not the installed Observal registry agent. The per-agent hook command is the attribution source of truth.

1. `observal agent pull` writes the agent UUID into the Kiro hook command as
   `OBSERVAL_AGENT_ID`.
2. The shared session exporter reads that UUID when Kiro fires `userPromptSubmit` or `stop`.
3. The CLI looks up the UUID in `~/.observal/lockfile.json` under the `kiro`
   harness.
4. The session payload is sent with the lockfile agent id and version.
5. If the UUID is missing or no lockfile entry exists, the session is left
   unattributed instead of guessing from the current directory.

### Event map

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

## Session push behavior

Kiro uses the shared acknowledged session delivery engine:

1. Resolve the conversation ID from the hook payload; if an older Kiro build omits it, select the newest SQLite conversation for the hook's working directory.
2. Read `conversations_v2` from Kiro's SQLite store, or fall back to the legacy JSONL path.
3. Convert SQLite history entries into stable indexed Kiro records without writing a temporary JSONL file.
4. Persist new batches to `~/.observal/telemetry_buffer.db` before network delivery.
5. Retry batches idempotently until the server returns a contiguous checkpoint covering them.
6. Advance the local line cursor only to that acknowledged checkpoint.

On `stop`, a delayed pass rereads the completed SQLite conversation and finalizes the cursor. Credit usage from conversation metadata is sent through the same durable outbox, including when no new conversation records were added by the final hook.

---

## Agent profile format

Observal generates Markdown agent profiles like this:

```markdown
---
name: my-agent
model: claude-sonnet-4
---

You are a Kiro agent with the following specialization...
```

The `model` field is present when a model is resolved for the agent.

---

## Skill file format

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

**Guidance files are scan-only.** Observal layers Kiro steering files and
`AGENTS.md` as context, but does not overwrite them during pull.

**Hooks are per agent.** Pulling a new agent includes telemetry hooks automatically, with `OBSERVAL_AGENT_ID` bound to that agent's UUID. Pull the agent again to replace an older Kiro-specific push command with the shared acknowledged exporter. `doctor patch` does not install generic Kiro attribution hooks.

**Default scope is user.** `observal agent pull <agent-name> --harness kiro`
writes to `~/.kiro/agents/` unless `--scope project` is set.

**No Claude Code subagent layout.** Kiro reads its own SQLite conversation rows or legacy flat JSONL sessions. It does not scan Claude Code's `subagents/` directory.

**MCP config is Kiro-specific.** Kiro uses `.kiro/settings/mcp.json` and
`~/.kiro/settings/mcp.json`, not Claude Code MCP paths.
