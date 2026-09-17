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
3. The SQL dialect is rewritten once, in place. No runtime translator, no
   dual-backend query layer. DuckDB is deleted from the application at the
   end of the cutover; the only DuckDB-aware code that remains is the
   source side of the one-way migration tool.
4. Migration is one-way (DuckDB -> DuckDB). There is no reverse tool.

## Schema mapping rules

| DuckDB | DuckDB |
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

The migration is one-way and the ClickHouse source is never modified, so every
step is safe to repeat and rollback is "redeploy the previous release".

1. **Start the DuckDB service alongside the running stack.**
   Compose: `docker compose up -d observal-duckdb` from the new release.
   Helm: apply the chart; the `duckdb` StatefulSet comes up without touching the
   ClickHouse release. Confirm `curl http://<host>:8484/health` reports
   `{"status":"ok"}`.
2. **Copy the telemetry across.**
   `observal server migrate duckdb --clickhouse-url <ch> --duckdb-url <duckdb>
   --duckdb-token "$DUCKDB_ANALYTICS_TOKEN" --export-dir ./telemetry-export`
   The command fails with a categorized error if any exported row is missing or
   a fresh table took fewer rows than the manifest expects.
3. **Deploy the new application version** (init, api, worker) and let the init
   container finish Postgres migrations. Analytics migrations are applied by the
   DuckDB service itself at boot; the init container no longer touches them.
4. **Verify before declaring success:** `/health` shows `"analytics":"ok"`,
   the sessions and insights pages render, one session detail opens, and
   `observal doctor support` shows the analytics tables with expected counts.
5. **Keep ClickHouse for a rollback window.** Leave its volume in place (no
   writes arrive once the new version is live). Rollback = redeploy the previous
   release; the ClickHouse data is exactly as the migration left it.
6. **Decommission** the ClickHouse service, volume, and any Terraform/Helm
   resources once the rollback window closes. Take a final DuckDB snapshot
   (daily S3 backup or `POST /admin/backup`) before deleting anything.
