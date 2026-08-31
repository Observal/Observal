<!-- SPDX-FileCopyrightText: 2026 Hemalatha Madeswaran <hemalathamadeswaran@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 tsitu0 <tomsitu0102@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# `observal agent`

Create, compose, publish, install, and govern agents. An agent bundles MCP servers, skills, hooks, prompts, and sandboxes into one versioned Registry object.

Canonical identities use `namespace/slug`. Commands also accept UUIDs, unambiguous bare names, aliases, and row numbers from the latest Agent list.

## Commands

| Command | Purpose |
| --- | --- |
| `create` | Create from flags, JSON, or an interactive wizard |
| `bulk-create` | Validate or create multiple agents from JSON |
| `list` | List approved visible agents |
| `my` | List agents owned or co-authored by the user |
| `show` | Show an agent and its composition |
| `install` | Generate an installation config without writing files |
| `pull` | Generate and write a complete harness installation |
| `archive` | Archive an agent |
| `delete` | Compatibility alias for `archive` |
| `unarchive` | Restore an archived agent |
| `init` | Create a local `observal-agent.yaml` |
| `add` | Add a Registry component UUID to local YAML |
| `build` | Validate local composition and target scope |
| `publish` | Create, update, save, or submit an agent |
| `release` | Publish a reviewed version bump |
| `versions` | List version history |
| `transfer-owner` | Transfer ownership |
| `co-authors` | List, add, or remove co-authors |

Every leaf command supports `--output table|json`. JSON success output contains no Rich text, prompt, banner, or spinner. JSON failures leave stdout empty and write one categorized object to stderr.

## Create

Use complete flags for automation:

```bash
observal agent create \
  --name reviewer \
  --description 'Reviews changes' \
  --prompt 'Review carefully.' \
  --model claude-sonnet-4 \
  --harness kiro \
  --output json
```

Other modes:

```bash
observal agent create --from-file agent.json --output json
observal agent create
```

The no-flag form is interactive and cannot run in JSON mode. Flag mode requires `--name` and either `--prompt` or `--prompt-file`. Versions must be semantic versions and every repeated `--harness` must be registered.

`--team HANDLE --visibility team` creates a private teamspace agent. `--visibility team` requires `--team`.

JSON returns the direct server Agent object.

## Bulk create

Input may be an array or an object containing an `agents` array:

```json
{
  "agents": [
    {
      "name": "reviewer",
      "version": "1.0.0",
      "owner": "alice",
      "prompt": "Review carefully.",
      "model_name": "claude-sonnet-4",
      "components": []
    }
  ]
}
```

```bash
observal agent bulk-create --from-file agents.json --dry-run --output json
observal agent bulk-create --from-file agents.json --yes --output json
```

JSON mode requires either `--dry-run` or `--yes`. It returns the direct bulk result, including per-agent statuses and summary counts.

## List, my, and show

```bash
observal agent list --search 'incident response' --output json
observal agent list --namespace alice --page 2 --limit 20 --output json
observal agent list --team platform --output json
observal agent my --output json
observal agent show alice/reviewer --output json
```

`list` JSON is paginated:

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 50
}
```

The most recent `list` or `my` result is cached for row-number references. Empty results clear stale Agent rows. `--interactive` is human-only and cannot be combined with JSON.

`my` returns the standard `items`, `total`, `page`, and `page_size` envelope, including pending, approved, rejected, and archived agents. Empty results use `items: []`.

`show` returns the direct Agent object, including component links and success criteria.

## Generate installation config

`install` asks the server to generate config but does not write it:

```bash
observal agent install alice/reviewer --harness kiro --output json
```

JSON returns the complete server installation result. Legacy `--raw` prints only `config_snippet`; new automation should use the shared output option.

Use [`observal agent pull`](pull.md) to write and track the generated installation.

## Archive, delete, and restore

```bash
observal agent archive alice/reviewer --yes --output json
observal agent delete alice/reviewer --yes --output json
observal agent unarchive alice/reviewer --yes --output json
```

`delete` is an alias for the same reversible archive operation. JSON mode never prompts and requires `--yes`. JSON returns the direct updated Agent object.

## Local authoring workflow

### Initialize

```bash
observal agent init \
  --dir ./reviewer \
  --name reviewer \
  --description 'Reviews changes' \
  --prompt-file ./PROMPT.md \
  --model claude-sonnet-4 \
  --harness kiro \
  --output json
```

The no-flag form is interactive. JSON mode requires complete flags and refuses to overwrite an existing definition. Writes are atomic.

JSON returns:

```json
{
  "path": "/work/reviewer/observal-agent.yaml",
  "agent": {
    "name": "reviewer",
    "version": "1.0.0"
  }
}
```

### Add components

Find a component in Registry JSON, then copy its UUID:

```bash
observal registry skill list --search review --output json
observal agent add skill 22222222-2222-2222-2222-222222222222 --dir ./reviewer --output json
```

Valid types are `mcp`, `skill`, `hook`, `prompt`, and `sandbox`. Duplicate type and UUID pairs return conflict exit code 6. Invalid types or IDs return validation exit code 7.

JSON returns the YAML path and added component.

### Build

```bash
observal agent build --dir ./reviewer --output json
observal agent build --dir ./reviewer --team platform --visibility team --output json
```

Build verifies every component and validates whether private components are visible to the target owner. A successful JSON result contains `valid`, `agent`, `components`, and `issues`. Invalid composition exits with code 7 and leaves JSON stdout empty.

### Publish

```bash
observal agent publish --dir ./reviewer --output json
observal agent publish --dir ./reviewer --draft --output json
observal agent publish --submit alice/reviewer --output json
observal agent publish --dir ./reviewer --update --bump minor --output json
```

`--draft` and `--submit` are mutually exclusive. Scope changes cannot be combined with `--update`; use ownership transfer or a separate visibility operation. Non-interactive updates may use `--bump patch|minor|major`.

JSON returns the direct created, saved, submitted, or updated Agent object.

## Release and versions

```bash
observal agent release alice/reviewer --bump patch --dir ./reviewer --output json
observal agent versions alice/reviewer --page 1 --page-size 50 --output json
```

Release obtains the server's semantic-version suggestion, submits the complete YAML snapshot, then updates local YAML atomically only after the server accepts the release. A failed server request leaves the local version unchanged.

Versions JSON returns the direct paginated server object. Page size is 1 through 100.

## Transfer ownership

```bash
observal agent transfer-owner alice/reviewer bob --yes --output json
```

The username may optionally begin with `@`. JSON mode requires `--yes` and returns the direct server result.

## Co-authors

Co-authors can edit and publish the same Agent:

```bash
observal agent co-authors list alice/reviewer --output json
observal agent co-authors add alice/reviewer dev@example.com --output json
observal agent co-authors add alice/reviewer @dev --output json
observal agent co-authors remove alice/reviewer 550e8400-e29b-41d4-a716-446655440000 --output json
```

List returns the standard list envelope. Add returns the added user. Remove requires the user UUID returned by list and returns the direct deletion result.

## Pull

```bash
observal agent pull alice/reviewer --harness kiro --no-prompt --output json
```

Pull writes harness files, records the exact Agent and component versions, and reports every file and setup action. See the [Pull reference](pull.md) for path, secret, merge, dry-run, and JSON behavior.

## Exit codes

Common Agent failures use:

| Code | Meaning |
| --- | --- |
| 3 | Authentication required or failed |
| 4 | Permission denied |
| 5 | Agent, component, or local definition not found |
| 6 | Existing definition, duplicate component, or unsafe config merge conflict |
| 7 | Invalid name, version, harness, component, scope, or command combination |
| 8 | Server rate limit |
| 9 | Server, filesystem, lockfile, generated config, or setup dependency unavailable |
| 10 | CLI and server version mismatch |

## Related

* [`observal agent pull`](pull.md): install into a harness
* [`observal registry`](registry.md): manage Agent components
* [`observal registry models`](models.md): inspect exact harness model IDs
