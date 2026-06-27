<!-- SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

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

### `observal-shim` not found

The shim didn't end up on your `PATH`. Reinstall:

```bash
uv tool install --force observal-cli
which observal-shim           # macOS/Linux
where observal-shim           # Windows
```

## Docker and networking

### `port is already allocated`

Another process is on one of Observal's default ports. Remap host ports:

```bash
POSTGRES_HOST_PORT=5433 REDIS_HOST_PORT=6380 \
  docker compose -f docker/docker-compose.yml up --build -d
```

Full list in [Ports and volumes](ports-and-volumes.md).

### Service stuck in `starting`

The API depends on Postgres, ClickHouse, and Redis being healthy. Check each:

```bash
docker compose -f docker/docker-compose.yml ps
docker compose -f docker/docker-compose.yml logs observal-db
docker compose -f docker/docker-compose.yml logs observal-clickhouse
docker compose -f docker/docker-compose.yml logs observal-redis
```

Common causes:

* ClickHouse stuck during initial `CREATE TABLE`. Restart it once the healthcheck passes on other DBs
* `CLICKHOUSE_PASSWORD` mismatch between services and API config

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
# 1. Are traces arriving at all?
observal ops telemetry status

# 2. Is the shim wired in?
observal doctor --harness <harness>

# 3. Is the API reachable from where the shim runs?
curl http://localhost/health
```

If the shim is wrapped but traces aren't arriving, the shim may be silently dropping events because the API is unreachable. Check `~/.observal/telemetry_buffer.db`. If it's growing, that's exactly the issue.

### `observal doctor patch` wraps 0 servers

Your harness's MCP config may be empty or in a non-standard location. Check:

```bash
cat .kiro/settings/mcp.json         # Kiro project
cat ~/.kiro/settings/mcp.json       # Kiro global
cat ~/.claude/settings.json         # Claude Code
cat .cursor/mcp.json                # Cursor
cat .vscode/mcp.json                # VS Code
```

If none exist, configure at least one MCP server in your harness first, then re-run `doctor patch`.

### ClickHouse not receiving data

Check the `CLICKHOUSE_URL` the API is using:

```bash
docker compose -f docker/docker-compose.yml exec observal-api \
  printenv CLICKHOUSE_URL
```

Default inside Docker: `clickhouse://default:clickhouse@observal-clickhouse:8123/observal`. Mismatches typically happen after you change `CLICKHOUSE_PASSWORD` without updating the URL.

Verify ClickHouse itself:

```bash
docker compose -f docker/docker-compose.yml exec observal-clickhouse \
  clickhouse-client --query "SELECT count() FROM observal.spans"
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
