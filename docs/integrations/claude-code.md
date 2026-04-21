# Claude Code

Claude Code is the most complete integration. Native OpenTelemetry traces and logs, HTTP hooks, skills, MCP — everything Observal needs, first-class.

## What you get

* **Full OTLP telemetry** — token counts, cost, latency, model name
* **HTTP hooks** — no shell-command bridging required
* **Skill installation** — drop `SKILL.md` files into `.claude/skills/`
* **MCP server instrumentation** — `observal scan` wraps your existing config
* **Agent sub-config** — per-agent model choice, tool allowlists, project vs user scope

## Setup

```bash
# 1. Install and log in to the Observal CLI
uv tool install observal-cli
observal auth login

# 2. Instrument any MCP servers you already have
observal scan --ide claude-code

# 3. (Optional) pull an agent from the registry
observal pull <agent-id> --ide claude-code

# 4. Verify
observal doctor --ide claude-code
```

Restart Claude Code after `scan` or `pull`.

## Where things live

| File | Purpose |
| --- | --- |
| `~/.claude/settings.json` | Hooks, MCP servers (wrapped via `observal-shim`), telemetry config |
| `~/.claude/agents/<name>.json` | User-scoped sub-agent definitions |
| `.claude/agents/<name>.json` | Project-scoped sub-agent definitions |
| `.claude/skills/<skill-name>/` | Installed skills |

## OTLP telemetry

Claude Code exports OpenTelemetry natively. `observal scan` configures `OTEL_EXPORTER_OTLP_ENDPOINT` to point at the Observal OTEL collector (`http://localhost:4318` by default). Resource attributes include session ID, IDE ("claude-code"), and model name.

Token counts and cost come through as span attributes — you see them in the trace viewer without any extra work.

## Hooks

Claude Code supports native HTTP hooks, so Observal wires hooks directly into `~/.claude/settings.json` as `type: http` rather than shell-command bridging.

Events captured:

| Event | What it records |
| --- | --- |
| `SessionStart` | Start of a Claude Code session |
| `UserPromptSubmit` | The user's prompt |
| `PreToolUse` | Tool name and input, before the call |
| `PostToolUse` | Tool response, after the call |
| `Stop` | Session end, final token/cost stats |
| `SubagentStop` | Sub-agent lifecycle |
| `Notification` | IDE notifications |

Hook schema and handler types: [Hooks specification](../reference/hooks-spec.md).

## Sub-agents (`observal pull` options)

Claude Code supports nested sub-agents, each with their own model and tool allowlist. Control these at pull time:

```bash
observal pull code-reviewer --ide claude-code \
  --scope project \
  --model sonnet \
  --tools "Read,Bash,Grep"
```

| Option | Values | Default |
| --- | --- | --- |
| `--scope` | `project`, `user` | Interactive prompt |
| `--model` | `inherit`, `sonnet`, `opus`, `haiku` | `inherit` |
| `--tools` | Comma-separated tool whitelist | All available |

## Skills

Skills are portable instruction packages. Install one:

```bash
observal registry skill install code-review-skill --ide claude-code
```

This drops a directory into `.claude/skills/` that Claude Code loads on demand.

## Rules files

`AGENTS.md` / `CLAUDE.md` at the repo root get loaded as context. Observal doesn't touch these — author them by hand. Agents you pull may reference skills, which themselves contain instructions.

## Known limitations

* **Per-sub-agent cost** — Claude Code reports cost at the session level, not per-sub-agent. Observal shows session-level cost.
* **Tool names** — Claude Code's built-in tools (Read, Write, Bash, Grep) appear in traces alongside MCP tool calls. Filter by tool type in the web UI if needed.

## Troubleshooting

* **Hooks not firing** — run `observal doctor --ide claude-code --fix`.
* **MCP traces missing** — confirm the shim is in `~/.claude/settings.json` for each server. `observal doctor` flags unwrapped servers.
* **OTLP export dropped** — check that the OTEL collector (`observal-otel-collector`) is up and that `OTEL_EXPORTER_OTLP_ENDPOINT` is reachable from where Claude Code runs.

## Related

* [`observal pull`](../cli/pull.md)
* [`observal scan`](../cli/scan.md)
* [Data model](../concepts/data-model.md)
