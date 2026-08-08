<!-- SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Environment variables

Complete reference for security-relevant server and CLI environment variables. Defaults are in `.env.example` and built into the CLI.

## File-backed values

Every credential listed with file support accepts `NAME_FILE=/path/to/secret` instead of `NAME=value`. Files must be UTF-8, are limited to 64 KiB, and may end with one newline. Configuring both forms is an error. The server-package installer writes generated credentials to operator-owned files under `secrets/`, with read access limited to the configured container service group.

## Server (`observal-server`)

### Core / security

| Variable                 | Default                        | Description                                                                                                                                                   |
| ------------------------ | ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SECRET_KEY`             | `change-me-to-a-random-string` | Application encryption secret. Supports `SECRET_KEY_FILE`. Generate a random value of at least 32 characters. |
| `OLD_SECRET_KEY`         | unset                          | Previous secret during encrypted-setting rotation. Supports `OLD_SECRET_KEY_FILE`. |
| `FRONTEND_URL`           | `http://localhost:3000`        | External frontend URL (OAuth redirects, email links)                                                                                                          |
| `CORS_ALLOWED_ORIGINS`   | `http://localhost:3000`        | Comma-separated allowed CORS origins                                                                                                                          |
| `MAX_REQUEST_SIZE_MB`    | `10`                           | Maximum request body size                                                                                                                                     |
| `RATE_LIMIT_AUTH`        | `10/minute`                    | General auth-endpoint rate limit                                                                                                                              |
| `RATE_LIMIT_AUTH_STRICT` | `5/minute`                     | Login and password-reset rate limit                                                                                                                           |

### Databases

| Variable              | Default                                                          | Description                                                 |
| --------------------- | ---------------------------------------------------------------- | ----------------------------------------------------------- |
| `DATABASE_URL`        | `postgresql+asyncpg://postgres:postgres@localhost:5432/observal` | Postgres connection string. Supports `DATABASE_URL_FILE`. |
| `POSTGRES_USER`       | `postgres`                                                       | Postgres container user |
| `POSTGRES_PASSWORD`   | container-specific                                              | Direct Postgres password for existing installs |
| `POSTGRES_PASSWORD_FILE` | unset                                                        | PostgreSQL native password-file input |
| `CLICKHOUSE_URL`      | `clickhouse://localhost:8123/observal`                           | ClickHouse endpoint. Supports `CLICKHOUSE_URL_FILE`. |
| `CLICKHOUSE_USER`     | `default`                                                        | ClickHouse user |
| `CLICKHOUSE_PASSWORD` | container-specific                                              | Direct ClickHouse password for existing installs |
| `REDIS_URL`           | `redis://localhost:6379`                                         | Redis connection string. Supports `REDIS_URL_FILE`. |
| `DATA_RETENTION_DAYS` | `90`                                                             | ClickHouse TTL in days. `0` disables. Minimum non-zero: `7` |

### SSO

OIDC, SAML, and SSO-only mode are configured in **Admin → SSO** and stored in dynamic settings. OIDC client changes require an API restart. Existing direct `OAUTH_*`, `SSO_ONLY`, and `SAML_*` values are imported once when the matching database setting is empty.

File-backed forms such as `OAUTH_CLIENT_SECRET_FILE`, `GOOGLE_OAUTH_CLIENT_SECRET_FILE`, `GITHUB_OAUTH_CLIENT_SECRET_FILE`, `INSIGHTS_API_KEY_FILE`, `SAML_IDP_X509_CERT_FILE`, and `SAML_SP_KEY_ENCRYPTION_PASSWORD_FILE` remain in memory and are not imported into PostgreSQL or Redis. `SAML_SP_PRIVATE_KEY_FILE` and `SAML_SP_X509_CERT_FILE` must be configured together and override generated database SP material.

### JWT signing

| Variable                | Default                                                     | Description                                             |
| ----------------------- | ----------------------------------------------------------- | ------------------------------------------------------- |
| `JWT_SIGNING_ALGORITHM` | `ES256`                                                     | `ES256` or `RS256`                                      |
| `JWT_KEY_DIR`           | `~/.observal/keys` (outside Docker) / `/data/keys` (Docker) | Directory for generated signing keys. **Back this up.** |
| `JWT_KEY_PASSWORD`      | unset                                                       | Optional private-key encryption password. Supports `JWT_KEY_PASSWORD_FILE`. |

### AWS (Bedrock)

> **Note:** Bedrock now supports [API keys](https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys.html) — generate one from the AWS console and use it like any other provider. See [Insights LLM Setup](https://github.com/Observal/Observal/blob/main/docs/insights-setup.md).

These environment variables are **not required** if you use Bedrock API keys (recommended). They exist only for legacy setups using instance roles or ECS task roles where LiteLLM auto-discovers credentials from the environment.

| Variable                | Default     | Description                                 |
| ----------------------- | ----------- | ------------------------------------------- |
| `AWS_ACCESS_KEY_ID`     | -           | Only for legacy IAM auth (not recommended)  |
| `AWS_SECRET_ACCESS_KEY` | -           | Only for legacy IAM auth (not recommended)  |
| `AWS_SESSION_TOKEN`     | -           | Temporary credentials (STS AssumeRole)      |
| `AWS_REGION_NAME`       | `us-east-1` | AWS region (used by LiteLLM's boto3 client) |

### Git operations (submission analysis)

| Variable               | Default          | Description                                                                     |
| ---------------------- | ---------------- | ------------------------------------------------------------------------------- |
| `ALLOW_INTERNAL_URLS`  | `false`          | Allow internal/private Git URLs (for GitLab / GHE)                              |
| `GIT_CLONE_TOKEN`      | -                | Auth token for private repos. Supports `GIT_CLONE_TOKEN_FILE`.                                                    |
| `GIT_CLONE_TOKEN_USER` | `x-access-token` | Token username: `x-access-token` (GitHub), `oauth2` or `private-token` (GitLab) |
| `GIT_CLONE_TIMEOUT`    | `120`            | Clone timeout, seconds                                                          |

### Demo accounts (seeded on first startup if no users exist)

| Variable                    | Default                 |
| --------------------------- | ----------------------- |
| `DEMO_SUPER_ADMIN_EMAIL`    | `super@demo.example`    |
| `DEMO_SUPER_ADMIN_PASSWORD` | unset; generated by server-package setup |
| `DEMO_ADMIN_EMAIL`          | `admin@demo.example`    |
| `DEMO_ADMIN_PASSWORD`       | unset; generated by server-package setup |
| `DEMO_REVIEWER_EMAIL`       | `reviewer@demo.example` |
| `DEMO_REVIEWER_PASSWORD`    | unset; generated by server-package setup |
| `DEMO_USER_EMAIL`           | `user@demo.example`     |
| `DEMO_USER_PASSWORD`        | unset; generated by server-package setup |

Each demo password supports its corresponding `_FILE` form. Remove demo variables and files before a real deployment.

### Docker host ports

Used only by Docker Compose. Prometheus and Grafana ports apply only when `docker-compose.observability.yml` is included. Remap if a default is already in use.

| Variable               | Default | Service                   |
| ---------------------- | ------- | ------------------------- |
| `OBSERVAL_BIND_ADDRESS` | `127.0.0.1` in the server package | Host address for published ports. A non-loopback value is explicit remote exposure. |
| `API_HOST_PORT`        | `8000`  | API (internal, behind LB) |
| `WEB_HOST_PORT`        | `3000`  | Web UI                    |
| `POSTGRES_HOST_PORT`   | `5432`  | Postgres                  |
| `CLICKHOUSE_HOST_PORT` | `8123`  | ClickHouse                |
| `REDIS_HOST_PORT`      | `6379`  | Redis                     |
| `PROMETHEUS_HOST_PORT` | `9090`  | Prometheus, optional      |
| `GRAFANA_HOST_PORT`    | `3001`  | Grafana, optional         |

### Grafana

Only used when the optional Grafana overlay or Terraform `observability_stack = "grafana"` is enabled.

| Variable                 | Default | Description            |
| ------------------------ | ------- | ---------------------- |
| `GRAFANA_ADMIN_USER`     | `admin` | Grafana admin username |
| `GRAFANA_ADMIN_PASSWORD` | `admin` | Direct Grafana admin password for existing installs |
| `GRAFANA_ADMIN_PASSWORD_FILE` | generated file in server package | Grafana password file |

## CLI (`observal-cli`)

Read from the environment at invocation time. Override values in `~/.observal/config.json` per invocation.

| Variable                | Default                        | Description                                                 |
| ----------------------- | ------------------------------ | ----------------------------------------------------------- |
| `OBSERVAL_SERVER_URL`   | from `~/.observal/config.json` | Server URL                                                  |
| `OBSERVAL_ACCESS_TOKEN` | from `~/.observal/config.json` | Access token (preferred for CI)                             |
| `OBSERVAL_API_KEY`      | from `~/.observal/config.json` | API key alias for `OBSERVAL_ACCESS_TOKEN` |
| `OBSERVAL_TOKEN`        | from `~/.observal/config.json` | CI token alias with highest legacy precedence |
| `OBSERVAL_TIMEOUT`      | `30`                           | HTTP timeout in seconds |

The three token variables support `OBSERVAL_ACCESS_TOKEN_FILE`, `OBSERVAL_API_KEY_FILE`, and `OBSERVAL_TOKEN_FILE`. When multiple aliases are present, the legacy precedence remains `OBSERVAL_TOKEN`, then `OBSERVAL_API_KEY`, then `OBSERVAL_ACCESS_TOKEN`.

Example CI usage:

```bash
export OBSERVAL_SERVER_URL=https://observal.your-company.internal
export OBSERVAL_API_KEY=<key>

observal ops traces --limit 100 --output json | jq
```

## Related

* [Self-Hosting → Configuration](../self-hosting/configuration.md), narrative view, grouped by concern
* [Config files](config-files.md), `~/.observal/` file layout
