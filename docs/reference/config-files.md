# Config files

Every file Observal reads or writes on the client (`~/.observal/`) and in each IDE's config directory.

## Client-side: `~/.observal/`

| File | Purpose | Permissions |
| --- | --- | --- |
| `config.json` | CLI config (server URL, access token, user info, timeout) | `0600` |
| `aliases.json` | User-defined shortcuts (`@my-mcp` → UUID) | `0600` |
| `last_results.json` | Last `list` / `show` output — enables row-number references | `0600` |
| `telemetry_buffer.db` | SQLite buffer for events when server is unreachable | `0600` |
| `profile.json` | Active `observal use` profile metadata | `0600` |
| `backups/` | Pre-switch IDE config backups (from `observal use`) | — |
| `keys/` | Server-side JWT keys (operators only; path controlled by `JWT_KEY_DIR`) | `0600` |

### `config.json` schema

```json
{
  "server_url": "https://observal.your-company.internal",
  "access_token": "ey...",
  "refresh_token": "ey...",
  "user_id": "f9f3...",
  "user_name": "alice@example.com",
  "output": "table",
  "color": "auto",
  "timeout": 30
}
```

Override any field at runtime with `observal config set <key> <value>` or with an env var (see [Environment variables](environment-variables.md)).

### `aliases.json` schema

```json
{
  "my-mcp":   "498c17ac-1234-4567-89ab-cdef01234567",
  "reviewer": "a01c5..."
}
```

Use anywhere that accepts `<id-or-name>` by prefixing with `@`.

## IDE-side

### Claude Code

| Path | Purpose |
| --- | --- |
| `~/.claude/settings.json` | Hooks, MCP servers (wrapped via `observal-shim`), telemetry config |
| `~/.claude/agents/<name>.json` | User-scoped sub-agent definitions |
| `.claude/agents/<name>.json` | Project-scoped sub-agent definitions |
| `.claude/skills/<skill>/` | Installed skills (SKILL.md + assets) |
| `AGENTS.md` / `CLAUDE.md` | Rules loaded into context |

### Kiro

| Path | Purpose |
| --- | --- |
| `.kiro/settings/mcp.json` | Project-level MCP servers (wrapped via `observal-shim`) |
| `~/.kiro/settings/mcp.json` | Global MCP servers |
| `.kiro/agents/<name>.json` | Project-level agent config with telemetry hooks |
| `~/.kiro/agents/<name>.json` | Global agent config |
| `.kiro/steering/<name>.md` | Steering files (system instructions with YAML frontmatter for inclusion modes) |
| `.kiro/skills/` | Kiro skills (SKILL.md) |
| `.kiro/hooks/` | Standalone hook definitions |
| `AGENTS.md` | Rules loaded into context (compat with Claude Code) |

### Cursor

| Path | Purpose |
| --- | --- |
| `.cursor/mcp.json` | MCP servers (wrapped via `observal-shim`) |
| `.cursor/rules/` | Cursor rules |
| `AGENTS.md` | Rules |

### VS Code

| Path | Purpose |
| --- | --- |
| `.vscode/mcp.json` | MCP servers (wrapped via `observal-shim`) |
| `AGENTS.md` | Rules loaded into context |

### Gemini CLI

| Path | Purpose |
| --- | --- |
| `.gemini/settings.json` | MCP servers + config |
| `AGENTS.md` / `GEMINI.md` | Rules |

### Codex CLI

| Path | Purpose |
| --- | --- |
| `AGENTS.md` | Rules (rules-only integration) |

## Backups

Every config modification by `observal scan`, `observal pull`, or `observal use` creates a timestamped `.bak` file next to the original:

```
~/.claude/settings.json.20260421_143055.bak
.kiro/settings/mcp.json.20260421_143055.bak
.cursor/mcp.json.20260421_143055.bak
```

Restore by moving the `.bak` back in place.

## File permissions

Client-side files under `~/.observal/` are created with mode `0600` (owner read/write only). This holds your access token — don't loosen the permissions.

## Related

* [Environment variables](environment-variables.md) — env-var override for every config field
* [`observal config`](../cli/config.md) — CLI surface for editing
