<!-- SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# Configuration

Boot-time infrastructure and secret settings live in `.env`. Runtime settings, including SSO, live in the admin UI as dynamic settings. Defaults are sane for local development.

## Required for production

Override these before going live:

| Variable               | Default                        | Why change                                                                                                                         |
| ---------------------- | ------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------- |
| `SECRET_KEY`           | `change-me-to-a-random-string` | Session signing key. **The server refuses to start with this default when a license is configured.** Generate a real one. |
| `POSTGRES_PASSWORD`    | `postgres`                     | Default password is not secure.                                                                                                    |
| `CLICKHOUSE_PASSWORD`  | `clickhouse`                   | Same.                                                                                                                              |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:3000`        | Scope to your real frontend origin(s). Configure as `deployment.cors_origins` in Admin Settings.                                   |
| `deployment.frontend_url` | `http://localhost:3000`     | Used for OAuth redirects and email links. Configure in Admin Settings.                                                             |

Generate a secret key:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

## SSO-only mode

Set `deployment.sso_only=true` in **Admin → SSO** when you want IdP-only access. Leave it `false` to keep password login available.

## Enterprise license key

```
OBSERVAL_LICENSE_KEY=
```

Set this to your Ed25519-signed license key to enable enterprise features such as SAML and AI insight reports. Leave it unset for community edition. The server validates the key at startup and logs the result.

The `setup.sh` interactive setup and both installer scripts (`install.sh`, `install-server.sh`) also accept the key via `--license-key` or this env var and write it into `.env` automatically.

## Demo accounts

Seeded on first startup _only_ when no users exist:

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

**Unset every `DEMO_*` env var before a real deployment.** Existing demo users survive after unsetting. Delete them manually (`observal admin delete-user <email>`).

> **Admin settings warning:** If demo accounts are still active or `SECRET_KEY` is insecure, the admin Settings page will display a warning banner at the top so operators can spot and fix the issue without digging through logs.

## Database connections

```
DATABASE_URL=postgresql+asyncpg://postgres:postgres@observal-db:5432/observal
CLICKHOUSE_URL=clickhouse://default:clickhouse@observal-clickhouse:8123/observal
REDIS_URL=redis://observal-redis:6379
```

Inside Docker Compose, hostnames resolve via the `observal-net` bridge (e.g. `observal-db`). Outside Docker (e.g. CLI running on host against dockerized DBs), use `localhost:<port>`.

## OAuth / SSO

Optional. Configure OIDC, SAML, and SSO-only mode in **Admin → SSO**. OIDC client changes are stored immediately, then take effect after the API restarts.

Full setup in [Authentication and SSO](authentication.md).

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

Traces, spans, and scores older than this are TTL'd by ClickHouse. Set to `0` to disable retention (keep everything forever, and disk grows without bound). The minimum non-zero value enforced on startup is 7.

## JWT keys

```
JWT_SIGNING_ALGORITHM=ES256        # ES256 (default) or RS256
JWT_KEY_DIR=/data/keys             # persisted in the apidata volume
```

The server generates asymmetric keys on first boot and stores them in `$JWT_KEY_DIR`. **Back up this directory**: losing the keys invalidates every session.

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

Not set in `.env` on the server. These live on the CLI user's machine.

| Variable                                     | Purpose                          |
| -------------------------------------------- | -------------------------------- |
| `OBSERVAL_SERVER_URL`                        | Default server URL               |
| `OBSERVAL_ACCESS_TOKEN` / `OBSERVAL_API_KEY` | Pre-authenticate without `login` |
| `OBSERVAL_TIMEOUT`                           | Request timeout (seconds)        |

Full list: [Environment variables](../reference/environment-variables.md).

## Next

→ [Ports and volumes](ports-and-volumes.md)
