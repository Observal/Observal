<!-- SPDX-FileCopyrightText: 2026 Nithin-Bhargav-07 <gaddamnithinbhargav@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# observal skill

Submit, browse, and install portable skill packages. A skill is a `SKILL.md`
instruction file that agents load on demand to handle a specific task.

## Subcommands

| Command | Description |
| --- | --- |
| [`skill submit`](#observal-skill-submit) | Submit a skill to the registry |
| [`skill list`](#observal-skill-list) | List approved skills |
| [`skill my`](#observal-skill-my) | List your own skills (all statuses) |
| [`skill show`](#observal-skill-show) | Show detailed information about a skill |
| [`skill install`](#observal-skill-install) | Install a skill into an harness |
| [`skill edit`](#observal-skill-edit) | Edit a draft, rejected, or pending skill |

---

## `observal skill submit`

Submit a skill to the registry. There are two delivery modes:

- **git_fetch** (default): provide `--git-url` and the server clones the
  `SKILL.md` from the repo on install.
- **registry_direct**: provide `--skill-md` (and optionally `--script`) with
  `--delivery-mode registry_direct`. The content is stored inline in the
  registry and written directly on install, no git repo needed.

You can also provide `--skill-md` alongside `--git-url` to auto-fill
frontmatter fields while still using git_fetch delivery.

```bash
# Git-based submission
observal skill submit --git-url https://github.com/your-org/your-skill
observal skill submit --skill-md ./SKILL.md --git-url https://github.com/your-org/your-skill
observal skill submit --git-url https://github.com/your-org/your-skill --draft

# Registry direct (no git repo required)
observal skill submit --skill-md ./SKILL.md --delivery-mode registry_direct
observal skill submit --skill-md ./SKILL.md --script ./run.sh --delivery-mode registry_direct

# From JSON file
observal skill submit --from-file skill.json

# Submit a saved draft
observal skill submit --submit abc123
```

| Option | Description |
| --- | --- |
| `--from-file`, `-f` | Create from a JSON file |
| `--skill-md` | Path to `SKILL.md` to paste (auto-fills fields from frontmatter) |
| `--git-url` | Git repository URL |
| `--git-ref` | Branch or tag (default: main) |
| `--script` | Path to script file (registry_direct mode only) |
| `--delivery-mode` | Delivery mode: `git_fetch` (default) or `registry_direct` |
| `--draft` | Save as draft instead of submitting for review |
| `--submit` | Submit a draft for review (skill ID) |

---

## `observal skill list`

List approved skills in the registry. Use `--task-type`, `--target-agent`, or
`--search` to filter results. Row numbers from the output can be used as
references in subsequent commands.

```bash
observal skill list
observal skill list --task-type coding
observal skill list --target-agent claude-code --output json
observal skill list --search "refactor"
```

| Option | Description |
| --- | --- |
| `--task-type`, `-t` | Filter by task type |
| `--target-agent` | Filter by target agent |
| `--search`, `-s` | Filter by search term |
| `--output`, `-o` | Output format: table, json, plain (default: table) |

---

## `observal skill my`

List your own skills across all statuses: drafts, pending, approved, and
rejected. Useful for tracking the review status of your submissions.

```bash
observal skill my
observal skill my --output json
```

| Option | Description |
| --- | --- |
| `--output`, `-o` | Output format: table, json, plain (default: table) |

---

## `observal skill show`

Show detailed information about a skill including validation status, task type,
git source, slash command, target agents, and timestamps. Accepts a UUID, name,
row number from a previous list, or @alias.

```bash
observal skill show my-skill
observal skill show 1
observal skill show @refactor-skill --output json
```

| Option | Description |
| --- | --- |
| `--output`, `-o` | Output format (default: table) |

---

## `observal skill install`

Install a skill into an harness. For git_fetch skills, clones the skill directory
from the configured `git_url`. For registry_direct skills, writes the stored
`SKILL.md` (and script, if present) directly. Falls back to cached content if
git clone fails.

Two scopes are supported:

- `--scope user` (default): writes to `~/.<harness>/skills/<name>/` globally.
- `--scope project`: writes to `.agents/skills/<name>/` in the current
  directory, then symlinks into each harness config dir found in the project.

```bash
observal skill install my-skill --harness claude-code
observal skill install @sk --harness kiro --scope project
observal skill install 2 --harness cursor --raw > config.json
```

| Option | Description |
| --- | --- |
| `--harness`, `-i` | Target harness (required) |
| `--scope`, `-s` | Install scope: user (default) or project |
| `--raw` | Output raw JSON only |
| `--no-write` | Print config without writing files |

---

## `observal skill edit`

Edit a draft, rejected, or pending skill submission. You can provide individual
field options or load all updates from a JSON file. Acquires an edit lock to
prevent concurrent modifications.

```bash
observal skill edit my-skill --description "Better desc"
observal skill edit abc123 --from-file updates.json
observal skill edit @sk --git-url https://github.com/org/new-repo
observal skill edit 2 --version 2.0.0 --task-type debugging
```

| Option | Description |
| --- | --- |
| `--from-file`, `-f` | Load updates from a JSON file |
| `--name`, `-n` | New listing name |
| `--description`, `-d` | New description |
| `--version`, `-v` | New version string |
| `--task-type`, `-t` | New task type |
| `--git-url` | New git URL |
| `--git-ref` | New git ref |

---

