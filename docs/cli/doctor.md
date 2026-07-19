<!-- SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 tsitu0 <tomsitu0102@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# observal doctor

Diagnose harness compatibility and session telemetry setup. Run this when session data is not appearing or a harness integration is unhealthy.

## Synopsis

```bash
observal doctor [--harness <harness>] [--fix]
```

## What it checks

- The harness is installed.
- Observal session hooks or extensions are present.
- The Observal server is configured and reachable.
- Local session delivery state is healthy.

MCP commands and remote URLs are not inspected or rewritten for telemetry.

## Examples

```bash
observal doctor
observal doctor --harness claude-code
observal doctor --harness kiro --fix
```

`--fix` applies supported hook repairs. Problems such as an unreachable server or a missing harness executable are reported with a remediation step.

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

The command is idempotent. Existing Observal hooks are retained, missing hooks are installed, and MCP configuration is left untouched. Restart the harness after applying hook changes.

## Related

- [`observal scan`](scan.md): read-only local inventory
- [`observal agent pull`](pull.md): install a complete agent
- [Telemetry pipeline](../self-hosting/telemetry-pipeline.md): session ingestion architecture
