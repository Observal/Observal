# Observal

A self-hosted evaluation and observability platform for agentic coding workflows. Observal acts as a fitness coach for your human-in-the-loop development - it traces every tool call, skill activation, hook execution, sandbox run, and RAG query across your team's AI-assisted coding sessions, then tells you exactly what's helping and what isn't.

## The Problem

Engineering teams using Cursor, Kiro, Claude Code, Gemini CLI, and similar agentic IDEs have no visibility into what actually happens during AI-assisted development. Agents call tools, activate skills, execute code in sandboxes, query knowledge graphs, and fire lifecycle hooks - but none of this is measured. Teams can't answer basic questions:

- Which tools speed up development and which ones waste time?
- Are prompts producing good results or causing rework?
- Do skills actually improve code quality when they activate?
- Which hooks are blocking legitimate actions vs catching real issues?
- Is the RAG system returning relevant context or noise?
- How do two versions of an agent compare on real developer workflows?

Without answers, teams can't improve their tooling. They guess, ship changes, and hope for the better.

## What Observal Does

Observal collects telemetry from every layer of the agentic coding stack, evaluates it with an LLM-as-judge engine, and surfaces actionable metrics. It manages 8 registry types that cover the full surface area of modern AI-assisted development:

| Registry Type | What It Is | What Observal Measures |
|--------------|-----------|----------------------|
| MCP Servers | Model Context Protocol servers that expose tools to agents | Call volume, latency percentiles, error rates, schema compliance |
| Agents | AI agent configurations with system prompts, model settings, and linked tools | Interaction count, acceptance rate, tool call efficiency, version-over-version comparison |
| Tool Calls | Standalone tools (non-MCP) exposed directly to agents | Invocation count, success rate, retry rate, schema validation |
| Skills | Portable instruction packages (SKILL.md) that agents load on demand | Activation frequency (auto vs manual), error rate correlation, session duration impact |
| Hooks | Lifecycle callbacks that fire at specific points during agent sessions | Execution count per event type, block rate, latency overhead |
| Prompts | Managed prompt templates with variable substitution | Render count, token expansion ratio, downstream LLM success rate |
| Sandbox Exec | Docker/LXC execution environments for code running and testing | CPU/memory/disk/network usage, exit codes, OOM rate, timeout rate |
| GraphRAGs | Knowledge graph and RAG system endpoints | Entities retrieved, relationships traversed, relevance scores, embedding latency |

Every type goes through a unified admin review workflow before it's available to developers. Every type emits telemetry into ClickHouse. Every type gets metrics, feedback, and eval scores.

## How It Works

Observal sits between your IDE and your tools. A transparent shim (`observal-shim` for stdio, `observal-proxy` for HTTP) intercepts traffic without modifying it, pairs requests with responses into spans, and streams them to ClickHouse. The shim is injected automatically when you install a tool through Observal - no code changes required.

```
IDE  <-->  observal-shim  <-->  MCP Server / Tool / Sandbox / GraphRAG
                |
                v (fire-and-forget)
          Observal API  -->  ClickHouse (traces, spans, scores)
                |
                v
          Eval Engine (LLM-as-judge)  -->  Scorecards
```

The eval engine runs on traces after the fact. It scores agent sessions across dimensions like tool selection quality, prompt effectiveness, RAG relevance, and code correctness. Scorecards let you compare versions, identify bottlenecks, and track improvements over time.

## IDE Support

Config generation and telemetry collection work across all major agentic IDEs:

| IDE | MCP | Agents | Skills | Hooks | Sandbox Exec | GraphRAGs | Prompts |
|-----|:---:|:------:|:------:|:-----:|:------------:|:---------:|:-------:|
| Cursor | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| Kiro IDE | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| Kiro CLI | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| Claude Code | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| GitHub Copilot | - | - | Yes | - | - | - | Yes |
| Gemini CLI | Yes | Yes | Yes | - | Yes | Yes | Yes |
| VS Code | Yes | Yes | - | - | Yes | Yes | Yes |
| Windsurf | Yes | Yes | - | - | Yes | Yes | Yes |

## Tech Stack

| Component | Technology |
|-----------|------------|
| Backend API | Python, FastAPI, Uvicorn |
| Database | PostgreSQL 16 (primary), ClickHouse (telemetry) |
| ORM | SQLAlchemy (async) + AsyncPG |
| CLI | Python, Typer, Rich |
| Eval Engine | AWS Bedrock / OpenAI-compatible LLMs |
| Background Jobs | arq + Redis |
| Real-time | GraphQL subscriptions (Strawberry + WebSocket) |
| Dependency Management | uv |
| Deployment | Docker Compose |

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Python 3.11+
- Git

## Getting Started

```bash
git clone https://github.com/BlazeUp-AI/Observal.git
cd Observal
cp .env.example .env
# edit .env with your values

cd docker
docker compose up --build -d
cd ..

uv tool install --editable .
observal init
```

This starts the API at http://localhost:8000 along with PostgreSQL, ClickHouse, Redis, and the background worker. The CLI is installed via `uv tool install` and `observal init` creates your admin account.

For detailed setup, eval engine configuration, and troubleshooting, see [SETUP.md](SETUP.md).

## Environment Variables

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

## CLI Usage

### Authentication

```bash
observal init          # first-time admin setup
observal login         # login with API key
observal whoami        # check current user
```

### Registry Operations

All registry types follow the same pattern: submit, list, show, install, delete.

```bash
# MCP Servers
observal submit <git-url>
observal list [--category <cat>] [--search <term>]
observal show <id>
observal install <id> --ide <ide>

# Agents
observal agent create
observal agent list [--search <term>]
observal agent show <id>
observal agent install <id> --ide <ide>

# Skills
observal skill submit <git-url-or-path>
observal skill list [--task-type <type>] [--target-agent <agent>]
observal skill install <id> --ide <ide>

# Hooks
observal hook submit
observal hook list [--event <event>] [--scope <scope>]
observal hook install <id> --ide <ide>

# Tools
observal tool submit
observal tool list [--category <cat>]
observal tool install <id> --ide <ide>

# Prompts
observal prompt submit [--from-file <path>]
observal prompt list [--category <cat>]
observal prompt render <id> --var key=value

# Sandboxes
observal sandbox submit
observal sandbox list [--runtime docker|lxc]
observal sandbox install <id> --ide <ide>

# GraphRAGs
observal graphrag submit
observal graphrag list [--query-interface graphql|rest|cypher|sparql]
observal graphrag install <id> --ide <ide>
```

### Admin Review

All registry types go through a single review workflow:

```bash
observal review list [--type mcp|agent|skill|hook|tool|prompt|sandbox|graphrag]
observal review show <id>
observal review approve <id>
observal review reject <id> --reason "Missing documentation"
```

### Observability

```bash
# Telemetry status
observal telemetry status

# Metrics for any registry type
observal metrics <id> --type mcp
observal metrics <id> --type agent
observal metrics <id> --type tool

# Enterprise overview
observal overview
```

### Evaluation

```bash
# Run eval on agent traces
observal eval run <agent-id>

# List and inspect scorecards
observal eval scorecards <agent-id> [--version "1.0.0"]
observal eval show <scorecard-id>

# Compare versions
observal eval compare <agent-id> --a "1.0.0" --b "2.0.0"
```

### Feedback

```bash
# Rate any registry item (1-5 stars)
observal rate <id> --stars 5 --type mcp --comment "Works great"

# View feedback
observal feedback <id> --type mcp
```

## API Endpoints

### Auth

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/auth/init` | First-run admin setup |
| `POST` | `/api/v1/auth/login` | Login with API key |
| `GET` | `/api/v1/auth/whoami` | Current user info |

### Registry (per type: mcps, agents, tools, skills, hooks, prompts, sandboxes, graphrags)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/{type}` | Submit / create |
| `GET` | `/api/v1/{type}` | List approved items |
| `GET` | `/api/v1/{type}/{id}` | Get details |
| `POST` | `/api/v1/{type}/{id}/install` | Get IDE config snippet |
| `DELETE` | `/api/v1/{type}/{id}` | Delete |
| `GET` | `/api/v1/{type}/{id}/metrics` | Metrics |

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

### GraphQL

| Endpoint | Description |
|----------|-------------|
| `/api/v1/graphql` | Traces, spans, scores, metrics (query + subscription) |

### Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |

## Project Structure

```
Observal/
├── observal-server/          # FastAPI backend
│   ├── api/
│   │   ├── deps.py           # Auth and dependency injection
│   │   ├── graphql.py        # Strawberry GraphQL schema
│   │   └── routes/           # REST route handlers (all 8 registry types)
│   ├── models/               # SQLAlchemy models
│   ├── schemas/              # Pydantic request/response schemas
│   ├── services/             # Business logic, validators, config generators
│   ├── main.py               # App entrypoint
│   ├── config.py             # Settings (pydantic-settings)
│   └── worker.py             # arq background worker
├── observal_cli/             # Typer CLI
│   ├── main.py               # App wiring
│   ├── cmd_auth.py           # Auth commands
│   ├── cmd_mcp.py            # MCP server commands
│   ├── cmd_agent.py          # Agent commands
│   ├── cmd_tool.py           # Tool commands
│   ├── cmd_skill.py          # Skill commands
│   ├── cmd_hook.py           # Hook commands
│   ├── cmd_prompt.py         # Prompt commands
│   ├── cmd_sandbox.py        # Sandbox commands
│   ├── cmd_graphrag.py       # GraphRAG commands
│   ├── cmd_ops.py            # Review, telemetry, eval, admin, traces
│   ├── client.py             # HTTP client wrapper
│   ├── config.py             # CLI config and alias management
│   ├── render.py             # Rich rendering helpers
│   ├── shim.py               # observal-shim: stdio telemetry proxy
│   ├── proxy.py              # observal-proxy: HTTP telemetry proxy
│   ├── sandbox_runner.py     # observal-sandbox-run: Docker executor with log capture
│   └── graphrag_proxy.py     # observal-graphrag-proxy: HTTP proxy for GraphRAG
├── docker/
│   ├── docker-compose.yml    # 5 services: api, db, clickhouse, redis, worker
│   └── Dockerfile.api        # API container
├── tests/                    # Unit tests (pytest, all mocked)
├── demo/                     # E2E test scripts and mock MCP servers
├── docs/                     # Design documents
├── AGENTS.md                 # Internal context for AI agents
├── SETUP.md                  # Setup and development guide
├── CONTRIBUTING.md           # Contribution guide
├── Makefile                  # Dev shortcuts
├── .env.example              # Environment variable template
├── pyproject.toml            # Package config
└── LICENSE                   # GNU Affero General Public License v3.0
```

## Running Tests

```bash
make test      # quick
make test-v    # verbose
```

All tests mock external services. No Docker needed.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide. The short version:

1. Fork and clone
2. `make hooks` to install pre-commit hooks
3. Create a feature branch
4. Make changes, run `make lint` and `make test`
5. Open a PR

See [AGENTS.md](AGENTS.md) for internal codebase context useful when working with AI coding agents.

## License

GNU Affero General Public License v3.0. See [LICENSE](LICENSE).
