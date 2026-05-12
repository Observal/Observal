<!-- SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# observal sandbox

Manage sandbox listings from the CLI. Sandboxes describe isolated runtimes that agents can use for safer code execution, testing, and tool workflows.

## Synopsis

```bash
observal sandbox <command> [args] [options]
```

## Commands

| Command | What it does |
| --- | --- |
| `submit` | Submit a new sandbox for review |
| `list` | List approved sandboxes |
| `show` | Show sandbox details |
| `install` | Generate install config for a sandbox |
| `edit` | Edit a draft, rejected, or pending sandbox submission |
| `delete` | Delete a sandbox |

IDs can be UUIDs, names, row numbers from the last list output, or aliases created with [`observal config alias`](config.md).

## `observal sandbox submit`

Submit a new sandbox for review. Only submit sandboxes you created or are the point of contact for.

### Synopsis

```bash
observal sandbox submit [OPTIONS]
```

### Options

| Option | Short | Description |
| --- | --- | --- |
| `--from-file <text>` | `-f` | Create from a JSON file |
| `--draft` | | Save as draft instead of submitting for review |
| `--submit <sandbox-id>` | | Submit an existing draft for review |

### Examples

```bash
observal sandbox submit
observal sandbox submit --from-file sandbox.json --draft
observal sandbox submit --submit 498c17ac-1234-4567-89ab-cdef01234567
```

## `observal sandbox list`

List approved sandboxes.

### Synopsis

```bash
observal sandbox list [OPTIONS]
```

### Options

| Option | Short | Description |
| --- | --- | --- |
| `--runtime <text>` | `-r` | Filter by runtime |
| `--search <text>` | `-s` | Search sandboxes |
| `--output <text>` | `-o` | Output format: `table`, `json`, or `plain`; default `table` |

### Examples

```bash
observal sandbox list
observal sandbox list --runtime docker
observal sandbox list --search python --output json
```

## `observal sandbox show`

Show details for one sandbox.

### Synopsis

```bash
observal sandbox show <sandbox-id> [OPTIONS]
```

### Arguments

| Argument | Description |
| --- | --- |
| `<sandbox-id>` | ID, name, row number, or `@alias` |

### Options

| Option | Short | Description |
| --- | --- | --- |
| `--output <text>` | `-o` | Output format; default `table` |

## `observal sandbox install`

Generate install config for one sandbox.

### Synopsis

```bash
observal sandbox install <sandbox-id> --ide <ide> [--raw]
```

### Arguments

| Argument | Description |
| --- | --- |
| `<sandbox-id>` | Sandbox ID, name, row number, or `@alias` |

### Options

| Option | Short | Description |
| --- | --- | --- |
| `--ide <text>` | `-i` | Target IDE; required |
| `--raw` | | Output raw JSON only |

## `observal sandbox edit`

Edit a draft, rejected, or pending sandbox submission.

### Synopsis

```bash
observal sandbox edit <sandbox-id> [OPTIONS]
```

### Arguments

| Argument | Description |
| --- | --- |
| `<sandbox-id>` | ID, name, row number, or `@alias` |

### Options

| Option | Short | Description |
| --- | --- | --- |
| `--from-file <text>` | `-f` | Load updates from a JSON file |
| `--name <text>` | `-n` | New listing name |
| `--description <text>` | `-d` | New description |
| `--version <text>` | `-v` | New version string |
| `--runtime-type <text>` | `-r` | New runtime type |
| `--image <text>` | `-i` | New container image |

## `observal sandbox delete`

Delete a sandbox.

### Synopsis

```bash
observal sandbox delete <sandbox-id> [OPTIONS]
```

### Arguments

| Argument | Description |
| --- | --- |
| `<sandbox-id>` | ID, name, row number, or `@alias` |

### Options

| Option | Short | Description |
| --- | --- | --- |
| `--yes` | `-y` | Skip confirmation |

## Related

* [`observal agent`](agent.md)
* [`observal registry`](registry.md)
* [`observal config`](config.md)
