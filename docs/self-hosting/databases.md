<!-- SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Databases

Observal runs two DBs with very different jobs.

| DB | Role | Access pattern | Schema source of truth |
| --- | --- | --- | --- |
| Postgres 16 | Registry, users, config | Relational, transactional | Alembic migrations in `observal-server/alembic/versions/` |
| DuckDB 1.5 | Telemetry and audit event storage | Columnar, single-writer file, analytic reads | Versioned SQL migrations in `observal-server/analytics/migrations/` |

## Postgres

### What's in it

* `users`, `roles`, RBAC bindings
* `mcps`, `agents`, `skills`, `hooks`, `prompts`, `sandboxes`: registry metadata
* `reviews`: submission review state
* `feedback`, `ratings`
* `alerts`, `alert_history`
* `api_keys`
* `audit_log` and related audit tables

### Migrations

Managed by Alembic. The server applies pending migrations automatically on startup. Migration files live in `observal-server/alembic/versions/`.

For Docker Compose deployments, run the init service manually when needed:

```bash
docker compose -f docker/docker-compose.yml run --rm observal-init
```

The init service applies Alembic and DuckDB migrations before API startup. `observal server migrate` moves data between deployments; it does not apply schema migrations.

### Reset

To wipe the registry and start over:

```bash
docker compose -f docker/docker-compose.yml down -v
docker compose -f docker/docker-compose.yml up --build -d
```

The `-v` deletes all named volumes. Use only in dev.

---

## DuckDB

### What's in it

Core tables:

| Table | Contents |
| --- | --- |
| `session_events` | Raw and parsed harness JSONL lines, token fields, tool fields, and session metadata |
| `session_stats_agg` | Pre-aggregated session list and summary metrics from `session_events` |
| `layer_snapshots` | Harness config snapshots used by version-aware insights |
| `audit_log` | Audit events |
| `security_events` | Security events for login, auth, and admin activity |
| `webhook_deliveries` | Alert webhook delivery attempts and status |

### Single writer and deduplication

One service container (`observal-duckdb`) owns the analytics database file and is its only writer; every other process reaches it over HTTP on port 8484. Never mount the same data directory into a second writer — DuckDB (and the service's own lock file) will refuse the second process.

Idempotent ingest is expressed with primary keys rather than merge engines:

* `session_events`, `session_checkpoints`, `session_stats_agg`, and `layer_snapshots` have primary keys; writes use `INSERT OR REPLACE`, so re-ingested rows replace the previous version.
* `audit_log`, `security_events`, and `webhook_deliveries` are append-only.
* `session_stats_agg` is recomputed by the ingest path (`refresh_session_summary`); there is no materialized view.

Reads do not need `FINAL`: each primary key holds exactly one row.

### Retention (TTL)

Controlled by the `data.retention_days` setting:

* Default `90`: the retention job deletes rows older than 90 days.
* `0`: retention disabled (disk grows without bound).
* The server enforces a minimum of `7` on any non-zero value.

Deletes free space inside the file lazily; the worker also checkpoints the write-ahead log on a schedule. Plan for periodic compaction headroom rather than expecting instant shrink.

### Schema migrations

DuckDB schema changes are managed separately from Alembic. Alembic is only for Postgres.

DuckDB migration files live in:

```bash
observal-server/analytics/migrations/*.sql
```

The DuckDB service applies pending migrations at boot, before it accepts queries, and records them in `analytics_schema_migrations`. The init container does not touch analytics DDL.

Each migration file is checksummed; changing an applied file is rejected so two deployments cannot silently diverge.

For local checks outside Docker, run the same runner from the server package:

```bash
cd docker
docker compose run --rm --no-deps observal-duckdb /app/.venv/bin/python -m services.analytics.duckdb.migrations
```

Do not put DuckDB DDL in startup code. Add a new migration file instead.

### Capacity planning

Session record size depends on harness transcript detail and tool output size. Measure representative sessions, apply the configured raw-line retention window, and plan 2 to 3 times headroom for merges and replicas.

### Migrating an existing ClickHouse deployment

Older Observal releases stored telemetry in ClickHouse. Those installations migrate once with the one-way command:

```bash
observal server migrate duckdb \
  --clickhouse-url clickhouse://default:clickhouse@observal-clickhouse:8123/observal \
  --duckdb-url duckdb://observal-duckdb:8484/observal \
  --duckdb-token "$DUCKDB_ANALYTICS_TOKEN" \
  --export-dir ./telemetry-export
```

See [Data migration](data-migration.md) and the [CLI reference](../cli/migrate.md) for the full flow, verification output, and rollback guidance.

---

## Backup

See [Backup and restore](backup-and-restore.md). Short version:

* Postgres: `pg_dump` from a running container.
* DuckDB: checkpoint the service, then snapshot the `duckdbdata` volume (or use the service's `/admin/backup` export).
* Both: back up before every upgrade.

## Next

→ [Authentication and SSO](authentication.md)
