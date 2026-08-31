<!-- SPDX-FileCopyrightText: 2026 Nithin-Bhargav-07 <gaddamnithinbhargav@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# `observal registry skill`

Submit, browse, install, edit, archive, restore, transfer, and manage co-authors for portable skill packages.

## Commands

| Command | Description |
| --- | --- |
| `submit` | Submit a Git-backed or registry-direct skill |
| `list` | List approved visible skills |
| `my` | List your skills across all statuses |
| `show` | Show one skill |
| `install` | Write a skill into a supported harness |
| `edit` | Edit a draft, pending, or rejected skill |
| `archive` | Archive an approved skill |
| `unarchive` | Restore an archived skill |
| `transfer-owner` | Transfer ownership |
| `co-authors` | List, add, or remove co-authors |

Every command that returns structured data supports table and JSON output. Archive, restore, and ownership transfer require the confirmation bypass in JSON mode.

## Submit

Git-backed skills require a Git URL. Registry-direct skills store SKILL.md and an optional script in Observal.

```bash
observal registry skill submit \
  --skill-md ./SKILL.md \
  --git-url https://github.com/acme/review-skill \
  --name review-skill \
  --description "Review code" \
  --task-type code-review \
  --output json

observal registry skill submit \
  --skill-md ./SKILL.md \
  --delivery-mode registry_direct \
  --name review-skill \
  --description "Review code" \
  --task-type code-review \
  --output json
```

JSON mode never prompts. Supply the name, description, task type, delivery mode, and required source inputs explicitly.

Valid task types are `code-review`, `code-generation`, `testing`, `documentation`, `debugging`, `refactoring`, `deployment`, `security-audit`, `performance`, and `general`.

## List and show

```bash
observal registry skill list --task-type code-review --output json
observal registry skill list --harness claude-code --output json
observal registry skill my --output json
observal registry skill show acme/review-skill --output json
```

Row numbers are scoped to the latest Skill list. Empty lists clear previous Skill row references.

## Install

```bash
observal registry skill install acme/review-skill --harness claude-code --scope user --output json
observal registry skill install acme/review-skill --harness pi --scope project --output json
observal registry skill install acme/review-skill --harness pi --no-write --output json
observal registry skill install acme/review-skill --harness pi --raw
```

JSON output performs the installation unless no-write is selected. It reports `write_performed` and `installed_path`. Raw mode emits only the generated config and performs no write. Lockfile state is recorded only after the skill content is written successfully.

The command fails if the harness lacks skill support, the source cannot be installed, a project symlink cannot be created, or installed state cannot be recorded.

## Edit

```bash
observal registry skill edit acme/review-skill --description "Updated" --output json
observal registry skill edit acme/review-skill --from-file updates.json --output json
```

Edit-lock conflicts preserve conflict exit code 6. Invalid fields and files use the shared validation, not-found, permission, and unavailable categories.

## Related

* [`observal registry`](registry.md): complete registry reference
* [`observal agent`](agent.md): attach skills to agents
