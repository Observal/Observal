<!-- SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 tsitu0 <tomsitu0102@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# observal agent

Create, author, and publish agents. An agent bundles registry components (MCPs, skills, hooks, prompts, sandboxes) into one installable YAML.

## Subcommands

| Command | Description |
| --- | --- |
| [`agent create`](#observal-agent-create) | Interactive agent creation wizard |
| [`agent bulk-create`](#observal-agent-bulk-create) | Bulk-create agents from a JSON file |
| [`agent list`](#observal-agent-list) | List agents |
| [`agent my`](#observal-agent-my) | List your own agents (all statuses) |
| [`agent show`](#observal-agent-show) | Show an agent's details and components |
| [`agent install`](#observal-agent-install) | Get install config for an agent |
| [`agent pull`](#observal-agent-pull) | Write agent config to IDE files |
| [`agent delete`](#observal-agent-delete) | Delete an agent |
| [`agent unarchive`](#observal-agent-unarchive) | Restore an archived agent |
| [`agent init`](#observal-agent-init) | Scaffold `observal-agent.yaml` in the current directory |
| [`agent add`](#observal-agent-add) | Add a component to the local `observal-agent.yaml` |
| [`agent build`](#observal-agent-build) | Validate an agent against the server (dry-run) |
| [`agent publish`](#observal-agent-publish) | Publish the agent to the registry |
| [`agent release`](#observal-agent-release) | Bump version and push a versioned release |
| [`agent versions`](#observal-agent-versions) | List all versions for an agent |

---

## `observal agent create`

Interactive wizard. Prompts for name, description, which MCP servers / skills / hooks to include, then submits to the registry.

Three modes are supported: load from a JSON file, pass flags for non-interactive creation, or run the interactive wizard.

```bash
observal agent create
observal agent create --from-file agent.json
observal agent create --name my-agent --prompt "You are..." --model claude-sonnet-4
observal agent create --name my-agent --prompt-file ./PROMPT.md --ide kiro --ide claude-code
```

| Option | Description |
| --- | --- |
| `--from-file`, `-f` | Create from a JSON file |
| `--name`, `-n` | Agent name (lowercase, hyphens, underscores) |
| `--version`, `-v` | Version (semver, e.g. 1.0.0) |
| `--description`, `-d` | Short description |
| `--owner` | Owner or team name |
| `--prompt`, `-p` | System prompt text |
| `--prompt-file` | Read system prompt from a file |
| `--model`, `-m` | Model name (e.g. claude-sonnet-4) |
| `--ide` | Supported IDEs (repeat for multiple) |

---

## `observal agent bulk-create`

Bulk-create agents from a JSON file. Accepts a JSON file containing an array of agent definitions, or an object with an `"agents"` key. Shows a preview table before creating. Use `--dry-run` to validate without actually creating agents.

```bash
observal agent bulk-create --from-file agents.json
observal agent bulk-create --from-file agents.json --dry-run
observal agent bulk-create --from-file agents.json --yes
```

| Option | Description |
| --- | --- |
| `--from-file` | (Required) JSON file with agent definitions |
| `--dry-run` | Preview without creating |
| `--yes`, `-y` | Skip confirmation |

---

## `observal agent list`

List active agents in the registry with pagination support. Use `--interactive` for fuzzy search with arrow-key selection.

```bash
observal agent list
observal agent list --search my-agent
observal agent list --page 2 --limit 20
observal agent list --interactive
observal agent list --output json
observal agent list --full-id
```

| Option | Description |
| --- | --- |
| `--search`, `-s` | Filter by search term |
| `--interactive`, `-i` | Interactive search mode |
| `--limit`, `-n` | Page size (1-200, default 50) |
| `--page`, `-p` | Page number (1-indexed) |
| `--id` | Include the agent ID column |
| `--full-id` | Show full UUID (implies --id) |
| `--output`, `-o` | Output format: table, json, plain |

---

## `observal agent my`

List your own agents across all statuses: pending, approved, rejected, and archived. Useful for checking the review status of your submissions.

```bash
observal agent my
observal agent my --output json
observal agent my --output plain
```

| Option | Description |
| --- | --- |
| `--output`, `-o` | Output format: table, json, plain |

---

## `observal agent show`

```bash
observal agent show <id-or-name>
```

Prints the agent's metadata and every bundled component.

---

## `observal agent install`

Get install config for an agent.

```bash
observal agent install <id-or-name> --ide <ide>
```

---

## `observal agent pull`

Fetch agent config and write IDE files to disk.

```bash
observal agent pull <id-or-name> --ide <ide>
```

---

## `observal agent delete`

Archive an agent (soft delete). The agent will no longer appear in public listings but can be restored with `agent unarchive`. Prompts for confirmation unless `--yes` is provided.

```bash
observal agent delete my-agent
observal agent delete my-agent --yes
observal agent delete @myalias
```

| Option | Description |
| --- | --- |
| `--yes`, `-y` | Skip confirmation |

---

## `observal agent unarchive`

Restore an archived agent back to active status. Reverses a previous archive (soft delete), making the agent visible in public listings again.

```bash
observal agent unarchive my-agent
observal agent unarchive my-agent --yes
observal agent unarchive a1b2c3d4-...
```

| Option | Description |
| --- | --- |
| `--yes`, `-y` | Skip confirmation |

---

## The YAML workflow

For teams, the YAML workflow is the recommended path: the file lives in a repo and changes flow through PR review.

### `observal agent init`

Scaffolds `observal-agent.yaml` in the current directory with required fields stubbed out.

```bash
observal agent init
```

### `observal agent add`

Add a component to `observal-agent.yaml` by ID or name.

```bash
observal agent add mcp github-mcp
observal agent add skill code-review-skill
observal agent add hook pretooluse-logger
observal agent add prompt system-intro
observal agent add sandbox node-18
```

Valid types: `mcp`, `skill`, `hook`, `prompt`, `sandbox`.

### `observal agent build`

Validate the agent against the server without publishing. Catches missing components, invalid references, and schema violations.

```bash
observal agent build
```

### `observal agent publish`

Submit the agent to the registry for review. Use `--update` to modify an existing agent (same name). Use `--draft` to save without submitting for review.

```bash
observal agent publish
observal agent publish --update
observal agent publish --draft
observal agent publish --dir /tmp/my-agent
```

| Option | Description |
| --- | --- |
| `--dir`, `-d` | Directory containing observal-agent.yaml |
| `--update`, `-u` | Update existing agent instead of creating |
| `--draft` | Save as draft instead of submitting for review |
| `--submit` | Submit an existing draft agent for review (agent ID) |

---

### `observal agent release`

Bump version and push a versioned release to the registry. Reads `observal-agent.yaml`, bumps the version according to the specified type, updates the YAML file, and submits a new version to the review queue.

```bash
observal agent release my-agent --bump patch
observal agent release my-agent --bump minor --dir /tmp/my-agent
observal agent release my-agent --bump major
```

| Option | Description |
| --- | --- |
| `--bump` | (Required) Version bump type: patch, minor, or major |
| `--dir`, `-d` | Directory containing observal-agent.yaml |

---

### `observal agent versions`

List all versions for an agent. Shows version history including version number, review status, release date, author, and component count.

```bash
observal agent versions my-agent
observal agent versions my-agent --output json
observal agent versions @myalias
```

| Option | Description |
| --- | --- |
| `--output`, `-o` | Output format: table or json |

## Naming rules

Agent names must match `^[a-z0-9][a-z0-9_-]*$`: lowercase, alphanumeric, hyphens or underscores, starting with a letter or digit.

Valid: `code-reviewer`, `my_agent_v2`, `kiro-helper`
Invalid: `Code-Reviewer` (uppercase), `-starts-with-hyphen`, `my.agent` (dot)

## Related

* [`observal agent pull`](pull.md): install a published agent
* [`observal registry`](registry.md): author the components an agent will bundle
* [Use Cases → Share agent configs](../use-cases/share-agent-configs.md)
