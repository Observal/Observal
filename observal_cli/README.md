# Observal CLI

Command-line interface for the Observal platform. Authenticate with a server, manage registry components, configure IDEs, and collect telemetry.

## Install

The CLI is packaged as a Python project. From the repo root:

```bash
uv pip install -e .
```

This installs five entry points:

| Command | Purpose |
|---------|---------|
| `observal` | Main CLI |
| `observal-shim` | Telemetry wrapper that sits in front of MCP servers |
| `observal-proxy` | HTTP proxy for MCP servers |
| `observal-sandbox-run` | Sandbox execution runner |
| `observal-graphrag-proxy` | GraphRAG integration proxy |

## Quick Start

```bash
observal auth login                  # connect to your Observal server
observal scan                        # discover and register IDE components
observal pull my-agent --ide cursor  # fetch agent config for Cursor
observal doctor                      # check IDE compatibility
```

## Commands

### Authentication

```
observal auth login       # connect to server (initializes admin on first run)
observal auth register    # create a new account
observal auth logout      # clear saved credentials
observal auth whoami      # show current user
observal auth status      # check connectivity and buffer status
```

### Agent Workflow

```
observal agent init              # scaffold observal-agent.yaml
observal agent add mcp <id>      # add a component to the agent definition
observal agent build             # validate the definition
observal agent publish           # push to the server
observal agent list              # list active agents
observal agent show <id>         # show agent details
observal agent install <id> --ide <ide>  # get IDE config snippet
```

### Component Registry

Each component type (mcp, skill, hook, prompt, sandbox) shares the same subcommand pattern:

```
observal registry <type> submit      # submit for review
observal registry <type> list        # list approved items
observal registry <type> show <id>   # show details
observal registry <type> install <id> --ide <ide>  # get IDE config
observal registry <type> delete <id> # delete
```

Hooks have an extra `sync` subcommand. Prompts have an extra `render` subcommand for variable substitution.

### Operations

```
observal ops review list           # pending submissions
observal ops review approve <id>   # approve
observal ops review reject <id> --reason "..."  # reject
observal ops telemetry status      # check telemetry flow
observal ops telemetry test        # send a test event
observal ops sync                  # flush buffered events
observal ops overview              # system-wide stats
observal ops metrics <id>          # metrics for an MCP or agent
```

### Utilities

```
observal pull <agent> --ide <ide>  # write agent config to IDE files
observal scan [--shim] [--all-ides]  # discover components, optionally wrap with shim
observal use <profile>             # swap IDE config from a profile
observal doctor                    # diagnose IDE/Observal issues
observal doctor sli                # reinstall telemetry hooks
observal config show               # show current config
observal uninstall                 # tear down Docker, remove config
```

## Supported IDEs

| IDE / Tool | Support Level |
|------------|--------------|
| Claude Code | Fully supported |
| Kiro CLI | Supported (next most tested) |
| Cursor, VS Code, Gemini CLI | Untested |

The `--ide` flag controls which config format is generated. Each IDE has its own config paths and JSON structure.

## Config Files

All CLI state lives in `~/.observal/`:

| File | Contents |
|------|----------|
| `config.json` | Server URL, tokens, user ID |
| `aliases.json` | User-defined name-to-UUID aliases |
| `last_results.json` | Cached list results for numeric shorthand |
| `telemetry_buffer.db` | SQLite buffer for offline event queuing |
| `keys/server_public.pem` | Server public key for payload encryption |

## Telemetry

When `observal scan --shim` wraps an MCP server, tool calls flow through `observal-shim` which records usage events. If the server is unreachable, events are buffered locally in `telemetry_buffer.db` and flushed on the next `observal ops sync`.

Hook scripts in `observal_cli/hooks/` capture IDE-level events (prompts, tool use, subagent spawning) and forward them to the server.

## Directory Layout

```
observal_cli/
├── main.py                  # Root app, command registration
├── config.py                # Config file I/O
├── client.py                # HTTP client with auth and token refresh
├── constants.py             # Valid IDEs, categories, component types
├── render.py                # Rich output formatting
├── analyzer.py              # Repo analysis for MCP submission
├── settings_reconciler.py   # Non-destructive Claude Code settings merge
├── cmd_auth.py              # Auth commands
├── cmd_agent.py             # Agent commands
├── cmd_mcp.py               # MCP commands
├── cmd_skill.py             # Skill commands
├── cmd_hook.py              # Hook commands
├── cmd_prompt.py            # Prompt commands
├── cmd_sandbox.py           # Sandbox commands
├── cmd_pull.py              # Pull command
├── cmd_scan.py              # Scan command
├── cmd_doctor.py            # Doctor command
├── cmd_ops.py               # Operations commands
├── cmd_profile.py           # Profile swapping
├── cmd_uninstall.py         # Uninstall command
├── shim.py                  # observal-shim entrypoint
├── proxy.py                 # observal-proxy entrypoint
├── sandbox_runner.py        # observal-sandbox-run entrypoint
├── graphrag_proxy.py        # observal-graphrag-proxy entrypoint
└── hooks/                   # Telemetry hook scripts
```
