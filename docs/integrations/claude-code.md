<!-- SPDX-FileCopyrightText: 2026 codessensei <rza.dadashov945@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Claude Code

Claude Code is a first-class Observal harness integration. Observal can install
Claude Code agents, expose skills, register MCP servers, install hooks, and
collect Claude Code session telemetry.

---

## Overview

Claude Code agent profiles are Markdown files with YAML frontmatter. Project
agents live in `.claude/agents/`. User agents live in `~/.claude/agents/`.

Session telemetry comes from the JSONL transcripts Claude Code already writes
under `~/.claude/projects/`. Observal installs two `command` hooks into
`~/.claude/settings.json` (`UserPromptSubmit` and `Stop`); each invocation reads
the transcript incrementally and pushes new lines to the Observal server.
Subagent transcripts are discovered next to their parent session and linked to
it.

---

## Supported capabilities

| Capability        | Support                                                                   |
| ----------------- | ------------------------------------------------------------------------- |
| Agent profiles    | Project and user scope, YAML frontmatter                                  |
| Skills            | `.claude/skills/{name}/SKILL.md` and `~/.claude/skills/{name}/SKILL.md`   |
| Hook bridge       | Registry hooks: `command` hooks in `.claude/settings.json` (project or user scope). Session push: `~/.claude/settings.json` only |
| MCP servers       | `claude mcp add` setup commands; project `.mcp.json` is scanned           |
| Rules             | `CLAUDE.md`, `.claude/CLAUDE.md`, `~/.claude/CLAUDE.md`, `CLAUDE.local.md` |
| Session parsing   | Built-in `claude-code` parser over `~/.claude/projects/**/*.jsonl`        |
| Subagents         | `<session>/subagents/agent-*.jsonl`, linked to the parent session         |
| Tool whitelist    | `--tools` on pull writes the `tools:` frontmatter field                   |
| Model selection   | Registry model mapped to the `opus`, `sonnet`, or `haiku` alias           |
| Default scope     | Project                                                                   |

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

This writes credentials to `~/.observal/config.json`. When `~/.claude` or the
`claude` binary is found, login offers to configure telemetry, which runs the
same reconciliation as `observal doctor patch --harness claude-code`.

### 3. Pull an agent into Claude Code

```bash
observal pull <agent-name> --harness claude-code
```

Claude Code's default scope is project scope. By default, the agent is written
to `.claude/agents/{name}.md`.

To install into your user configuration:

```bash
observal pull <agent-name> --harness claude-code --scope user
```

User agents are written to `~/.claude/agents/{name}.md`.

Claude Code accepts a tool whitelist at pull time:

```bash
observal pull <agent-name> --harness claude-code --tools "Read,Grep,Bash"
```

The list is written verbatim to the `tools:` frontmatter field.

### 4. Install or repair the session push hooks

```bash
observal doctor patch --harness claude-code
```

This reconciles the Observal-managed entries in `~/.claude/settings.json`. It
adds what is missing, updates entries that carry an older spec version, and
leaves every hook it does not own untouched. Add `--dry-run` to preview.

---

## Config paths

| Purpose       | Project scope                    | User scope                         |
| ------------- | -------------------------------- | ---------------------------------- |
| Agent profile | `.claude/agents/{name}.md`       | `~/.claude/agents/{name}.md`       |
| Skills        | `.claude/skills/{name}/SKILL.md` | `~/.claude/skills/{name}/SKILL.md` |
| Hook config   | `.claude/settings.json`          | `~/.claude/settings.json`          |
| Hook scripts  | `.claude/hooks/`                 | `.claude/hooks/`                   |
| MCP servers   | `.mcp.json` (scanned)            | managed by `claude mcp add`        |

Claude Code MCP configs use the `mcpServers` key. A pulled agent lists its MCP
servers under `mcpServers:` in the profile frontmatter; stdio servers are
registered through `claude mcp add <name> -- <command> <args>` setup commands,
and SSE or streamable-HTTP servers are emitted as-is with their `url`,
`headers`, and `env`.

---

## Generated agent profile

```markdown
---
name: my-agent
description: "What the agent does"
model: sonnet
tools: Read,Grep,Bash
color: blue
mcpServers:
  - github
---

<rules content from the registry>
```

`model` is derived from the registry model name: any name containing `opus`,
`sonnet`, or `haiku` is reduced to that alias, and anything else is passed
through unchanged. `tools` and `color` appear only when set.

---

## Hook spec

### Event map

Claude Code event names are used as-is.

| Observal event     | Claude Code event  |
| ------------------ | ------------------ |
| `PreToolUse`       | `PreToolUse`       |
| `PostToolUse`      | `PostToolUse`      |
| `Stop`             | `Stop`             |
| `SessionStart`     | `SessionStart`     |
| `UserPromptSubmit` | `UserPromptSubmit` |
| `Notification`     | `Notification`     |
| `SubagentStop`     | `SubagentStop`     |

### Registry hooks

Hooks installed from the registry use the `command` handler type and are
written in Claude Code's native shape, one group per event with a wildcard
matcher:

```json
{
  "hooks": {
    "PreToolUse": [
      { "matcher": "*", "hooks": [{ "type": "command", "command": "python -m my_org.hooks.guard", "timeout": 30 }] }
    ]
  }
}
```

Script-based hooks are written to `.claude/hooks/`. Skill hooks are allowed to
read `OBSERVAL_ACCESS_TOKEN` through `allowedEnvVars`.

### Session push hooks

`observal doctor patch` installs one hook group for `UserPromptSubmit` and one
for `Stop`, each running:

```bash
python -m observal_cli.hooks.session_push --harness claude-code
```

Both entries carry an Observal metadata key with the hook spec version, which
is how later patches recognise and update their own entries. Server URL and
credentials are read from `~/.observal/config.json`, so no environment
variables are written into `settings.json`.

---

## Session delivery and parsing

Claude Code writes one JSONL transcript per session at
`~/.claude/projects/<project-key>/<session-id>.jsonl`, where `<project-key>` is
derived from the working directory. Subagent transcripts live at
`~/.claude/projects/<project-key>/<session-id>/subagents/agent-<id>.jsonl`.

On each hook invocation Observal resolves the transcript from the `session_id`
and `cwd` in the hook payload, reads only the lines added since the last
push, and sends them to the server, where the built-in `claude-code` parser
turns them into traces. Subagent transcripts are pushed alongside the parent
session and keyed to it, so they appear under the parent trace.

`observal reconcile` discovers recent transcripts directly from
`~/.claude/projects/` (default: the last 7 days, adjustable with `--since`) and
pushes anything the hooks missed.

---

## Scanning

`observal scan` reads the Claude Code home directory and reports:

- Skills from `~/.claude/skills/*/SKILL.md`
- Agents from `~/.claude/agents/*.md`
- Enabled plugins from `enabledPlugins` in `~/.claude/settings.json`, including
  their MCP servers (`.mcp.json`), skills (`SKILL.md`), and hooks (`hooks.json`)
- Project MCP servers from `.mcp.json` in the current project

---

## Caveats

**Default scope is project.** `observal pull <agent-name> --harness claude-code`
writes to `.claude/agents/` unless `--scope user` is specified.

**Session push hooks are user scope only.** `observal doctor patch` reconciles
`~/.claude/settings.json`. Project-level `.claude/settings.json` files are
used for registry hooks but are not patched for telemetry.

**MCP servers are not written to a settings file.** Pulling an agent with stdio
MCP servers produces `claude mcp add` commands to run; Observal does not edit
`.mcp.json` or `~/.claude.json` for you.

**Subagent transcripts depend on the parent transcript.** A subagent is linked
through its parent session id, so telemetry for a subagent whose parent was
never pushed has no trace to attach to.

**Plugin discovery relies on Claude Code's own plugin cache.** Plugins that are
enabled but not present under `~/.claude/plugins/` are skipped during scan.
