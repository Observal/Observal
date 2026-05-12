<!-- SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# observal skill

Manage skill listings from the CLI. Skills are reusable task packages that can be submitted to the registry and installed into supported IDEs.

## Synopsis

```bash
observal skill <command> [args] [options]
```

## Commands

| Command | What it does |
| --- | --- |
| `submit` | Submit a new skill for review |
| `list` | List approved skills |
| `my` | List your own skills across all statuses |
| `show` | Show skill details |
| `install` | Install a skill by writing the skill file to disk and showing config |
| `edit` | Edit a draft, rejected, or pending skill submission |
| `delete` | Delete a skill |

IDs can be UUIDs, names, row numbers from the last list output, or aliases created with [`observal config alias`](config.md).

## `observal skill submit`

Submit a new skill for review. Only submit skills you created or are the point of contact for.

### Synopsis

```bash
observal skill submit [OPTIONS]
```

### Options

| Option | Short | Description |
| --- | --- | --- |
| `--from-file <text>` | `-f` | Create from a JSON file |
| `--draft` | | Save as draft instead of submitting for review |
| `--submit <skill-id>` | | Submit an existing draft for review |

### Examples

```bash
observal skill submit
observal skill submit --from-file skill.json --draft
observal skill submit --submit 498c17ac-1234-4567-89ab-cdef01234567
```

## `observal skill list`

List approved skills.

### Synopsis

```bash
observal skill list [OPTIONS]
```

### Options

| Option | Short | Description |
| --- | --- | --- |
| `--task-type <text>` | `-t` | Filter by task type |
| `--target-agent <text>` | | Filter by target agent |
| `--search <text>` | `-s` | Search skills |
| `--output <text>` | `-o` | Output format: `table`, `json`, or `plain`; default `table` |

### Examples

```bash
observal skill list
observal skill list --task-type code-review
observal skill list --target-agent claude-code --output json
```

## `observal skill my`

List your own skills across all statuses.

### Synopsis

```bash
observal skill my [OPTIONS]
```

### Options

| Option | Short | Description |
| --- | --- | --- |
| `--output <text>` | `-o` | Output format: `table`, `json`, or `plain`; default `table` |

## `observal skill show`

Show details for one skill.

### Synopsis

```bash
observal skill show <skill-id> [OPTIONS]
```

### Arguments

| Argument | Description |
| --- | --- |
| `<skill-id>` | ID, name, row number, or `@alias` |

### Options

| Option | Short | Description |
| --- | --- | --- |
| `--output <text>` | `-o` | Output format; default `table` |

## `observal skill install`

Install a skill. By default, this writes the skill file to disk and shows the generated IDE config.

### Synopsis

```bash
observal skill install <skill-id> --ide <ide> [--raw] [--no-write]
```

### Arguments

| Argument | Description |
| --- | --- |
| `<skill-id>` | Skill ID, name, row number, or `@alias` |

### Options

| Option | Short | Description |
| --- | --- | --- |
| `--ide <text>` | `-i` | Target IDE; required |
| `--raw` | | Output raw JSON only |
| `--no-write` | | Print config without writing files |

### Examples

```bash
observal skill install code-reviewer --ide claude-code
observal skill install @review-skill --ide claude-code --no-write
```

## `observal skill edit`

Edit a draft, rejected, or pending skill submission.

### Synopsis

```bash
observal skill edit <skill-id> [OPTIONS]
```

### Arguments

| Argument | Description |
| --- | --- |
| `<skill-id>` | ID, name, row number, or `@alias` |

### Options

| Option | Short | Description |
| --- | --- | --- |
| `--from-file <text>` | `-f` | Load updates from a JSON file |
| `--name <text>` | `-n` | New listing name |
| `--description <text>` | `-d` | New description |
| `--version <text>` | `-v` | New version string |
| `--task-type <text>` | `-t` | New task type |

## `observal skill delete`

Delete a skill.

### Synopsis

```bash
observal skill delete <skill-id> [OPTIONS]
```

### Arguments

| Argument | Description |
| --- | --- |
| `<skill-id>` | ID, name, row number, or `@alias` |

### Options

| Option | Short | Description |
| --- | --- | --- |
| `--yes` | `-y` | Skip confirmation |

## Related

* [`observal agent`](agent.md)
* [`observal registry`](registry.md)
* [`observal config`](config.md)
