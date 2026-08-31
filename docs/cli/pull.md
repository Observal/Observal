<!-- SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 tsitu0 <tomsitu0102@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# `observal agent pull`

Install a complete Agent into a harness. Pull resolves the requested Agent version, asks the server for harness-native config, merges generated files safely, installs bundled skills and hooks, runs required harness setup, and records exact installed state.

## Synopsis

```bash
observal agent pull <agent-reference> --harness <harness> [OPTIONS]
```

Agent references may be UUIDs, canonical `namespace/slug`, unambiguous bare names, aliases, or row numbers from the latest Agent list.

## Examples

```bash
observal agent pull alice/reviewer --harness kiro --no-prompt --output json
observal agent pull alice/reviewer --harness claude-code --scope project --dry-run --no-prompt --output json
observal agent pull alice/reviewer --harness pi --version 1.2.3 --no-prompt --output json
```

## Options

| Option | Description |
| --- | --- |
| `--harness`, `-i` | Required target: `cursor`, `kiro`, `claude-code`, `codex`, `copilot`, `copilot-cli`, `opencode`, `antigravity`, `goose`, or `pi` |
| `--dir`, `-d` | Project directory used to resolve generated paths |
| `--dry-run`, `-n` | Return planned files and setup commands without changing disk or installation metadata |
| `--scope` | `project` or `user`, only for harnesses that support explicit scope |
| `--model` | Model ID, or `harness=model`; repeatable |
| `--tools` | Claude Code tool allowlist |
| `--refresh-models` | Refresh the model catalog before an interactive model picker |
| `--no-prompt`, `-y` | Disable environment, header, scope, and model prompts |
| `--env`, `-e` | MCP environment value in `NAME=VALUE` form; repeatable |
| `--header`, `-H` | MCP header in `NAME=VALUE` form; repeatable |
| `--version`, `-V` | Exact semantic Agent version |
| `--output`, `-o` | Table or JSON output |

Unknown harnesses, unsupported scopes, malformed assignments, unused harness model overrides, unsupported model or tool options, and invalid versions fail locally with validation exit code 7.

JSON mode cannot prompt and requires `--no-prompt`.

## Secrets

Pull discovers required MCP environment variables and headers from the Agent's components. Interactive mode prompts for missing values. Non-interactive mode uses matching `--env` and `--header` assignments and leaves unprovided values for the generated config's placeholder behavior.

Values are sent only in the installation request and generated config. They are not included in JSON results, success messages, traces, or error details.

Prefer environment expansion or secure shell input so secrets do not remain in shell history.

## File safety

Generated relative paths are confined to `--dir`. Home paths are allowed only for an explicit user-scope installation supported by that harness. Absolute paths, parent traversal, and symlink escapes are rejected before installation tracking is updated.

Pull behavior by file type:

* JSON MCP and hook sections merge into existing objects.
* YAML sections merge only when the existing top level and target section are mappings.
* TOML managed tables are replaced idempotently while unrelated tables remain.
* Generated text, prompt, Agent, and hook config files use atomic replacement.
* Malformed or structurally incompatible existing config is never overwritten. The command exits with conflict code 6 and leaves it untouched.

No `OTEL_*` or harness telemetry environment variables are generated. Session telemetry continues through Observal-managed hooks and reconciliation.

## Installation sequence

Pull performs these steps:

1. Validate harness, scope, model, tool, assignment, version, and output combinations.
2. Resolve the canonical Agent and load component requirements.
3. Check installed component version conflicts.
4. Request the harness-specific installation config.
5. Resolve and validate every generated path.
6. Write or preview files and install bundled skills.
7. Run required harness MCP registration commands.
8. Record Agent and component versions in the Registry-scoped lockfile.
9. Refresh the local layer snapshot and active-Agent state.

Failed skill installation or MCP setup prevents installation metadata from being recorded. A lockfile write failure is reported as exit code 9 instead of claiming success. A layer-snapshot failure is returned as a visible warning because the generated harness installation remains usable.

## JSON result

Successful JSON output has this shape:

```json
{
  "agent": {
    "id": "11111111-1111-1111-1111-111111111111",
    "qualified_name": "alice/reviewer",
    "version": "1.2.3",
    "local_name": "reviewer"
  },
  "harness": "kiro",
  "scope": "project",
  "dry_run": false,
  "target_directory": "/work/project",
  "files": [
    {
      "path": "/work/project/.kiro/agents/reviewer.json",
      "status": "created"
    }
  ],
  "warnings": [],
  "setup_commands": []
}
```

File statuses include `created`, `updated`, `merged`, `installed`, `cloned`, `would write`, and `would clone`.

Dry-run returns the same shape with `dry_run: true`, planned statuses, and `would_run` setup actions. It does not write files, execute setup commands, update the lockfile, persist an active Agent, or emit a pull audit event.

## Human output

Human mode lists every created, updated, merged, installed, cloned, or planned path. Component version conflicts, server warnings, snapshot warnings, and setup commands are printed explicitly.

## Exit codes

| Code | Meaning |
| --- | --- |
| 3 | Authentication required or failed |
| 4 | Agent or component access denied |
| 5 | Agent or component not found |
| 6 | Existing config cannot be merged safely |
| 7 | Invalid harness, scope, version, path, assignment, or option combination |
| 8 | Rate limit reached |
| 9 | Server, filesystem, skill source, lockfile, or setup command unavailable |
| 10 | CLI and server version mismatch |

## Related

* [`observal agent`](agent.md): create and publish Agents
* [`observal scan`](scan.md): inspect installed harness content
* [`observal outdated`](outdated.md): compare installed Agent versions
* [`observal doctor`](doctor.md): verify hooks and local installation state
