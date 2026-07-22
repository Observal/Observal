<!-- SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 tsitu0 <tomsitu0102@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# observal doctor

Diagnose harness compatibility and session telemetry setup. Run this when session data is not appearing or a harness integration is unhealthy.

## Synopsis

```bash
observal doctor [--yes]
```

## What it checks

- The Observal server is configured and reachable.
- Every UUID in the active registry's lockfile section still resolves on the server.
- Canonical names, namespaces, slugs, and statuses match server metadata.
- Observal session hooks or extensions are present.
- UUID-attributed Kiro hooks match their locked agents.
- Local session delivery state is healthy.

MCP commands and remote URLs are not inspected or rewritten for telemetry.

## Examples

```bash
observal doctor
observal doctor --yes
```

Doctor asks before applying repairs. `--yes` confirms them non-interactively. Canonical registry metadata is updated from the server without changing installed version pins. Harness repairs only replace Observal-managed hooks and preserve user hooks.

The version 2 lockfile groups installations under normalized server URLs in a top-level `registries` object. Switching servers selects a separate registry section while preserving installations from other registries.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | All checks passed |
| 1 | At least one check failed |
| 3 | No harness configs found |

# observal doctor patch

Install session telemetry hooks for selected harnesses.

## Synopsis

```bash
observal doctor patch [--all-harnesses] [--harness <harness>] [--dry-run]
```

## Options

| Option | Description |
| --- | --- |
| `--all-harnesses` | Target every supported harness |
| `--harness <harness>` | Target a harness; repeat to select several |
| `--dry-run` / `-n` | Show hook changes without writing files |

You must choose `--all-harnesses` or at least one `--harness`.

## Examples

```bash
observal doctor patch --all-harnesses
observal doctor patch --harness claude-code
observal doctor patch --harness kiro --harness copilot-cli
observal doctor patch --all-harnesses --dry-run
```

The command is idempotent. Existing Observal hooks are retained, missing hooks are installed, stale Kiro UUID hooks are repaired, and MCP configuration is left untouched. For Pi, Doctor copies the bundled TypeScript extension directly to `~/.pi/agent/extensions/observal.ts` and removes the legacy npm package registration. Restart the harness after applying changes.

## Related

- [`observal scan`](scan.md): read-only local inventory
- [`observal agent pull`](pull.md): install a complete agent
- [Session tracking and reconciliation](../core-concepts/session-tracking.md): session ingestion architecture
