<!-- SPDX-FileCopyrightText: 2026 Vedant Gajbhiye <focusedfalcon17@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# `observal registry mcp`

Discover, submit, install, and manage MCP (Model Context Protocol) servers in the Observal registry.

MCP server entries can be referenced by UUID, canonical name, row number from the latest `list`/`my` result, or an `@alias`.

## Commands

| Command | Purpose |
| --- | --- |
| `submit` | Submit an MCP server to the registry |
| `list` | List approved MCP servers in the registry |
| `my` | List your own MCP servers across all statuses |
| `show` | Show full details of an MCP server |
| `install` | Generate an install config snippet for an MCP server |
| `edit` | Edit an MCP server submission |
| `transfer-owner` | Transfer ownership to another username |
| `archive` | Archive this component |
| `unarchive` | Restore an archived component |
| `co-authors` | List, add, or remove co-authors |

Every command supports `--output table|json`.

## Submit

```bash
observal registry mcp submit
observal registry mcp submit --git https://github.com/org/mcp-server --yes
observal registry mcp submit --submit my-server --output json
```

Opens an interactive JSON paste prompt matching your harness's `mcpServers` config block. Pass `--git` to have Observal clone the repository and detect local OCI setup instructions (Dockerfile, Containerfile, or compose build). Only submit servers you created or are the point of contact for — submissions enter a pending review queue unless saved with `--draft`. You can install your own submissions immediately without approval. Environment variables written as `$VAR` or `${VAR}` in args or header values are auto-detected and become install-time prompts. Use `--submit MCP_ID` to submit an existing draft for review.

## List, my, and show

```bash
observal registry mcp list
observal registry mcp list --search postgres
observal registry mcp list --category ai-ml --output json
observal registry mcp my --output json
observal registry mcp show my-server
observal registry mcp show @fav
observal registry mcp show my-server --output json
```

`list` shows publicly approved servers by default. Filter with `--search` (keyword), `--category`, `--namespace`, or `--team`; change ordering with `--sort` (`name`, `category`, or `version`); cap results with `--limit` (max 200, default 50). `--interactive` opens a fuzzy-search picker and prints the selected server's full details. Results are cached locally so you can reference a row number from the last `list` in later commands.

`my` lists your own servers across every status — pending, approved, rejected, and draft — useful for checking submission state or finding a draft ID to resume editing.

`show` accepts a UUID, server name, row number from the last `list`, or an `@alias`, and prints metadata, validation results, supported harnesses, environment variables, and timestamps.

## Install

```bash
observal registry mcp install my-server --harness claude-code
observal registry mcp install my-server --harness claude-code --env-file .env --no-prompt
observal registry mcp install my-server --harness cursor --raw > .cursor/mcp.json
```

Generates harness-specific config to paste into your editor's MCP settings. By default it prompts interactively for any required environment variables or headers; skip prompts with `--no-prompt` (`-y`). Supply values non-interactively with repeatable `--env KEY=VALUE` and `--header KEY=VALUE` flags, or load them from a file with `--env-file`. `--raw` outputs bare JSON (with placeholders for any missing variables), suited for piping straight into a config file. `--version` installs a specific version instead of the latest.

## Edit

```bash
observal registry mcp edit my-server
observal registry mcp edit my-server -d "New description" -c databases
observal registry mcp edit my-server --from-file updates.json --output json
```

For draft, pending, or rejected listings, `edit` updates the submission in place. For an already-approved listing, it instead publishes a new version with a semver bump — pass `--bump patch|minor|major` to choose non-interactively, or you'll be prompted. With no flags it opens the same interactive JSON paste prompt as `submit`; alternatively pass individual fields (`--name`, `--description`, `--category`, `--version`, `--git-url`, `--command`, `--url`) or load a complete update from a file with `--from-file`. `--changelog` sets the changelog text for a new version without prompting.

## Transfer ownership, archive, and restore

```bash
observal registry mcp transfer-owner alice/my-component bob
observal registry mcp transfer-owner alice/my-component bob --yes --output json
observal registry mcp archive alice/my-component --yes --output json
observal registry mcp unarchive alice/my-component --yes --output json
```

`transfer-owner` hands ownership to another username. `archive` and `unarchive` toggle a component's archived state. All three accept `--yes` to skip the confirmation prompt.

## Co-authors

Co-authors can edit and publish the same MCP server listing:

```bash
observal registry mcp co-authors list alice/my-component
observal registry mcp co-authors add alice/my-component alice@example.com
observal registry mcp co-authors add alice/my-component @alice --output json
observal registry mcp co-authors remove alice/my-component 550e8400-e29b-41d4-a716-446655440000
```

`add` accepts either an email address or an `@username`. `remove` requires the co-author's user UUID, as returned by `list`.

## Exit codes

`registry mcp` commands use the CLI's standard exit codes:

| Code | Meaning |
| --- | --- |
| 0 | Success |
| 1 | Unexpected or uncategorized failure |
| 2 | Usage error |
| 3 | Authentication required or failed |
| 4 | Permission denied |
| 5 | Resource not found |
| 6 | Conflict with current state |
| 7 | Validation failure |
| 8 | Rate limit reached |
| 9 | Network, service, or dependency unavailable |
| 10 | CLI and server version mismatch |

See the [CLI Reference overview](README.md) for the complete list, including batch-operation codes used elsewhere in the CLI, and the JSON error format.

## Related

* [`observal agent`](agent.md): bundle MCP servers, along with other components, into a versioned Agent
* [`observal registry`](registry.md): the parent command group covering all component types