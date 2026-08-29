# DuckDB analytics store (ClickHouse replacement)

Observal's analytics store is now **embedded DuckDB**. ClickHouse is removed from the
runtime path: no container, no HTTP interface, no credentials.

## Architecture

- `observal-server/services/duckdb/` — the real implementation:
  - `client.py` — process-wide connection (RLock + `asyncio.to_thread`), `_query()`
    returning an httpx-shaped `QueryResult`, and a **compatibility layer** that
    auto-translates legacy ClickHouse syntax (`{name:Type}` placeholders, `FINAL`,
    `FORMAT JSON`, trailing `SETTINGS`, `count()`, `now64(3)`, `toUnixTimestamp64Milli`,
    `INTERVAL {n:Type} UNIT`, `toUInt64`). Unused named params are dropped (DuckDB
    rejects them; legacy callers pass them).
    `{name:Array(T)}` placeholders are coerced from stringified ClickHouse literals
    (e.g. `"['a','b']"`) into real Python LIST parameters and `IN ($name)` is
    rewritten to `= ANY($name)` — DuckDB rejects LIST params bound to `IN (?)`.
    `QueryResult.json()` keeps the ClickHouse `rows` key alongside `data`.
  - `insert.py` — batch inserts via Arrow relations (DuckDB `executemany` and
    row-at-a-time `INSERT OR REPLACE` are both pathologically slow; the Arrow scan +
    set merge path is ~30k rows/s and preserves column DEFAULTs).
    `ReplacingMergeTree` semantics are preserved with PRIMARY KEY + `INSERT OR REPLACE`
    (dedup at write time — no `FINAL` anywhere).
  - `query.py`, `migrations.py`, `schema.py` — query helpers, versioned SQL runner,
    runtime init + resource pragmas.
- `observal-server/services/clickhouse/` — **deprecated shim** re-exporting the DuckDB
  implementation under the legacy names. All existing imports keep working.
- `observal-server/duckdb/migrations/001_baseline.sql` — consolidated final-state
  schema (squashes legacy CH migrations 001–004).
- `observal-server/clickhouse/migrations/` — kept as legacy reference for data
  migration tooling and the benchmark (`scripts/bench_duckdb_vs_clickhouse.py`).

## Deployment topology (important)

DuckDB is single-process read-write. Therefore:

- `API_WORKERS` must be **1** (compose default changed).
- The arq background worker runs **inside the API process** (`EMBEDDED_WORKER=true`,
  default). The standalone `observal-worker` compose service is removed.
- `DUCKDB_PATH` (default `data/observal.duckdb`) must be on a persistent volume
  (`/data/duckdb` in compose).
- `DUCKDB_READ_ONLY=true` opens the file read-only (multiple read-only processes may
  share a file, but then no writes are possible from that process).

## Behaviour preserved from ClickHouse

- **TTLs** (730d audit/security logs, 30d `raw_line` scrub) — now explicit statements
  in `services/retention.py::_purge_global_tables`, run by the retention cron.
- **Rollup table** (`session_stats_agg`) — maintained in app code by
  `refresh_session_summary()` exactly as before (the CH materialized view is gone).
- **Maintenance job** — `maintain_clickhouse` is now `maintain_duckdb` (legacy alias
  kept); `OPTIMIZE TABLE` becomes `CHECKPOINT`.
- **Value types** — `QueryResult.json()` renders timestamps/dates as ClickHouse-style
  strings so downstream consumers (JSON export, string slicing) behave identically.

## Known differences / follow-ups

- **Storage footprint**: DuckDB is ~3–4x larger on disk than ClickHouse for
  `raw_line`-heavy data (FSST vs ZSTD(3)). Both are trivially small at Observal scale;
  query latency and ingest rate favour DuckDB (see `scripts/bench_duckdb_vs_clickhouse.py`).
- **Deployment-migration jobs** (`scope=clickhouse|both`) are rejected with a clear
  error; DuckDB archive export/import is follow-up work.
- **observal_cli installer / server-package / observability compose / Grafana
  dashboards** still reference ClickHouse and are follow-up work.
- `CLICKHOUSE_URL` and related env vars are accepted but ignored.

## Benchmark

```
python ../scripts/bench_duckdb_vs_clickhouse.py --clickhouse-url http://localhost:18123 \
    --sessions 2000 --events 500 --audit-rows 500000
```

(requires `docker run -p 18123:8123 -e CLICKHOUSE_PASSWORD=clickhouse clickhouse/clickhouse-server:26.6`)
