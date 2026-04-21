# Troubleshooting

Common failure modes and their fixes. If none of these match, open a [GitHub Discussion](https://github.com/BlazeUp-AI/Observal/discussions) with the output of `observal auth status` and relevant logs from `docker compose logs`.

## Install and CLI

### `"Connection failed. Is the server running?"`

The CLI cannot reach the API. Check:

```bash
docker compose -f docker/docker-compose.yml ps     # API status
curl http://localhost:8000/health                  # API health
observal config show                               # is server_url right?
```

If `server_url` is wrong:

```bash
observal config set server_url http://localhost:8000
observal auth login
```

### `"System already initialized"` when logging in

The server already has users, so bootstrap is disabled. Use `observal auth login` with an email + password or an API key — not a fresh bootstrap flow.

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

* ClickHouse stuck during initial `CREATE TABLE` — restart it once the healthcheck passes on other DBs
* `CLICKHOUSE_PASSWORD` mismatch between services and API config

### Services restart in a loop

Check logs (`docker compose logs -f <service>`). Three frequent causes:

* Memory limit too tight — bump limits in `docker-compose.yml`
* Corrupt volume — wipe and restore from backup
* Config error introduced during an upgrade — roll back

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

# 2. Is the telemetry buffer flushing?
observal ops sync

# 3. Is the shim wired in?
observal doctor --ide <ide>

# 4. Is the API reachable from where the shim runs?
curl http://localhost:8000/health
```

If the shim is wrapped but traces aren't arriving, the shim may be silently dropping events because the API is unreachable. Check `~/.observal/telemetry_buffer.db` — if it's growing, that's exactly the issue.

### `observal scan` wraps 0 servers

Your IDE's MCP config may be empty or in a non-standard location. Check:

```bash
cat .kiro/settings/mcp.json         # Kiro project
cat ~/.kiro/settings/mcp.json       # Kiro global
cat ~/.claude/settings.json         # Claude Code
cat .cursor/mcp.json                # Cursor
cat .vscode/mcp.json                # VS Code
cat .gemini/settings.json           # Gemini CLI
```

If none exist, configure at least one MCP server in your IDE first, then re-run `scan`.

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

## Evaluation

### Scorecards return empty or all zeros

* `EVAL_MODEL_NAME` probably isn't set. Without a real judge, scoring falls back to heuristics.
* If Bedrock: verify `bedrock:InvokeModel` IAM permission for the configured model.
* Tail API logs during an `observal admin eval run`:
  ```bash
  docker compose -f docker/docker-compose.yml logs -f observal-api
  ```

### `boto3.NoCredentialsError`

AWS credentials aren't reaching the API container. Check `.env`:

```
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1
```

For temporary credentials, also set `AWS_SESSION_TOKEN`.

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
* You're on HTTP behind a proxy that's setting `secure` cookies — terminate TLS at your proxy and keep `FRONTEND_URL=https://...`.

## Where to get more help

* Logs: `docker compose -f docker/docker-compose.yml logs -f`
* Health: `curl http://localhost:8000/health`
* Status: `observal auth status`
* Community: [GitHub Discussions](https://github.com/BlazeUp-AI/Observal/discussions)
* Bugs: [GitHub Issues](https://github.com/BlazeUp-AI/Observal/issues) — please use Discussions for questions, Issues only for confirmed bugs
