# Observal E2E Demo

End-to-end integration tests that run against your **real local setup** — your actual `~/.claude` config, real MCP servers, real plugins, real agents. No mocks.

## Prerequisites

- Docker stack running (`cd docker && docker compose up -d`)
- CLI installed (`uv tool install --editable .`)
- `jq` and `curl` available
- Your `~/.claude/` directory has MCP plugins and agents configured

## Quick Start

```bash
cd demo
./run_demo.sh
```

The script:

1. Checks Docker services are healthy
2. Authenticates (auto-bootstraps admin on fresh server)
3. Reads your real `~/.claude/settings.json` to discover enabled plugins
4. Reads your real `~/.claude/agents/` to discover agent definitions
5. Registers discovered MCP servers and skills with Observal
6. Approves all pending submissions
7. Composes an agent from your real components
8. Pulls the agent back and verifies IDE config generation
9. Tests scan against your real IDE config
10. Queries ClickHouse and the API to verify everything landed

## What It Tests

| Phase | What |
|-------|------|
| Auth | `observal auth login` auto-bootstrap on fresh server |
| Discovery | Reads `~/.claude/settings.json` `enabledPlugins` and `~/.claude/plugins/cache/` |
| Registration | Submits each discovered MCP server / skill to the registry |
| Approval | Admin approves all pending items |
| Agent Compose | Creates an agent bundling all discovered components |
| Pull | Pulls agent as cursor, vscode, and claude-code IDE configs |
| Scan | Runs `observal scan` against real IDE config directory |
| Telemetry | Queries API endpoints to verify stats flow |

## Your Setup

The demo reads whatever is currently in your `~/.claude/`. A typical setup includes:

**MCP Servers:** context7, playwright, github, telegram
**Skills/Plugins:** frontend-design, superpowers, skill-creator, typescript-lsp, impeccable
**Agents:** 12 agent definitions in `~/.claude/agents/`

The script adapts dynamically — if you add or remove plugins, the demo picks it up.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OBSERVAL_SERVER` | `http://localhost:8000` | API server URL |
| `OBSERVAL_KEY` | from `~/.observal/config.json` | API key (auto-created if missing) |

## Full Test Suite

For a comprehensive multi-phase test (registration of all types, install flows, feedback, scan), use the all-types test:

```bash
./test_all_types.sh
```

This requires the Docker stack and a logged-in CLI.
