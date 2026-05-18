<!-- SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 tsitu0 <tomsitu0102@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# observal doctor

Diagnose IDE compatibility end-to-end. Run this when something isn't working; use `doctor patch` to apply instrumentation.

## Synopsis

```bash
observal doctor [--ide <ide>] [--fix]
```

## Options

| Option | Description |
| --- | --- |
| `--ide <ide>` | Scope to one IDE: `claude-code`, `kiro`, `cursor`, `vscode`, `gemini-cli`, `codex`, `copilot` |
| `--fix` | Auto-apply suggested fixes |

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

`--fix` applies the same operations `doctor patch` and `pull` would -- rewriting configs and backing up originals. The action is logged and reversible.

Not every issue is auto-fixable. Unfixable ones (server unreachable, CLI not installed) are reported with a specific remediation step.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | All checks passed |
| 1 | At least one check failed |
| 3 | No IDE configs found |

## When `--fix` doesn't help

* **Server unreachable** -- check `docker compose ps`. See [Self-Hosting -- Troubleshooting](../self-hosting/troubleshooting.md).
* **API key invalid** -- `observal auth login` again.
* **IDE CLI not installed** -- install the IDE CLI first ([Kiro](../integrations/kiro.md) / [Claude Code](../integrations/claude-code.md)).

---

# observal doctor patch

Apply instrumentation to your IDEs: install telemetry hooks, wrap MCP servers with `observal-shim`, and configure OTel export. This is the command that actually modifies files. A timestamped backup is created before any file is changed.

## Synopsis

```bash
observal doctor patch [--hook] [--shim] [--all] [--all-ides] [--ide <ide>] [--dry-run]
```

## Options

| Option | Description |
| --- | --- |
| `--hook` | Install telemetry hooks into IDE configs |
| `--shim` | Wrap MCP servers with `observal-shim` for telemetry |
| `--all` | All of the above: hooks + shims + OTel config |
| `--all-ides` | Target every detected IDE |
| `--ide <ide>` | Target a specific IDE (repeatable: `--ide kiro --ide claude-code`) |
| `--dry-run` / `-n` | Print what would be changed without writing any files |

You must specify at least one of `--hook`, `--shim`, or `--all` to tell `patch` what to do. You must specify at least one of `--all-ides` or `--ide <name>` to tell it where.

## What it does

1. **`--hook`**: Installs Observal telemetry hooks into IDE config files (native HTTP hooks for Claude Code, shell-command hooks for Kiro, Copilot CLI, etc.).
2. **`--shim`**: Rewrites MCP server entries so each server runs through `observal-shim` (stdio) or `observal-proxy` (HTTP/SSE). The original command + args become wrapper arguments.
3. **`--all`**: Does everything `--hook` and `--shim` do, plus configures `OTEL_EXPORTER_OTLP_ENDPOINT` for IDEs that support native OTLP export.

Each modified file gets a timestamped `.bak` saved next to it (e.g. `.kiro/settings/mcp.json.20260421_143055.bak`).

## Examples

### Instrument everything across all IDEs

```bash
observal doctor patch --all --all-ides
```

### Instrument a single IDE

```bash
observal doctor patch --all --ide kiro
observal doctor patch --all --ide claude-code
```

### Only install hooks for Claude Code

```bash
observal doctor patch --hook --ide claude-code
```

### Only wrap MCP servers for Kiro

```bash
observal doctor patch --shim --ide kiro
```

### Preview first (recommended)

```bash
observal doctor patch --all --all-ides --dry-run
```

Prints what would change without touching any files. Useful for reviewing unfamiliar configs.

### Multiple IDEs

```bash
observal doctor patch --all --ide kiro --ide gemini-cli
```

## Re-running is safe

`doctor patch` is idempotent. A server already wrapped by `observal-shim` is detected and skipped. Hooks already installed are detected and skipped. You can run it after every new MCP install to bring the new server into telemetry.

## Example output

```bash
observal doctor patch --all --all-ides
```

```
Patching Claude Code...
  ✓ filesystem        wrapped  (was: npx @modelcontextprotocol/server-filesystem)
  ✓ github            wrapped  (was: npx @modelcontextprotocol/server-github)
  ✓ Telemetry hooks installed

Patching Kiro...
  ✓ mcp-obsidian      wrapped
  ✓ Telemetry hooks installed

Backups saved:
  ~/.claude/settings.json.20260421_143055.bak
  .kiro/settings/mcp.json.20260421_143055.bak

3 server(s) instrumented, hooks installed across 2 IDE(s).
```

Restart your IDE to pick up the new config.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | At least one change applied or everything already instrumented |
| 1 | Server unreachable / auth failed |
| 3 | No IDE configs found |

## Undo

Each modified file has a `.bak`. Restore manually:

```bash
mv ~/.claude/settings.json.20260421_143055.bak ~/.claude/settings.json
```

## Related

* [`observal scan`](scan.md) -- read-only discovery of what's installed
* [`observal agent pull`](pull.md) -- install a full agent (also wires up MCP servers)
* [Use Cases -- Observe MCP traffic](../use-cases/observe-mcp-traffic.md) -- narrative walkthrough
