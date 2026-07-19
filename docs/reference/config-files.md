<!-- SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 tsitu0 <tomsitu0102@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Config files

Every file Observal reads or writes on the client (`~/.observal/`) and in each harness's config directory.

## Client-side: `~/.observal/`

| File | Purpose | Permissions |
| --- | --- | --- |
| `config.json` | CLI config (server URL, access token, user info, timeout) | `0600` |
| `aliases.json` | User-defined shortcuts (`@my-mcp` → UUID) | `0600` |
| `last_results.json` | Last `list` / `show` output - enables row-number references | `0600` |
| `telemetry_buffer.db` | Durable SQLite outbox for Python session exporters awaiting contiguous server acknowledgement | `0600` |
| `opencode_session_outbox/` | Per-session durable OpenCode plugin batches and acknowledged line state | `0600` files |
| `pi_session_outbox/` | Durable pending Pi extension batches | `0600` files |
| `sync_state.json` | Acknowledged byte/line cursors for file-backed exporters | owner read/write |
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

### Durable session outbox

Python session exporters persist each observed batch in `telemetry_buffer.db` before network delivery. OpenCode and Pi use per-session files under their native outbox directories because their TypeScript runtimes cannot call the Python SQLite engine. All follow the same protocol: pending data survives process restarts and failed attempts, and the source line advances only when the server's contiguous checkpoint covers the complete batch. Observal does not silently evict unacknowledged records at capacity.

`sync_state.json` is a cache of acknowledged local positions, not the authority for delivered history. If it is missing, corrupt, or stale, recovery validates and restores positions from the authenticated server checkpoint. Finalized sessions also send a SHA-256 audit manifest; hashing is not performed on ordinary incremental uploads.

Use `observal ops telemetry status` to inspect pending batch count, disk use, oldest pending time, and last successful acknowledgement.

### `aliases.json` schema

```json
{
  "my-mcp":   "498c17ac-1234-4567-89ab-cdef01234567",
  "reviewer": "a01c5..."
}
```

Use anywhere that accepts `<id-or-name>` by prefixing with `@`.

## harness-side

### Claude Code

| Path | Purpose |
| --- | --- |
| `~/.claude/settings.json` | Hooks, MCP servers, telemetry config |
| `~/.claude/agents/<name>.json` | User-scoped sub-agent definitions |
| `.claude/agents/<name>.json` | Project-scoped sub-agent definitions |
| `.claude/skills/<skill>/` | Installed skills (SKILL.md + assets) |
| `AGENTS.md` / `CLAUDE.md` | Rules loaded into context |

### Kiro

| Path | Purpose |
| --- | --- |
| `.kiro/settings/mcp.json` | Project-level MCP servers with direct commands or URLs |
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
| `.cursor/mcp.json` | MCP servers with direct commands or URLs |
| `.cursor/rules/` | Cursor rules |
| `AGENTS.md` | Rules |

### VS Code

| Path | Purpose |
| --- | --- |
| `.vscode/mcp.json` | MCP servers with direct commands or URLs |
| `AGENTS.md` | Rules loaded into context |

### Codex CLI

| Path | Purpose |
| --- | --- |
| `AGENTS.md` | Rules (rules-only integration) |

## Backups

Every config modification by `observal doctor patch` or `observal agent pull` creates a timestamped `.bak` file next to the original:

```
~/.claude/settings.json.20260421_143055.bak
.kiro/settings/mcp.json.20260421_143055.bak
.cursor/mcp.json.20260421_143055.bak
```

Restore by moving the `.bak` back in place.

## File permissions

Client-side files under `~/.observal/` are created with mode `0600` (owner read/write only). This holds your access token, so don't loosen the permissions.

## Related

* [Environment variables](environment-variables.md) - env-var override for every config field
* [`observal config`](../cli/config.md), CLI surface for editing
