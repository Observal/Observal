---
# SPDX-FileCopyrightText: 2026 Hemalatha Madeswaran <hemalathamadeswaran@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only
name: observal-advanced
command: observal
description: Advanced Observal operations including session reconciliation, CLI upgrades and downgrades, complete uninstallation, and local fallback mode for offline use. Use when the user wants to reconcile sessions, upgrade or downgrade the CLI, uninstall Observal, or write agent configs locally when the server is unreachable.
version: 2.0.0
owner: observal
---

# Observal Advanced Operations

## Procedure: Reconcile Sessions

Push local session JSONL to server for full trace context. Normally automatic via hooks.

Manual run for crash recovery:

```bash
python -m observal_cli.cmd_reconcile
```

Not a Typer command. No flags needed.

---

## Procedure: Self-Manage CLI

```bash
observal self status
observal self upgrade
observal self upgrade --version 2.5.0
observal self downgrade --list
observal self downgrade --version 2.4.0
observal self rollback
```

---

## Procedure: Uninstall

Completely removes Observal. **Destructive and irreversible.**

```bash
observal self uninstall
```

Requires typing `confirm` (not `--yes`). Selective flags:
- `--keep-config`: preserve `~/.observal/`
- `--keep-cli`: keep the CLI binary
- `--keep-repo`: keep the cloned repo
- `--repo-dir PATH`: specify repo location

---

## Procedure: Local Fallback Mode

Use **only** when a command exits with `Connection failed` or `Not configured`.

| IDE | User-scope path | Project-scope path |
|---|---|---|
| Claude Code | `~/.claude/agents/<name>.md` | `.claude/agents/<name>.md` |
| Kiro | `~/.kiro/agents/<name>.json` | `.kiro/agents/<name>.json` |
| Cursor | `~/.cursor/rules/<name>.mdc` | `.cursor/rules/<name>.mdc` |
| Gemini CLI | `~/.gemini/agents/<name>.md` | `.gemini/agents/<name>.md` |
| VS Code | `~/.config/Code/User/agents/<name>.md` | `.vscode/agents/<name>.md` |
| Codex CLI | `~/.codex/agents/<name>.md` | `.codex/agents/<name>.md` |
| Copilot CLI | `~/.config/github-copilot/agents/<name>.md` | `.github/copilot/agents/<name>.md` |
| OpenCode | `~/.opencode/agents/<name>.md` | `.opencode/agents/<name>.md` |

**Kiro** (`~/.kiro/agents/<name>.json`):

```json
{"name":"<name>","description":"<desc>","prompt":"<prompt>","model":"claude-sonnet-4-20250514","mcpServers":{},"tools":["*"],"resources":["skill://~/.kiro/skills/*/SKILL.md"]}
```

**Claude Code, Gemini CLI, VS Code, Codex CLI, Copilot CLI, OpenCode** (markdown):

```markdown
---
name: <name>
description: <desc>
---
<prompt>
```

**Cursor** (`.mdc`):

```markdown
---
name: <name>
description: <desc>
---
<prompt>
```

After writing locally, remind the user to run `observal agent create` once the server is reachable.

---

## Output Contract

1. One sentence stating intent.
2. The exact command in a fenced code block.
3. The result: success / specific error.
4. The next action, or "done".
