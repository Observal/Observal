<!-- SPDX-FileCopyrightText: 2026 Anubrata Guin <anu.guin.01@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# Claude Code

Claude Code is a first-class integration in Observal with full support for agents, skills,
hooks, MCP servers, session parsing, and OTLP telemetry.

---

## Overview

When Claude Code is connected to Observal, every session is captured automatically.
Two lightweight hooks (`UserPromptSubmit` and `Stop`) fire at the start and end of each
conversation. Each hook invokes `observal_cli.hooks.session_push`, which reads the session
JSONL file **incrementally** (byte-cursor based, not event-by-event) and ships new lines
to the Observal ingest endpoint. The result is a full trace of prompts, tool calls,
thinking blocks, and token usage visible in the Observal dashboard with no manual
instrumentation.

---

## Supported features

| Feature | Supported |
|---|---|
| Agents (subagents) | project and user scope |
| Skills | project and user scope |
| Hooks (event bridge) |  `UserPromptSubmit`, `Stop`, `PreToolUse`, `PostToolUse`, `Notification`, `SubagentStop` |
| MCP servers |  via `~/.claude.json` global config |
| Session parsing |  full JSONL parser (prompts, tool use, tool results, thinking, token usage) |
| Subagent sessions |  pushed incrementally from `subagents/` subdirectory |
| Agent marker attribution |  sessions tagged to pulled agent via `.observal/agent` |
| Model selection |  `accepts_model_choice: true` |

---

## Setup

### 1. Install the Observal CLI

```bash
pip install observal-cli
```

### 2. Authenticate

```bash
observal auth login
```

This writes credentials to `~/.observal/config.json`.

### 3. Install hooks

```bash
observal doctor --patch
```

This performs a non-destructive merge into `.claude/settings.json` (project scope) or
`~/.claude/settings.json` (user scope), adding the two Observal hook entries under
`UserPromptSubmit` and `Stop`. Existing hooks are preserved.

Verify the installation status at any time:

```bash
observal doctor
```

The doctor reports `installed` when at least 3 Observal-managed hook entries are found,
`partial` if some are present but not all, and `missing` otherwise.

### 4. Pull an agent (optional)

```bash
# Project scope (default)
observal pull <agent-name> --ide claude-code

# User scope
observal pull <agent-name> --ide claude-code --scope user
```

Project-scope agents are written to `.claude/agents/<name>.md`.  
User-scope agents are written to `~/.claude/agents/<name>.md`.

After pulling, a marker file is written to `<cwd>/.observal/agent` so that sessions
started after the pull are automatically attributed to the agent in the Observal UI.

---

## Config file paths

| Purpose | Project scope | User scope |
|---|---|---|
| Agent definition | `.claude/agents/{name}.md` | `~/.claude/agents/{name}.md` |
| Skill definition | `.claude/skills/{name}/SKILL.md` | `~/.claude/skills/{name}/SKILL.md` |
| Hook config | `.claude/settings.json` | `~/.claude/settings.json` |
| Hook scripts dir | `.claude/hooks/` | — |
| MCP global config | `~/.claude.json` | `~/.claude.json` |
| Session JSONL files | `~/.claude/projects/<project-key>/<session-id>.jsonl` | — |
| Subagent JSONL files | `~/.claude/projects/<project-key>/<session-id>/subagents/agent-<id>.jsonl` | — |
| Observal credentials | `~/.observal/config.json` | — |
| Agent marker | `<cwd>/.observal/agent` | — |

The project key is derived from the working directory path by replacing `/` with `-`:

```
/home/user/code/myproject  →  -home-user-code-myproject
```

---

## Hook spec

Observal installs exactly two hook events into `settings.json`. Both invoke the same
session push command:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "_observal": { "version": "10" },
        "hooks": [
          { "type": "command", "command": "python -m observal_cli.hooks.session_push" }
        ]
      }
    ],
    "Stop": [
      {
        "_observal": { "version": "10" },
        "hooks": [
          { "type": "command", "command": "python -m observal_cli.hooks.session_push" }
        ]
      }
    ]
  }
}
```

The `_observal.version` field is the `HOOKS_SPEC_VERSION` constant in
`observal_cli/ide_specs/claude_code_hooks_spec.py` (currently `"10"`). When the hook
definition changes, this version is bumped and `observal doctor --patch` upgrades the
installed hooks automatically.

### Available hook events

The full event map supported by Claude Code (used if you configure custom hooks):

| Observal event name | Claude Code event name |
|---|---|
| `PreToolUse` | `PreToolUse` |
| `PostToolUse` | `PostToolUse` |
| `Stop` | `Stop` |
| `SessionStart` | `SessionStart` |
| `UserPromptSubmit` | `UserPromptSubmit` |
| `Notification` | `Notification` |
| `SubagentStop` | `SubagentStop` |

---

## Session push behavior

The `session_push` hook does **not** parse individual hook event payloads. Instead it:

1. Resolves the session JSONL file path from `~/.claude/projects/<project-key>/<session-id>.jsonl`.
2. Reads a persistent byte-cursor from `~/.observal/cursors/<session-id>` to find the
   last-processed position.
3. Reads only the **new bytes** since the last cursor position (`read_new_lines`).
4. POSTs the new lines as a batch to the Observal `/ingest` endpoint.
5. Advances the cursor on success.

For subagent sessions, after pushing the main session the hook also scans
`~/.claude/projects/<project-key>/<session-id>/subagents/agent-*.jsonl` and pushes each
incrementally using a composite cursor key `<parent-id>__sub__<agent-id>`.

---

## Agent file format

Claude Code agents are Markdown files with a YAML frontmatter header:

```markdown
---
name: my-agent
description: "Does X and Y"
model: claude-opus-4-5
tools: bash,read_file,write_file
mcpServers:
  - my-mcp-server
---

Agent system prompt content goes here.
```

The `model` field accepts Anthropic model names. If omitted, Claude Code uses its default
model. The `mcpServers` list references servers already registered in `~/.claude.json`.

---

## Skill file format

Skills live at `.claude/skills/<name>/SKILL.md` and use YAML frontmatter:

```markdown
---
description: "Runs the project test suite"
task_type: testing
---

# Run Tests

Run `pytest -q` from the project root...
```

`task_type` is used by Observal's skill search. Common values: `general`, `testing`,
`documentation`, `refactoring`.

---

## Caveats and known limitations

**`PYTHONPATH` on first install.** If `observal_cli` is not on the system Python path, the
hook command is prefixed with `PYTHONPATH=<pkg-root>` automatically. If you move the
package installation directory after running `observal doctor --patch`, re-run
`observal doctor --patch` to update the path in `settings.json`.

**Hook detection threshold.** The doctor marks hooks as `installed` only when 3 or more
Observal-managed hook entries are present. A fresh install writes exactly 2 entries
(`UserPromptSubmit` + `Stop`). If the doctor reports `partial` after a fresh install,
run `observal doctor --patch` again.

**Project-scope MCP config.** Claude Code reads project-level MCP servers from `.mcp.json`
at the project root (not `.claude/mcp.json`). Observal's scan reads `.mcp.json`
accordingly. The global MCP config path is `~/.claude.json`.

**Agent marker timing guard.** If a session was started before `observal pull` was run,
the `.observal/agent` marker is ignored for that session (the cursor offset is 0 check).
Sessions started after the pull are attributed correctly.

**Subagent JSONL path.** Claude Code writes subagent files to:

```
~/.claude/projects/<project-key>/<parent-session-id>/subagents/agent-<agent-id>.jsonl
```

If Claude Code changes this layout in a future release, subagent push will silently
produce no events (the `subagents/` directory check returns early). No data is lost;
the main session is still pushed normally.

**No `SessionStart` hook in default install.** The default two-hook install only covers
`UserPromptSubmit` and `Stop`. `SessionStart`, `PreToolUse`, `PostToolUse`,
`Notification`, and `SubagentStop` are available for custom hook configs but are not
installed by `observal doctor --patch` by default.
