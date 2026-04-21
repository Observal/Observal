# observal scan

Auto-detect MCP servers in your IDE configs, register them with Observal, and wrap them with `observal-shim` for telemetry. A timestamped backup is created automatically before any file is modified.

If you only do one thing with Observal, this is it.

## Synopsis

```bash
observal scan [--ide <ide>] [--all-ides] [--home] [--dry-run]
```

## Options

| Option | Description |
| --- | --- |
| `--ide <ide>` | Scope to one IDE: `claude-code`, `kiro`, `cursor`, `vscode`, `gemini-cli`, `codex`, `copilot` |
| `--all-ides` | Scan every IDE Observal knows about |
| `--home` | For Kiro: scan the global `~/.kiro/settings/mcp.json` (default is project-local `.kiro/settings/mcp.json`) |
| `--dry-run` | Print what would be changed without writing |

If you run `observal scan` with no flags, it auto-detects every installed IDE and scans each in turn.

## What it does

1. Finds MCP config files:
   * Claude Code: `~/.claude/settings.json`
   * Kiro: `.kiro/settings/mcp.json` (project) or `~/.kiro/settings/mcp.json` (home)
   * Cursor: `.cursor/mcp.json`
   * VS Code: `.vscode/mcp.json`
   * Gemini CLI: `.gemini/settings.json`
2. For each MCP server found, calls `POST /api/v1/scan` to register it with Observal (idempotent — running scan twice won't duplicate).
3. Rewrites the config so each server is invoked via `observal-shim` (stdio) or `observal-proxy` (HTTP/SSE). The wrapper is inserted as the new `command`, and the original command + args become wrapper arguments.
4. Saves a timestamped `.bak` next to each modified file — e.g. `.kiro/settings/mcp.json.20260421_143055.bak`.

## Example

```bash
observal scan
```

Output:

```
Scanning Claude Code config...
  ✓ filesystem        wrapped  (was: npx @modelcontextprotocol/server-filesystem)
  ✓ github            wrapped  (was: npx @modelcontextprotocol/server-github)

Scanning Kiro config (.kiro/settings/mcp.json)...
  ✓ mcp-obsidian      wrapped

Backups saved:
  ~/.claude/settings.json.20260421_143055.bak
  .kiro/settings/mcp.json.20260421_143055.bak

3 server(s) instrumented across 2 IDE(s).
```

Restart your IDE to pick up the new config.

## Dry-run first (recommended)

```bash
observal scan --dry-run
```

Prints what would change without touching any files. Useful for reviewing unfamiliar configs.

## Re-running is safe

`scan` is idempotent. A server already wrapped by `observal-shim` is detected and skipped. You can run it after every new MCP install to bring the new server into telemetry.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | At least one server instrumented or everything already instrumented |
| 1 | Server unreachable / auth failed |
| 3 | No IDE configs found |

## Undo

Each modified file has a `.bak`. Restore manually:

```bash
mv ~/.claude/settings.json.20260421_143055.bak ~/.claude/settings.json
```

## Related

* [`observal pull`](pull.md) — install a full agent (also wires up MCP servers)
* [`observal doctor`](doctor.md) — verify instrumentation end-to-end
* [Use Cases → Observe MCP traffic](../use-cases/observe-mcp-traffic.md) — narrative walkthrough
