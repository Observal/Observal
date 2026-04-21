# observal agent

Create, author, and publish agents. An agent bundles registry components (MCPs, skills, hooks, prompts, sandboxes) into one installable YAML.

## Subcommands

| Command | Description |
| --- | --- |
| [`agent create`](#observal-agent-create) | Interactive agent creation wizard |
| [`agent list`](#observal-agent-list) | List agents |
| [`agent show`](#observal-agent-show) | Show an agent's details and components |
| [`agent install`](#observal-agent-install) | Install an agent into an IDE (see also [`observal pull`](pull.md)) |
| [`agent delete`](#observal-agent-delete) | Delete an agent |
| [`agent init`](#observal-agent-init) | Scaffold `observal-agent.yaml` in the current directory |
| [`agent add`](#observal-agent-add) | Add a component to the local `observal-agent.yaml` |
| [`agent build`](#observal-agent-build) | Validate an agent against the server (dry-run) |
| [`agent publish`](#observal-agent-publish) | Publish the agent to the registry |

---

## `observal agent create`

Interactive wizard. Prompts for name, description, which MCP servers / skills / hooks to include, then submits to the registry.

```bash
observal agent create
```

---

## `observal agent list`

```bash
observal agent list [--search TERM] [--limit N] [--output table|json|plain]
```

---

## `observal agent show`

```bash
observal agent show <id-or-name>
```

Prints the agent's metadata and every bundled component.

---

## `observal agent install`

Install an agent into an IDE. Equivalent to [`observal pull`](pull.md); `pull` is the preferred shorthand.

```bash
observal agent install <id-or-name> --ide <ide>
```

---

## `observal agent delete`

```bash
observal agent delete <id-or-name> [--yes]
```

---

## The YAML workflow

For teams, the YAML workflow is the recommended path — the file lives in a repo and changes flow through PR review.

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

Submit the agent to the registry for review.

```bash
observal agent publish
```

## Naming rules

Agent names must match `^[a-z0-9][a-z0-9_-]*$` — lowercase, alphanumeric, hyphens or underscores, starting with a letter or digit.

Valid: `code-reviewer`, `my_agent_v2`, `kiro-helper`
Invalid: `Code-Reviewer` (uppercase), `-starts-with-hyphen`, `my.agent` (dot)

## Related

* [`observal pull`](pull.md) — install a published agent
* [`observal registry`](registry.md) — author the components an agent will bundle
* [Use Cases → Share agent configs](../use-cases/share-agent-configs.md)
