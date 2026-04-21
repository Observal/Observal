# Ports and volumes

Every exposed port and persistent volume, at a glance.

## Host ports (default)

| Service | Host port | Env var (to remap) | Protocol |
| --- | --- | --- | --- |
| API | 8000 | `API_HOST_PORT` | HTTP / WebSocket |
| Web UI | 3000 | `WEB_HOST_PORT` | HTTP |
| Postgres | 5432 | `POSTGRES_HOST_PORT` | TCP |
| ClickHouse | 8123 | `CLICKHOUSE_HOST_PORT` | HTTP |
| Redis | 6379 | `REDIS_HOST_PORT` | TCP |
| OTEL Collector (gRPC) | 4317 | `OTEL_GRPC_HOST_PORT` | gRPC |
| OTEL Collector (HTTP) | 4318 | `OTEL_HTTP_HOST_PORT` | HTTP |
| Grafana | 3001 | `GRAFANA_HOST_PORT` | HTTP |

The worker has no exposed port — it talks to Redis and ClickHouse internally only.

### Remap on startup

```bash
POSTGRES_HOST_PORT=5433 REDIS_HOST_PORT=6380 \
  docker compose -f docker/docker-compose.yml up --build -d
```

### Checking port conflicts

```bash
# macOS / Linux
lsof -nP -iTCP:5432 -sTCP:LISTEN
lsof -nP -iTCP:6379 -sTCP:LISTEN

# Windows (PowerShell)
netstat -ano | findstr :5432
```

## Persistent volumes

All volumes are named and managed by Docker — they survive `docker compose down` but are deleted by `docker compose down -v`.

| Volume | Mount point | Contents | Loss impact |
| --- | --- | --- | --- |
| `pgdata` | `/var/lib/postgresql/data` | Postgres data (users, registry, RBAC) | Catastrophic — all accounts, agents, MCPs lost |
| `chdata` | `/var/lib/clickhouse` | ClickHouse data (traces, spans, scores) | High — all telemetry lost; accounts and registry survive |
| `redisdata` | `/data` | Redis persistence | Low — job queue lost; pending jobs need to be re-kicked |
| `grafanadata` | `/var/lib/grafana` | Grafana dashboards and config | Medium — custom dashboards lost; defaults are re-provisioned |
| `apidata` | `/data` (API container) | **JWT signing keys** | Catastrophic — every session invalidated, users must re-login; backup/restore required |

**Back up `apidata` and `pgdata` before any upgrade.** See [Backup and restore](backup-and-restore.md).

## Security posture defaults

The stack uses hardened defaults out of the box:

* **Read-only root filesystem** on `observal-api`, `observal-worker`, `observal-web`, `observal-otel-collector` (tmpfs for `/tmp`).
* **`no-new-privileges`** on every service.
* **Memory limits** on all services (see [Requirements](requirements.md#hardware)).
* **Health checks** on Postgres, ClickHouse, Redis, API.
* **Bridge network** (`observal-net`) isolates inter-service traffic.

## Internal DNS

Inside the compose network, services resolve each other by service name:

| From | To | URL |
| --- | --- | --- |
| API / worker | Postgres | `postgresql+asyncpg://postgres:postgres@observal-db:5432/observal` |
| API / worker | ClickHouse | `clickhouse://default:clickhouse@observal-clickhouse:8123/observal` |
| API / worker | Redis | `redis://observal-redis:6379` |
| Web | API | `http://observal-api:8000` |

The CLI running on your host machine resolves via `localhost:<host port>`.

## Next

→ [Databases](databases.md)
