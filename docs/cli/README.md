# CLI Reference

Complete reference for the `observal` CLI. Every subcommand has its own page — this overview is the index.

> **New to Observal?** Start with [Quickstart](../getting-started/quickstart.md) and come back here when you need a specific command.

## Command groups

| Command | What it does |
| --- | --- |
| [`observal auth`](auth.md) | Authentication and account management |
| [`observal config`](config.md) | Local CLI configuration, aliases |
| [`observal scan`](scan.md) | Auto-detect and instrument IDE MCP configs |
| [`observal pull`](pull.md) | Install a published agent into an IDE |
| [`observal registry`](registry.md) | Publish and manage components (MCP / skill / hook / prompt / sandbox) |
| [`observal agent`](agent.md) | Author and publish agents |
| [`observal ops`](ops.md) | Observability and operations (traces, spans, metrics, feedback) |
| [`observal admin`](admin.md) | Admin operations (settings, users, review, eval, canaries) |
| [`observal doctor`](doctor.md) | Diagnose IDE compatibility |
| [`observal profile`](profile.md) | Switch IDE configs to a git-hosted profile |
| [`observal self`](self.md) | Upgrade or downgrade the CLI |

## Global options

Any subcommand accepts these.

| Option | Short | Description |
| --- | --- | --- |
| `--version` | `-V` | Print the CLI version and exit |
| `--verbose` | `-v` | Verbose output |
| `--debug` | — | Debug-level logging (extremely verbose) |
| `--help` | — | Show help for any command or subcommand |

## Exit codes

Consistent across all commands:

| Code | Meaning |
| --- | --- |
| 0 | Success |
| 1 | General error (network, auth, validation) |
| 2 | Usage error (bad flags, unknown subcommand) |
| 3 | Not found (agent, MCP, user, etc.) |
| 4 | Permission denied (RBAC role too low) |

## Non-interactive mode

For scripts and CI, pair flags with environment variables:

```bash
export OBSERVAL_SERVER_URL=https://observal.your-company.internal
export OBSERVAL_API_KEY=<your-key>

observal ops traces --limit 100 --output json | jq
```

Full env var reference: [Environment variables](../reference/environment-variables.md).

## Output formats

Read-heavy commands (`list`, `show`, `traces`, `spans`) support `--output`:

```bash
observal registry mcp list --output table    # default, TTY-friendly
observal registry mcp list --output json     # machine-readable
observal registry mcp list --output plain    # CSV-like, script-friendly
```

## Aliases

IDs get long fast. Create shortcuts:

```bash
observal config alias my-mcp 498c17ac-1234-4567-89ab-cdef01234567
observal registry mcp show @my-mcp
```

See [`observal config`](config.md) for details.

## Next

→ [`observal auth`](auth.md) — you'll need to log in first.
