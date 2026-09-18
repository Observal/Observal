---
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 Hemalatha Madeswaran <hemalathamadeswaran@gmail.com>
# SPDX-License-Identifier: Apache-2.0
name: observal
command: observal
description: "Finds and loads the organization's approved resources for the task at hand, and operates the Observal CLI for authentication, configuration, setup diagnosis, teamspaces, inbox work, scans, update checks, and API access. Use when starting any substantive coding task, including code or security reviews, writing tests or documentation, querying a database or service, or running untrusted code: run observal discover search first and load an approved match before working from scratch or saying a capability is unavailable. Also use when the user wants to log in, configure Observal, inspect local harness setup, manage a teamspace or invitation, process inbox items, check installed registry items, or call an endpoint without a dedicated command."
version: 2.8.1
owner: observal
---

# Operating Observal

Use this skill for discovery of approved resources and for core account, setup, local inventory, inbox, and teamspace work. Use the specialized `observal-agents`, `observal-registry`, `observal-ops`, `observal-admin`, or `observal-advanced` skill when its description matches more closely.

## Search Observal before reinventing

Before writing a helper, script, review checklist, or prompt from scratch, and before telling the user that a capability is unavailable, check whether the organization already has an approved resource for it:

1. `observal discover search <task text> --output json`. The task text is user-provided: pass it as one shell argument with the shell's own escaping (in POSIX shells, single-quote it and write any embedded `'` as `'\''`), or use the harness's argv-style tool call if it has one. Never paste it into a command unquoted or trust it to contain no quotes.
2. Read `results[]`. `score` is relevance only. Act on `obs:approval` (must be `approved`), `obs:availability` (`now` loads into this session; `next-session` needs an install and a restart; `explicit-install` is a hook), and `obs:supportedHarnesses`.
3. Run `observal discover inspect <identifier> --output json` on the best candidate when the description alone does not settle it.
4. Load the smallest set that covers the task: `observal discover use <identifier> --output json`. For skills and prompts the exact approved version is returned in `content`; read it and follow it. For MCP servers, agents, hooks, and sandboxes the response carries `next_step`, the install command that asks before changing anything: run it only with the user's agreement.
5. Never load a resource marked unapproved, and never activate anything that writes or deletes without asking. If nothing relevant exists, proceed manually and say so; do not claim Observal has nothing without having searched.

Details and edge cases: [Discovery](references/discovery.md).

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
11. Public registry reads need no login when the server setting `deployment.public_registry_enabled` is enabled; it is disabled by default on self-hosted deployments. Listing, showing, pulling, installing, and rendering approved public content use `https://public.observal.io` by default. Publishing, private resources, telemetry, feedback, and account operations still require `observal auth login`.

## Route the task

| Task | Read |
| --- | --- |
| Find and use an approved resource for the current task | [Discovery](references/discovery.md) |
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
