<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# observal component

Manage versioned releases for registry components. The `component version` subgroup lets you publish new versions and view version history for any component type (mcp, skill, hook, prompt, sandbox).

## Synopsis

```bash
observal component version publish <type> <listing> [options]
observal component version list <type> <listing> [options]
```

## Subcommands

### `version publish`

Publish a new version for a registry component.

```bash
observal component version publish <type> <listing> [--version <semver>] --description <text> [--changelog <text>] [--ide <ide>...] [--extra <json>]
```

| Option | Description |
| --- | --- |
| `<type>` | Component type: `mcp`, `skill`, `hook`, `prompt`, or `sandbox`. |
| `<listing>` | Listing name, UUID, or alias (e.g. `@my-server`). |
| `--version, -v` | Semantic version string (e.g. `2.0.0`). If omitted, the CLI fetches suggestions from the server and prompts interactively. |
| `--description, -d` | **Required.** Short description of this version. |
| `--changelog` | Changelog or release notes for this version. |
| `--ide` | Supported IDEs. Repeat the flag for multiple values. |
| `--extra` | JSON string with type-specific metadata (e.g. `'{"transport": "http"}'` for MCP servers). |

After publishing, the version enters `pending` status and awaits admin review before becoming publicly visible. Submitters can install their own pending versions immediately.

#### Examples

```bash
# Publish with an explicit version
observal component version publish mcp my-server -v 2.0.0 -d "Breaking change: new auth flow"

# Include changelog and IDE support
observal component version publish hook guard-hook -v 1.1.0 \
  -d "Add timeout handling" \
  --changelog "Fixed race condition on slow networks"

# Multiple IDE targets
observal component version publish skill my-skill -v 1.0.0 \
  -d "Initial release" \
  --ide claude-code --ide cursor

# Type-specific extra metadata
observal component version publish mcp analyzer \
  --extra '{"transport": "http"}' \
  -d "HTTP transport support"

# Omit --version to get interactive suggestions
observal component version publish prompt welcome-prompt -d "Revised tone"
```

---

### `version list`

List all published versions for a registry component.

```bash
observal component version list <type> <listing> [--output <format>]
```

| Option | Description |
| --- | --- |
| `<type>` | Component type: `mcp`, `skill`, `hook`, `prompt`, or `sandbox`. |
| `<listing>` | Listing name, UUID, or alias. |
| `--output, -o` | Output format: `table` (default) or `json`. |

The table view shows version number, review status, release date, and who published each version.

#### Examples

```bash
# Table output (default)
observal component version list mcp my-server

# JSON for scripting
observal component version list hook guard-hook --output json

# Using an alias
observal component version list skill @my-skill-alias
```

## Valid component types

The following types are accepted by all `component version` commands:

- `mcp`
- `skill`
- `hook`
- `prompt`
- `sandbox`

Passing any other type results in an error with the list of valid options.
