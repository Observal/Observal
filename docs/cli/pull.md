# observal pull

Install a complete agent — MCP servers, skills, hooks, prompts, sandboxes, and IDE-specific config — into an IDE in one command.

## Synopsis

```bash
observal pull <agent-id-or-name> --ide <ide> [OPTIONS]
```

## Required

| Argument / option | Description |
| --- | --- |
| `<agent-id-or-name>` | Agent UUID, name, `@alias`, or row number from last `agent list` |
| `--ide <ide>` | Target IDE: `claude-code`, `kiro`, `cursor`, `vscode`, `gemini-cli`, `codex`, `copilot` |

## Options

| Option | Description |
| --- | --- |
| `--dir <path>` | Install target directory (default: current working directory for project-scoped installs) |
| `--dry-run` | Preview files that would be written without writing them |
| `--scope project\|user` | Claude Code / Kiro / Gemini: install at project or user scope |
| `--model inherit\|sonnet\|opus\|haiku` | Claude Code only: sub-agent model (default: `inherit`) |
| `--tools <list>` | Claude Code only: comma-separated tool allowlist |
| `--yes` / `-y` | Skip confirmation prompts |

## What gets installed

Varies by IDE. For Claude Code:

| File | Contents |
| --- | --- |
| `~/.claude/agents/<name>.json` (user scope) | Sub-agent definition with instructions, model, tools |
| `.claude/agents/<name>.json` (project scope) | Project-scoped version of the above |
| `~/.claude/settings.json` | Telemetry hooks, MCP servers wrapped via `observal-shim` |
| `.claude/skills/<skill-name>/` | Every skill referenced by the agent |

For Kiro:

| File | Contents |
| --- | --- |
| `~/.kiro/agents/<name>.json` | Agent config with Observal telemetry hooks |
| `.kiro/steering/<name>.md` | Steering file (the agent's system instructions) |
| `.kiro/settings/mcp.json` | MCP servers, wrapped via `observal-shim` |

For Cursor / VS Code / Gemini CLI: primarily MCP config + rules files at the appropriate path.

## Environment variables

Every MCP server the agent depends on may declare required env vars (GitHub token, API keys, etc.). The CLI prompts you for each one during pull:

```
MCP github-mcp requires GITHUB_TOKEN — enter value (or leave blank to set later):
```

Values are written into your IDE config (not uploaded to Observal).

## Examples

### Basic

```bash
observal pull code-reviewer --ide claude-code
```

### Preview first

```bash
observal pull code-reviewer --ide claude-code --dry-run
```

### Project-scoped Claude Code install with a specific model and tool allowlist

```bash
observal pull code-reviewer --ide claude-code \
  --scope project \
  --model sonnet \
  --tools "Read,Bash,Grep"
```

### Non-interactive

```bash
export GITHUB_TOKEN=ghp_...
observal pull code-reviewer --ide claude-code -y
```

## Restart your IDE

After pull, restart the IDE so it picks up the new config. Telemetry starts flowing immediately after restart.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | All components installed successfully |
| 1 | Network / auth / write error |
| 3 | Agent not found |
| 4 | Agent requires a feature the target IDE doesn't support |

## Related

* [`observal agent`](agent.md) — author and publish agents
* [`observal scan`](scan.md) — instrument the MCP servers you already have (no pulling)
* [`observal doctor`](doctor.md) — verify the pull wired up correctly
* [Use Cases → Share agent configs across IDEs](../use-cases/share-agent-configs.md)
