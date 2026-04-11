<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/logo.svg">
  <source media="(prefers-color-scheme: light)" srcset="docs/logo-light.svg">
  <img alt="Observal" src="docs/logo-light.svg" width="320">
</picture>

### Discover, share, and monitor AI coding agents with full observability built in.

<p>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue?style=flat-square" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.11+-3776ab?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/status-alpha-orange?style=flat-square" alt="Status">
  <a href="https://github.com/BlazeUp-AI/Observal/stargazers"><img src="https://img.shields.io/github/stars/BlazeUp-AI/Observal?style=flat-square" alt="Stars"></a>
</p>

> If you find Observal useful, please consider giving it a star. It helps others discover the project and keeps development going.

---

Observal is a **self-hosted AI agent registry with built-in observability**. Think Docker Hub, but for AI coding agents.

Browse agents created by others, publish your own, and pull complete agent configurations, all defined in a portable YAML format that templates out to **Claude Code**, **Codex CLI**, **Gemini CLI**, and more. Every agent bundles its MCP servers, skills, hooks, prompts, and sandboxes into a single installable package. One command to install, zero manual config.

Every interaction generates traces, spans, and sessions that flow into a telemetry pipeline, giving you full observability, traceability, and real-time metrics for your agents in production. The built-in eval engine (WIP) scores agent sessions so you can measure performance and make your agents better over time.

**Supported tools:** Claude Code, Codex CLI, and Gemini CLI are fully supported. Kiro support is a work in progress.

## Quick Start

```bash
git clone https://github.com/BlazeUp-AI/Observal.git
cd Observal
cp .env.example .env          # edit with your values

cd docker && docker compose up --build -d && cd ..
uv tool install --editable .
observal auth init             # create admin account
```

Already have MCP servers in your IDE? Instrument them in one command:

```bash
observal scan                  # auto-detect, register, and instrument everything
observal pull <agent> --ide cursor  # install a complete agent
```

This detects MCP servers from your IDE config files, registers them with Observal, and wraps them with `observal-shim` for telemetry without breaking your existing setup. A timestamped backup is created automatically.

## The Problem

AI coding agents today are hard to share and impossible to measure. Components (MCP servers, skills, hooks, prompts) are scattered across repos with no standard way to package them together. There's no visibility into what's actually working, and no way to compare one version of an agent against another on real workflows.

Observal solves this by giving you a registry to package and distribute complete agents, and a telemetry pipeline to measure them.

## How It Works

Agents in the registry are defined in YAML. Each agent bundles its components (MCP servers, skills, hooks, prompts, sandboxes) into a single configuration. When you run `observal pull <agent>`, it installs everything and generates the right config files for your tool.

A transparent shim (`observal-shim` for stdio, `observal-proxy` for HTTP) sits between your tool and the MCP server. It never modifies traffic, it only observes. Every request/response pair becomes a span, spans group into traces, and traces form sessions. All of this streams into ClickHouse for analysis.

```
Tool  <-->  observal-shim  <-->  MCP Server / Sandbox
                |
                v (fire-and-forget)
          Observal API  -->  ClickHouse (traces, spans, scores)
                |
                v
          Eval Engine (LLM-as-judge)  -->  Scorecards
```

The eval engine runs on collected traces after the fact. It scores agent sessions across dimensions like tool selection quality, prompt effectiveness, and code correctness. Scorecards let you compare agent versions, identify bottlenecks, and track improvements over time.

## The Registry

Observal manages 6 component types that agents bundle together:

| Component | Description |
|-----------|-------------|
| **Agents** | Complete configurations that bundle all the components below |
| **MCP Servers** | Model Context Protocol servers that expose tools to agents |
| **Skills** | Portable instruction packages that agents load on demand |
| **Hooks** | Lifecycle callbacks that fire during agent sessions |
| **Prompts** | Managed templates with variable substitution |
| **Sandboxes** | Docker execution environments for code running and testing |

Anyone can publish components to the registry. Admin review controls visibility in the public listing, but your own items are usable immediately without approval. Browse the web UI or CLI to discover agents and components shared by others.

## CLI Reference

The CLI is organized into command groups. Run `observal --help` or `observal <group> --help` for full details.

### Primary Workflows

```bash
observal pull <agent> --ide <ide>    # install a complete agent with all dependencies
observal scan [--ide <ide>]          # detect and instrument existing IDE configs
observal use <git-url|path>          # swap IDE configs to a git-hosted profile
observal profile                     # show active profile and backup info
```

<details>
<summary><strong>Authentication</strong> &mdash; <code>observal auth</code></summary>

```bash
observal auth init             # first-time setup (connect to team or create admin)
observal auth login             # login with API key
observal auth logout            # clear saved credentials
observal auth whoami            # show current user
observal auth status            # check server connectivity and health
```

</details>

<details>
<summary><strong>Component Registry</strong> &mdash; <code>observal registry &lt;type&gt;</code></summary>

All 5 component types (mcp, skill, hook, prompt, sandbox) support the same core commands:

```bash
observal registry <type> submit [<git-url> | --from-file <path>]
observal registry <type> list [--search <term>]
observal registry <type> show <id-or-name>
observal registry <type> install <id-or-name> --ide <ide>
observal registry <type> delete <id-or-name>
```

Prompts also have `observal registry prompt render <id> --var key=value`.

</details>

<details>
<summary><strong>Agent Authoring</strong> &mdash; <code>observal agent</code></summary>

```bash
# Browse and manage
observal agent create              # interactive agent creation
observal agent list [--search <term>]
observal agent show <id>
observal agent install <id> --ide <ide>
observal agent delete <id>

# Local YAML workflow
observal agent init                # scaffold observal-agent.yaml
observal agent add <type> <id>     # add component (mcp, skill, hook, prompt, sandbox)
observal agent build               # validate against server (dry-run)
observal agent publish             # submit to registry
```

</details>

<details>
<summary><strong>Observability</strong> &mdash; <code>observal ops</code></summary>

```bash
observal ops overview              # dashboard stats
observal ops metrics <id> [--type mcp|agent] [--watch]
observal ops top [--type mcp|agent]
observal ops traces [--type <type>] [--mcp <id>] [--agent <id>]
observal ops spans <trace-id>
observal ops rate <id> --stars 5 [--type mcp|agent] [--comment "..."]
observal ops feedback <id> [--type mcp|agent]
observal ops telemetry status
observal ops telemetry test
```

</details>

<details>
<summary><strong>Admin</strong> &mdash; <code>observal admin</code></summary>

```bash
# Settings and users
observal admin settings
observal admin set <key> <value>
observal admin users

# Review workflow
observal admin review list
observal admin review show <id>
observal admin review approve <id>
observal admin review reject <id> --reason "..."

# Evaluation engine
observal admin eval run <agent-id> [--trace <trace-id>]
observal admin eval scorecards <agent-id> [--version "1.0.0"]
observal admin eval show <scorecard-id>
observal admin eval compare <agent-id> --a "1.0.0" --b "2.0.0"
observal admin eval aggregate <agent-id> [--window 50]

# Penalty and weight tuning
observal admin penalties
observal admin penalty-set <name> [--amount 10] [--active]
observal admin weights
observal admin weight-set <dimension> <weight>
```

</details>

<details>
<summary><strong>Configuration</strong> &mdash; <code>observal config</code></summary>

```bash
observal config show               # show current config
observal config set <key> <value>  # set a config value
observal config path               # show config file path
observal config alias <name> <id>  # create @alias for an ID
observal config aliases            # list all aliases
```

</details>

<details>
<summary><strong>Self-Management &amp; Diagnostics</strong></summary>

```bash
observal self upgrade              # upgrade CLI to latest version
observal self downgrade            # downgrade to previous version
observal doctor [--ide <ide>] [--fix]  # diagnose IDE settings compatibility
```

</details>

## Tech Stack

| Component | Technology |
|-----------|------------|
| Frontend | Next.js 16, React 19, Tailwind CSS 4, shadcn/ui, Recharts |
| Backend API | Python, FastAPI, Uvicorn |
| Database | PostgreSQL 16 (primary), ClickHouse (telemetry) |
| ORM | SQLAlchemy (async) + AsyncPG |
| CLI | Python, Typer, Rich |
| Eval Engine | AWS Bedrock / OpenAI-compatible LLMs |
| Background Jobs | arq + Redis |
| Real-time | GraphQL subscriptions (Strawberry + WebSocket) |
| Dependency Management | uv |
| Telemetry Pipeline | OpenTelemetry Collector |
| Deployment | Docker Compose (7 services) |

## Setup & Configuration

For detailed setup, eval engine configuration, environment variables, and troubleshooting, see [SETUP.md](SETUP.md).

<details>
<summary><strong>API Endpoints</strong></summary>

### Auth

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/auth/init` | First-run admin setup |
| `POST` | `/api/v1/auth/login` | Login with API key |
| `GET` | `/api/v1/auth/whoami` | Current user info |

### Registry (per type: mcps, agents, skills, hooks, prompts, sandboxes)

All `{id}` parameters accept either a UUID or a name.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/{type}` | Submit / create |
| `GET` | `/api/v1/{type}` | List approved items |
| `GET` | `/api/v1/{type}/{id}` | Get details |
| `POST` | `/api/v1/{type}/{id}/install` | Get IDE config snippet |
| `DELETE` | `/api/v1/{type}/{id}` | Delete |
| `GET` | `/api/v1/{type}/{id}/metrics` | Metrics |
| `POST` | `/api/v1/agents/{id}/pull` | Pull agent (installs all components) |

### Scan

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/scan` | Bulk register items from IDE config scan |

### Review

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/review` | List pending submissions |
| `GET` | `/api/v1/review/{id}` | Submission details |
| `POST` | `/api/v1/review/{id}/approve` | Approve |
| `POST` | `/api/v1/review/{id}/reject` | Reject |

### Telemetry

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/telemetry/ingest` | Batch ingest traces, spans, scores |
| `POST` | `/api/v1/telemetry/events` | Legacy event ingestion |
| `GET` | `/api/v1/telemetry/status` | Data flow status |

### Evaluation

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/eval/agents/{id}` | Run evaluation |
| `GET` | `/api/v1/eval/agents/{id}/scorecards` | List scorecards |
| `GET` | `/api/v1/eval/scorecards/{id}` | Scorecard details |
| `GET` | `/api/v1/eval/agents/{id}/compare` | Compare versions |
| `GET` | `/api/v1/eval/agents/{id}/aggregate` | Aggregate scoring stats |

### Feedback

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/feedback` | Submit rating |
| `GET` | `/api/v1/feedback/{type}/{id}` | Get feedback |
| `GET` | `/api/v1/feedback/summary/{id}` | Rating summary |

### Admin

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/admin/settings` | List settings |
| `PUT` | `/api/v1/admin/settings/{key}` | Set a value |
| `GET` | `/api/v1/admin/users` | List users |
| `POST` | `/api/v1/admin/users` | Create user |
| `PUT` | `/api/v1/admin/users/{id}/role` | Change role |
| `GET` | `/api/v1/admin/penalties` | List penalty catalog |
| `PUT` | `/api/v1/admin/penalties/{id}` | Modify penalty |
| `GET` | `/api/v1/admin/weights` | Get dimension weights |
| `PUT` | `/api/v1/admin/weights` | Set dimension weights |

### GraphQL

| Endpoint | Description |
|----------|-------------|
| `/api/v1/graphql` | Traces, spans, scores, metrics (query + subscription) |

### Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |

</details>

<details>
<summary><strong>Environment Variables</strong></summary>

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | | PostgreSQL connection string (asyncpg) |
| `CLICKHOUSE_URL` | Yes | | ClickHouse connection string |
| `POSTGRES_USER` | Yes | `postgres` | PostgreSQL user |
| `POSTGRES_PASSWORD` | Yes | | PostgreSQL password |
| `SECRET_KEY` | Yes | | Secret key for API key hashing |
| `CLICKHOUSE_USER` | No | `default` | ClickHouse user |
| `CLICKHOUSE_PASSWORD` | No | `clickhouse` | ClickHouse password |
| `EVAL_MODEL_URL` | No | | OpenAI-compatible endpoint for the eval engine |
| `EVAL_MODEL_API_KEY` | No | | API key for the eval model |
| `EVAL_MODEL_NAME` | No | | Model name (e.g. `us.anthropic.claude-3-5-haiku-20241022-v1:0`) |
| `EVAL_MODEL_PROVIDER` | No | | `bedrock`, `openai`, or empty for auto-detect |
| `AWS_ACCESS_KEY_ID` | No | | AWS credentials for Bedrock |
| `AWS_SECRET_ACCESS_KEY` | No | | AWS credentials for Bedrock |
| `AWS_SESSION_TOKEN` | No | | AWS session token (temporary credentials) |
| `AWS_REGION` | No | `us-east-1` | AWS region for Bedrock |

</details>

## Running Tests

```bash
make test      # quick (526 tests)
make test-v    # verbose
```

All tests mock external services. No Docker needed.

## Community

Have a question, idea, or want to share what you've built? Head to [GitHub Discussions](https://github.com/BlazeUp-AI/Observal/discussions). Please use Discussions for questions instead of opening issues. Issues are reserved for bug reports and feature requests.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide. The short version:

1. Fork and clone
2. `make hooks` to install pre-commit hooks
3. Create a feature branch
4. Make changes, run `make lint` and `make test`
5. Open a PR

See [AGENTS.md](AGENTS.md) for internal codebase context useful when working with AI coding agents.

## Star History

If you find Observal useful, please star the repo. It helps others discover the project and motivates continued development.

<a href="https://www.star-history.com/?repos=BlazeUp-AI%2FObserval&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=BlazeUp-AI/Observal&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=BlazeUp-AI/Observal&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=BlazeUp-AI/Observal&type=date&legend=top-left" />
 </picture>
</a>

## License

GNU Affero General Public License v3.0. See [LICENSE](LICENSE).
