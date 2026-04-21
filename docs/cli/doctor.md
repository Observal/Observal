# observal doctor

Diagnose IDE compatibility end-to-end. Run this when something isn't working; run it with `--fix` to auto-repair common issues.

## Synopsis

```bash
observal doctor [--ide <ide>] [--fix] [--home]
```

## Options

| Option | Description |
| --- | --- |
| `--ide <ide>` | Scope to one IDE: `claude-code`, `kiro`, `cursor`, `vscode`, `gemini-cli`, `codex`, `copilot` |
| `--fix` | Auto-apply suggested fixes |
| `--home` | For Kiro: check global `~/.kiro/settings/mcp.json` (default is project) |

## What it checks

* The IDE CLI is installed and authenticated.
* MCP servers in the IDE config are wrapped with `observal-shim` / `observal-proxy`.
* Agent configs include Observal telemetry hooks.
* The Observal server is reachable at the configured URL.
* Your API key is valid.
* The telemetry buffer is healthy (not dangerously large).

## Example

```bash
observal doctor --ide claude-code
```

Output:

```
Claude Code diagnostics
  ✓ claude command found
  ✓ ~/.claude/settings.json exists
  ✓ 3 MCP server(s) wrapped with observal-shim
  ✓ Observal telemetry hooks installed
  ✓ Server reachable at http://localhost:8000
  ✓ API key valid

All checks passed.
```

When something is off:

```
Kiro diagnostics
  ✓ kiro command found
  ✗ 2 of 4 MCP server(s) NOT wrapped
    unwrapped: mcp-obsidian, filesystem
  ✗ Observal telemetry hooks MISSING from .kiro/agents/code-reviewer.json
  ✓ Server reachable at http://localhost:8000

2 issue(s) found. Run with --fix to auto-repair.
```

## Auto-fix

```bash
observal doctor --ide kiro --fix
```

`--fix` applies the same operations `scan` and `pull` would — rewriting configs and backing up originals. The action is logged and reversible.

Not every issue is auto-fixable. Unfixable ones (server unreachable, CLI not installed) are reported with a specific remediation step.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | All checks passed |
| 1 | At least one check failed |
| 3 | No IDE configs found |

## When `--fix` doesn't help

* **Server unreachable** — check `docker compose ps`. See [Self-Hosting → Troubleshooting](../self-hosting/troubleshooting.md).
* **API key invalid** — `observal auth login` again.
* **IDE CLI not installed** — install the IDE CLI first ([Kiro](../integrations/kiro.md) / [Claude Code](../integrations/claude-code.md)).

## Related

* [`observal scan`](scan.md) — the command `--fix` leans on for MCP wrapping
* [`observal pull`](pull.md) — the command `--fix` leans on for hook installation
