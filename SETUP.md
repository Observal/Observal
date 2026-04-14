# Setup Guide

Everything works out of the box with defaults. No configuration needed for local development.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Python 3.11+
- Node.js 20+ and pnpm (for frontend development)
- Git

## Quickstart (Docker)

### 1. Clone and configure

```bash
git clone https://github.com/BlazeUp-AI/Observal.git
cd Observal
cp .env.example .env
```

The `.env.example` ships with working defaults for every setting, including demo account credentials. No editing needed for local development.

### 2. Start the stack

```bash
docker compose -f docker/docker-compose.yml up --build -d
```

The first build takes a few minutes (pulling images, installing dependencies). Subsequent starts are fast.

This starts eight services:

| Service | URL | Description |
|---------|-----|-------------|
| `observal-api` | http://localhost:8000 | FastAPI backend |
| `observal-web` | http://localhost:3000 | Next.js web UI |
| `observal-db` | localhost:5432 | PostgreSQL 16 |
| `observal-clickhouse` | localhost:8123 | ClickHouse (telemetry) |
| `observal-redis` | localhost:6379 | Redis (job queue, pub/sub) |
| `observal-worker` | (internal) | Background job processor (arq) |
| `observal-otel-collector` | localhost:4317 | OpenTelemetry Collector |
| `observal-grafana` | http://localhost:3001 | Grafana dashboards (optional) |

### 3. Verify services are healthy

```bash
docker compose -f docker/docker-compose.yml ps
```

All services should show `healthy` or `running`. The API waits for PostgreSQL, ClickHouse, and Redis to pass their health checks before starting, so it may take 15-30 seconds. If a service shows `starting`, wait a moment and check again.

You can also hit the health endpoint directly:

```bash
curl http://localhost:8000/health
# {"status": "ok"}
```

### 4. Install the CLI

From the project root:

```bash
uv tool install --editable .
```

This installs the `observal` command globally. Verify it works:

```bash
observal --version
```

### 5. Log in

```bash
observal auth login
```

The CLI will prompt you for:
1. **Server URL** — press Enter to accept the default (`http://localhost:8000`)
2. **Login method** — choose `[E]mail` or `[K]ey`
3. **Email and password** — use a demo account (see below)

**Demo accounts:** The `.env.example` includes four demo accounts that are seeded automatically on first startup:

| Role | Email | Password |
|------|-------|----------|
| Super Admin | `super@demo.example` | `super-changeme` |
| Admin | `admin@demo.example` | `admin-changeme` |
| Reviewer | `reviewer@demo.example` | `reviewer-changeme` |
| User | `user@demo.example` | `user-changeme` |

Log in as super admin for full access. Your credentials are saved to `~/.observal/config.json`.

Verify you are logged in:

```bash
observal auth whoami
```

**Fresh server without demo accounts:** If you remove the `DEMO_*` variables from `.env`, no accounts are seeded. In that case, `observal auth login` detects that no users exist and bootstraps an admin account interactively — it prompts for an email and password to create the first admin.

### 6. You are ready

Open the web UI at http://localhost:3000 or start using the CLI:

```bash
observal ops overview           # dashboard stats
observal registry mcp list      # list MCP servers
observal auth status            # check connectivity
```

To add team members, they can self-register:

```bash
observal auth register
```

For CI/scripts, use environment variables instead of interactive login:

```bash
export OBSERVAL_SERVER_URL=http://localhost:8000
export OBSERVAL_API_KEY=<your-key>
```

See the [README](README.md) for full CLI and API reference.

## Environment Variables

All settings have sensible defaults that work for local development. The server starts without any `.env` file at all (it will use built-in defaults). For Docker Compose, just copy the example file and you are set.

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/observal` | PostgreSQL connection string |
| `CLICKHOUSE_URL` | `clickhouse://localhost:8123/observal` | ClickHouse connection string |
| `REDIS_URL` | `redis://localhost:6379` | Redis connection string |
| `SECRET_KEY` | `change-me-to-a-random-string` | Session signing key. For production, generate a real one: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `POSTGRES_USER` | `postgres` | PostgreSQL container user |
| `POSTGRES_PASSWORD` | `postgres` | PostgreSQL container password |
| `FRONTEND_URL` | `http://localhost:3000` | Frontend URL (used for OAuth redirects) |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:3000` | Comma-separated allowed CORS origins |
| `CLICKHOUSE_USER` | `default` | ClickHouse user |
| `CLICKHOUSE_PASSWORD` | `clickhouse` | ClickHouse password |
| `OAUTH_CLIENT_ID` | disabled | OAuth/OIDC client ID (SSO is disabled when unset) |
| `OAUTH_CLIENT_SECRET` | disabled | OAuth/OIDC client secret |
| `OAUTH_SERVER_METADATA_URL` | disabled | OIDC discovery URL |
| `EVAL_MODEL_URL` | | OpenAI-compatible endpoint for the eval engine |
| `EVAL_MODEL_API_KEY` | | API key for the eval model. Leave empty for AWS credential chain |
| `EVAL_MODEL_NAME` | | Model name (e.g. `us.anthropic.claude-3-5-haiku-20241022-v1:0`) |
| `EVAL_MODEL_PROVIDER` | | `bedrock`, `openai`, or empty for auto-detect |
| `AWS_ACCESS_KEY_ID` | | AWS credentials for Bedrock eval engine |
| `AWS_SECRET_ACCESS_KEY` | | AWS credentials for Bedrock eval engine |
| `AWS_SESSION_TOKEN` | | AWS session token (if using temporary credentials) |
| `AWS_REGION` | `us-east-1` | AWS region for Bedrock |
| `RATE_LIMIT_AUTH` | `10/minute` | Rate limit for general auth endpoints |
| `RATE_LIMIT_AUTH_STRICT` | `5/minute` | Rate limit for login and password reset |
| `DEPLOYMENT_MODE` | `local` | `local` or `enterprise` (SSO-only, SCIM provisioning) |
| `DATA_RETENTION_DAYS` | `90` | ClickHouse data retention in days |
| `DEMO_SUPER_ADMIN_EMAIL` | `super@demo.example` | Demo super admin email (seeded on first startup) |
| `DEMO_SUPER_ADMIN_PASSWORD` | `super-changeme` | Demo super admin password |
| `DEMO_ADMIN_EMAIL` | `admin@demo.example` | Demo admin email |
| `DEMO_ADMIN_PASSWORD` | `admin-changeme` | Demo admin password |
| `DEMO_REVIEWER_EMAIL` | `reviewer@demo.example` | Demo reviewer email |
| `DEMO_REVIEWER_PASSWORD` | `reviewer-changeme` | Demo reviewer password |
| `DEMO_USER_EMAIL` | `user@demo.example` | Demo user email |
| `DEMO_USER_PASSWORD` | `user-changeme` | Demo user password |
| `GRAFANA_ADMIN_USER` | `admin` | Grafana admin username |
| `GRAFANA_ADMIN_PASSWORD` | `admin` | Grafana admin password |

## Local Development

For development you can run the backend, frontend, and CLI individually outside Docker while keeping Docker for the databases.

### Databases only

Start just PostgreSQL, ClickHouse, and Redis:

```bash
docker compose -f docker/docker-compose.yml up observal-db observal-clickhouse observal-redis -d
```

### Backend (FastAPI)

```bash
cd observal-server
uv sync
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at http://localhost:8000. Database tables are created automatically on startup. All settings use built-in defaults pointing to localhost, so no `.env` file is strictly necessary. If you want to override anything, create a `.env` in the project root or the server directory:

```
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/observal
CLICKHOUSE_URL=clickhouse://default:clickhouse@localhost:8123/observal
SECRET_KEY=dev-secret-key
```

### Frontend (Next.js)

```bash
cd web
pnpm install
pnpm dev
```

The web UI will be at http://localhost:3000. All `/api/*` requests are proxied to the backend through Next.js rewrites, so the browser talks directly to the frontend only. If the backend is on a different host, set `NEXT_PUBLIC_API_URL` in `web/.env.local`.

### CLI

From the project root:

```bash
uv tool install --editable .
```

This installs the `observal` command globally. Configure it to point at your local server:

```bash
observal auth login
# Server URL: http://localhost:8000
```

On a fresh server this auto-creates an admin account. On an existing server, log in with an API key:

```bash
observal auth login --key <api-key>    # API key
```

## Eval Engine Setup

The evaluation engine uses an LLM-as-judge approach to score agent traces. It supports two providers.

### AWS Bedrock

Set these in your `.env`:

```
EVAL_MODEL_NAME=us.anthropic.claude-3-5-haiku-20241022-v1:0
EVAL_MODEL_PROVIDER=bedrock
AWS_ACCESS_KEY_ID=your-key
AWS_SECRET_ACCESS_KEY=your-secret
AWS_REGION=us-east-1
```

If you are using temporary credentials (e.g. from `aws sts assume-role`), also set `AWS_SESSION_TOKEN`.

The Bedrock provider uses `boto3` and calls the Converse API. Your IAM principal needs `bedrock:InvokeModel` permission for the model you configure.

### OpenAI-compatible API

This works with OpenAI, Azure OpenAI, or any provider that implements the `/v1/chat/completions` endpoint (e.g. Ollama, vLLM).

```
EVAL_MODEL_URL=https://api.openai.com/v1
EVAL_MODEL_API_KEY=sk-...
EVAL_MODEL_NAME=gpt-4o
EVAL_MODEL_PROVIDER=openai
```

For local models via Ollama:

```
EVAL_MODEL_URL=http://localhost:11434/v1
EVAL_MODEL_API_KEY=
EVAL_MODEL_NAME=llama3
EVAL_MODEL_PROVIDER=openai
```

### Auto-detect

If `EVAL_MODEL_PROVIDER` is empty, the system checks if the model name contains `anthropic`. If it does, it uses Bedrock. Otherwise it falls back to the OpenAI-compatible path.

### Without an eval model

If `EVAL_MODEL_NAME` is not set, the eval engine falls back to heuristic scoring based on trace metadata (tool call counts, latency, etc.). You can still run `observal eval run <agent-id>`, but scores will be less accurate.

## RAGAS Evaluation for GraphRAGs

Observal implements the four core [RAGAS](https://docs.ragas.io/) metrics for evaluating GraphRAG retrieval quality. Unlike the agent eval engine which scores full traces, RAGAS evaluation targets individual retrieval spans captured by the `observal-graphrag-proxy`.

### What it measures

| Metric | What It Does |
|--------|-------------|
| Faithfulness | Extracts claims from the answer and verifies each against the retrieved context. Score = supported claims / total claims. |
| Answer Relevancy | Evaluates whether the generated answer directly addresses the original query. |
| Context Precision | Checks each retrieved chunk's relevance to the question. Score = relevant chunks / total chunks. |
| Context Recall | Extracts statements from ground truth and checks if each is attributable to the context. Requires ground truth data. |

All four metrics use LLM-as-judge under the hood, the same eval model configured via `EVAL_MODEL_NAME` / `EVAL_MODEL_URL`. No additional dependencies are needed.

### Running a RAGAS evaluation

Trigger an evaluation via the API:

```bash
curl -X POST http://localhost:8000/api/v1/dashboard/graphrag-ragas-eval \
  -H "X-API-Key: $OBSERVAL_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "graphrag_id": "<your-graphrag-id>",
    "limit": 20
  }'
```

This evaluates the most recent 20 retrieval spans for that GraphRAG. Each span gets scored on all four dimensions, and scores are written to ClickHouse for the dashboard.

To include ground truth data (required for context recall):

```bash
curl -X POST http://localhost:8000/api/v1/dashboard/graphrag-ragas-eval \
  -H "X-API-Key: $OBSERVAL_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "graphrag_id": "<your-graphrag-id>",
    "limit": 10,
    "ground_truths": {
      "<span-id-1>": "Expected answer for this query",
      "<span-id-2>": "Expected answer for this query"
    }
  }'
```

### Viewing RAGAS scores

Retrieve previously computed scores:

```bash
# Scores for a specific GraphRAG
curl "http://localhost:8000/api/v1/dashboard/graphrag-ragas-scores?graphrag_id=<id>" \
  -H "X-API-Key: $OBSERVAL_KEY"

# Aggregate scores across all GraphRAGs
curl "http://localhost:8000/api/v1/dashboard/graphrag-ragas-scores" \
  -H "X-API-Key: $OBSERVAL_KEY"
```

The response contains average scores and evaluation counts per dimension:

```json
{
  "faithfulness": { "avg": 0.87, "count": 40 },
  "answer_relevancy": { "avg": 0.82, "count": 40 },
  "context_precision": { "avg": 0.79, "count": 40 },
  "context_recall": { "avg": null, "count": 0 }
}
```

A `null` average means no evaluations have been run for that dimension (context recall will be null if no ground truths were provided).

### Dashboard

The web UI at `/graphrag-metrics` displays RAGAS scores alongside the standard GraphRAG telemetry (query volume, entity counts, relevance distribution). Scores appear automatically once you run at least one RAGAS evaluation.

## Database Details

### PostgreSQL

Tables are created automatically when the API starts via SQLAlchemy's `create_all`. There are no manual migrations to run.

The schema includes tables for users, MCP listings, agents, reviews, feedback, eval scorecards, and enterprise config. All managed through SQLAlchemy models in `observal-server/models/`.

### ClickHouse

ClickHouse tables are also created automatically on startup. The API runs `CREATE TABLE IF NOT EXISTS` for the telemetry tables:

- `traces` - distributed trace data (ReplacingMergeTree)
- `spans` - individual operation spans with resource metrics (ReplacingMergeTree)
- `scores` - evaluation scores (ReplacingMergeTree)
- `audit_log` - enterprise audit events for compliance (ReplacingMergeTree)
- `mcp_tool_calls` - legacy tool call events (MergeTree)
- `agent_interactions` - legacy agent interaction events (MergeTree)

All ReplacingMergeTree tables use `is_deleted` + `event_ts` for soft deletes and deduplication. Use the `FINAL` modifier in queries to get deduplicated results. Data retention is controlled by `DATA_RETENTION_DAYS` (default: 90 days).

If ClickHouse is unavailable at startup, the API still starts. Telemetry ingestion and dashboard queries will fail silently until ClickHouse becomes available.

### Resetting the database

To wipe everything and start fresh:

```bash
docker compose -f docker/docker-compose.yml down -v
docker compose -f docker/docker-compose.yml up --build -d
```

The `-v` flag removes the named volumes (`pgdata`, `chdata`, `redisdata`, `grafanadata`, `apidata`), which deletes all data. After restarting, run `observal auth login` again. It will auto-create a new admin account.

## Docker Details

### Viewing logs

```bash
# All services
docker compose -f docker/docker-compose.yml logs -f

# Single service
docker compose -f docker/docker-compose.yml logs -f observal-api
```

Or use the Makefile shortcuts:

```bash
make logs              # tail all service logs
```

### Restarting a single service

```bash
docker compose -f docker/docker-compose.yml restart observal-api
```

### Rebuilding after code changes

```bash
make rebuild           # rebuild and restart everything
# or target a single service:
docker compose -f docker/docker-compose.yml up --build -d observal-api
```

### Health checks

All database services have health checks configured:

| Service | Check | Interval |
|---------|-------|----------|
| PostgreSQL | `pg_isready` | 5s |
| ClickHouse | `clickhouse-client --query 'SELECT 1'` | 5s |
| Redis | `redis-cli ping` | 5s |
| API | HTTP `/health` endpoint | 10s |

The API waits for all three databases to be healthy before starting (`service_healthy` dependency). You can verify the API is healthy:

```bash
curl http://localhost:8000/health
```

## Production Notes

For production deployments, you should at minimum:

1. Generate a unique `SECRET_KEY` (the default is not secure for production)
2. Set strong `POSTGRES_PASSWORD` credentials
3. Configure `CORS_ALLOWED_ORIGINS` to your actual frontend domain
4. Set up OAuth/SSO if you need single sign-on (`OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET`, `OAUTH_SERVER_METADATA_URL`)
5. Consider enabling rate limiting tuning via `RATE_LIMIT_AUTH` and `RATE_LIMIT_AUTH_STRICT`

The `/auth/bootstrap` endpoint is restricted to localhost access only for security.

## Troubleshooting

**"Connection failed. Is the server running?"**
The CLI cannot reach the API. Check that the Docker stack is up (`docker compose ps`) and that the server URL in `~/.observal/config.json` is correct.

**Port already in use**
Another process is using port 8000, 3000, 5432, or 8123. Either stop the conflicting process or change the port mappings in `docker/docker-compose.yml`.

**"System already initialized"**
The server already has users. Use `observal auth login` with an API key, or reset the database (see above).

**ClickHouse not receiving data**
Check that `CLICKHOUSE_URL` in `.env` matches the credentials in the docker-compose ClickHouse environment. The default is `clickhouse://default:clickhouse@observal-clickhouse:8123/observal`.

**Eval engine returns empty scores**
Make sure `EVAL_MODEL_NAME` is set. If using Bedrock, verify your AWS credentials have `bedrock:InvokeModel` permission. Check the API logs for error details: `docker compose logs -f observal-api`.

**Web UI shows blank page**
The frontend may still be building. Check `docker compose logs -f observal-web`. If running locally, make sure `NEXT_PUBLIC_API_URL` is set in `web/.env.local` and the backend is running.
