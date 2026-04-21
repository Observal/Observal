# observal registry

Publish and manage registry components. The registry has five component types — MCP servers, skills, hooks, prompts, and sandboxes — and all five share the same command structure.

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
| `show` | Show details for one component |
| `install` | Generate an IDE config snippet |
| `delete` | Delete a component |

Prompts also support [`render`](#observal-registry-prompt-render).

---

## `observal registry mcp submit`

Submit an MCP server for review. The CLI clones the repo locally (using your git credentials), analyzes it via AST parsing, then sends the analysis to the server.

### Synopsis

```bash
observal registry mcp submit <git-url> [OPTIONS]
observal registry mcp submit --from-file <path> [OPTIONS]
```

### Options

| Option | Short | Description |
| --- | --- | --- |
| `--name` | `-n` | Pre-fill server name (skip prompt) |
| `--category` | `-c` | Pre-fill category (skip prompt) |
| `--yes` | `-y` | Accept all defaults from repo analysis |

### What happens

1. Shallow-clones the repo.
2. Detects the MCP framework (FastMCP, MCP SDK, TypeScript SDK, Go SDK).
3. Extracts server name, description, and exposed tools via AST.
4. Scans for required env vars (`os.environ`, `os.getenv`, `.env.example`, Dockerfile `ENV`/`ARG`).
5. Prompts for metadata (description, owner, category, supported IDEs, setup instructions).
6. Shows detected env vars — confirm, reject, or add more.
7. Submits to the server with `client_analysis` attached. The server stores the analysis directly without re-cloning.

If local analysis fails (e.g., git not available), falls back to server-side analysis.

### Examples

```bash
# Interactive
observal registry mcp submit https://github.com/MarkusPfundstein/mcp-obsidian

# Non-interactive, accept defaults
observal registry mcp submit https://github.com/sooperset/mcp-atlassian -y
```

### Valid categories

`browser-automation`, `cloud-platforms`, `code-execution`, `communication`, `databases`, `developer-tools`, `devops`, `file-systems`, `finance`, `knowledge-memory`, `monitoring`, `multimedia`, `productivity`, `search`, `security`, `version-control`, `ai-ml`, `data-analytics`, `general`.

### Valid transports

`stdio`, `sse`, `streamable-http`.

### Valid frameworks

`python`, `docker`, `typescript`, `go`.

---

## `observal registry <type> list`

List approved components.

### Synopsis

```bash
observal registry <type> list [--search TERM] [--category CAT] [--limit N] [--sort name|category|version] [--output table|json|plain]
```

### Example

```bash
observal registry mcp list --search github
observal registry skill list --limit 100 --output json | jq
```

---

## `observal registry <type> show`

Show details for one component.

```bash
observal registry <type> show <id-or-name> [--output table|json]
```

`<id-or-name>` accepts: UUID, name, row number from last `list`, or `@alias`.

---

## `observal registry <type> install`

Generate an IDE config snippet. Prompts for any required env var values.

```bash
observal registry <type> install <id-or-name> --ide <ide> [--raw]
```

`--raw` prints JSON only, suitable for piping to a file.

---

## `observal registry <type> delete`

Delete a component you own.

```bash
observal registry <type> delete <id-or-name> [--yes]
```

---

## `observal registry prompt render`

Prompts have an extra subcommand — render a template locally with variable substitution.

```bash
observal registry prompt render <prompt-id> --var name=Alice --var ticket=SHOP-42
```

## Per-type notes

### Skills

Skills are portable instruction packages — for example, a `code-review-skill` with a SKILL.md file describing how the agent should approach a review. [Valid task types](../reference/config-files.md): `code-review`, `code-generation`, `testing`, `documentation`, `debugging`, `refactoring`, `deployment`, `security-audit`, `performance`, `general`.

### Hooks

Hooks fire on IDE lifecycle events. Events: `PreToolUse`, `PostToolUse`, `Notification`, `Stop`, `SubagentStop`, `SessionStart`, `UserPromptSubmit`. Handler types: `command` (local script), `http` (webhook). Execution modes: `async`, `sync`, `blocking`. Scopes: `agent`, `session`, `global`. Full schema: [Hooks specification](../reference/hooks-spec.md).

### Prompts

Categories: `system-prompt`, `code-review`, `code-generation`, `testing`, `documentation`, `debugging`, `general`. Variables use `{{ name }}` syntax.

### Sandboxes

Runtime types: `docker`, `lxc`, `firecracker`, `wasm`. Network policies: `none`, `host`, `bridge`, `restricted`.

## Related

* [`observal agent`](agent.md) — bundle registry components into an installable agent
* [Use Cases → Share agent configs](../use-cases/share-agent-configs.md)
