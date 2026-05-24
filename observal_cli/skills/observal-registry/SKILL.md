<!-- SPDX-FileCopyrightText: 2026 Hemalatha Madeswaran <hemalathamadeswaran@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

---
name: observal-registry
command: observal
description: Submit, browse, install, edit, delete, and version MCPs, skills, hooks, prompts, and sandboxes in the Observal registry. Use when the user wants to submit a component, install one, edit a draft, publish a new version, or browse the component library.
version: 2.0.0
owner: observal
---

# Observal Registry: Component CRUD

## Critical Rules

1. **EXECUTE commands**: run them in your shell. Set timeout to 60 seconds.
2. **Pass `--output json`** on list/show commands.
3. **Pass `--yes`** on destructive commands (`delete`, `submit --git`).
4. **When in doubt about a flag, run `<command> --help` first.**
5. **`--from-file` does NOT exist on `mcp submit`**: that flag is on `mcp edit`.

---

## Procedure: Browse Registry

```bash
observal mcp list --category developer-tools --output json
observal skill list --task-type code-review --output json
observal registry hook list --event UserPromptSubmit --output json
observal prompt list --category coding --output json
observal sandbox list --runtime docker --output json

observal mcp my --output json
observal skill my --output json
observal prompt my --output json

observal mcp show NAME --output json
observal registry hook show NAME --output json
```

After `list`, use row numbers (1, 2, 3...) in subsequent commands. Add `--interactive` for fuzzy picker.

**MCP categories:** `browser-automation`, `cloud-platforms`, `code-execution`, `communication`, `databases`, `developer-tools`, `devops`, `file-systems`, `finance`, `knowledge-memory`, `monitoring`, `multimedia`, `productivity`, `search`, `security`, `version-control`, `ai-ml`, `data-analytics`, `general`

**Skill task types:** `code-review`, `code-generation`, `testing`, `documentation`, `debugging`, `refactoring`, `deployment`, `security-audit`, `performance`, `general`

---

## Procedure: Submit Component

### MCP (from git, recommended)

```bash
observal mcp submit --git https://github.com/org/mcp-server --name my-mcp --category developer-tools --yes
```

Without `--git`, opens interactive JSON paste (accepts IDE config block, named config, bare config, or HTTP transport JSON). Press Enter on empty line to submit.

### Skill

```bash
observal skill submit --skill-md ./SKILL.md --git-url https://github.com/org/repo --git-ref main
```

### Hook

```bash
observal registry hook submit --from-file hook.json
observal registry hook submit   # interactive
```

Optional: `--script 'code'`, `--source-url URL --source-ref main`, `--requires dep1 --requires dep2`. Timeout caps: blocking 30s, sync 10s, async 60s.

### Prompt

```bash
observal prompt submit --from-file prompt.json
```

### Sandbox

```bash
observal sandbox submit --from-file sandbox.json
```

All types support `--draft` (save without review) and `--submit NAME` (submit existing draft).

---

## Procedure: Install Component

```bash
observal mcp install NAME --ide kiro
observal mcp install NAME --ide claude-code --raw
observal skill install NAME --ide kiro --scope user
observal skill install NAME --ide claude-code --scope project
observal registry hook install NAME --ide kiro
observal registry hook install NAME --ide claude-code --platform darwin --dir .
observal prompt install NAME --ide kiro
```

`sandbox install` is deprecated. Use `observal agent add sandbox UUID` + `observal agent pull` instead.

---

## Procedure: Edit Component

**Warning:** Editing an approved listing triggers a version bump flow. For draft/pending/rejected items, edits in place with an optimistic lock.

```bash
observal mcp edit NAME --from-file updates.json
observal mcp edit NAME --name new-name --description 'New desc'
observal skill edit NAME --from-file updates.json
observal registry hook edit NAME --version 1.2.0 --event Stop
observal prompt edit NAME --template 'New template body'
observal sandbox edit NAME --image python:3.12-slim
```

---

## Procedure: Publish Component Version

```bash
observal component version publish mcp NAME --version 1.2.0 --description 'What changed'
observal component version publish skill NAME --version 0.3.0 --description 'New tasks'
observal component version publish hook NAME --version 1.0.1 --description 'Bug fix'
observal component version publish prompt NAME --version 2.0.0 --description 'Rewrite'
observal component version publish sandbox NAME --version 1.1.0 --description 'New image'

observal component version list mcp NAME --output json
```

---

## Procedure: Delete Component

```bash
observal mcp delete NAME --yes
observal skill delete NAME --yes
observal registry hook delete NAME --yes
observal prompt delete NAME --yes
observal sandbox delete NAME --yes
```

---

## Error Reference

| Error | Fix |
|-------|-----|
| `--from-file` not on `mcp submit` | Use `--git`, `--draft`, or interactive paste |
| `412 Edit lock held` | Wait a few minutes, retry |
| Hook `timeout` | Caps: blocking 30s, sync 10s, async 60s |

---

## Output Contract

1. One sentence stating intent.
2. The exact command in a fenced code block.
3. The result: success / specific error.
4. The next action, or "done".
