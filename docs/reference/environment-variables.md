<!-- SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# Environment variables

Complete reference for every environment variable the server and CLI read. Defaults are in `.env.example` (server) and built into the CLI (client).

## Server (`observal-server`)

### Core / security

| Variable                 | Default                        | Description                                                                                                                                                |
| ------------------------ | ------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SECRET_KEY`             | `change-me-to-a-random-string` | Session signing key. Generate: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`                                                             |
| `OBSERVAL_LICENSE_KEY`   | -                              | Ed25519-signed enterprise license key. Enables enterprise features such as SAML and insight reports. Validated at startup; leave unset for community edition. |
| `FRONTEND_URL`           | `http://localhost:3000`        | External frontend URL (OAuth redirects, email links)                                                                                                       |
| `CORS_ALLOWED_ORIGINS`   | `http://localhost:3000`        | Comma-separated allowed CORS origins                                                                                                                       |
| `MAX_REQUEST_SIZE_MB`    | `10`                           | Maximum request body size                                                                                                                                  |
| `RATE_LIMIT_AUTH`        | `10/minute`                    | General auth-endpoint rate limit                                                                                                                           |
| `RATE_LIMIT_AUTH_STRICT` | `5/minute`                     | Login and password-reset rate limit                                                                                                                        |

### Databases

| Variable              | Default                                                          | Description                                                 |
| --------------------- | ---------------------------------------------------------------- | ----------------------------------------------------------- |
| `DATABASE_URL`        | `postgresql+asyncpg://postgres:postgres@localhost:5432/observal` | Postgres async connection string                            |
| `POSTGRES_USER`       | `postgres`                                                       | Postgres container user                                     |
| `POSTGRES_PASSWORD`   | `postgres`                                                       | Postgres container password                                 |
| `CLICKHOUSE_URL`      | `clickhouse://localhost:8123/observal`                           | ClickHouse HTTP endpoint                                    |
| `CLICKHOUSE_USER`     | `default`                                                        | ClickHouse user                                             |
| `CLICKHOUSE_PASSWORD` | `clickhouse`                                                     | ClickHouse password                                         |
| `REDIS_URL`           | `redis://localhost:6379`                                         | Redis connection string                                     |
| `DATA_RETENTION_DAYS` | `90`                                                             | ClickHouse TTL in days. `0` disables. Minimum non-zero: `7` |

### SSO

OIDC, SAML, and SSO-only mode are configured in **Admin → SSO** and stored in dynamic settings. OIDC client changes require an API restart. Existing `OAUTH_*`, `SSO_ONLY`, and `SAML_*` values are imported once on startup when the matching dynamic setting is not already present.

### JWT signing

| Variable                | Default                                                     | Description                                             |
| ----------------------- | ----------------------------------------------------------- | ------------------------------------------------------- |
| `JWT_SIGNING_ALGORITHM` | `ES256`                                                     | `ES256` or `RS256`                                      |
| `JWT_KEY_DIR`           | `~/.observal/keys` (outside Docker) / `/data/keys` (Docker) | Directory for generated signing keys - **back this up** |

### AWS (Bedrock)

### AWS (Bedrock)

> **Note:** Bedrock now supports [API keys](https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys.html) — generate one from the AWS console and use it like any other provider. See [Insights LLM Setup](../insights-setup.md).

These environment variables are **not required** if you use Bedrock API keys (recommended). They exist only for legacy setups using instance roles or ECS task roles where LiteLLM auto-discovers credentials from the environment.

| Variable                | Default     | Description                                  |
| ----------------------- | ----------- | -------------------------------------------- |
| `AWS_ACCESS_KEY_ID`     | -           | Only for legacy IAM auth (not recommended)   |
| `AWS_SECRET_ACCESS_KEY` | -           | Only for legacy IAM auth (not recommended)   |
| `AWS_SESSION_TOKEN`     | -           | Temporary credentials (STS AssumeRole)       |
| `AWS_REGION_NAME`       | `us-east-1` | AWS region (used by LiteLLM's boto3 client)  |

### Git operations (submission analysis)

| Variable               | Default          | Description                                                                     |
| ---------------------- | ---------------- | ------------------------------------------------------------------------------- |
| `ALLOW_INTERNAL_URLS`  | `false`          | Allow internal/private Git URLs (for GitLab / GHE)                              |
| `GIT_CLONE_TOKEN`      | -                | Auth token for private repos                                                    |
| `GIT_CLONE_TOKEN_USER` | `x-access-token` | Token username: `x-access-token` (GitHub), `oauth2` or `private-token` (GitLab) |
| `GIT_CLONE_TIMEOUT`    | `120`            | Clone timeout, seconds                                                          |

### Demo accounts (seeded on first startup if no users exist)

| Variable                    | Default                 |
| --------------------------- | ----------------------- |
| `DEMO_SUPER_ADMIN_EMAIL`    | `super@demo.example`    |
| `DEMO_SUPER_ADMIN_PASSWORD` | `super-changeme`        |
| `DEMO_ADMIN_EMAIL`          | `admin@demo.example`    |
| `DEMO_ADMIN_PASSWORD`       | `admin-changeme`        |
| `DEMO_REVIEWER_EMAIL`       | `reviewer@demo.example` |
| `DEMO_REVIEWER_PASSWORD`    | `reviewer-changeme`     |
| `DEMO_USER_EMAIL`           | `user@demo.example`     |
| `DEMO_USER_PASSWORD`        | `user-changeme`         |

**Unset every `DEMO_*` variable before a real deployment.**

### Docker host ports

Used only by Docker Compose. Prometheus and Grafana ports apply only when `docker-compose.observability.yml` is included. Remap if a default is already in use.

| Variable               | Default | Service                |
| ---------------------- | ------- | ---------------------- |
| `API_HOST_PORT`        | `8000`  | API (internal, behind LB) |
| `WEB_HOST_PORT`        | `3000`  | Web UI                 |
| `POSTGRES_HOST_PORT`   | `5432`  | Postgres               |
| `CLICKHOUSE_HOST_PORT` | `8123`  | ClickHouse             |
| `REDIS_HOST_PORT`      | `6379`  | Redis                  |
| `PROMETHEUS_HOST_PORT` | `9090`  | Prometheus, optional   |
| `GRAFANA_HOST_PORT`    | `3001`  | Grafana, optional      |

### Grafana

Only used when the optional Grafana overlay or Terraform `observability_stack = "grafana"` is enabled.

| Variable                 | Default | Description            |
| ------------------------ | ------- | ---------------------- |
| `GRAFANA_ADMIN_USER`     | `admin` | Grafana admin username |
| `GRAFANA_ADMIN_PASSWORD` | `admin` | Grafana admin password |

## CLI (`observal-cli`)

Read from the environment at invocation time. Override values in `~/.observal/config.json` per invocation.

| Variable                | Default                        | Description                                                 |
| ----------------------- | ------------------------------ | ----------------------------------------------------------- |
| `OBSERVAL_SERVER_URL`   | from `~/.observal/config.json` | Server URL                                                  |
| `OBSERVAL_ACCESS_TOKEN` | from `~/.observal/config.json` | Access token (preferred for CI)                             |
| `OBSERVAL_API_KEY`      | from `~/.observal/config.json` | API key alias for `OBSERVAL_ACCESS_TOKEN` (backward-compat) |
| `OBSERVAL_TIMEOUT`      | `30`                           | HTTP timeout in seconds                                     |

Example CI usage:

```bash
export OBSERVAL_SERVER_URL=https://observal.your-company.internal
export OBSERVAL_API_KEY=<key>

observal ops traces --limit 100 --output json | jq
```

## Related

- [Self-Hosting → Configuration](../self-hosting/configuration.md), narrative view, grouped by concern
- [Config files](config-files.md), `~/.observal/` file layout
