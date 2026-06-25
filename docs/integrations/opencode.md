<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# OpenCode

OpenCode is a first-class Observal harness integration. Observal can install
OpenCode agents, configure MCP servers, expose skills, install hook plugins, and
collect OpenCode session telemetry.

---

## Overview

OpenCode agent profiles are Markdown files. Project agents live in
`.opencode/agents/`. User agents live in `~/.config/opencode/agents/`.

OpenCode session telemetry uses an in-process TypeScript plugin. The plugin is
installed by `observal auth login` or `observal doctor patch`. Agent pulls write
agent profiles and update the Observal lockfile, but they do not embed the
telemetry plugin in each agent file.

The plugin listens to OpenCode session and message events, reads message data
through the OpenCode client API, converts new messages into Observal session
lines, and sends them to Observal.

---

## Supported capabilities

| Capability | Support |
|---|---|
| Agent profiles | Project and user scope |
| Hook bridge | OpenCode plugin |
| Plugin events | `session.created`, `session.idle`, `message.updated` |
| MCP servers | `opencode.json` and `~/.config/opencode/opencode.json` |
| Agent prompt | Registry prompts are written into the generated OpenCode agent profile |
| Skills | `.opencode/skills/{name}/SKILL.md` and `~/.config/opencode/skills/{name}/SKILL.md` |
| Session parsing | OpenCode plugin exports JSONL-compatible session lines |
| Telemetry | MCP telemetry through `observal-shim`; session telemetry through the plugin |
| Model selection | Registry-backed OpenCode model catalog |

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

This writes credentials to `~/.observal/config.json`. If OpenCode is detected,
login can install the Observal plugin.

### 3. Pull an agent into OpenCode

```bash
observal agent pull <agent-name> --harness opencode
```

OpenCode's default scope is user scope. By default, the agent is written to
`~/.config/opencode/agents/{name}.md`.

To install into the current project:

```bash
observal agent pull <agent-name> --harness opencode --scope project
```

Project agents are written to `.opencode/agents/{name}.md`.

### 4. Install or refresh the OpenCode plugin

```bash
observal doctor patch --all --harness opencode
```

This installs or updates `observal-plugin.ts` when the plugin is missing, stale,
or different from the bundled source.

---

## Config paths

| Purpose | Project scope | User scope |
|---|---|---|
| Agent profile | `.opencode/agents/{name}.md` | `~/.config/opencode/agents/{name}.md` |
| MCP config | `opencode.json` | `~/.config/opencode/opencode.json` |
| Skill definition | `.opencode/skills/{name}/SKILL.md` | `~/.config/opencode/skills/{name}/SKILL.md` |
| Plugin hooks | `.opencode/plugins/{name}.ts` | `~/.config/opencode/plugins/{name}.ts` |
| Observal plugin | `.opencode/plugins/observal-plugin.ts` | `~/.config/opencode/plugins/observal-plugin.ts` |
| Observal credentials | `~/.observal/config.json` | `~/.observal/config.json` |
| Observal lockfile | `~/.observal/lockfile.json` | `~/.observal/lockfile.json` |

OpenCode MCP configs use the `mcp` key.

---

## Plugin spec

Observal installs a TypeScript plugin named `observal-plugin.ts`. The plugin
subscribes to OpenCode runtime events:

| OpenCode event | Observal use |
|---|---|
| `session.created` | Capture the active OpenCode agent name for the session |
| `message.updated` | Mark the session as having new data to push |
| `session.idle` | Fetch new messages and send them to Observal |
| `session.updated` | Refresh active agent tracking when emitted by OpenCode |
| `session.next.agent.switched` | Refresh active agent tracking when the active agent changes |

The bundled spec version is checked by `doctor patch`, along with the plugin
content hash, so stale local copies are replaced.

---

## Attribution

OpenCode exposes the active agent name in session events, not an Observal UUID.
The Observal lockfile maps that OpenCode agent name back to the registry agent
id and installed version.

1. `observal agent pull` writes the OpenCode agent profile and records the
   agent name, id, version, scope, and project directory in
   `~/.observal/lockfile.json`.
2. The OpenCode plugin receives `session.created` or agent switch events and
   reads the active OpenCode agent name.
3. Built-in OpenCode agents such as `build`, `plan`, `general`, `explore`,
   `scout`, `compaction`, `title`, and `summary` are ignored.
4. The plugin searches `~/.observal/lockfile.json` under the `opencode` harness
   for an entry whose `name` or `id` matches the active agent.
5. If multiple entries match, a project-scoped entry for the current directory
   wins, then a user-scoped entry, then the first match.
6. The session payload is sent with the resolved `agent_id` and
   `agent_version`.
7. If no lockfile match exists, the plugin skips attribution for that session
   instead of guessing.

---

## Session push behavior

The OpenCode plugin works as follows:

1. Load `~/.observal/config.json` for server URL and API key.
2. Track active sessions in memory.
3. Resolve the active OpenCode agent name through `~/.observal/lockfile.json`.
4. On `session.idle`, fetch messages from `client.session.messages`.
5. Convert messages into JSONL-compatible Observal session lines.
6. Send only messages that have not already been pushed for that session.
7. Mark the final payload when OpenCode reports completion.

The plugin keeps a small in-memory session cache and drops the oldest tracked
session when the cache is full.

---

## Agent profile format

OpenCode agents are Markdown files. Observal writes the agent prompt into the
profile selected by scope:

```markdown
---
name: my-agent
---

You are an OpenCode agent with the following specialization...
```

---

## Caveats

**The plugin is shared per OpenCode install.** It is installed by auth login or
`doctor patch`, not by each agent pull.

**Attribution depends on the lockfile.** If an agent profile is copied by hand
without running `observal agent pull`, the plugin may see the OpenCode agent
name but have no Observal id or version to send.

**Built-in OpenCode agents are ignored.** Sessions for built-in agents are not
attributed to registry agents.

**MCP config is OpenCode-specific.** OpenCode uses `opencode.json` and the
`mcp` key, not Kiro or Claude Code MCP paths.
