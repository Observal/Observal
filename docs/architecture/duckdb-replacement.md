<!-- SPDX-FileCopyrightText: 2026 Observal contributors -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# DuckDB replacement for DuckDB (ADR)

Status: accepted
Date: 2026-09-17

## Context

DuckDB is the analytics store behind session telemetry, audit logs, security
events, webhook deliveries, layer snapshots, retention, dashboards, and insights.
It is reached exclusively over HTTP (``POST`` to ``:8123``) through
``services/analytics/duckdb``.

Two earlier attempts are abandoned:

- ``feat/duckdb-port`` embedded DuckDB in-process, which turned DuckDB's
  single-writer rule into a cross-service invariant (WAL permissions, restart
  races, single-writer guards).
- ``feat/duckdb-analytics-service`` grew a parallel typed analytics API
  (~66k lines) instead of replacing the store.

## Decision

1. DuckDB runs as a dedicated service container (``observal-duckdb``) that owns
   ``/data/analytics.duckdb`` as the only writer process and exposes an HTTP SQL
   interface. Every other service keeps talking to analytics the same way it
   talks to DuckDB today: over HTTP.
2. ``services/analytics`` becomes the only analytics client surface. It mirrors
   the shape of ``services/analytics/duckdb`` (``_query``/``_execute``/``_insert``,
   health, timestamp helpers) so call sites change SQL dialect, not plumbing.
3. The SQL dialect is rewritten once, in place. No runtime translator or
   dual-backend query layer remains. ClickHouse is deleted from the application
   at the end of the cutover; the only ClickHouse-aware code that remains is
   the source side of the one-way migration tool.
4. Migration is one-way (ClickHouse -> DuckDB). There is no reverse tool.

## Schema mapping rules

| ClickHouse | DuckDB |
|---|---|
| ``LowCardinality(String)`` / ``String`` | ``VARCHAR`` |
| ``DateTime64(3, 'UTC')`` | ``TIMESTAMP`` (UTC convention, microsecond-capable superset) |
| ``UInt8/16/32/64`` | ``UTINYINT/USMALLINT/UINTEGER/UBIGINT`` |
| ``Int32/Int64`` | ``INTEGER/BIGINT`` |
| ``Float32/64`` | ``FLOAT/DOUBLE`` |
| ``UUID`` | ``VARCHAR`` (callers already pass strings; avoids 128-bit ordering drift) |
| ``ReplacingMergeTree(v) ORDER BY k`` + ``FINAL`` | ``PRIMARY KEY k`` + ``INSERT OR REPLACE`` |
| ``AggregatingMergeTree`` + ``SimpleAggregateFunction`` | plain columns + writer-side recomputation (``refresh_session_summary``) |
| ``MATERIALIZED VIEW session_stats_mv`` | removed; the ingest path already recomputes summaries explicitly |
| projections / ``bloom_filter`` skip indexes | ART indexes on lookup columns, validated with ``EXPLAIN ANALYZE`` |
| ``TTL`` | ``services/retention.py`` ``DELETE`` + periodic ``CHECKPOINT`` |
| ``system.parts`` materialization probes | removed |
| ``{name:Type}`` query parameters | service-side named parameters (``$name``) |
| ``countIf/sumIf/anyIf/minIf/maxIf/anyLastIf`` | ``COUNT(*) FILTER (WHERE ...)``, ``MIN/MAX(...) FILTER``, ``arg_max`` |

## Consequences

- One writer process keeps DuckDB honest; no shared volume between services.
- Backup/restore becomes file-based (``EXPORT DATABASE``), not "managed
  DuckDB". Single-node storage semantics must be documented for helm and
  terraform consumers.
- Grafana has no DuckDB datasource. Decision: the eight ClickHouse-backed
  dashboards and the ClickHouse datasource were deleted; the shipped Grafana
  stack is infrastructure-only (`self-observability` stays) and telemetry
  dashboards live in the in-app admin surfaces.
- Verification of the migration relies on parity tests: the same Parquet export
  loaded into both engines, identical logical queries, diffed results.

## Rejected alternatives

- **Embedded DuckDB in the API/worker processes** — reintroduces cross-process
  write coordination on a network filesystem and makes every service a writer.
- **SQL dialect translator in front of DuckDB** — DuckDB SQL is not a superset
  of ClickHouse SQL; ``FINAL``, aggregate combinators, and ``SETTINGS`` clauses
  would need an unreliable shim. The 60-odd statements are better rewritten.
- **Keeping ClickHouse behind a runtime switch forever** — the project's hard
  rewrite policy and the goal ("full replacement") rule this out.

## Parity check (2026-09-17)

Method: 20,000 synthetic `session_events` rows (200 sessions, four harnesses,
three event types) loaded over HTTP into a single-node ClickHouse 26.6 container
and into the `observal-duckdb` service on the same host; the summary table was
rebuilt in each engine with its own aggregate SQL; then the five query shapes
the application issues were timed 15 times each (p50/p95, milliseconds).

| Query shape | ClickHouse p50 / p95 | DuckDB p50 / p95 |
|---|---|---|
| Session list (dashboard) | 8.5 / 12.8 | **4.2 / 7.4** |
| Session detail (trace view) | 4.4 / 4.8 | **3.8 / 5.2** |
| Dashboard aggregate | 4.6 / 11.2 | **2.0 / 4.9** |
| Insight aggregate (per agent) | 7.8 / 13.5 | **2.7 / 7.0** |
| Dedup lookup (ingest) | 4.0 / 5.3 | **2.0 / 3.0** |

Bulk load of the same 20k rows: ClickHouse 2.6 s, DuckDB 0.5 s.

Caveats: one host, one process, warm caches, 20k rows — this is a directional
check that the ported queries and indexes hold up, not a capacity test. Large
multi-million-row scans and concurrent writer behaviour under sustained ingest
still need the full workload benchmark before a production cutover.

### Scale check (200k rows)

The same harness with 200,000 events (2,000 sessions, six query shapes including
a wide 60-day aggregate) and HTTP ingest through each engine's own protocol:

| Measure | ClickHouse | DuckDB |
|---|---|---|
| Ingest throughput | 15,107 rows/s | **30,661 rows/s** |
| Session list | 22.5 ms | **6.1 ms** |
| Session detail | **6.0 ms** | 6.6 ms |
| Dashboard aggregate | 15.6 ms | **3.3 ms** |
| Insight aggregate | 22.3 ms | **3.7 ms** |
| Dedup lookup | 3.4 ms | **3.0 ms** |
| Wide 60-day aggregate | 66.8 ms | **16.3 ms** |

Caveats unchanged: single host, single writer, warm caches, synthetic rows. The
remaining unknown is sustained concurrent ingest alongside dashboard traffic; the
single-writer topology bounds that to one writer process by construction, so the
risk is queueing latency rather than correctness.

## Cutover runbook

> **Breaking deployment change:** a deployment using the ClickHouse compose
> topology cannot be upgraded with only `docker compose pull`. The release
> compose file and analytics token must be installed, and telemetry must be
> copied before the new API is started. `observal server upgrade` detects the
> legacy topology and stops with this runbook instead of attempting a lossy
> upgrade and rollback.

The migration is one-way and the ClickHouse source is never modified, so every
step is safe to repeat and rollback is "redeploy the previous release".

1. **Update the CLI, then back up the existing deployment and preserve its
   files.** Download the `observal-server-v<VERSION>.tar.gz` asset from the target GitHub release into
   a temporary directory. Do not extract it over the live directory yet. Keep
   the old compose file and ClickHouse volume until the rollback window closes.
2. **Install the new deployment files without replacing configuration.** Copy
   `docker-compose.yml`, `nginx.conf`, and supporting observability files from
   the release archive into the deployment directory. Keep the existing `.env`
   and `secrets/` directory. Run `setup.sh`; when it detects the existing
   configuration, choose to keep it. The script creates the missing
   `secrets/duckdb/duckdb_analytics_token` file and adds only the required
   DuckDB secret references to `.env`. For source checkouts instead, generate a
   strong `DUCKDB_ANALYTICS_TOKEN` in `.env` before starting DuckDB.
3. **Start only DuckDB alongside ClickHouse.** Run
   `docker compose up -d observal-duckdb`. Do not use `--remove-orphans` yet;
   the old ClickHouse container must remain available. Confirm the authenticated
   endpoint, not just liveness:
   `curl -H "Authorization: Bearer $(cat secrets/duckdb/duckdb_analytics_token)" http://127.0.0.1:8484/version`.
4. **Copy the telemetry across.** Run:
   `observal server migrate duckdb --clickhouse-url <ch> --duckdb-url <duckdb>
   --duckdb-token "$DUCKDB_ANALYTICS_TOKEN" --export-dir ./telemetry-export`.
   The command fails if any checksum differs or any exported row is missing.
5. **Deploy the new application version** (init, API, and worker) and let the
   init container finish PostgreSQL migrations. Analytics migrations are applied
   by the DuckDB service itself at boot.
6. **Verify before declaring success:** `/health` shows `"analytics":"ok"`,
   the sessions and insights pages render, one session detail opens, and
   `observal doctor support` shows the analytics tables with expected counts.
7. **Keep ClickHouse for a rollback window.** Leave its volume in place. Rollback
   means restoring the old compose file and redeploying the previous release.
8. **Decommission** the ClickHouse container and volume only after the rollback
   window. Take a final DuckDB snapshot first.

### Embedded server cutover

For an installation managed by `observal server start`, keep the old server
running while updating the CLI, then stop and restart it with the new CLI. The
legacy ClickHouse process and data directory are intentionally not deleted.
The new DuckDB service uses port 8484 while the legacy ClickHouse process remains
on 8123, so run step 4 against `clickhouse://127.0.0.1:8123/observal` and
`duckdb://127.0.0.1:8484/observal`. Verify the migration before stopping the
legacy ClickHouse process or removing its data. Release binaries include the
migration runtime; source or minimal pip installations need the migration extra
(`pip install 'observal-cli[migrate]'`).
