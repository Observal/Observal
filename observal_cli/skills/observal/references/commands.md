<!-- SPDX-FileCopyrightText: 2026 Hemalatha Madeswaran <hemalathamadeswaran@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# Observal CLI Command Reference

Auto-generated from the Typer app by `scripts/sync_observal_skill.py`. Do not edit manually.

<!-- BEGIN AUTO-GENERATED COMMAND REFERENCE -->
Every command available in the installed CLI. This block is generated from the Typer app by `scripts/sync_observal_skill.py`. If a flag you need is missing here, run `<command> --help` for full options.

**Root commands**

- `observal outdated`: Show installed components that have newer versions available.
- `observal scan`: Show a read-only inventory of your local harness setup.

**`observal admin`**: Admin commands

- `observal admin review`: Admin review commands
  - `observal admin review approve`: Approve a submission (component, agent, or bundle).
  - `observal admin review list`: List pending submissions awaiting admin review.
  - `observal admin review reject`: Reject a submission (component, agent, or bundle).
  - `observal admin review show`: Show review details for a component or agent.
  - `observal admin audit-log`: Query the audit log. (Enterprise only)
  - `observal admin audit-log-export`: Export audit log as CSV. (Enterprise only)
  - `observal admin cache-clear`: Clear all server caches.
  - `observal admin create-user`: Create a new user account. Requires admin privileges.
  - `observal admin delete-user`: Delete a user account. Requires admin privileges.
  - `observal admin diagnostics`: Show system diagnostics and health status.
  - `observal admin reset-password`: Reset a user's password. Requires admin privileges.
  - `observal admin saml-config`: View current SAML SSO configuration. (Enterprise only)
  - `observal admin saml-config-delete`: Delete SAML SSO configuration. Disables SAML SSO. (Enterprise only)
  - `observal admin saml-config-set`: Create or update SAML SSO configuration.
  - `observal admin scim-token-create`: Create a new SCIM provisioning token.
  - `observal admin scim-token-revoke`: Revoke a SCIM provisioning token. (Enterprise only)
  - `observal admin scim-tokens`: List SCIM provisioning tokens. (Enterprise only)
  - `observal admin security-events`: View security events log.
  - `observal admin set`: Set an enterprise setting.
  - `observal admin set-role`: Change a user's role.
  - `observal admin settings`: List enterprise settings.
  - `observal admin trace-privacy`: View trace privacy setting.
  - `observal admin trace-privacy-set`: Enable or disable trace privacy (redacts sensitive trace data).
  - `observal admin users`: List all users.

**`observal agent`**: Agent registry commands

- `observal agent co-authors`: Manage co-authors for agents
  - `observal agent co-authors add`: Add a co-author.
  - `observal agent co-authors list`: List co-authors.
  - `observal agent co-authors remove`: Remove a co-author.
  - `observal agent add`: Add a component reference to observal-agent.yaml.
  - `observal agent archive`: Archive an agent.
  - `observal agent build`: Validate agent definition against the server (dry-run).
  - `observal agent bulk-create`: Bulk-create agents from a JSON file.
  - `observal agent create`: Create a new agent (interactive wizard, from file, or via flags).
  - `observal agent delete`: Archive an agent. Prefer the archive command.
  - `observal agent init`: Scaffold an observal-agent.yaml definition file.
  - `observal agent install`: Get install config for an agent.
  - `observal agent list`: List active agents (paginated).
  - `observal agent my`: List your own agents (all statuses).
  - `observal agent publish`: Publish the agent definition to the server.
  - `observal agent pull`: Fetch agent config and write harness files to disk.
  - `observal agent release`: Bump version and push a versioned release to the registry.
  - `observal agent show`: Show full agent details.
  - `observal agent transfer-owner`: Transfer ownership to another username.
  - `observal agent unarchive`: Restore an archived agent back to active status.
  - `observal agent versions`: List all versions for an agent.

**`observal auth`**: Authentication and account commands

  - `observal auth login`: Connect to Observal.
  - `observal auth logout`: Clear saved credentials.
  - `observal auth whoami`: Show current authenticated user.
  - `observal auth status`: Check server connectivity and health.
  - `observal auth change-password`: Change your password.
  - `observal auth set-username`: Set or update your username.

**`observal config`**: CLI configuration

  - `observal config alias`: Set or remove an alias for an MCP/agent ID.
  - `observal config aliases`: List all aliases.
  - `observal config path`: Show config file path.
  - `observal config set`: Set a CLI config value.
  - `observal config show`: Show current CLI configuration.

**`observal doctor`**: Diagnose and patch harness settings for Observal telemetry

- `observal doctor support`: Generate and inspect diagnostic support bundles. Bundles contain no customer data or row contents.
  - `observal doctor support bundle`: Generate a diagnostic support bundle. No customer data or row contents included.
  - `observal doctor support inspect`: Inspect a support bundle.
  - `observal doctor cleanup`: Remove ALL Observal hooks, env vars, and legacy telemetry config.
  - `observal doctor patch`: Instrument harnesses with Observal telemetry hooks and shims.

**`observal ops`**: Observability and operational commands (traces, telemetry, dashboard, feedback)

- `observal ops insights`: Agent insight reports
  - `observal ops insights generate`: Trigger generation of a new insight report.
  - `observal ops insights list`: List insight reports for an agent.
  - `observal ops insights show`: Show an insight report with pretty-printed narrative.
- `observal ops logs`: Live log viewer (open in a separate tab)
- `observal ops telemetry`: Telemetry commands
  - `observal ops telemetry status`: Check telemetry data flow status.
  - `observal ops telemetry test`: Send a test telemetry event.
  - `observal ops feedback`: Show feedback for an MCP server or agent.
  - `observal ops metrics`: Show metrics for an MCP server or agent.
  - `observal ops rate`: Rate an MCP server, agent, or component.
  - `observal ops rate-delete`: Delete your review for an item.
  - `observal ops rate-update`: Update your existing review for an item.
  - `observal ops spans`: List spans for a trace.
  - `observal ops top`: Show top MCP servers or agents by usage.
  - `observal ops traces`: List recent traces (sessions).

**`observal reconcile`**: Push local session transcripts to the server

- (no subcommands)

**`observal registry`**: Component registry (MCPs, skills, hooks, prompts, sandboxes)

- `observal registry hook`: Hook registry commands
- `observal registry hook co-authors`: Manage co-authors for hooks
  - `observal registry hook co-authors add`: Add a co-author.
  - `observal registry hook co-authors list`: List co-authors.
  - `observal registry hook co-authors remove`: Remove a co-author.
  - `observal registry hook archive`: Archive this component.
  - `observal registry hook edit`: Edit a draft, rejected, or pending hook submission.
  - `observal registry hook install`: Install a hook for a specific harness.
  - `observal registry hook list`: List approved hooks from the registry.
  - `observal registry hook show`: Show detailed information for a single hook.
  - `observal registry hook submit`: Submit a new hook for review.
  - `observal registry hook transfer-owner`: Transfer ownership to another username.
  - `observal registry hook unarchive`: Restore an archived component.
- `observal registry mcp`: MCP server registry commands
- `observal registry mcp co-authors`: Manage co-authors for mcps
  - `observal registry mcp co-authors add`: Add a co-author.
  - `observal registry mcp co-authors list`: List co-authors.
  - `observal registry mcp co-authors remove`: Remove a co-author.
  - `observal registry mcp submit`: Submit an MCP server to the registry.
  - `observal registry mcp show`: Show full details of an MCP server.
  - `observal registry mcp install`: Generate an install config snippet for an MCP server.
  - `observal registry mcp archive`: Archive this component.
  - `observal registry mcp edit`: Edit an MCP server submission.
  - `observal registry mcp list`: List approved MCP servers in the registry.
  - `observal registry mcp my`: List your own MCP servers across all statuses.
  - `observal registry mcp transfer-owner`: Transfer ownership to another username.
  - `observal registry mcp unarchive`: Restore an archived component.
- `observal registry models`: Inspect registry-backed harness model data.
  - `observal registry models list`
- `observal registry prompt`: Prompt registry commands
- `observal registry prompt co-authors`: Manage co-authors for prompts
  - `observal registry prompt co-authors add`: Add a co-author.
  - `observal registry prompt co-authors list`: List co-authors.
  - `observal registry prompt co-authors remove`: Remove a co-author.
  - `observal registry prompt archive`: Archive this component.
  - `observal registry prompt edit`: Edit a draft, rejected, or pending prompt submission.
  - `observal registry prompt list`: List approved prompts in the registry.
  - `observal registry prompt my`: List your own prompts across all statuses.
  - `observal registry prompt render`: Render a prompt template with variable substitution.
  - `observal registry prompt show`: Show detailed information about a prompt.
  - `observal registry prompt submit`: Submit a new prompt template for review.
  - `observal registry prompt transfer-owner`: Transfer ownership to another username.
  - `observal registry prompt unarchive`: Restore an archived component.
- `observal registry sandbox`: Sandbox registry commands
- `observal registry sandbox co-authors`: Manage co-authors for sandboxes
  - `observal registry sandbox co-authors add`: Add a co-author.
  - `observal registry sandbox co-authors list`: List co-authors.
  - `observal registry sandbox co-authors remove`: Remove a co-author.
  - `observal registry sandbox archive`: Archive this component.
  - `observal registry sandbox edit`: Edit a draft, rejected, or pending sandbox submission.
  - `observal registry sandbox list`: List approved sandboxes in the registry.
  - `observal registry sandbox show`: Show detailed information about a sandbox.
  - `observal registry sandbox submit`: Submit a new sandbox environment for review.
  - `observal registry sandbox transfer-owner`: Transfer ownership to another username.
  - `observal registry sandbox unarchive`: Restore an archived component.
- `observal registry skill`: Skill registry commands
- `observal registry skill co-authors`: Manage co-authors for skills
  - `observal registry skill co-authors add`: Add a co-author.
  - `observal registry skill co-authors list`: List co-authors.
  - `observal registry skill co-authors remove`: Remove a co-author.
  - `observal registry skill archive`: Archive this component.
  - `observal registry skill edit`: Edit a draft, rejected, or pending skill submission.
  - `observal registry skill install`: Install a skill by fetching the full skill directory from git.
  - `observal registry skill list`: List approved skills in the registry.
  - `observal registry skill my`: List your own skills across all statuses.
  - `observal registry skill show`: Show detailed information about a skill.
  - `observal registry skill submit`: Submit a new skill for review.
  - `observal registry skill transfer-owner`: Transfer ownership to another username.
  - `observal registry skill unarchive`: Restore an archived component.
- `observal registry version`: Manage component versions
  - `observal registry version list`: List version history for a registry component.
  - `observal registry version publish`: Publish a new version for a registry component.

**`observal self`**: CLI self-management commands (upgrade, downgrade, rollback, status)

  - `observal self upgrade`: Upgrade the observal CLI to the latest (or specified) version.
  - `observal self downgrade`: Downgrade the observal CLI to a previous version.
  - `observal self rollback`: Restore the CLI to the version before the last upgrade/downgrade.
  - `observal self status`: Show current CLI version, install method, and update availability.
  - `observal self uninstall`: Completely uninstall Observal: stop containers, remove volumes, delete repo and config.
<!-- END AUTO-GENERATED COMMAND REFERENCE -->
