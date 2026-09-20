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
| ``ReplacingMergeTree(v) ORDER BY k`` + ``FINAL`` | logical identity keys + serialized, transactional batch deduplication and replacement |
| ``AggregatingMergeTree`` + ``SimpleAggregateFunction`` | plain columns + writer-side recomputation (``refresh_session_summary``) |
| ``MATERIALIZED VIEW session_stats_mv`` | removed; the ingest path already recomputes summaries explicitly |
| projections / ``bloom_filter`` skip indexes | DuckDB zone maps; mutable ART indexes are avoided on replay-heavy telemetry tables |
| ``TTL`` | ``services/retention.py`` ``DELETE`` + periodic ``CHECKPOINT`` |
| ``system.parts`` materialization probes | removed |
| ``{name:Type}`` query parameters | service-side named parameters (``$name``) |
| ``countIf/sumIf/anyIf/minIf/maxIf/anyLastIf`` | ``COUNT(*) FILTER (WHERE ...)``, ``MIN/MAX(...) FILTER``, ``arg_max`` |

Exports keep the ClickHouse exporter's monthly layout (``<table>_<YYYY>-<MM>.parquet``).
The service writes them with a single partitioned ``COPY``, so each file also
carries the partition value as ``_analytics_month``; importers select the
declared table columns and ignore it. Rows whose time column is NULL land in
``<table>_null.parquet``.

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
> topology cannot be upgraded with only `docker compose pull`. The compose
> topology, an analytics token, and every telemetry row must move before the
> new API starts.

### Automatic cutover (Docker Compose deployments)

`observal server upgrade` performs the cutover itself when it finds a legacy
deployment (a ClickHouse compose file or a `.env` with `CLICKHOUSE_URL`, plus
this project's `observal-clickhouse` container and no completion marker):

```bash
observal self upgrade          # the CLI must be upgraded first
observal server upgrade        # add --dry-run to see the plan
```

The upgrade then runs, in order. It briefly pauses the legacy API and workers
so no telemetry can arrive after the export cutoff. A failure before deployment
restores the legacy compose file and resumes those exact containers:

1. Pauses the legacy API and workers, then backs up PostgreSQL
   (`~/.observal/config/backups/`). ClickHouse is never written to.
2. Installs the release `docker-compose.yml`/`nginx.conf` from the GitHub
   release bundle (server-package installs) and keeps the old file as
   `docker-compose.clickhouse.bak.yml`. Source checkouts must already have
   pulled the new compose file; the command says so if not.
3. Provisions `DUCKDB_ANALYTICS_TOKEN`/`DUCKDB_ANALYTICS_URL` (secrets files for
   server-package installs, `.env` entries for source checkouts). Existing
   values are never overwritten.
4. Starts only `observal-duckdb` next to the running ClickHouse and waits for
   its **authenticated** `/version` endpoint.
5. Exports every telemetry table from ClickHouse to Parquet, loads it into
   DuckDB, and verifies checksums and row counts. Any missing row aborts the
   upgrade.
6. Pulls and starts the new release, then health-checks it. If the health check
   fails the legacy compose file is restored and the previous version restarted.
7. Re-verifies `/health` reports `analytics: ok` and the DuckDB row counts hold.
8. Stops the ClickHouse container (its volume is kept for archival only) and
   writes `.observal-cutover-complete.json` in the deployment directory.
   This permanently pins the deployment to DuckDB.

Running `observal server upgrade` again is a normal upgrade: the marker file
tells it the cutover already happened, and it will never start ClickHouse.

After successful cutover, `observal server rollback` is an **application rollback
on DuckDB**, never a return to ClickHouse. It accepts only releases at or above
the marker's `to_version`, the first verified DuckDB release for this deployment.
Older targets are rejected before restoring data or changing configuration;
`server upgrade --version` enforces the same boundary. The DuckDB compose,
secrets, and completion marker remain in place, even if rollback fails.
Do not restore `docker-compose.clickhouse.bak.yml` after a completed cutover.
The retained ClickHouse volume is an archive, not a live rollback target; it
does not contain telemetry written since cutover. If no compatible backup
exists yet, deploy a corrected DuckDB-compatible release instead.

### Manual runbook (Helm, Terraform, or when automation is not possible)

The migration is one-way and the ClickHouse source is never modified. Before
cutover completes, a failed deployment can resume the legacy stack. After
successful cutover, application rollback must retain DuckDB and use a
DuckDB-compatible release; never restore the old ClickHouse topology.
**Helm and Terraform users must complete step 4 before `helm upgrade` /
`terraform apply`: those remove the ClickHouse source.**

1. **Update the CLI, then back up the existing deployment and preserve its
   files.** Download the `observal-server-v<VERSION>.tar.gz` asset from the target GitHub release into
   a temporary directory. Do not extract it over the live directory yet. Keep
   the old compose file and ClickHouse volume for failed-cutover recovery and archival.
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
7. **Retire ClickHouse after verification.** Stop its container and retain its
   volume for archival only. Application rollback must keep the DuckDB topology
   and use a DuckDB-compatible release. Never restart ClickHouse after cutover.
8. **Decommission** the archived ClickHouse container and volume when retention
   requirements allow. Verify a DuckDB backup first.

### Embedded server cutover

For an installation managed by `observal server start`, the cutover is
automatic:

```bash
observal server stop
observal self upgrade
observal server start
```

The pre-DuckDB embedded ClickHouse listened on port 8124, which the DuckDB
analytics service now owns, and the old `server stop` left ClickHouse running
under the previous CLI. On start the new CLI therefore stops any ClickHouse
process recorded in `~/.observal/run/clickhouse.pid`, starts DuckDB, relaunches
the legacy ClickHouse binary on a temporary port (18124) against its existing
data directory, migrates and verifies every table, stops it again, and writes
`~/.observal/data/.clickhouse-cutover-complete.json`. The start fails (and the
API is not launched) if verification fails; `~/.observal/data/clickhouse` is
never modified and can be deleted once you are satisfied.
