<!-- SPDX-FileCopyrightText: 2026 Rishika Kaur <kaurrishika377@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Claude Code

Claude Code is a first-class Observal harness integration. Observal can install Claude Code agents, configure MCP servers, add hooks, expose skills, and collect session telemetry.

---

## Overview

Claude Code agent profiles are Markdown files with YAML frontmatter. Project agents live in `.claude/agents/`. User agents live in `~/.claude/agents/`.

Observal installs session push hooks into Claude Code's `settings.json`. The default hooks run the shared `observal_cli.hooks.session_push --harness claude-code` entry point for `UserPromptSubmit` and `Stop`.

---

## Supported capabilities

| Capability      | Support                                                                 |
| --------------- | ----------------------------------------------------------------------- |
| Agent profiles  | Project and user scope                                                  |
| Hook bridge     | `UserPromptSubmit` and `Stop` by default                                |
| Custom hooks    | `PreToolUse`, `PostToolUse`, `Notification`, `Stop`, `SubagentStop`     |
| MCP servers     | `.mcp.json`                                                             |
| Skills          | `.claude/skills/{name}/SKILL.md` and `~/.claude/skills/{name}/SKILL.md` |
| Session parsing | Claude Code JSONL parser                                                |
| Telemetry       | Session transcripts delivered through hooks and reconciliation          |

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

### 3. Pull an agent into Claude Code

```bash
observal agent pull <agent-name> --harness claude-code
```

Claude Code's default scope is project scope. By default, the agent is written to `.claude/agents/{name}.md`.

To install into the current user's Claude Code configuration:

```bash
observal agent pull <agent-name> --harness claude-code --scope user
```

User agents are written to `~/.claude/agents/{name}.md`.

---

## Config paths

| Purpose          | Project scope                    | User scope                         |
| ---------------- | -------------------------------- | ---------------------------------- |
| Agent profile    | `.claude/agents/{name}.md`       | `~/.claude/agents/{name}.md`       |
| Skill definition | `.claude/skills/{name}/SKILL.md` | `~/.claude/skills/{name}/SKILL.md` |
| Hook config      | `.claude/settings.json`          | `~/.claude/settings.json`          |
| MCP config       | `.mcp.json`                      | —                                  |

---

## Hook spec

Observal installs session push hooks for `UserPromptSubmit` and `Stop`.

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "type": "command",
        "command": "python -m observal_cli.hooks.session_push --harness claude-code"
      }
    ],
    "Stop": [
      {
        "type": "command",
        "command": "python -m observal_cli.hooks.session_push --harness claude-code"
      }
    ]
  }
}
```

The Claude Code adapter recognizes `PreToolUse`, `PostToolUse`, `Notification`, `Stop`, and `SubagentStop` hook events.

---

## Session push behavior

Claude Code session data is stored as JSONL. Observal reads new session data incrementally and delivers it through the session ingestion endpoint.

Sessions can also be pushed using:

```bash
observal reconcile
```

The session delivery system uses a local outbox and resumes after transient network failures.

---

## Agent profile format

Observal generates Markdown agent profiles with YAML frontmatter:

```markdown
---
name: my-agent
model: claude-sonnet-4
description: Agent description
---

Agent instructions go here.
```

---

## Skill file format

Claude Code skills live at:

| Scope   | Path                               |
| ------- | ---------------------------------- |
| Project | `.claude/skills/{name}/SKILL.md`   |
| User    | `~/.claude/skills/{name}/SKILL.md` |

---

## MCP servers

Claude Code project MCP configuration is stored in:

```text
.mcp.json
```

Observal can discover MCP servers from this configuration and supports both command-based and URL-based MCP configurations.

When an agent contains MCP servers, `observal agent pull` generates the corresponding Claude Code MCP configuration.

---

## Rules and guidance

Claude Code supports guidance files such as:

```text
CLAUDE.md
.claude/CLAUDE.md
~/.claude/CLAUDE.md
CLAUDE.local.md
```

These files provide instructions to Claude Code and are separate from Observal-managed agent profiles and skills.

---

## OTLP telemetry

Observal does not require Claude Code OTLP environment variables for its telemetry integration.

Do **not** configure:

```text
OTEL_*
CLAUDE_CODE_ENABLE_TELEMETRY
```

for Observal's Claude Code integration.

Instead, Observal's telemetry flow is based on session push hooks and `observal reconcile`, which deliver session data to the Observal ingestion endpoint.

---

## Caveats

Claude Code supports both project and user scopes, with project scope as the default. MCP project configuration uses `.mcp.json`. Session delivery depends on Claude Code's local JSONL session data. Observal session telemetry uses session push and reconciliation rather than Claude Code OTLP environment variables.
