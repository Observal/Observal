---
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 Hemalatha Madeswaran <hemalathamadeswaran@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only
name: observal
command: observal
description: "Core Observal CLI operations: pull agents into your IDE, scan installed components, diagnose and patch IDE configs, authenticate, manage CLI settings, and discuss agent insights. Use when the user wants to install an agent, check setup, login, configure the CLI, or ask how an agent is doing."
version: 2.1.0
owner: observal
---

# Observal: Core CLI Operations

## Critical Rules

1. **EXECUTE commands**: run them in your shell, do not just display them.
2. **Set timeout to 60 seconds**: most commands make HTTP calls.
3. **Use single quotes** for `--prompt` and `--description` values to avoid shell quoting issues.
4. **Do NOT run `observal auth status` first.** Other commands surface auth problems clearly on their own.
5. **When in doubt about a flag, run `<command> --help` first.** Never guess flag names.
6. **Pass `--output json` on every list/show command.** It is stable and machine readable.
7. **Pass `--yes` / `-y` on destructive commands** so they do not block on a confirmation prompt.
8. **Resolve 409 conflicts deterministically:** `--update` for in-place edits, `--bump` for versioned releases.
9. **Only fall back to local file writes** if a command exits with `Connection failed` or `Not configured`.
10. **Never invent `OTEL_*` or `CLAUDE_CODE_ENABLE_TELEMETRY` environment variables.** Telemetry flows through `observal-shim` and session push hooks only.

---

## Procedure: Pull Agent

Install an agent's full config (rules, MCP servers, hooks, skills) into a local IDE.

```bash
observal agent pull AGENT_NAME --ide kiro --no-prompt --dir .
```

**Flags:**
- `--ide` (required): `claude-code`, `kiro`, `cursor`, `gemini-cli`, `vscode`, `codex`, `copilot`, `copilot-cli`, `opencode`
- `--version <semver>`: install a specific version (e.g. `1.2.0`). Omit for latest.
- `--scope user|project`: install scope (Claude Code, Kiro, Gemini only)
- `--model <name>` or `--model <ide>=<name>`: override saved model (repeatable)
- `--tools t1,t2`: Claude Code tool whitelist
- `--dry-run`: preview file writes without touching disk
- `--no-prompt`: skip interactive confirmation
- `--dir <path>`: target directory (default: current)

**Merge behavior:** MCP configs are merged with existing IDE config files, not overwritten. Existing user entries are preserved.

**Version pinning:** When `--version` is specified, the exact content from that version is installed. The lockfile (`~/.observal/lockfile.json`) records the pin. If another agent depends on the same component at a different version, a warning is displayed.

If the user did not specify an IDE, ask which one before running.

---

## Procedure: Outdated

Check for newer versions of installed agents and components.

```bash
observal outdated
observal outdated --ide claude-code
observal outdated --output json
```

Reads `~/.observal/lockfile.json` and compares each pinned version against the registry's latest. Reports a table of outdated items with current vs latest version.

---

## Procedure: Scan IDEs

Read-only inventory of installed components across all detected IDEs. **Never modifies any file.**

```bash
observal scan
observal scan --ide kiro
observal scan --ide claude-code
```

Reports: detected IDEs, MCP servers (with shimmed status), skills, hooks, agents, and unregistered components.

---

## Procedure: Doctor

Diagnose only. Does not fix anything.

```bash
observal doctor
```

Reports: Observal config validity, server reachability, hook installation status per IDE, skill presence. Exits non-zero if issues found.

---

## Procedure: Doctor Patch

Apply instrumentation. Run with `--dry-run` first when the user is unsure.

```bash
observal doctor patch --all --all-ides --dry-run
observal doctor patch --all --all-ides
observal doctor patch --hook --shim --ide kiro
observal doctor patch --all --ide claude-code
observal doctor patch --hook --all-ides
observal doctor patch --shim --all-ides
```

**Required:** at least one of `--hook` / `--shim` / `--all`, AND at least one of `--all-ides` / `--ide`. Creates timestamped backups before modifying any file.

---

## Procedure: Doctor Cleanup

Remove Observal-managed hooks and env vars from IDE configs. Leaves user content untouched.

```bash
observal doctor cleanup --dry-run
observal doctor cleanup
observal doctor cleanup --ide kiro
```

---

## Procedure: Auth

```bash
observal auth login
observal auth login --server https://observal.example.com
observal auth login --sso
observal auth login --email me@x.com --password '...'
observal auth whoami --output json
observal auth status
observal auth logout
observal auth change-password
observal auth set-username new-handle
```

On a fresh server, `auth login` auto-bootstraps an admin from localhost (no prompts needed).

---

## Procedure: CLI Config

```bash
observal config show
observal config path
observal config set output json
observal config set server_url https://observal.example.com
observal config aliases
observal config alias MY_AGENT abc-123
```

---

## Procedure: Discuss Agent Insights

Use this when the user asks how an agent is doing, what is working, what is broken, why a version changed, or what to improve.

Always fetch JSON first so you can reason over every report section, then answer conversationally.

```bash
observal ops insights list AGENT_NAME --output json
observal ops insights show AGENT_NAME latest --output json
observal ops insights show AGENT_NAME latest --section suggestions --output json
observal ops insights show AGENT_NAME latest --section friction_analysis --output json
```

Available sections:

- `at_a_glance`: health, working areas, blockers, quick win
- `what_they_work_on`: project areas and session counts
- `interaction_style`: how users interact with the agent
- `usage_patterns`: session shape, tools, prompts, duration
- `what_works`: strengths backed by sessions
- `friction_analysis`: recurring failure modes and examples
- `suggestions`: config additions, features to try, usage changes
- `usage_cost_analysis`: cost, cache, and model efficiency
- `version_comparison`: current version compared with a baseline
- `regression_detection`: what improved or degraded versus previous data
- `on_the_horizon`: higher leverage workflow opportunities
- `fun_ending`: memorable qualitative moment

For broad questions, run full `show` JSON and summarize health, top friction, top strengths, cost, and next actions. For narrow questions, fetch the specific section. If no completed report exists, offer to generate one:

```bash
observal ops insights generate AGENT_NAME --period 14 --wait
observal ops insights generate AGENT_NAME --version 1.2.0 --compare 1.1.0 --period 30 --wait
```

Keep the answer grounded in the JSON. Say when the report is missing a section or has low session count.

---

## Error Reference

| Error | Action |
|-------|--------|
| `Connection failed` | Server unreachable. Use the `observal-advanced` skill's Local Fallback procedure |
| `Not configured` / `No server` | Run `observal auth login` |
| `403 Forbidden` | Check `observal auth whoami`; user lacks required role |
| `404 Not found` | Verify name with `observal agent list --output json` |

---

## Output Contract

For every CLI invocation, format your response:

1. One sentence stating intent.
2. The exact command in a fenced code block.
3. The result: success / specific error.
4. The next action, or "done".

---

For full command reference, read `references/commands.md`. For agent creation use the `observal-agents` skill. For registry operations use `observal-registry`. For observability use `observal-ops`. For admin tasks use `observal-admin`.
