<!--
SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
SPDX-License-Identifier: Apache-2.0
-->

# Resource Tuning

Connection pool sizes, query limits, and timeout configuration. These settings control how Observal connects to its backing stores (PostgreSQL, Redis, DuckDB). Most deployments work fine with defaults. Tune when you see connection timeouts, pool exhaustion, or slow queries under load.

## When to Tune

- **Connection pool errors** in API logs ("pool exhausted", "connection timeout")
- **Slow dashboard loads** under concurrent users (increase pool sizes)
- **OOM kills** on the API container (decrease pool sizes, each connection uses memory)
- **DuckDB query timeouts** on large trace datasets (increase timeout)

## PostgreSQL {#postgresql}

### DB Pool Size {#db-pool-size}

Number of persistent database connections maintained in the connection pool.

| Value | Effect |
|-------|--------|
| `10` (default) | Suitable for small teams (< 20 concurrent users) |
| `20` | Medium deployments (20-100 users) |
| `50` | Large deployments (100+ concurrent users) |

**Memory impact:** Each connection uses approximately 5MB of RAM on the API server.

**When to increase:** You see "pool exhausted" errors or requests queuing during peak usage.

**When to decrease:** Running on memory-constrained containers, or your PostgreSQL instance has a low `max_connections` limit.

### DB Max Overflow {#db-max-overflow}

Temporary connections created when the pool is full. These are closed after use.

| Value | Effect |
|-------|--------|
| `20` (default) | Allows bursts of up to 30 total connections (pool + overflow) |
| `0` | No overflow; requests wait for a pool connection (safest for DB) |
| `50` | High burst tolerance; use when traffic is very spiky |

**Total max connections** = pool_size + max_overflow. Ensure your PostgreSQL `max_connections` is at least this value plus a buffer for admin connections.

## Redis {#redis}

### Redis Max Connections {#redis-max-connections}

Maximum concurrent connections to Redis.

| Value | Effect |
|-------|--------|
| `50` (default) | Handles most workloads |
| `100` | High-traffic deployments with heavy pub/sub (GraphQL subscriptions) |
| `20` | Constrained environments with limited Redis resources |

**When to increase:** "Connection pool exhausted" errors in Redis client logs, or high latency on GraphQL subscriptions.

### Redis Timeout {#redis-timeout}

Socket timeout in seconds for Redis operations.

| Value | Effect |
|-------|--------|
| `2.0` (default) | Balanced; detects failures quickly without false positives |
| `5.0` | Use when Redis is on a high-latency network (cross-region) |
| `1.0` | Aggressive; faster failure detection but may false-positive on slow queries |

**When to increase:** Redis is in a different availability zone or region, causing occasional timeout errors on valid operations.

## DuckDB {#analytics}

Analytics settings split in two: connection limits and timeouts are boot-time
environment variables, while memory and thread tuning is pushed to the running
service from the admin Resource Tuning card (or re-applied with
`POST /api/v1/admin/resources/apply`).

### DuckDB Connections and Timeouts (environment)

| Variable | Default | Effect |
|----------|---------|--------|
| `DUCKDB_ANALYTICS_MAX_CONNECTIONS` | `100` | HTTP connection pool between api/worker and the analytics service |
| `DUCKDB_ANALYTICS_TIMEOUT` | `30.0` | Client-side timeout for a single analytics request |

Per-query execution limits belong to the service container:
`DUCKDB_QUERY_TIMEOUT` (default `60`), `DUCKDB_MAX_RESULT_ROWS` (default
`100000`), and `DUCKDB_READ_CONNECTIONS` (default `4`).

### Skip DDL on Startup {#skip-ddl-on-startup}

Skip PostgreSQL schema creation on server startup (`SKIP_DDL_ON_STARTUP`).

| Value | Effect |
|-------|--------|
| `false` (default) | The API creates missing Postgres tables at boot |
| `true` | Skip that step when the init container already prepared the database |

Analytics DDL is never applied by the API: the DuckDB service runs its own
versioned migrations before it accepts queries.

### Query Memory Limit {#query-memory-limit}

`resource.max_query_memory_mb` — memory ceiling applied to every analytics
connection (`PRAGMA memory_limit`).

| Value | Effect |
|-------|--------|
| `1024` (default) | 1 GB ceiling; enough for dashboard and trace queries |
| `4096` | Heavy insight generation on large session sets |
| `512` | Small deployments sharing a host with other services |

**When to increase:** the service logs an out-of-memory error while generating
insights or dashboards over wide time ranges.

### DuckDB Threads {#analytics-threads}

`resource.threads` — worker threads DuckDB uses per query (`PRAGMA threads`).

| Value | Effect |
|-------|--------|
| `4` (default) | Balanced for a shared 4–8 vCPU host |
| `8` | Faster scans when the analytics host has spare cores |
| `2` | Keeps the API responsive when analytics shares its host |

### DuckDB Temp Directory {#analytics-temp-directory}

`resource.temp_directory` — where DuckDB spills larger-than-memory operations.
Empty means DuckDB's default (next to the database file).

| Value | Effect |
|-------|--------|
| empty (default) | Spills inside the analytics volume |
| `/data/tmp` | Pin spills to the data volume explicitly |
| a fast local disk | Faster large sorts/joins when the volume is network-attached |

### Spills and Large Sorts {#analytics-spills}

DuckDB spills GROUP BY, ORDER BY, and hash joins to disk automatically once they
exceed the memory ceiling; there is no per-operator spill threshold to tune.
Control the spill location with `resource.temp_directory` and the overall
ceiling with `resource.max_query_memory_mb`. If wide-range insight reports spill
constantly, give the analytics container a faster disk before raising the memory
limit.
