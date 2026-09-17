<!-- SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Srihari <sriharilegend23@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Troubleshooting

Common failure modes and their fixes. If none of these match, open a [GitHub Discussion](https://github.com/Observal/Observal/discussions) with the output of `observal auth status` and relevant logs from `docker compose logs`.

## Install and CLI

### `"Connection failed. Is the server running?"`

The CLI cannot reach the API. Check:

```bash
docker compose -f docker/docker-compose.yml ps     # API status
curl http://localhost/health                       # API health
observal config show                               # is server_url right?
```

If `server_url` is wrong:

```bash
observal config set server_url http://localhost
observal auth login
```

### `"System already initialized"` when logging in

The server already has users, so bootstrap is disabled. Use `observal auth login` with an email + password or an API key, not a fresh bootstrap flow.

## Docker and networking

### `port is already allocated`

Another process is on one of Observal's default ports. Remap host ports:

```bash
POSTGRES_HOST_PORT=5433 REDIS_HOST_PORT=6380 \
  docker compose -f docker/docker-compose.yml up --build -d
```

Full list in [Ports and volumes](ports-and-volumes.md).

### Service stuck in `starting`

The API depends on Postgres, DuckDB, and Redis being healthy. Check each:

```bash
docker compose -f docker/docker-compose.yml ps
docker compose -f docker/docker-compose.yml logs observal-db
docker compose -f docker/docker-compose.yml logs observal-duckdb
docker compose -f docker/docker-compose.yml logs observal-redis
```

Common causes:

* DuckDB stuck during initial `CREATE TABLE`. Restart it once the healthcheck passes on other DBs
* `DUCKDB_ANALYTICS_TOKEN` mismatch between services and API config

### Services restart in a loop

Check logs (`docker compose logs -f <service>`). Three frequent causes:

* Memory limit too tight. Bump limits in `docker-compose.yml`
* Corrupt volume. Wipe and restore from backup
* Config error introduced during an upgrade. Roll back

## Auth

### Admin forgot password

```bash
observal auth reset-password --email admin@demo.example
```

Then read the reset code from the server log:

```bash
docker logs observal-api 2>&1 | grep "PASSWORD RESET CODE"
```

Enter the code when the CLI prompts.

### OAuth login fails with `redirect_uri_mismatch`

The IdP doesn't have the right redirect URI registered. Add:

```
{FRONTEND_URL}/api/v1/auth/oauth/callback
```

with `FRONTEND_URL` set to your real external URL (scheme and host must match exactly).

### All users logged out after restart

Likely the `apidata` volume was recreated, so the JWT signing keys are new. Restore the `apidata` volume from backup, or accept that all sessions are invalid and everyone has to log in again.

## Telemetry

### Nothing in the dashboard

Run through, in order:

```bash
# 1. Are sessions arriving at all?
observal ops telemetry status

# 2. Are session hooks installed for the harness?
observal doctor --output json

# 3. Is the API reachable from the harness environment?
curl http://localhost/health
```

If hooks are missing, run `observal doctor patch --harness <harness>`. If sessions still are not arriving, check `~/.observal/telemetry_buffer.db`; growth indicates pending session delivery rather than silent loss.

### DuckDB not receiving data

Check the `DUCKDB_ANALYTICS_URL` the API is using:

```bash
docker compose -f docker/docker-compose.yml exec observal-api \
  printenv DUCKDB_ANALYTICS_URL
```

The Compose default is `duckdb://observal-duckdb:8484/observal`. Check that the API's `DUCKDB_ANALYTICS_TOKEN` matches the service's token; a mismatch returns HTTP 401 from every analytics call.

Server-package installs use `DUCKDB_ANALYTICS_URL_FILE=/run/secrets/duckdb_analytics_url` and `DUCKDB_ANALYTICS_TOKEN_FILE=/run/secrets/duckdb/duckdb_analytics_token` (the token lives in the `duckdb/` sub-directory, which the analytics service mounts as its own `/run/secrets`). Confirm the files are readable by each side without printing them:

```bash
docker compose exec observal-api test -r /run/secrets/duckdb_analytics_url
docker compose exec observal-api test -r /run/secrets/duckdb/duckdb_analytics_token
docker compose exec observal-duckdb test -r /run/secrets/duckdb_analytics_token
```

Verify DuckDB itself:

```bash
docker compose -f docker/docker-compose.yml exec observal-duckdb \
  /app/.venv/bin/python -c "import json,urllib.request; \
print(urllib.request.urlopen(urllib.request.Request('http://localhost:8484/query', data=json.dumps({'sql': 'SELECT count(*) AS rows FROM session_events'}).encode(), headers={'Content-Type': 'application/json'})).read().decode())"
```

## Web UI

### Blank white page

Frontend is still building. Check:

```bash
docker compose -f docker/docker-compose.yml logs -f observal-web
```

For local dev (running Next.js outside Docker), verify `NEXT_PUBLIC_API_URL` in `web/.env.local` matches your backend.

### Login redirects back to login immediately

Browser cookies aren't being set. Usually one of:

* `FRONTEND_URL` doesn't match the URL you're hitting.
* `CORS_ALLOWED_ORIGINS` doesn't include your frontend origin.
* You're on HTTP behind a proxy that's setting `secure` cookies. Terminate TLS at your proxy and keep `FRONTEND_URL=https://...`.

## Where to get more help

* Logs: `docker compose -f docker/docker-compose.yml logs -f`
* Health: `curl http://localhost/health`
* Status: `observal auth status`
* Community: [GitHub Discussions](https://github.com/Observal/Observal/discussions)
* Bugs: [GitHub Issues](https://github.com/Observal/Observal/issues). Please use Discussions for questions, Issues only for confirmed bugs
