---
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 Hemalatha Madeswaran <hemalathamadeswaran@gmail.com>
# SPDX-License-Identifier: Apache-2.0
name: observal
command: observal
description: "Operates the Observal CLI for authentication, configuration, setup diagnosis, teamspaces, inbox work, scans, update checks, and authenticated API access. Use when the user wants to log in, configure Observal, inspect local harness setup, manage a teamspace or invitation, process inbox items, check installed registry items, or call an endpoint without a dedicated command."
version: 2.7.0
owner: observal
---

# Operating Observal

Use this skill for core account, setup, local inventory, inbox, and teamspace work. Use the specialized `observal-agents`, `observal-registry`, `observal-ops`, `observal-admin`, or `observal-advanced` skill when its description matches more closely.

## Execution contract

1. Execute commands in the shell. Do not merely print commands for the user to run.
2. Set a 60 second timeout for normal CLI calls. Increase it only for an operation documented as long-running.
3. **Use machine output by default:** add `--output json` whenever supported. Dedicated lists return `items`, `total`, `page`, and `page_size`; streams emit JSON Lines.
4. Run the relevant `--help` command before acting when a path or flag is uncertain. Never invent flags.
5. Supply every required input and confirmation flag so agent workflows never wait for a prompt.
6. Reuse returned UUIDs and `qualified_name` values. Never scrape table rows or assume a bare name is unique.
7. After a mutation, verify the returned state or run the smallest read command that confirms the requested change.
8. Treat tokens, invitation URLs, credentials, generated passwords, headers, and environment values as secrets. Do not echo them.
9. Fail openly. Do not silently switch to direct API calls, database access, or local file writes.
10. Automatic transient retries apply only to reads. After an uncertain mutation failure, verify state before retrying.

## Route the task

| Task | Read |
| --- | --- |
| Login, account, CLI config, scan, doctor, outdated, inbox | [Core workflows](references/core-workflows.md) |
| Teamspaces, visibility review, members, requests, invitations | [Teamspace workflows](references/teamspaces.md) |
| Exact command inventory or authenticated API escape hatch | [Generated command reference](references/commands.md) |
| Create, edit, release, or pull an Agent | Use `observal-agents` |
| Search, submit, install, or version a component | Use `observal-registry` |
| Traces, telemetry, logs, ratings, or insight reports | Use `observal-ops` |
| Reviews, users, settings, security, or server administration | Use `observal-admin` |
| Reconciliation, CLI version recovery, or explicit offline fallback | Use `observal-advanced` |

Read the selected reference completely before executing its workflow.

## Default loop

1. Identify the canonical command path from the reference or local help.
2. Read current state in JSON when the operation depends on existing IDs, roles, versions, or status.
3. Execute one noninteractive mutation with the canonical identifier.
4. Verify the result. A zero exit status alone does not prove the requested state transition occurred.
5. Report the outcome, important identifiers, warnings, and any required next action. Include the exact command only when useful for reproduction or requested by the user.

## Error decisions

| Result | Action |
| --- | --- |
| Authentication error | Run `observal auth whoami --output json`; log in only if needed |
| Permission denied | Report the required role or ownership; do not retry with broader authority |
| Not found | Re-list in JSON and retry with the returned UUID or `qualified_name` |
| Conflict | Read the server message and current state; choose update, version bump, or no-op deliberately |
| Validation error | Correct the named input; do not repeat the same request |
| Unavailable or not configured | Stop and use `observal-advanced` only if the user still wants an explicit fallback |

Do not report success when JSON contains a pending review, warning, failed setup command, or partial result that still requires action.
