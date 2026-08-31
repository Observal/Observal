<!-- SPDX-FileCopyrightText: 2026 Observal Contributors -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Core workflows

## Contents

- Authentication and account
- CLI configuration
- Local inventory and update checks
- Diagnosis and telemetry setup
- Inbox
- API escape hatch
- Error handling

## Authentication and account

Do not run an authentication probe before every command. Execute the requested read operation first. If authentication fails, inspect identity and then log in.

```bash
observal auth whoami --output json
observal auth login
observal auth login --sso --output json
observal auth logout --output json
observal auth status --output json
observal auth set-username new-handle --output json
```

For noninteractive password authentication, keep passwords out of arguments:

```bash
OBSERVAL_PASSWORD_FILE=/path/to/password observal auth login --server https://observal.example.com --email me@example.com --name 'Example User' --output json
OBSERVAL_CURRENT_PASSWORD_FILE=/path/to/current OBSERVAL_NEW_PASSWORD_FILE=/path/to/new observal auth change-password --output json
```

Fresh-server JSON bootstrap can require `--name`. SSO JSON emits an authorization event followed by an authenticated event. A username becomes the Registry namespace and can become immutable after ownership is established.

At every CLI startup, bundled Observal skill trees are hash-checked against the packaged copies. Drift causes complete replacement of only the six Observal-managed skill directories, including stale extra files.

## CLI configuration

```bash
observal config show --output json
observal config path --output json
observal config set server_url https://observal.example.com --output json
observal config set timeout 60 --output json
observal config aliases --output json
observal config alias MY_AGENT namespace/slug --output json
```

Only use keys accepted by `config set`. Authentication fields are managed by `auth`. Config output must not contain token values or fragments.

## Local inventory and update checks

`scan` is read-only and never writes harness files.

```bash
observal scan --output json
observal scan --harness kiro --output json
observal outdated --output json
observal outdated --harness claude-code --no-report --output json
```

For scan results, report detected harnesses, installed components, Agents, and unregistered items. For outdated results, inspect `items`, `summary`, and `report`. `--no-report` suppresses inbox reporting, not the Registry check.

## Diagnosis and telemetry setup

Diagnosis does not mutate unless the user explicitly requests a fix option.

```bash
observal doctor --output json
observal doctor patch --all-harnesses --dry-run --output json
observal doctor patch --all-harnesses --output json
observal doctor patch --harness kiro --output json
observal doctor cleanup --dry-run --output json
observal doctor cleanup --yes --output json
```

Patch requires at least one harness or `--all-harnesses`. Cleanup removes only Observal-managed artifacts. JSON cleanup requires confirmation. For Pi, patch installs the bundled extension directly.

Support bundles are sensitive diagnostic artifacts:

```bash
observal doctor support bundle --file /tmp/observal-support.tar.gz --output json
observal doctor support inspect /tmp/observal-support.tar.gz --output json
```

Verify `healthy`, `issues`, `warnings`, and per-harness results. Exit status zero means checks ran, not necessarily that every check is healthy.

## Inbox

```bash
observal inbox count --output json
observal inbox list --state open --action-required --output json
observal inbox show ITEM_UUID --output json
observal inbox read ITEM_UUID --output json
observal inbox done ITEM_UUID --output json
observal inbox dismiss ITEM_UUID --output json
observal inbox reopen ITEM_UUID --output json
observal inbox read-all --kind update_available --yes --output json
```

Use item UUIDs from JSON. Reading does not resolve an item. Confirm an `action_command` against the user's request before executing it. `read-all` affects every item matching its filters.

## API escape hatch

Use only when no dedicated command exists. It preserves raw endpoint JSON and uses configured authentication.

```bash
observal api GET /api/v1/teams --output json
observal api GET /api/v1/agents --param limit=10 --output json
observal api POST /api/v1/teams --from-file team.json --output json
```

Mutation bodies come from one JSON object in a file or standard input. Full URLs and arbitrary authorization headers are rejected. Prefer dedicated commands for validation and confirmations.

## Error handling

- Authentication: run `auth whoami`, then login only when needed.
- Permission: report the role or ownership requirement.
- Not found: re-list and use the returned UUID or canonical name.
- Conflict: inspect current state and server detail before choosing an action.
- Version mismatch: use `observal-advanced` for CLI version recovery.
- Unavailable or not configured: stop. Use explicit local fallback only if the user requests it after the failure.
