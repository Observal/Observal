# Observal CLI Reference

Complete command reference for the Observal CLI. All commands use the `observal` prefix.

> **Maintaining this doc:** When adding or modifying CLI commands, update the corresponding section below. Keep options tables, examples, and descriptions in sync with the actual Typer definitions in `observal_cli/`.

---

## Command Structure

```
observal
├── auth          Authentication and account management
├── registry      Component registry (mcp, skill, hook, prompt, sandbox)
├── agent         Agent authoring and management
├── ops           Observability and operational commands
├── admin         Admin commands (settings, users, review, eval, canaries)
├── config        CLI configuration
├── self          CLI self-management (upgrade, downgrade)
├── doctor        IDE diagnostics
├── pull          Install an agent (shorthand)
├── scan          Detect and instrument existing IDE configs
├── uninstall     Remove an installed agent
└── use/profile   Switch between server profiles
```

## Global Options

| Option | Short | Description |
|--------|-------|-------------|
| `--version` | `-V` | Show CLI version and exit |
| `--verbose` | `-v` | Verbose output |
| `--debug` | | Debug logging |
| `--help` | | Show help for any command |

---

## Authentication (`observal auth`)

| Command | Description |
|---------|-------------|
| `auth login` | Log in to an Observal server (auto-creates admin on fresh server) |
| `auth register` | Create a new account with email + password |
| `auth logout` | Clear saved credentials |
| `auth whoami` | Show current authenticated user |
| `auth status` | Check server connectivity, health, and local telemetry buffer |

### `observal auth login`

```bash
observal auth login [--server URL] [--key KEY] [--email EMAIL] [--password PASSWORD] [--name NAME]
```

On a fresh server, detects no users exist and bootstraps an admin account with email + password prompts. On an existing server, choose between email+password or API key login interactively, or pass flags directly.

### `observal auth register`

```bash
observal auth register [--server URL] [--email EMAIL] [--password PASSWORD] [--name NAME]
```

Self-registration for new users. Creates an account and logs in. Only available in local deployment mode.

---

## Configuration (`observal config`)

| Command | Description |
|---------|-------------|
| `config show` | Show current config (API key masked) |
| `config set <key> <value>` | Set a config key |
| `config path` | Show config file path |
| `config alias <name> <id>` | Create a shorthand @alias for a listing ID |
| `config aliases` | List all aliases |

Config is stored in `~/.observal/config.json`. Aliases are in `~/.observal/aliases.json`.

### `observal config alias`

```bash
observal config alias my-mcp 498c17ac-...
observal registry mcp show @my-mcp      # use the alias anywhere
```

---

## Registry (`observal registry`)

The registry manages five component types, each with the same command structure.

### MCP Servers (`observal registry mcp`)

#### `observal registry mcp submit`

Submit an MCP server for review. The CLI clones the repo locally using your git credentials, analyzes it for MCP tools and environment variables via AST parsing, then sends the analysis to the server.

```bash
observal registry mcp submit <git_url> [OPTIONS]
```

| Option | Short | Description |
|--------|-------|-------------|
| `--name` | `-n` | Pre-fill server name (skip prompt) |
| `--category` | `-c` | Pre-fill category (skip prompt) |
| `--yes` | `-y` | Accept all defaults from repo analysis |

**What happens:**

1. Clones the repo locally (shallow clone) and analyzes it:
   - Detects MCP framework (FastMCP, MCP SDK, TypeScript SDK, Go SDK)
   - Extracts server name, description, and tools via AST parsing
   - Scans for required environment variables (`os.environ`, `os.getenv`, `.env.example`, Dockerfile `ENV`/`ARG`)
2. Shows analysis results (name, tools, env vars, warnings)
3. Prompts for metadata (name, description, owner, category, IDEs, setup instructions)
4. Shows detected env vars and lets you confirm, reject, or add extras
5. Submits with `client_analysis` attached — server stores validation results directly without re-cloning

If local analysis fails (e.g. git not available), falls back to server-side analysis.

```bash
# Interactive
observal registry mcp submit https://github.com/MarkusPfundstein/mcp-obsidian

# Non-interactive
observal registry mcp submit https://github.com/sooperset/mcp-atlassian -y
```

#### `observal registry mcp list`

```bash
observal registry mcp list [--category CAT] [--search TERM] [--limit N] [--sort name|category|version] [--output table|json|plain]
```

#### `observal registry mcp show`

```bash
observal registry mcp show <id-or-name> [--output table|json]
```

`id-or-name` accepts a UUID, server name, row number from last `list`, or `@alias`.

#### `observal registry mcp install`

Generate an IDE config snippet. Prompts for required environment variable values.

```bash
observal registry mcp install <id-or-name> --ide <ide> [--raw]
```

Supported IDEs: `cursor`, `kiro`, `claude-code`, `gemini-cli`, `vscode`, `codex`, `copilot`

Use `--raw` to output JSON only (for piping to a file).

#### `observal registry mcp delete`

```bash
observal registry mcp delete <id-or-name> [--yes]
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
| `prompt render <id> --var key=value` | Render a prompt with variables |
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
| `agent init` | Scaffold `observal-agent.yaml` in current directory |
| `agent add <type> <id>` | Add a component to an agent |
| `agent build` | Validate an agent against the server (dry-run) |
| `agent publish` | Submit an agent to the registry |

---

## Workflows (root level)

### `observal pull`

Install an agent into an IDE with all its dependencies.

```bash
observal pull <agent_id> --ide <ide>
```

### `observal scan`

Scan and wrap existing MCP servers in an IDE for telemetry.

```bash
observal scan [--ide <ide>]
```

Detects MCP servers from IDE config files, registers them with Observal, and wraps them with `observal-shim` for telemetry. Creates a timestamped backup automatically.

### `observal uninstall`

Remove an installed agent from an IDE.

```bash
observal uninstall <agent_id> --ide <ide>
```

### `observal use`

Switch IDE configs to a git-hosted or local profile.

```bash
observal use <git-url|path>
```

### `observal profile`

Show active profile and backup info.

```bash
observal profile
```

---

## Operations (`observal ops`)

| Command | Description |
|---------|-------------|
| `ops overview` | Dashboard summary stats |
| `ops metrics <id> [--type mcp\|agent] [--watch]` | Metrics for an MCP server or agent |
| `ops top [--type mcp\|agent]` | Top items by usage |
| `ops traces [--type TYPE] [--mcp ID] [--agent ID]` | List recent traces |
| `ops spans <trace-id>` | List spans for a trace |
| `ops rate <id> --stars N [--type mcp\|agent]` | Rate an item (1-5 stars) |
| `ops feedback <id> [--type mcp\|agent]` | Show feedback for an item |
| `ops sync` | Flush locally buffered telemetry events to server |
| `ops telemetry status` | Telemetry pipeline status + local buffer stats |
| `ops telemetry test` | Send a test telemetry event |

### `observal ops sync`

When the server is unreachable, hook events are stored in a local SQLite buffer (`~/.observal/telemetry_buffer.db`). This command sends pending events in batches.

---

## Admin (`observal admin`)

Requires admin role.

### Settings and Users

| Command | Description |
|---------|-------------|
| `admin settings` | View server settings |
| `admin set <key> <value>` | Update a server setting |
| `admin users` | List all users |
| `admin reset-password <email>` | Reset a user's password (interactive or `--generate`) |
| `admin delete-user <email>` | Permanently delete a user account |

### Review Workflow

| Command | Description |
|---------|-------------|
| `admin review list` | List pending submissions |
| `admin review show <id>` | Show submission details |
| `admin review approve <id>` | Approve a submission |
| `admin review reject <id> --reason "..."` | Reject a submission |

### Evaluation Engine

| Command | Description |
|---------|-------------|
| `admin eval run <agent-id> [--trace ID]` | Run evaluation on agent traces |
| `admin eval scorecards <agent-id> [--version V]` | List scorecards |
| `admin eval show <scorecard-id>` | Show scorecard with dimension breakdown |
| `admin eval compare <agent-id> --a V1 --b V2` | Compare two versions |
| `admin eval aggregate <agent-id> [--window N]` | Aggregate scoring stats with drift detection |

### Penalty and Weight Tuning

| Command | Description |
|---------|-------------|
| `admin penalties` | View scoring penalty catalog |
| `admin penalty-set <name> [--amount N] [--active]` | Modify a penalty definition |
| `admin weights` | View global dimension weights |
| `admin weight-set <dimension> <weight>` | Set a dimension weight (0.0-1.0) |

### Canary Injection (Eval Integrity)

| Command | Description |
|---------|-------------|
| `admin canaries <agent-id>` | List canary configs for an agent |
| `admin canary-add <agent-id> [--type TYPE] [--point POINT]` | Add a canary config |
| `admin canary-reports <agent-id>` | Show canary detection reports |
| `admin canary-delete <canary-id>` | Delete a canary config |

Canary types: `numeric`, `entity`, `instruction`. Injection points: `tool_output`, `context`.

---

## Self-Management (`observal self`)

| Command | Description |
|---------|-------------|
| `self upgrade` | Upgrade the CLI to the latest version |
| `self downgrade` | Downgrade the CLI (WIP) |

---

## Doctor (`observal doctor`)

```bash
observal doctor [--ide <ide>] [--fix]
```

Diagnose IDE settings compatibility. Use `--fix` to auto-repair common issues.

---

## Server Environment Variables

For self-hosted Observal deployments, these affect server-side behavior for git operations:

| Variable | Description | Default |
|----------|-------------|---------|
| `ALLOW_INTERNAL_URLS` | Allow internal/private Git URLs (for corporate GitLab/GHE) | `false` |
| `GIT_CLONE_TOKEN` | Auth token for cloning private repos | (none) |
| `GIT_CLONE_TOKEN_USER` | Token username: `x-access-token` (GitHub), `oauth2` or `private-token` (GitLab) | `x-access-token` |
| `GIT_CLONE_TIMEOUT` | Clone timeout in seconds | `120` |
