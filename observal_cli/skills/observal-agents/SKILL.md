---
# SPDX-FileCopyrightText: 2026 Hemalatha Madeswaran <hemalathamadeswaran@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only
name: observal-agents
command: observal
description: Create, update, version, and manage Observal agents. Use when the user wants to create a new agent, update an existing one, release a new version, scaffold a YAML project, add components, build, publish, bulk-create, delete, or restore agents.
version: 2.0.0
owner: observal
---

# Observal Agents: Agent Lifecycle Management

## Critical Rules

1. **EXECUTE commands**: run them in your shell. Set timeout to 60 seconds.
2. **Use single quotes** for `--prompt` and `--description` values.
3. **Pass `--output json`** on list/show/versions commands.
4. **Pass `--yes`** on destructive commands (`delete`, `unarchive`, `bulk-create`).
5. **Resolve 409:** `observal agent publish --update` for in-place edits, `observal agent release --bump` for reviewed releases.
6. **When in doubt about a flag, run `<command> --help` first.**

---

## Procedure: Create Agent

Required: `--name`, `--description`, `--prompt`. Optional: `--model` (default: `claude-sonnet-4`), `--ide` (repeatable), `--owner`, `--prompt-file`, `--from-file`.

> **WARNING:** Without `--name` and `--prompt`, the command launches an interactive wizard. Always pass at least `--name`, `--description`, and `--prompt`.

```bash
observal agent create \
  --name AGENT_NAME \
  --description 'Short description' \
  --prompt 'System prompt content' \
  --model claude-sonnet-4 \
  --ide kiro --ide claude-code
```

Error branching:
- **`409`**: switch to Procedure: Update Agent or Release Agent Version.
- **`422`**: missing required field. Check message, fix, retry.
- **`Connection failed`**: server unreachable; use `observal-advanced` skill's Local Fallback.

---

## Procedure: Update Agent

Skips review queue. Overwrites in place.

1. Write `observal-agent.yaml`. **Critical:** include `model_config_json: {}` and `external_mcps: []` literally.
   ```bash
   mkdir -p /tmp/myagent && cat > /tmp/myagent/observal-agent.yaml << 'EOF'
   name: existing-agent-name
   version: "1.0.0"
   description: "Updated description"
   owner: "team-name"
   model_name: claude-sonnet-4
   model_config_json: {}
   models_by_ide: {}
   external_mcps: []
   prompt: |
     Updated system prompt here.
   supported_ides:
     - kiro
     - claude-code
   components: []
   EOF
   ```
2. Push: `observal agent publish --update --dir /tmp/myagent`
3. Confirm: `observal agent show existing-agent-name --output json`

---

## Procedure: Release Agent Version

Goes through review queue. Use for "new version", "bump", or "release".

1. Write `observal-agent.yaml` (same schema as Update Agent).
2. Release:
   ```bash
   observal agent release AGENT_NAME --bump patch --dir /tmp/myagent
   ```
   Bump types: `patch`, `minor`, `major`.
3. Verify: `observal agent versions AGENT_NAME --output json`

---

## Procedure: Author Agent Locally

1. Scaffold (interactive):
   ```bash
   observal agent init --dir ./my-agent
   ```
2. Add components (second arg is UUID, find with `observal registry mcp show NAME --output json`):
   ```bash
   observal agent add mcp COMPONENT_UUID --dir ./my-agent
   observal agent add skill COMPONENT_UUID --dir ./my-agent
   ```
3. Validate: `observal agent build --dir ./my-agent`
4. Publish: `observal agent publish --dir ./my-agent`
   - `--draft` saves without submitting. `--submit` submits a saved draft.

---

## Procedure: Bulk Create

```bash
observal agent bulk-create --from-file agents.json --dry-run --yes
observal agent bulk-create --from-file agents.json --yes
```

---

## Procedure: Delete / Restore

```bash
observal agent delete AGENT_NAME --yes
observal agent unarchive AGENT_NAME --yes
```

---

## Browse Agents

```bash
observal agent list --output json
observal agent list --search keyword --output json
observal agent list --page 2 --limit 20 --output json
observal agent my --output json
observal agent show AGENT_NAME --output json
observal agent versions AGENT_NAME --output json
```

After `list`, use row numbers (1, 2, 3...) in subsequent commands.

---

## Procedure: Manage Co-Authors

Co-authors have full edit and publish access (equal to owner).

```bash
# List co-authors
observal co-authors list agents <agent-id-or-name>

# Add by email or username
observal co-authors add agents <agent-id-or-name> user@example.com
observal co-authors add agents <agent-id-or-name> @username

# Remove by user UUID (from list output)
observal co-authors remove agents <agent-id-or-name> <user-uuid>
```

Works for all entity types: `agents`, `mcps`, `skills`, `hooks`, `prompts`, `sandboxes`.


## Error Reference

| Error | Fix |
|-------|-----|
| `409` / `already have an agent named` | Use `publish --update` or `release --bump` |
| `422` `model_config_json` | Add `model_config_json: {}` to YAML |
| `422` `external_mcps` | Add `external_mcps: []` to YAML |
| `422` `system prompt is required` | Add `--prompt` or `prompt:` in YAML |

---

## Output Contract

1. One sentence stating intent.
2. The exact command in a fenced code block.
3. The result: success or specific error.
4. The next action, or "done".
