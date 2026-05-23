<!-- SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# observal registry

Publish and manage registry components. The registry has five component types (MCP servers, skills, hooks, prompts, and sandboxes), and all five share a similar command structure.

## Subcommand structure

```
observal registry <type> <action> [args]
```

`<type>` is one of: `mcp`, `skill`, `hook`, `prompt`, `sandbox`.

Every type supports these actions:

| Action | Description |
| --- | --- |
| `submit` | Submit a new component for review |
| `list` | List approved components |
| `my` | List your own components across all statuses |
| `show` | Show details for one component |
| `install` | Generate an IDE config snippet |
| `edit` | Edit a draft, pending, or rejected submission |
| `delete` | Delete a component |

Notes:
- `my` is available for `mcp`, `skill`, and `prompt`. Hooks and sandboxes do not have a `my` subcommand.
- Prompts also support [`render`](#observal-registry-prompt-render).

All `<id-or-name>` arguments accept: a UUID, a component name, a row number from the last `list` output, or an `@alias`.

---

## MCP servers

MCP server registry commands for submitting, browsing, installing, editing, and deleting MCP server listings.

### `observal registry mcp submit`

Submit an MCP server to the registry. By default, paste your server's JSON config (the same format you use in your IDE). Use `--git` to analyze a git repository instead.

#### Synopsis

```bash
observal registry mcp submit [OPTIONS]
observal registry mcp submit --git <url> [OPTIONS]
```

#### Options

| Option | Short | Description |
| --- | --- | --- |
| `--git` | `-g` | Analyze a git repository instead of pasting config |
| `--name` | `-n` | Pre-fill server name (skip prompt) |
| `--category` | `-c` | Pre-fill category (skip prompt) |
| `--yes` | `-y` | Accept all defaults |
| `--draft` | | Save as draft instead of submitting for review |
| `--submit` | | Submit an existing draft for review (MCP ID) |

#### Default flow (JSON paste)

1. Prompts you to paste your MCP server JSON config.
2. Accepts multiple formats:
   - **IDE config**: `{"mcpServers": {"name": {"command": "...", "args": [...], "env": {...}}}}`
   - **Bare config**: `{"command": "npx", "args": ["-y", "pkg"]}`
   - **SSE/HTTP**: `{"url": "http://...", "type": "sse", "headers": {...}}`
   - **server.json manifest**: `{"packages": [...], "remotes": [...]}`
3. Auto-detects environment variables from `$VAR` patterns and `env` keys.
4. Shows a config preview and prompts for metadata (name, description, category).
5. Submits to registry for review.

#### Git analysis flow (`--git`)

1. Shallow-clones the repo.
2. Detects the MCP framework (FastMCP, MCP SDK, TypeScript SDK, Go SDK).
3. Extracts server name, description, and exposed tools via AST.
4. Scans for required env vars (`os.environ`, `os.getenv`, `.env.example`, `server.json`).
5. Prompts for metadata confirmation.
6. Submits to registry for review.

#### Examples

```bash
# Paste config (default, recommended)
observal registry mcp submit

# Non-interactive with piped JSON
echo '{"command": "npx", "args": ["-y", "@example/mcp-server"]}' | observal registry mcp submit -y -n my-server -c developer-tools

# Save as draft
observal registry mcp submit --draft

# Analyze a git repo
observal registry mcp submit --git https://github.com/MarkusPfundstein/mcp-obsidian

# Non-interactive git analysis
observal registry mcp submit --git https://github.com/sooperset/mcp-atlassian -y

# Submit an existing draft for review
observal registry mcp submit --submit my-server
```

#### Valid categories

`browser-automation`, `cloud-platforms`, `code-execution`, `communication`, `databases`, `developer-tools`, `devops`, `file-systems`, `finance`, `knowledge-memory`, `monitoring`, `multimedia`, `productivity`, `search`, `security`, `version-control`, `ai-ml`, `data-analytics`, `general`.

#### Valid transports

`stdio`, `sse`, `streamable-http`.

#### Valid frameworks

`python`, `docker`, `typescript`, `go`.

---

### `observal registry mcp list`

List approved MCP servers in the registry.

```bash
observal registry mcp list [--search TERM] [--category CAT] [--limit N] [--sort name|category|version] [--output table|json|plain] [--interactive]
```

| Option | Short | Description |
| --- | --- | --- |
| `--search` | `-s` | Search by name or description |
| `--category` | `-c` | Filter by category |
| `--limit` | `-n` | Max results (default: 50) |
| `--sort` | | Sort by: `name`, `category`, `version` |
| `--output` | `-o` | Output format: `table`, `json`, `plain` |
| `--interactive` | `-i` | Open a fuzzy-search picker |

```bash
observal registry mcp list --search github
observal registry mcp list --category ai --output json
observal registry mcp list --interactive
observal registry mcp list --sort category --limit 10
```

---

### `observal registry mcp my`

List your own MCP servers across all statuses (draft, pending, approved, rejected).

```bash
observal registry mcp my [--output table|json|plain]
```

```bash
observal registry mcp my
observal registry mcp my --output json
```

---

### `observal registry mcp show`

Show full details of an MCP server including validation results, env vars, and supported IDEs.

```bash
observal registry mcp show <id-or-name> [--output table|json]
```

```bash
observal registry mcp show my-server
observal registry mcp show 3
observal registry mcp show @fav --output json
```

---

### `observal registry mcp install`

Generate an IDE config snippet for an MCP server. Prompts for required environment variables and headers interactively.

```bash
observal registry mcp install <id-or-name> --ide <ide> [--raw]
```

| Option | Short | Description |
| --- | --- | --- |
| `--ide` | `-i` | Target IDE (required) |
| `--raw` | | Output bare JSON only, suitable for piping to a file |

```bash
observal registry mcp install my-server --ide claude-code
observal registry mcp install my-server --ide cursor --raw > .cursor/mcp.json
observal registry mcp install 2 --ide vscode
observal registry mcp install @db --ide kiro
```

---

### `observal registry mcp edit`

Edit an MCP server submission. For draft/pending/rejected listings, edits in place. For approved listings, publishes a new version with a semver bump.

```bash
observal registry mcp edit <id-or-name> [OPTIONS]
```

| Option | Short | Description |
| --- | --- | --- |
| `--from-file` | `-f` | Load updates from a JSON file |
| `--name` | `-n` | New listing name |
| `--description` | `-d` | New description |
| `--category` | `-c` | New category |
| `--version` | `-v` | New version string |
| `--git-url` | | New git URL |
| `--command` | | New command |
| `--url` | | New URL (SSE/HTTP) |

Without flags, opens an interactive JSON paste prompt (same format as submit).

```bash
# Interactive JSON paste edit
observal registry mcp edit my-server

# Update specific fields
observal registry mcp edit my-server -d "New description" -c databases

# Load updates from a file
observal registry mcp edit my-server --from-file updates.json

# Bump version on an approved listing
observal registry mcp edit my-server --version 1.2.0
```

---

### `observal registry mcp delete`

Delete an MCP server from the registry. You can only delete servers you own (or any server if you are an admin).

```bash
observal registry mcp delete <id-or-name> [--yes]
```

| Option | Short | Description |
| --- | --- | --- |
| `--yes` | `-y` | Skip confirmation prompt |

```bash
observal registry mcp delete my-server
observal registry mcp delete abc123 --yes
observal registry mcp delete 3 -y
```

---

## Skills

Skill registry commands. Skills are portable SKILL.md instruction packages that provide agents with task-specific guidance.

Valid task types: `code-review`, `code-generation`, `testing`, `documentation`, `debugging`, `refactoring`, `deployment`, `security-audit`, `performance`, `general`.

### `observal registry skill submit`

Submit a new skill for review. Provide `--git-url` to let the server fetch SKILL.md automatically, or use `--skill-md` to paste content directly.

```bash
observal registry skill submit [OPTIONS]
```

| Option | Short | Description |
| --- | --- | --- |
| `--from-file` | `-f` | Create from JSON file |
| `--skill-md` | | Path to SKILL.md (auto-fills fields from frontmatter) |
| `--git-url` | | Git repository URL |
| `--git-ref` | | Branch or tag (default: main) |
| `--draft` | | Save as draft instead of submitting for review |
| `--submit` | | Submit a draft for review (skill ID) |

```bash
observal registry skill submit --git-url https://github.com/org/repo
observal registry skill submit --from-file skill.json
observal registry skill submit --skill-md ./SKILL.md --git-url https://github.com/org/repo
observal registry skill submit --draft
observal registry skill submit --submit abc123
```

---

### `observal registry skill list`

List approved skills in the registry.

```bash
observal registry skill list [--task-type TYPE] [--target-agent AGENT] [--search TERM] [--output table|json|plain]
```

| Option | Short | Description |
| --- | --- | --- |
| `--task-type` | `-t` | Filter by task type |
| `--target-agent` | | Filter by target agent |
| `--search` | `-s` | Search by name or description |
| `--output` | `-o` | Output format: `table`, `json`, `plain` |

```bash
observal registry skill list
observal registry skill list --task-type code-review
observal registry skill list --target-agent claude-code --output json
observal registry skill list --search "refactor"
```

---

### `observal registry skill my`

List your own skills across all statuses (draft, pending, approved, rejected).

```bash
observal registry skill my [--output table|json|plain]
```

```bash
observal registry skill my
observal registry skill my --output json
```

---

### `observal registry skill show`

Show detailed information about a skill, including validation status, task type, git source, and slash command.

```bash
observal registry skill show <id-or-name> [--output table|json]
```

```bash
observal registry skill show my-skill
observal registry skill show 1
observal registry skill show @refactor-skill --output json
```

---

### `observal registry skill install`

Install a skill by fetching the full skill directory from git. Clones the skill directory via sparse checkout and writes it to the appropriate IDE skill path.

```bash
observal registry skill install <id-or-name> --ide <ide> [--scope user|project] [--raw] [--no-write]
```

| Option | Short | Description |
| --- | --- | --- |
| `--ide` | `-i` | Target IDE (required) |
| `--scope` | `-s` | Install scope: `user` (global, default) or `project` |
| `--raw` | | Output raw JSON only |
| `--no-write` | | Print config without writing files |

Scopes:
- `user` (default): writes to `~/.<ide>/skills/<name>/` (global).
- `project`: writes to `.agents/skills/<name>/` in cwd, then symlinks into each IDE config dir found in the project.

```bash
observal registry skill install my-skill --ide claude-code
observal registry skill install @sk --ide kiro --scope project
observal registry skill install 2 --ide cursor --raw
observal registry skill install my-skill --ide gemini-cli --no-write
```

---

### `observal registry skill edit`

Edit a draft, pending, or rejected skill submission. Acquires an edit lock to prevent concurrent modifications.

```bash
observal registry skill edit <id-or-name> [OPTIONS]
```

| Option | Short | Description |
| --- | --- | --- |
| `--from-file` | `-f` | Load updates from JSON file |
| `--name` | `-n` | New listing name |
| `--description` | `-d` | New description |
| `--version` | `-v` | New version string |
| `--task-type` | `-t` | New task type |
| `--git-url` | | New git URL |
| `--git-ref` | | New git ref |

```bash
observal registry skill edit my-skill --description "Better desc"
observal registry skill edit abc123 --from-file updates.json
observal registry skill edit @sk --git-url https://github.com/org/new-repo
observal registry skill edit 2 --version 2.0.0 --task-type debugging
```

---

### `observal registry skill delete`

Delete a skill from the registry. Only the owner or an admin can delete.

```bash
observal registry skill delete <id-or-name> [--yes]
```

```bash
observal registry skill delete my-skill
observal registry skill delete abc123 --yes
observal registry skill delete @old-skill -y
```

---

## Hooks

Hook registry commands. Hooks fire on IDE lifecycle events and run custom logic.

Valid events: `PreToolUse`, `PostToolUse`, `Notification`, `Stop`, `SubagentStop`, `SessionStart`, `UserPromptSubmit`.

Handler types: `command` (local script), `http` (webhook).

Execution modes: `async`, `sync`, `blocking`.

### `observal registry hook submit`

Submit a new hook for review. Supports inline script content via `--script`, or git-hosted hooks via `--source-url`.

```bash
observal registry hook submit [OPTIONS]
```

| Option | Short | Description |
| --- | --- | --- |
| `--from-file` | `-f` | Create from JSON file |
| `--draft` | | Save as draft instead of submitting for review |
| `--submit` | | Submit a draft for review (hook ID) |
| `--script` | | Path to hook script file (content stored in registry) |
| `--source-url` | | Git repo containing hook scripts |
| `--source-ref` | | Branch/tag to track (default: main) |
| `--source-path` | | Directory within repo containing hook files |
| `--requires` | | Install prerequisites (repeatable) |

```bash
observal registry hook submit
observal registry hook submit --script ./protect-files.sh
observal registry hook submit --source-url https://github.com/org/hooks --source-path hooks/guard/
observal registry hook submit --from-file hook.json
observal registry hook submit --draft
observal registry hook submit --submit abc123
```

---

### `observal registry hook list`

List approved hooks from the registry.

```bash
observal registry hook list [--event EVENT] [--search TERM] [--output table|json|plain]
```

| Option | Short | Description |
| --- | --- | --- |
| `--event` | `-e` | Filter by event type |
| `--search` | `-s` | Search by name or description |
| `--output` | `-o` | Output format: `table`, `json`, `plain` |

```bash
observal registry hook list
observal registry hook list --event Stop
observal registry hook list --search guard --output json
```

---

### `observal registry hook show`

Show detailed information for a single hook, including event type, handler config, and execution mode.

```bash
observal registry hook show <id-or-name> [--output table|json]
```

```bash
observal registry hook show my-hook
observal registry hook show 1
observal registry hook show @guard --output json
```

---

### `observal registry hook install`

Install a hook for a specific IDE. Writes script files and merges hook config into the IDE's settings. Existing hooks are preserved during merge.

```bash
observal registry hook install <id-or-name> --ide <ide> [--platform PLATFORM] [--raw] [--dir DIR]
```

| Option | Short | Description |
| --- | --- | --- |
| `--ide` | `-i` | Target IDE (required) |
| `--platform` | `-p` | Platform: `win32`, `darwin`, `linux` |
| `--raw` | | Output raw JSON only (no file writes) |
| `--dir` | `-d` | Project directory for file writes (default: cwd) |

```bash
observal registry hook install my-hook --ide claude-code
observal registry hook install @guard --ide kiro --dir ./project
observal registry hook install my-hook --ide cursor --raw
observal registry hook install my-hook --ide claude-code --platform darwin
```

---

### `observal registry hook edit`

Edit a draft, pending, or rejected hook submission. Acquires an edit lock to prevent concurrent modifications.

```bash
observal registry hook edit <id-or-name> [OPTIONS]
```

| Option | Short | Description |
| --- | --- | --- |
| `--from-file` | `-f` | Load updates from JSON file |
| `--name` | `-n` | New listing name |
| `--description` | `-d` | New description |
| `--version` | `-v` | New version string |
| `--event` | `-e` | New event type |

```bash
observal registry hook edit my-hook --description "Updated guard hook"
observal registry hook edit my-hook --event Stop --version 1.1.0
observal registry hook edit @guard --from-file updated-hook.json
observal registry hook edit 1 --name new-name
```

---

### `observal registry hook delete`

Delete a hook from the registry. Only the owner or an admin can delete.

```bash
observal registry hook delete <id-or-name> [--yes]
```

```bash
observal registry hook delete my-hook
observal registry hook delete @guard --yes
observal registry hook delete abc12345 -y
```

---

## Prompts

Prompt registry commands. Prompts are reusable templates with `{{ variable }}` placeholders that agents can render at runtime.

Valid categories: `system-prompt`, `code-review`, `code-generation`, `testing`, `documentation`, `debugging`, `general`.

### `observal registry prompt submit`

Submit a new prompt template for review. You can submit interactively, from a JSON file, or from a raw template file.

```bash
observal registry prompt submit [OPTIONS]
```

| Option | Short | Description |
| --- | --- | --- |
| `--from-file` | `-f` | Create from JSON file, or read template from a text file |
| `--draft` | | Save as draft instead of submitting for review |
| `--submit` | | Submit a draft for review (prompt ID) |

If `--from-file` points to a non-JSON file, its content is used as the template and you are prompted for metadata interactively.

```bash
observal registry prompt submit
observal registry prompt submit --from-file prompt.json
observal registry prompt submit --from-file template.md
observal registry prompt submit --draft
observal registry prompt submit --submit abc123
```

---

### `observal registry prompt list`

List approved prompts in the registry.

```bash
observal registry prompt list [--category CAT] [--search TERM] [--output table|json|plain]
```

| Option | Short | Description |
| --- | --- | --- |
| `--category` | `-c` | Filter by category |
| `--search` | `-s` | Search by name or description |
| `--output` | `-o` | Output format: `table`, `json`, `plain` |

```bash
observal registry prompt list
observal registry prompt list --category code-review
observal registry prompt list --search "refactor" --output json
```

---

### `observal registry prompt my`

List your own prompts across all statuses (draft, pending, approved, rejected).

```bash
observal registry prompt my [--output table|json|plain]
```

```bash
observal registry prompt my
observal registry prompt my --output json
```

---

### `observal registry prompt show`

Show detailed information about a prompt, including the template content.

```bash
observal registry prompt show <id-or-name> [--output table|json]
```

```bash
observal registry prompt show my-prompt
observal registry prompt show 1
observal registry prompt show @refactor-prompt --output json
```

---

### `observal registry prompt install`

Generate IDE install configuration for a prompt.

```bash
observal registry prompt install <id-or-name> --ide <ide> [--raw]
```

| Option | Short | Description |
| --- | --- | --- |
| `--ide` | `-i` | Target IDE (required) |
| `--raw` | | Output bare JSON only, suitable for piping |

```bash
observal registry prompt install my-prompt --ide claude-code
observal registry prompt install @tpl --ide cursor --raw > prompt.json
```

---

### `observal registry prompt render`

Render a prompt template with variable substitution. Sends key=value pairs to the server, which substitutes them into the template and returns the rendered output. Also emits a `prompt_render` telemetry span.

```bash
observal registry prompt render <id-or-name> --var key=value [--var key2=value2 ...]
```

| Option | Short | Description |
| --- | --- | --- |
| `--var` | `-v` | Variable as `key=value` (repeatable) |

```bash
observal registry prompt render my-prompt --var lang=python
observal registry prompt render @tpl --var file=main.py --var task=refactor
```

---

### `observal registry prompt edit`

Edit a draft, pending, or rejected prompt submission. Acquires an edit lock to prevent concurrent modifications.

```bash
observal registry prompt edit <id-or-name> [OPTIONS]
```

| Option | Short | Description |
| --- | --- | --- |
| `--from-file` | `-f` | Load updates from JSON file |
| `--name` | `-n` | New listing name |
| `--description` | `-d` | New description |
| `--version` | `-v` | New version string |
| `--category` | `-c` | New category |
| `--template` | `-t` | New template text |

```bash
observal registry prompt edit my-prompt --description "Updated desc"
observal registry prompt edit abc123 --from-file updates.json
observal registry prompt edit @tpl --template "New template: {{ var }}"
observal registry prompt edit 2 --version 2.0.0 --category debugging
```

---

### `observal registry prompt delete`

Delete a prompt from the registry. Only the owner or an admin can delete.

```bash
observal registry prompt delete <id-or-name> [--yes]
```

```bash
observal registry prompt delete my-prompt
observal registry prompt delete abc123 --yes
observal registry prompt delete @old-template -y
```

---

## Sandboxes

Sandbox registry commands. Sandboxes are containerized execution environments for agent tasks.

Valid runtime types: `docker`, `lxc`, `firecracker`, `wasm`.

Network policies: `none`, `host`, `bridge`, `restricted`.

### `observal registry sandbox submit`

Submit a new sandbox environment for review.

```bash
observal registry sandbox submit [OPTIONS]
```

| Option | Short | Description |
| --- | --- | --- |
| `--from-file` | `-f` | Create from JSON file |
| `--draft` | | Save as draft instead of submitting for review |
| `--submit` | | Submit a draft for review (sandbox ID) |

```bash
observal registry sandbox submit
observal registry sandbox submit --from-file sandbox.json
observal registry sandbox submit --draft
observal registry sandbox submit --submit abc123
```

---

### `observal registry sandbox list`

List approved sandboxes in the registry.

```bash
observal registry sandbox list [--runtime TYPE] [--search TERM] [--output table|json|plain]
```

| Option | Short | Description |
| --- | --- | --- |
| `--runtime` | `-r` | Filter by runtime type |
| `--search` | `-s` | Search by name or description |
| `--output` | `-o` | Output format: `table`, `json`, `plain` |

```bash
observal registry sandbox list
observal registry sandbox list --runtime docker
observal registry sandbox list --search "node" --output json
```

---

### `observal registry sandbox show`

Show detailed information about a sandbox, including runtime type, container image, and resource limits.

```bash
observal registry sandbox show <id-or-name> [--output table|json]
```

```bash
observal registry sandbox show my-sandbox
observal registry sandbox show 1
observal registry sandbox show @dev-env --output json
```

---

### `observal registry sandbox install`

Generate IDE install configuration for a sandbox.

> **Note:** Standalone sandbox install is deprecated. Sandboxes should be added as agent components instead. Preferred workflow: `observal agent add --type sandbox --id <id>` then `observal pull <agent> --ide <ide>`.

```bash
observal registry sandbox install <id-or-name> --ide <ide> [--raw]
```

| Option | Short | Description |
| --- | --- | --- |
| `--ide` | `-i` | Target IDE (required) |
| `--raw` | | Output bare JSON only |

```bash
observal registry sandbox install my-sandbox --ide claude-code
observal registry sandbox install @env --ide cursor --raw
```

---

### `observal registry sandbox edit`

Edit a draft, pending, or rejected sandbox submission. Acquires an edit lock to prevent concurrent modifications.

```bash
observal registry sandbox edit <id-or-name> [OPTIONS]
```

| Option | Short | Description |
| --- | --- | --- |
| `--from-file` | `-f` | Load updates from JSON file |
| `--name` | `-n` | New listing name |
| `--description` | `-d` | New description |
| `--version` | `-v` | New version string |
| `--runtime-type` | `-r` | New runtime type |
| `--image` | `-i` | New container image |

```bash
observal registry sandbox edit my-sandbox --image node:20-alpine
observal registry sandbox edit abc123 --from-file updates.json
observal registry sandbox edit @env --runtime-type docker --version 2.0.0
```

---

### `observal registry sandbox delete`

Delete a sandbox from the registry. Only the owner or an admin can delete.

```bash
observal registry sandbox delete <id-or-name> [--yes]
```

```bash
observal registry sandbox delete my-sandbox
observal registry sandbox delete abc123 --yes
observal registry sandbox delete @old-env -y
```

---

## Shared behavior

### ID resolution

All commands that take `<id-or-name>` accept four forms:

1. **UUID**: the full component ID.
2. **Name**: the component's registered name.
3. **Row number**: the `#` column from the last `list` or `my` output.
4. **@alias**: a user-defined alias set via `observal config alias`.

### Draft workflow

All component types support a draft workflow:

1. Submit with `--draft` to save without triggering review.
2. Edit freely with the `edit` command while in draft status.
3. Submit the draft for review: `observal registry <type> submit --submit <id>`.

### Edit locking

The `edit` command acquires an optimistic lock before saving changes. If another session is editing the same component, the command fails with a 409 conflict. The lock is released automatically on success or cancellation.

### Output formats

All `list`, `my`, and `show` commands support `--output`:

- `table` (default): Rich formatted table.
- `json`: Raw JSON for scripting and piping.
- `plain`: Minimal one-line-per-item format.

---

## Related

* [`observal agent`](agent.md): bundle registry components into an installable agent
* [Use Cases: Share agent configs](../use-cases/share-agent-configs.md)
