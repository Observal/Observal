<!-- SPDX-FileCopyrightText: 2026 Rajat <rajattempest8736@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Pi

Pi is a first-class Observal harness. Observal can pull agents into Pi, write each agent's MCP servers and skills to the right Pi paths, and collect traces through the `observal-pi` extension.

## How Pi works with Observal

Pi loads its active runtime from files under `~/.pi/agent/` plus project context files. Observal keeps user-scoped pulled agents in profile directories under `~/.pi/agent/agents/` so you can keep more than one agent installed and swap between them inside Pi.

The `observal-pi` extension owns the Pi-specific behavior:

1. It provides `/agent`, a Pi command that switches between Observal-managed user profiles.
2. It copies the selected profile into Pi's active files.
3. It updates `~/.observal/config.json` with the active agent binding.
4. It sends Pi session JSONL lines to Observal on Pi lifecycle events.

Pi does not use shell hook scripts for telemetry. Install `observal-pi` for trace collection.

## Supported features

| Feature | Support |
|---|---|
| Agents | User profiles with `/agent` switching, project pull for the current project |
| MCP servers | `mcp.json` with `mcpServers` |
| Skills | `SKILL.md` directories inside the active or profile `skills/` directory |
| Hooks | Extension based, via `observal-pi` |
| Session parsing | Pi JSONL parser on the server |
| Default scope | User |

## Setup

### 1. Install and authenticate the Observal CLI

```bash
uv tool install observal-cli
observal auth login
```

### 2. Install the Pi extension

Install it directly with Pi:

```bash
pi install npm:observal-pi
```

Or let Observal add it to `~/.pi/agent/settings.json`:

```bash
observal doctor patch --hook --harness pi
```

### 3. Pull an agent for Pi

User scope is the default and is the mode that supports `/agent` profile switching:

```bash
observal pull <agent-name> --harness pi
```

Project scope writes the agent into the current project instead:

```bash
observal pull <agent-name> --harness pi --scope project
```

### 4. Switch active user profiles in Pi

Inside Pi, run:

```text
/agent
```

Choose a profile from the list, or pass one explicitly:

```text
/agent <safe-agent-name>
```

The command reads profiles from `~/.pi/agent/agents/`. It does not select project-scoped profiles.

## File locations

### User scoped pull

A user scoped pull writes an isolated profile. Nothing is activated until `/agent` copies the profile into the active Pi files.

| Purpose | Pulled profile path | Active path after `/agent` |
|---|---|---|
| Agent instructions | `~/.pi/agent/agents/{safe-agent-name}/AGENTS.md` | `~/.pi/agent/AGENTS.md` |
| MCP servers | `~/.pi/agent/agents/{safe-agent-name}/mcp.json` | `~/.pi/agent/mcp.json` |
| Skills | `~/.pi/agent/agents/{safe-agent-name}/skills/{skill}/SKILL.md` | `~/.pi/agent/skills/{skill}/SKILL.md` |
| Sandboxes, when present | `~/.pi/agent/agents/{safe-agent-name}/sandboxes/` | `~/.pi/agent/sandboxes/` |

On first switch, `/agent` backs up the current active files into `~/.pi/agent/agents/default/`. Switching to another profile replaces the active `AGENTS.md`, `SYSTEM.md`, `mcp.json`, `skills/`, and `sandboxes/` with the selected profile's files.

### Project scoped pull

Project scope is for a repo-local Pi setup. It does not participate in `/agent` switching.

| Purpose | Project path |
|---|---|
| Agent instructions | `AGENTS.md` |
| MCP servers | `.pi/agents/{safe-agent-name}/mcp.json` |
| Skills | `.pi/agents/{safe-agent-name}/skills/{skill}/SKILL.md` |

Pi reads `AGENTS.md` from the project context. The isolated `.pi/agents/{safe-agent-name}/` paths keep MCP and skill assets grouped with the pulled agent.

## Trace collection

The `observal-pi` extension reads Pi's session JSONL files and sends new lines to Observal. It runs on Pi lifecycle events:

| Pi event | Observal behavior |
|---|---|
| `session_start` | Load `~/.observal/config.json`, compute layer snapshot, recover recent unfinished sessions |
| `agent_end` | Push newly written session lines |
| `session_shutdown` | Push remaining lines and mark the cursor finalized |

Uploads are incremental and split into batches of at most 500 lines. Failures are fail open, so telemetry errors do not stop Pi.

The extension also uploads a Pi layer snapshot that includes active files, user profiles, skill files, MCP config, settings, and sandbox files when present. This lets Observal attribute traces to the active agent and detect config drift.

## Extension commands

| Command | Description |
|---|---|
| `/agent` | List installed user profiles and switch to one |
| `/agent <safe-agent-name>` | Switch directly to one user profile |
| `/obs-sync` | Show pushed line count and server URL |
| `/obs-sync flush` | Push pending session lines immediately |
| `/obs-sync config` | Show the Observal config path and server URL |

## Caveats

- Pulling a user scoped agent does not activate it. Use `/agent` in Pi.
- `/agent` only reads `~/.pi/agent/agents/`, not project `.pi/agents/`.
- Telemetry requires `observal-pi`; shell hook specs are not used for Pi.
- MCP configs use `mcpServers`.
- The active agent binding lives in `~/.observal/config.json` under `active_agent`.
