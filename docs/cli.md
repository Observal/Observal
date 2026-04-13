# Observal CLI Reference

Complete command reference for the Observal CLI. All commands use the `observal` prefix.

> **Maintaining this doc:** When adding or modifying CLI commands, update the corresponding section below. Keep options tables, examples, and descriptions in sync with the actual Typer definitions in `observal_cli/`.

---

## Global Options

| Option | Short | Description |
|--------|-------|-------------|
| `--version` | `-V` | Show CLI version and exit |
| `--help` | | Show help for any command |

---

## Authentication (`observal auth`)

| Command | Description |
|---------|-------------|
| `auth init` | First-time setup: create admin account and configure server |
| `auth login` | Log in to an Observal server |
| `auth signup` | Create a new account |
| `auth reset-password` | Reset your password |
| `auth logout` | Log out and clear local credentials |
| `auth whoami` | Show current authenticated user |
| `auth status` | Show server connection status |
| `auth version` | Show CLI and server versions |

### `observal auth login`

```bash
observal auth login [--server URL] [--email EMAIL] [--password PASSWORD]
```

### `observal auth init`

```bash
observal auth init [--server URL]
```

First-time server setup. Creates the admin user and configures the CLI to talk to the server.

---

## Configuration (`observal config`)

| Command | Description |
|---------|-------------|
| `config show` | Show current config |
| `config set` | Set a config key |
| `config path` | Show config file path |
| `config alias` | Create a shorthand alias for a listing ID |
| `config aliases` | List all aliases |

### `observal config set`

```bash
observal config set <key> <value>
```

### `observal config alias`

```bash
observal config alias <name> <listing_id>
```

---

## Registry (`observal registry`)

The registry contains five component types, each with the same command structure.

### MCP Servers (`observal registry mcp`)

#### `observal registry mcp submit`

Submit an MCP server for review. Clones the repo, analyzes for tools and required environment variables, then prompts for metadata.

```bash
observal registry mcp submit <git_url> [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--name` | `-n` | Pre-fill server name (skip prompt) |
| `--category` | `-c` | Pre-fill category (skip prompt) |
| `--yes` | `-y` | Accept all defaults from repo analysis |

**What happens:**

1. Clones the repo and analyzes it:
   - Detects MCP framework (FastMCP, MCP SDK, TypeScript SDK, Go SDK)
   - Extracts server name, description, and tools via AST
   - Scans for required environment variables (`os.environ`, `os.getenv`, `.env.example`, Dockerfile `ENV`/`ARG`)
2. Shows analysis results (name, tools, env vars, warnings)
3. Prompts for metadata (name, description, owner, category, IDEs, setup instructions)
4. Shows detected env vars and lets you confirm, reject, or add extras
5. Submits with status `pending`. Validation runs as a background task.

```bash
# Interactive
observal registry mcp submit https://github.com/MarkusPfundstein/mcp-obsidian

# Non-interactive
observal registry mcp submit https://github.com/sooperset/mcp-atlassian -y

# Pre-fill name and category
observal registry mcp submit https://github.com/example/server -n my-server -c productivity
```

#### `observal registry mcp list`

List approved MCP servers.

```bash
observal registry mcp list [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--category` | `-c` | Filter by category |
| `--search` | `-s` | Search by name or description |
| `--limit` | `-n` | Max results (default: 50) |
| `--sort` | | Sort by: `name`, `category`, `version` |
| `--output` | `-o` | Output format: `table`, `json`, `plain` |

```bash
observal registry mcp list
observal registry mcp list -c productivity
observal registry mcp list -s "jira" -o json
```

#### `observal registry mcp show`

Show full details of an MCP server including validation results.

```bash
observal registry mcp show <mcp_id> [OPTIONS]
```

`mcp_id` can be a UUID, server name, row number from the last `list`, or `@alias`.

| Option | Short | Description |
|--------|-------|-------------|
| `--output` | `-o` | Output format: `table`, `json` |

```bash
observal registry mcp show mcp-obsidian
observal registry mcp show 498c17ac
observal registry mcp show mcp-obsidian -o json
```

#### `observal registry mcp install`

Generate an IDE config snippet for an MCP server. Prompts for required environment variable values.

```bash
observal registry mcp install <mcp_id> --ide <ide> [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--ide` | `-i` | **Required.** Target IDE |
| `--raw` | | Output raw JSON only (for piping to a file) |

Supported IDEs: `cursor`, `kiro`, `claude-code`, `gemini-cli`, `vscode`, `codex`, `copilot`

**What happens:**

1. Fetches the server listing and its declared environment variables
2. Prompts for each required env var value (e.g. `JIRA_URL`, `JIRA_API_TOKEN`)
3. Prompts for optional env vars (Enter to skip)
4. Generates IDE-specific config with env values merged into the `env` block
5. Warns about any env vars still missing values

```bash
# Interactive
observal registry mcp install mcp-atlassian --ide cursor

# Raw JSON for piping
observal registry mcp install mcp-atlassian --ide cursor --raw > .cursor/mcp.json

# Claude Code
observal registry mcp install mcp-obsidian --ide claude-code
```

#### `observal registry mcp delete`

Delete an MCP server listing you own.

```bash
observal registry mcp delete <mcp_id> [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--yes` | `-y` | Skip confirmation prompt |

```bash
observal registry mcp delete mcp-obsidian
observal registry mcp delete mcp-obsidian -y
```

### Skills (`observal registry skill`)

| Command | Description |
|---------|-------------|
| `skill submit` | Submit a skill for review |
| `skill list` | List approved skills |
| `skill show <id>` | Show skill details |
| `skill install <id> --ide <ide>` | Generate install config |
| `skill delete <id>` | Delete a skill |

### Hooks (`observal registry hook`)

| Command | Description |
|---------|-------------|
| `hook submit` | Submit a hook for review |
| `hook list` | List approved hooks |
| `hook show <id>` | Show hook details |
| `hook install <id> --ide <ide>` | Generate install config |
| `hook delete <id>` | Delete a hook |

### Prompts (`observal registry prompt`)

| Command | Description |
|---------|-------------|
| `prompt submit` | Submit a prompt template for review |
| `prompt list` | List approved prompts |
| `prompt show <id>` | Show prompt details |
| `prompt render <id>` | Render a prompt with variables |
| `prompt install <id>` | Generate install config |
| `prompt delete <id>` | Delete a prompt |

### Sandboxes (`observal registry sandbox`)

| Command | Description |
|---------|-------------|
| `sandbox submit` | Submit a sandbox for review |
| `sandbox list` | List approved sandboxes |
| `sandbox show <id>` | Show sandbox details |
| `sandbox install <id> --ide <ide>` | Generate install config |
| `sandbox delete <id>` | Delete a sandbox |

---

## Agents (`observal agent`)

| Command | Description |
|---------|-------------|
| `agent create` | Create a new agent from registry components |
| `agent list` | List your agents |
| `agent show <id>` | Show agent details and components |
| `agent install <id> --ide <ide>` | Install an agent into an IDE |
| `agent delete <id>` | Delete an agent |
| `agent init` | Initialize an agent project in current directory |
| `agent add` | Add a component to an agent |
| `agent build` | Build and validate an agent |
| `agent publish` | Publish an agent to the registry |

### `observal agent install`

```bash
observal agent install <agent_id> --ide <ide>
```

### `observal agent create`

```bash
observal agent create [--name NAME] [--description DESC]
```

---

## Workflows (root level)

### `observal pull`

Install an agent into an IDE. Shorthand for `agent install`.

```bash
observal pull <agent_id> --ide <ide>
```

### `observal scan`

Scan and wrap existing MCP servers in an IDE for telemetry.

```bash
observal scan --ide <ide>
```

### `observal uninstall`

Remove an installed agent from an IDE.

```bash
observal uninstall <agent_id> --ide <ide>
```

### `observal use`

Switch between Observal profiles (server/account pairs).

```bash
observal use [profile_name]
```

### `observal profile`

Manage profiles.

```bash
observal profile
```

---

## Operations (`observal ops`)

| Command | Description |
|---------|-------------|
| `ops overview` | Dashboard summary |
| `ops metrics` | Telemetry metrics |
| `ops top` | Top agents/servers by usage |
| `ops rate` | Rate limiting status |
| `ops feedback` | User feedback |
| `ops traces` | View OpenTelemetry traces |
| `ops spans` | View individual spans |
| `ops sync` | Sync component sources |
| `ops telemetry status` | Telemetry pipeline status |
| `ops telemetry test` | Send a test telemetry event |

---

## Admin (`observal admin`)

Requires admin role.

| Command | Description |
|---------|-------------|
| `admin settings` | View server settings |
| `admin set <key> <value>` | Update a server setting |
| `admin users` | List users |
| `admin invite` | Create an invite link |
| `admin invites` | List pending invites |
| `admin penalties` | View scoring penalties |
| `admin penalty-set` | Set a scoring penalty |
| `admin weights` | View scoring weights |
| `admin weight-set` | Set a scoring weight |
| `admin canaries` | List canary configs |
| `admin canary-add` | Add a canary config |
| `admin canary-reports` | View canary reports |
| `admin canary-delete` | Delete a canary config |
| `admin review list` | List pending submissions |
| `admin review show <id>` | Show submission details |
| `admin review approve <id>` | Approve a submission |
| `admin review reject <id>` | Reject a submission |
| `admin eval run` | Run an evaluation |
| `admin eval scorecards` | View eval scorecards |
| `admin eval show <id>` | Show eval run details |
| `admin eval compare` | Compare eval runs |
| `admin eval aggregate` | Aggregate eval results |

---

## Self-Management (`observal self`)

| Command | Description |
|---------|-------------|
| `self upgrade` | Upgrade the CLI to the latest version |
| `self downgrade` | Downgrade the CLI |

---

## Doctor (`observal doctor`)

```bash
observal doctor --ide <ide>
```

Verify that your IDE integration is correctly configured.

---

## Server Environment Variables

For self-hosted Observal deployments:

| Variable | Description | Default |
|----------|-------------|---------|
| `ALLOW_INTERNAL_URLS` | Allow internal/private Git URLs (for corporate GitLab/GHE) | `false` |
| `GIT_CLONE_TOKEN` | Auth token for cloning private repos | (none) |
| `GIT_CLONE_TOKEN_USER` | Token username: `x-access-token` (GitHub), `oauth2` or `private-token` (GitLab) | `x-access-token` |
| `GIT_CLONE_TIMEOUT` | Clone timeout in seconds | `120` |

---

## Deprecated Commands

These still work but print a deprecation warning. Use the canonical versions.

| Deprecated | Use instead |
|------------|-------------|
| `observal submit` | `observal registry mcp submit` |
| `observal list` | `observal registry mcp list` |
| `observal show` | `observal registry mcp show` |
| `observal install` | `observal registry mcp install` |
| `observal delete` | `observal registry mcp delete` |
| `observal login` | `observal auth login` |
| `observal logout` | `observal auth logout` |
| `observal init` | `observal auth init` |
| `observal whoami` | `observal auth whoami` |
| `observal status` | `observal auth status` |
| `observal version` | `observal auth version` |
| `observal upgrade` | `observal self upgrade` |
| `observal downgrade` | `observal self downgrade` |
| `observal overview` | `observal ops overview` |
| `observal metrics` | `observal ops metrics` |
| `observal top` | `observal ops top` |
| `observal rate` | `observal ops rate` |
| `observal feedback` | `observal ops feedback` |
| `observal traces` | `observal ops traces` |
| `observal spans` | `observal ops spans` |
| `observal skill` | `observal registry skill` |
| `observal hook` | `observal registry hook` |
| `observal prompt` | `observal registry prompt` |
| `observal sandbox` | `observal registry sandbox` |
