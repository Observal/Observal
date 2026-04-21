# Configuration

Every Observal server setting lives in `.env`. Defaults are sane for local development. This page groups settings by concern; the full table is in [Reference → Environment variables](../reference/environment-variables.md).

## Required for production

Override these before going live:

| Variable | Default | Why change |
| --- | --- | --- |
| `SECRET_KEY` | `change-me-to-a-random-string` | Session signing key. Generate a real one. |
| `POSTGRES_PASSWORD` | `postgres` | Default password is not secure. |
| `CLICKHOUSE_PASSWORD` | `clickhouse` | Same. |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:3000` | Scope to your real frontend origin(s). |
| `FRONTEND_URL` | `http://localhost:3000` | Used for OAuth redirects and email links. |

Generate a secret key:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

## Deployment mode

```
DEPLOYMENT_MODE=local
```

| Mode | Self-registration | Bootstrap admin | Auth methods |
| --- | --- | --- | --- |
| `local` (default) | Yes | Yes | Email + password, API key, SSO (if configured) |
| `enterprise` | No | No | SSO only; SCIM provisioning |

Switch to `enterprise` when you want IdP-only access.

## Demo accounts

Seeded on first startup *only* when no users exist:

```
DEMO_SUPER_ADMIN_EMAIL=super@demo.example
DEMO_SUPER_ADMIN_PASSWORD=super-changeme
DEMO_ADMIN_EMAIL=admin@demo.example
DEMO_ADMIN_PASSWORD=admin-changeme
DEMO_REVIEWER_EMAIL=reviewer@demo.example
DEMO_REVIEWER_PASSWORD=reviewer-changeme
DEMO_USER_EMAIL=user@demo.example
DEMO_USER_PASSWORD=user-changeme
```

**Unset every `DEMO_*` env var before a real deployment.** Existing demo users survive after unsetting — delete them manually (`observal admin delete-user <email>`).

## Database connections

```
DATABASE_URL=postgresql+asyncpg://postgres:postgres@observal-db:5432/observal
CLICKHOUSE_URL=clickhouse://default:clickhouse@observal-clickhouse:8123/observal
REDIS_URL=redis://observal-redis:6379
```

Inside Docker Compose, hostnames resolve via the `observal-net` bridge (e.g. `observal-db`). Outside Docker (e.g. CLI running on host against dockerized DBs), use `localhost:<port>`.

## OAuth / SSO

Optional. Leave unset and SSO is disabled.

```
OAUTH_CLIENT_ID=...
OAUTH_CLIENT_SECRET=...
OAUTH_SERVER_METADATA_URL=https://accounts.example.com/.well-known/openid-configuration
```

Full setup in [Authentication and SSO](authentication.md).

## Evaluation engine

Either Bedrock:

```
EVAL_MODEL_NAME=us.anthropic.claude-3-5-haiku-20241022-v1:0
EVAL_MODEL_PROVIDER=bedrock
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1
```

Or OpenAI-compatible:

```
EVAL_MODEL_URL=https://api.openai.com/v1
EVAL_MODEL_API_KEY=sk-...
EVAL_MODEL_NAME=gpt-4o
EVAL_MODEL_PROVIDER=openai
```

Deep dive: [Evaluation engine](evaluation-engine.md).

## Rate limiting

```
RATE_LIMIT_AUTH=10/minute          # general auth endpoints
RATE_LIMIT_AUTH_STRICT=5/minute    # login and password reset
```

Tighten for higher-traffic deployments.

## ClickHouse retention

```
DATA_RETENTION_DAYS=90
```

Traces, spans, and scores older than this are TTL'd by ClickHouse. Set to `0` to disable retention (keep everything forever — disk grows without bound). The minimum non-zero value enforced on startup is 7.

## JWT keys

```
JWT_SIGNING_ALGORITHM=ES256        # ES256 (default) or RS256
JWT_KEY_DIR=/data/keys             # persisted in the apidata volume
```

The server generates asymmetric keys on first boot and stores them in `$JWT_KEY_DIR`. **Back up this directory** — losing the keys invalidates every session.

More: [Authentication and SSO](authentication.md).

## Git operations (submission analysis)

```
ALLOW_INTERNAL_URLS=false          # allow internal/private Git URLs (GitLab/GHE)
GIT_CLONE_TOKEN=                   # auth token for cloning private repos
GIT_CLONE_TOKEN_USER=x-access-token
GIT_CLONE_TIMEOUT=120              # seconds
```

`GIT_CLONE_TOKEN_USER` varies by provider: `x-access-token` for GitHub, `oauth2` or `private-token` for GitLab.

## Observal CLI (client-side) env vars

Not set in `.env` on the server — these live on the CLI user's machine.

| Variable | Purpose |
| --- | --- |
| `OBSERVAL_SERVER_URL` | Default server URL |
| `OBSERVAL_ACCESS_TOKEN` / `OBSERVAL_API_KEY` | Pre-authenticate without `login` |
| `OBSERVAL_TIMEOUT` | Request timeout (seconds) |

Full list: [Environment variables](../reference/environment-variables.md).

## Next

→ [Ports and volumes](ports-and-volumes.md)
