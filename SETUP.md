# Setup Guide

This guide covers all the ways to get Observal running, from the quickstart Docker path to local development and optional services like the eval engine.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Python 3.11+
- Node.js 20+ (for local web UI development)
- Git

## Quickstart (Docker)

This is the fastest way to get everything running.

```bash
git clone https://github.com/BlazeUp-AI/Observal.git
cd Observal
cp .env.example .env
```

Edit `.env` with your values (see [Environment Variables](#environment-variables) below). The `.env` file must stay in the project root. All Docker services reference it from there via `env_file: ../.env`.

```bash
cd docker
docker compose up --build -d
```

This starts four services:

| Service | URL | Description |
|---------|-----|-------------|
| `observal-api` | http://localhost:8000 | FastAPI backend |
| `observal-web` | http://localhost:3000 | Next.js web UI |
| `observal-db` | localhost:5432 | PostgreSQL 16 |
| `observal-clickhouse` | localhost:8123 | ClickHouse (telemetry) |

Install the CLI and run first-time setup:

```bash
cd ..
uv tool install --editable .
observal init
```

`observal init` prompts for the server URL (defaults to http://localhost:8000), your admin email, and name. It creates the admin account and saves your API key to `~/.observal/config.json`.

You're ready to go. See the [README](README.md) for usage.

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | | PostgreSQL connection string (e.g. `postgresql+asyncpg://postgres:secret@observal-db:5432/observal`) |
| `CLICKHOUSE_URL` | Yes | | ClickHouse connection string (e.g. `clickhouse://default:clickhouse@observal-clickhouse:8123/observal`) |
| `POSTGRES_USER` | Yes | `postgres` | PostgreSQL user |
| `POSTGRES_PASSWORD` | Yes | | PostgreSQL password |
| `SECRET_KEY` | Yes | | Secret key for API key hashing. Generate one with `openssl rand -hex 32` |
| `CLICKHOUSE_USER` | No | `default` | ClickHouse user |
| `CLICKHOUSE_PASSWORD` | No | `clickhouse` | ClickHouse password |
| `EVAL_MODEL_URL` | No | | OpenAI-compatible endpoint for the eval engine |
| `EVAL_MODEL_API_KEY` | No | | API key for the eval model. Leave empty for AWS credential chain |
| `EVAL_MODEL_NAME` | No | | Model name (e.g. `us.anthropic.claude-3-5-haiku-20241022-v1:0`) |
| `EVAL_MODEL_PROVIDER` | No | | `bedrock`, `openai`, or empty for auto-detect |
| `AWS_ACCESS_KEY_ID` | No | | AWS credentials for Bedrock eval engine |
| `AWS_SECRET_ACCESS_KEY` | No | | AWS credentials for Bedrock eval engine |
| `AWS_SESSION_TOKEN` | No | | AWS session token (if using temporary credentials) |
| `AWS_REGION` | No | `us-east-1` | AWS region for Bedrock |

## Local Development

For development you can run the backend, frontend, and CLI individually outside Docker while still using Docker for the databases.

### Databases only

Start just PostgreSQL and ClickHouse:

```bash
cd docker
docker compose up observal-db observal-clickhouse -d
```

### Backend (FastAPI)

```bash
cd observal-server
```

Create a `.env` file in the server directory (or the project root) with connection strings pointing to localhost:

```
DATABASE_URL=postgresql+asyncpg://postgres:yourpassword@localhost:5432/observal
CLICKHOUSE_URL=clickhouse://default:clickhouse@localhost:8123/observal
SECRET_KEY=dev-secret-key
```

Install dependencies and run:

```bash
uv sync
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at http://localhost:8000. Database tables are created automatically on startup.

### Frontend (Next.js)

```bash
cd observal-web
npm install
```

Set the API URL for the dev proxy. Create a `.env.local` file:

```
API_INTERNAL_URL=http://localhost:8000
```

Then run:

```bash
npm run dev
```

The web UI will be at http://localhost:3000. All `/api/*` requests are proxied to the backend through Next.js rewrites, so the browser talks directly to the frontend only.

### CLI

From the project root:

```bash
uv tool install --editable .
```

This installs the `observal` command globally. Configure it to point at your local server:

```bash
observal init
# Server URL: http://localhost:8000
```

Your config is saved to `~/.observal/config.json`. You can also log in with an existing API key:

```bash
observal login
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

All four metrics use LLM-as-judge under the hood — the same eval model configured via `EVAL_MODEL_NAME` / `EVAL_MODEL_URL`. No additional dependencies are needed.

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

ClickHouse tables are also created automatically on startup. The API runs `CREATE TABLE IF NOT EXISTS` for two tables:

- `mcp_tool_calls` - tool call telemetry events, partitioned by month
- `agent_interactions` - agent interaction events, partitioned by month

If ClickHouse is unavailable at startup, the API still starts. Telemetry ingestion and dashboard queries will fail silently until ClickHouse becomes available.

### Resetting the database

To wipe everything and start fresh:

```bash
cd docker
docker compose down -v
docker compose up --build -d
```

The `-v` flag removes the named volumes (`pgdata`, `chdata`), which deletes all data. After restarting, run `observal init` again to create a new admin account.

## Docker Details

### Viewing logs

```bash
cd docker

# All services
docker compose logs -f

# Single service
docker compose logs -f observal-api
```

### Restarting a single service

```bash
cd docker
docker compose restart observal-api
```

### Rebuilding after code changes

```bash
cd docker
docker compose up --build -d observal-api
```

### Health checks

PostgreSQL has a health check configured (`pg_isready`). The API waits for it before starting. ClickHouse currently uses `service_started` only.

You can verify the API is healthy:

```bash
curl http://localhost:8000/health
```

## Troubleshooting

**"Connection failed. Is the server running?"**
The CLI cannot reach the API. Check that the Docker stack is up (`docker compose ps`) and that the server URL in `~/.observal/config.json` is correct.

**Port already in use**
Another process is using port 8000, 3000, 5432, or 8123. Either stop the conflicting process or change the port mappings in `docker/docker-compose.yml`.

**"System already initialized"**
`observal init` was already run. Use `observal login` instead, or reset the database (see above).

**ClickHouse not receiving data**
Check that `CLICKHOUSE_URL` in `.env` matches the credentials in the docker-compose ClickHouse environment. The default is `clickhouse://default:clickhouse@observal-clickhouse:8123/observal`.

**Eval engine returns empty scores**
Make sure `EVAL_MODEL_NAME` is set. If using Bedrock, verify your AWS credentials have `bedrock:InvokeModel` permission. Check the API logs for error details: `docker compose logs -f observal-api`.

**Web UI shows blank page**
The frontend may still be building. Check `docker compose logs -f observal-web`. If running locally, make sure `API_INTERNAL_URL` is set in `.env.local` and the backend is running.
