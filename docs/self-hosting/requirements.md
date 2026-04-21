# Requirements

Minimum and recommended specs for running the Observal stack.

## Hardware

| Profile | CPU | Memory | Disk | Who it's for |
| --- | --- | --- | --- | --- |
| Developer | 2 vCPU | 4 GB | 20 GB | One engineer, local machine |
| Small team (≤10) | 2 vCPU | 6 GB | 50 GB | Small org, moderate telemetry |
| Team (10–50) | 4 vCPU | 12 GB | 200 GB + fast SSD | Typical production deployment |
| Large team (50+) | 8+ vCPU | 32 GB | 500 GB + fast SSD | High telemetry volume; consider externalizing ClickHouse |

The stack's Docker memory limits out-of-the-box:

| Service | Limit |
| --- | --- |
| `observal-api` | 512 MB |
| `observal-worker` | 512 MB |
| `observal-web` | 256 MB |
| `observal-clickhouse` | 1 GB |
| `observal-redis` | 256 MB |
| `observal-otel-collector` | 256 MB |
| `observal-grafana` | 512 MB |

ClickHouse is the memory-hungry one. On a long-running team server, bump it to 2–4 GB in `docker/docker-compose.yml`.

## Disk: where the data goes

The heaviest user of disk is **ClickHouse** (traces, spans, scores). Growth depends on:

* Number of agents
* Traces per agent per day
* `DATA_RETENTION_DAYS` (default 90; TTL handled by ClickHouse)

Rule of thumb: **~1 KB per span**. A team running 10K spans/day at 90-day retention will accumulate ~900 MB of ClickHouse data. Plan 2–3× headroom.

Postgres stays under 500 MB for most deployments — it holds only registry metadata and user accounts.

## Software

| Software | Version | Notes |
| --- | --- | --- |
| Docker | ≥ 24.0 | With Compose v2 (`docker compose`, not `docker-compose`) |
| Linux / macOS host | any modern | Windows via WSL2 works |
| Bash / zsh | any | For the CLI install |

For the **CLI** (developer machines, not the server):

* Python **3.11, 3.12, or 3.13**
* Any of `uv` (recommended), `pipx`, or `pip`

## Network

* **Outbound HTTPS** — only needed to pull Docker images on first `docker compose up --build`. Not needed at runtime (the stack is fully self-contained).
* **Inbound** — users hit the API (`:8000`), web (`:3000`), and optionally OTEL (`:4317` gRPC or `:4318` HTTP).
* **Between services** — the private `observal-net` bridge handles all of it.

If your eval model is Bedrock or a cloud-hosted OpenAI-compatible endpoint, the API and worker need outbound access to that endpoint. A fully-offline eval path is available with a local Ollama or vLLM deployment.

## TLS / HTTPS

Docker Compose does not terminate TLS. For production, put a reverse proxy in front (nginx, Caddy, Traefik) and terminate TLS there. Point it at `localhost:8000` (API) and `localhost:3000` (web).

Example (Caddy):

```caddyfile
observal.your-company.internal {
  reverse_proxy /api/* localhost:8000
  reverse_proxy /* localhost:3000
}
```

## Next

→ [Docker Compose setup](docker-compose.md)
