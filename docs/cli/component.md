<!-- SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# observal component

Manage versions for registry components. Components include hooks, skills, prompts, MCP servers, and sandboxes.

## Synopsis

```bash
observal component <command> [args] [options]
```

## Commands

| Command | What it does |
| --- | --- |
| `version` | Manage component versions |

## `observal component version`

Manage version history for registry components.

### Synopsis

```bash
observal component version <command> [args] [options]
```

### Commands

| Command | What it does |
| --- | --- |
| `publish` | Publish a new version for a registry component |
| `list` | List version history for a registry component |

## `observal component version publish`

Publish a new version for a registry component.

### Synopsis

```bash
observal component version publish <component-type> <listing> [OPTIONS]
```

### Arguments

| Argument | Description |
| --- | --- |
| `<component-type>` | Component type: `hook`, `skill`, `prompt`, `mcp`, or `sandbox` |
| `<listing>` | Listing name or ID |

### Options

| Option | Short | Description |
| --- | --- | --- |
| `--version <text>` | `-v` | Version to publish, for example `1.2.0` |
| `--description <text>` | `-d` | Short description of this version; required |
| `--changelog <text>` | | Changelog notes |
| `--ide <text>` | | Supported IDE; repeat for multiple IDEs |
| `--extra <text>` | | Extra JSON for type-specific fields |

### Example

```bash
observal component version publish skill code-reviewer \
  --version 1.2.0 \
  --description "Improve review checklist coverage" \
  --changelog "Adds security and testing prompts" \
  --ide claude-code \
  --ide cursor
```

## `observal component version list`

List version history for a registry component.

### Synopsis

```bash
observal component version list <component-type> <listing> [OPTIONS]
```

### Arguments

| Argument | Description |
| --- | --- |
| `<component-type>` | Component type: `hook`, `skill`, `prompt`, `mcp`, or `sandbox` |
| `<listing>` | Listing name or ID |

### Options

| Option | Short | Description |
| --- | --- | --- |
| `--output <text>` | `-o` | Output format: `table` or `json`; default `table` |

### Example

```bash
observal component version list skill code-reviewer --output json
```

## Related

* [`observal registry`](registry.md)
* [`observal skill`](skill.md)
* [`observal prompt`](prompt.md)
* [`observal mcp`](mcp.md)
* [`observal sandbox`](sandbox.md)
