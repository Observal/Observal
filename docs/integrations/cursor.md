<!-- SPDX-FileCopyrightText: 2026 Faatih <22oo1cso41faatih@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Cursor

Cursor is a first-class Observal harness integration. Observal can install Cursor agents,
configure MCP servers, and collect Cursor session telemetry.

---

## Overview

Cursor agent profiles are Markdown files. Project agents live in `.cursor/agents/`.
User agents live in `~/.cursor/agents/`.

Cursor supports project and user installation scopes. MCP servers, hooks,
and agent profiles are managed under the `.cursor` configuration directory.

---

## Supported capabilities

| Capability      | Support                                                     |
| --------------- | ----------------------------------------------------------- |
| Agent profiles  | Project and user scope                                      |
| Hook bridge     | Supported                                                   |
| MCP servers     | `.cursor/mcp.json` and `~/.cursor/mcp.json`                 |
| Session parsing | Built-in Cursor session parser                              |
| Default scope   | Project                                                     |

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

### 3. Pull an agent into Cursor

```bash
observal agent pull <agent-name> --harness cursor
```

Cursor's default scope is project scope. By default, the agent is written to
`.cursor/agents/{name}.md`.

To install into your user configuration:

```bash
observal agent pull <agent-name> --harness cursor --scope user
```

User agents are written to `~/.cursor/agents/{name}.md`.

---

## Config paths

| Purpose       | Project scope                    | User scope                         |
| ------------- | -------------------------------- | ---------------------------------- |
| Agent profile | `.cursor/agents/{name}.md`       | `~/.cursor/agents/{name}.md`       |
| MCP config    | `.cursor/mcp.json`               | `~/.cursor/mcp.json`               |
| Skills        | `.cursor/skills/{name}/SKILL.md` | `~/.cursor/skills/{name}/SKILL.md` |
| Hook config   | `.cursor/hooks.json`             | `~/.cursor/hooks.json`             |

Cursor MCP configs use the `mcpServers` key.

---

## Hook spec

### Event map

| Observal event     | Cursor event         |
| ------------------ | -------------------- |
| `PreToolUse`       | `preToolUse`         |
| `PostToolUse`      | `postToolUse`        |
| `Stop`             | `sessionEnd`         |
| `SessionStart`     | `sessionStart`       |
| `UserPromptSubmit` | `beforeSubmitPrompt` |
| `SubagentStop`     | `subagentStop`       |

---

## Session parsing

Cursor uses the built-in `cursor` session parser.

---

## Caveats

**Default scope is project.** `observal agent pull <agent-name> --harness cursor`
writes to `.cursor/agents/` unless `--scope user` is specified.

**Configuration lives under `.cursor`.** Agent profiles, MCP configuration,
skills, and hooks are stored in the `.cursor` directory for project
installs and under `~/.cursor` for user installs.

**Auto model sentinel configuration is not available.**
