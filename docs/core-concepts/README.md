<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Core concepts

The vocabulary you need to be productive with Observal.

## The registry

The registry stores users, agents, components, review state, and alert rules in PostgreSQL. Session events and aggregates are stored separately in ClickHouse. See [Session tracking and reconciliation](session-tracking.md) for the complete session data flow.

## Registry components

Six component types are available. Agents bundle the other five.

| Type | What it is |
| --- | --- |
| **Agent** | A complete, installable AI agent. Bundles MCP servers, skills, hooks, prompts, and sandboxes into one YAML. |
| **MCP Server** | A [Model Context Protocol](https://modelcontextprotocol.io/) server, the tools an agent can call. |
| **Skill** | A portable instruction package agents load on demand. |
| **Hook** | A lifecycle callback that runs on session start, tool use, session end, and other supported events. |
| **Prompt** | A named, parameterized prompt template with variable substitution. |
| **Sandbox** | A Docker execution environment for running code the agent generates. |

Anyone can publish. Admin review controls what appears in the public listing, but your own items are usable immediately without approval.

## Canonical identity

An agent or component has a canonical `namespace/slug` identity. The namespace is the owner's username. The slug is stable within that namespace. Display names can change without changing the canonical identity.

UUIDs are the stable reconciliation key. The server supplies canonical namespace, slug, display name, qualified name, and review status. Installed versions in the local lockfile remain local pins.

## Deployment mode

SSO-only access is controlled by `deployment.sso_only`:

| Mode | Self-registration | Bootstrap | Auth |
| --- | --- | --- | --- |
| `deployment.sso_only=false` (default) | Yes | Yes, a fresh server creates an admin on first login | Email and password or API key |
| `deployment.sso_only=true` | No | No | SSO only |

Most self-hosters use `deployment.sso_only=false`.

## Next

* [Session tracking and reconciliation](session-tracking.md)
* [Use cases](../use-cases/README.md)
