# Run a team-wide agent registry

Once two or more people are authoring agents, you need a single source of truth. Observal becomes your team's internal Docker Hub for AI agents — with review, RBAC, telemetry, and evaluation baked in.

## What changes at team scale

* **Discovery** — everyone sees the same list of agents, MCPs, skills, hooks, prompts, and sandboxes.
* **Review** — admins approve what appears in the public listing. Authors' own items are still immediately usable.
* **Governance** — RBAC roles (`super_admin`, `admin`, `reviewer`, `user`) control who can publish and approve.
* **Visibility** — centralized dashboards instead of "ask Sarah which version she's running."
* **Evaluation** — canonical scorecards per agent instead of N engineers evaluating in isolation.

## Setup shape

Deploy once, everyone points at it.

```
                        ┌──────────────────────┐
                        │  Observal server     │
                        │  (self-hosted)       │
                        │                      │
                        │   Postgres           │
                        │   ClickHouse         │
                        │   Redis              │
                        │   API + Web UI       │
                        └──────────┬───────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              │                    │                    │
         Engineer A           Engineer B           Engineer C
         Claude Code            Kiro                Cursor
```

Install the server once — [Self-Hosting](../self-hosting/README.md). Then every engineer installs the CLI and runs `observal auth login` pointed at your shared server URL.

## Users and roles

Four roles, RBAC-enforced on every endpoint.

| Role | Can | Cannot |
| --- | --- | --- |
| `user` | Publish components (subject to review), install agents, view their own traces | Approve submissions, see other users' private traces, change server settings |
| `reviewer` | Everything `user` can + approve/reject submissions | Change server settings, manage users |
| `admin` | Everything `reviewer` can + manage users, change server settings | Only restriction: certain super-admin operations |
| `super_admin` | Everything | — |

Manage users:

```bash
observal admin users
observal admin reset-password <email>          # interactive or --generate
observal admin delete-user <email>
```

Change a role via the web UI (`/settings/users`) or the API (`PUT /api/v1/admin/users/{id}/role`).

## Onboarding a new engineer

Two commands to get them productive:

```bash
# The new engineer runs:
uv tool install observal-cli
observal auth register --server https://observal.your-company.internal
```

Self-registration is enabled in `DEPLOYMENT_MODE=local`. For enterprise mode (SSO / SCIM), users provision via your IdP — see [Authentication and SSO](../self-hosting/authentication.md).

After registering, they can:

```bash
observal agent list                           # see every agent the team has published
observal pull team-reviewer --ide claude-code # install one
observal scan                                 # instrument everything they had already
```

## Review workflow

Authors submit. Reviewers approve. Approved items appear in the public listing.

```bash
observal admin review list                    # pending submissions
observal admin review show <id>
observal admin review approve <id>
observal admin review reject <id> --reason "missing env var docs"
```

What reviewers look for:

* Does the README/description make it clear what the component does?
* Does the MCP analysis (from `submit`) look correct — tools, env vars, transport?
* Are required env vars documented?
* Is the repo URL trustworthy (pinned commit or tag)?

Everything published is visible to the author immediately. Review controls what appears in the public listing.

## Telemetry across the whole team

Because every engineer's shim streams into the same server, `observal ops` becomes a team dashboard:

```bash
observal ops top --type agent           # most-used agents across the team
observal ops top --type mcp             # hottest MCP servers
observal ops overview                   # summary stats
```

Filters in the web UI let you slice by user, agent, IDE, and time range.

## Scorecards as team truth

When someone claims "v2 of the reviewer agent is better," you don't take their word for it:

```bash
observal admin eval compare team-reviewer --a 1.0.0 --b 2.0.0
```

If the comparison is favorable, publish v2. If not, v1 stays canonical. See [Evaluate and compare agents](evaluate-agents.md).

## Enterprise concerns

For orgs that need SSO, SCIM, and audit logging, enable enterprise mode:

```
DEPLOYMENT_MODE=enterprise
OAUTH_CLIENT_ID=...
OAUTH_CLIENT_SECRET=...
OAUTH_SERVER_METADATA_URL=...
```

See [Authentication and SSO](../self-hosting/authentication.md). The enterprise CLI adds SCIM-related commands (see `/ee/docs/cli.md` in the repo).

## Next

→ [Self-Hosting](../self-hosting/README.md) — the operator's playbook for actually running the server this use case depends on.
