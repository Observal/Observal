# Docker Compose setup

Step-by-step bring-up of the Observal stack. End state: eight healthy containers, API responding at `http://localhost:8000/health`, web UI at `http://localhost:3000`.

## 1. Clone and configure

```bash
git clone https://github.com/BlazeUp-AI/Observal.git
cd Observal
cp .env.example .env
```

The `.env.example` ships with working defaults for every setting, including demo account credentials. You do not need to edit it for local development.

## 2. Start the stack

```bash
docker compose -f docker/docker-compose.yml up --build -d
```

First build takes a few minutes (pulls images, builds `observal-api` and `observal-web`). Subsequent starts are fast.

## 3. Verify health

```bash
docker compose -f docker/docker-compose.yml ps
```

Every service should show `healthy` or `running`. The API waits for Postgres, ClickHouse, and Redis to pass health checks before starting — expect 15–30 seconds on first boot.

Hit the API health endpoint directly:

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

## 4. Configure a reverse proxy (production only)

For local dev, `http://localhost:3000` and `http://localhost:8000` are fine. For production, see [Requirements → TLS / HTTPS](requirements.md#tls--https).

## 5. Bootstrap the first user

### Option A — demo accounts (fastest for trying it out)

`.env.example` seeds four demo accounts on first startup:

| Role | Email | Password |
| --- | --- | --- |
| Super Admin | `super@demo.example` | `super-changeme` |
| Admin | `admin@demo.example` | `admin-changeme` |
| Reviewer | `reviewer@demo.example` | `reviewer-changeme` |
| User | `user@demo.example` | `user-changeme` |

Log in with the CLI:

```bash
uv tool install observal-cli     # if you haven't already
observal auth login              # Email: super@demo.example, Password: super-changeme
```

**Remove demo accounts before real deployment.** Unset the `DEMO_*` env vars in `.env` and restart. Already-seeded accounts stay until you delete them manually (`observal admin delete-user <email>`).

### Option B — fresh bootstrap (recommended for production)

Remove `DEMO_*` from `.env` and start the stack. Run:

```bash
observal auth login
# Server URL: http://localhost:8000
# No users detected — bootstrapping admin account.
# Email: alice@your-company.com
# Password: **************
```

The CLI detects that no users exist and interactively creates the first admin. The `/api/v1/auth/bootstrap` endpoint is restricted to localhost access for security.

## 6. Verify with the CLI

```bash
observal auth whoami
observal auth status

observal ops overview              # summary dashboard
observal registry mcp list         # empty list — you haven't added anything yet
```

## 7. Stop, restart, rebuild

```bash
# Stop
docker compose -f docker/docker-compose.yml down

# Stop + DELETE all data (wipes volumes — be careful)
docker compose -f docker/docker-compose.yml down -v

# Restart one service
docker compose -f docker/docker-compose.yml restart observal-api

# Rebuild after code changes
docker compose -f docker/docker-compose.yml up --build -d observal-api
```

Makefile shortcuts from the repo root:

```bash
make logs       # tail all service logs
make rebuild    # rebuild and restart everything
```

## 8. Logs

```bash
docker compose -f docker/docker-compose.yml logs -f                # all
docker compose -f docker/docker-compose.yml logs -f observal-api   # one service
```

## 9. Port conflicts

If `docker compose up` fails with `port is already allocated`, remap host ports via env vars:

```bash
POSTGRES_HOST_PORT=5433 REDIS_HOST_PORT=6380 \
  docker compose -f docker/docker-compose.yml up --build -d
```

Every host port is configurable. See [Ports and volumes](ports-and-volumes.md) for the full list.

## Next

→ [Configuration](configuration.md) — which env vars to change for production.
