# Self-Hosting

Run Observal entirely on your own infrastructure. No SaaS, no egress, every byte of telemetry stays inside your network.

## Architecture at a glance

```
                  ┌─────────────────────────────────────────┐
                  │           observal-net (bridge)         │
                  │                                         │
  [Engineers] ──► │  observal-web  ◄──►  observal-api       │
   (port 3000)    │      │                    │             │
                  │      ▼                    ▼             │
                  │  (static)        observal-worker        │
                  │                     │  │  │             │
                  │          ┌──────────┘  │  └──────────┐  │
                  │          ▼             ▼             ▼  │
                  │   observal-db   observal-redis  observal-clickhouse
                  │   (Postgres)    (jobs, pubsub)   (telemetry)   │
                  │                                               │
                  │   observal-otel-collector  ──►  clickhouse    │
                  │                                               │
                  │   observal-grafana  ──►  clickhouse (optional)│
                  └───────────────────────────────────────────────┘
```

**Eight services:**

| Service | Image | Ports | Purpose |
| --- | --- | --- | --- |
| `observal-api` | built from `docker/Dockerfile.api` | 8000 | FastAPI backend |
| `observal-web` | built from `docker/Dockerfile.web` | 3000 | Next.js web UI |
| `observal-db` | `postgres:16` | 5432 | Registry, users, config |
| `observal-clickhouse` | `clickhouse/clickhouse-server:26.3` | 8123 | Traces, spans, scores |
| `observal-redis` | `redis:7-alpine` | 6379 | Job queue (arq) + pub/sub |
| `observal-worker` | built from `docker/Dockerfile.api` | (internal) | Background eval + async jobs |
| `observal-otel-collector` | `otel/opentelemetry-collector-contrib:0.150.1` | 4317, 4318 | OTEL ingestion |
| `observal-grafana` | `grafana/grafana-oss:11.6.5` | 3001 | Dashboards (optional) |

All services run on a private `observal-net` bridge network. Named volumes (`pgdata`, `chdata`, `redisdata`, `grafanadata`, `apidata`) hold persistent data.

## Where to start

| If you want to... | Read |
| --- | --- |
| Confirm your machine can run Observal | [Requirements](requirements.md) |
| Get the stack running locally | [Docker Compose setup](docker-compose.md) |
| Know every env var that matters | [Configuration](configuration.md) |
| See every port and volume at a glance | [Ports and volumes](ports-and-volumes.md) |
| Understand the DBs and retention | [Databases](databases.md) |
| Set up SSO, JWT keys, demo accounts | [Authentication and SSO](authentication.md) |
| Configure the eval model (Bedrock, OpenAI, Ollama) | [Evaluation engine](evaluation-engine.md) |
| Tune OTEL ingestion and the shim | [Telemetry pipeline](telemetry-pipeline.md) |
| Upgrade safely | [Upgrades](upgrades.md) |
| Back up and restore | [Backup and restore](backup-and-restore.md) |
| Fix something that's broken | [Troubleshooting](troubleshooting.md) |

## Production checklist

Before putting Observal in front of real users:

1. **Generate a real `SECRET_KEY`** — `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`.
2. **Set strong Postgres and ClickHouse passwords** — not the `.env.example` defaults.
3. **Scope `CORS_ALLOWED_ORIGINS`** to your real frontend host.
4. **Configure SSO** (`OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET`, `OAUTH_SERVER_METADATA_URL`) or set `DEPLOYMENT_MODE=enterprise` if you want SSO-only.
5. **Tune rate limits** (`RATE_LIMIT_AUTH`, `RATE_LIMIT_AUTH_STRICT`).
6. **Set `DATA_RETENTION_DAYS`** to match your retention policy (default 90 days).
7. **Back up the JWT key volume** (`apidata`) — losing it invalidates every session.
8. **Remove demo accounts** — unset `DEMO_*` env vars before the first startup in a real environment.

Each of these is covered in the linked deep-dive below. Start with [Requirements](requirements.md).
