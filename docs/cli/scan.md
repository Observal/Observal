<!-- SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 tsitu0 <tomsitu0102@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# observal scan

Discover MCP servers, hooks, and telemetry configuration across your IDE configs. `scan` is **read-only** -- it shows what you have without modifying any files.

To actually instrument your IDEs (wrap MCP servers with `observal-shim`, install hooks, configure OTel), use [`observal doctor patch`](doctor.md).

## Synopsis

```bash
observal scan [--ide <ide>]
```

## Options

| Option | Description |
| --- | --- |
| `--ide <ide>` | Scope to one IDE: `claude-code`, `kiro`, `cursor`, `vscode`, `gemini-cli`, `codex`, `copilot` |

If you run `observal scan` with no flags, it auto-detects every installed IDE and scans each in turn.

## What it does

1. Finds MCP config files:
   * Claude Code: `~/.claude/settings.json`
   * Kiro: `.kiro/settings/mcp.json` (project) or `~/.kiro/settings/mcp.json` (home)
   * Cursor: `.cursor/mcp.json`
   * VS Code: `.vscode/mcp.json`
   * Gemini CLI: `.gemini/settings.json`
   * Copilot CLI: `~/.copilot/mcp-config.json`
2. Lists every MCP server found, its transport type, and whether it is already wrapped by `observal-shim`.
3. Reports any installed telemetry hooks and OTel configuration.

No files are written. No servers are contacted. No registration happens.

## Example

```bash
observal scan
```

Output:

```
Claude Code (~/.claude/settings.json)
  filesystem        npx @modelcontextprotocol/server-filesystem   not wrapped
  github            npx @modelcontextprotocol/server-github       not wrapped

Kiro (.kiro/settings/mcp.json)
  mcp-obsidian      mcp-obsidian                                  not wrapped

2 IDE(s) found, 3 MCP server(s) total, 0 wrapped.
```

## Scoping to a single IDE

```bash
observal scan --ide claude-code
```

## What to do next

Once you see what's installed, instrument it:

```bash
# Instrument everything (hooks + shims + OTel config) across all IDEs
observal doctor patch --all --all-ides

# Or target a specific IDE
observal doctor patch --all --ide kiro

# Or only install hooks
observal doctor patch --hook --ide claude-code

# Preview changes without writing anything
observal doctor patch --all --all-ides --dry-run
```

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | At least one IDE config found |
| 1 | Server unreachable / auth failed |
| 3 | No IDE configs found |

## Related

* [`observal doctor patch`](doctor.md) — instrument your IDEs (hooks, shims, OTel)
* [`observal agent pull`](pull.md) — install a full agent (also wires up MCP servers)
* [`observal doctor`](doctor.md) — diagnose instrumentation end-to-end
* [Use Cases -- Observe MCP traffic](../use-cases/observe-mcp-traffic.md) — narrative walkthrough
