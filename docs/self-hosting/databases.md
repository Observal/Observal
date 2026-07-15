<!-- SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Databases

Observal runs two DBs with very different jobs.

| DB | Role | Access pattern | Schema source of truth |
| --- | --- | --- | --- |
| Postgres 16 | Registry, users, config | Relational, transactional | Alembic migrations in `observal-server/alembic/versions/` |
| ClickHouse 26.5 | Telemetry and audit event storage | Columnar, time-series, high-write | Versioned SQL migrations in `observal-server/clickhouse/migrations/` |

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

Run migrations manually if needed:

```bash
observal migrate
```

(Requires the `migrate` extra: `uv tool install 'observal-cli[migrate]'`.)

For rolling deploys, run `observal migrate` once as a pre-deploy step before bringing up the new API image.

### Reset

To wipe the registry and start over:

```bash
docker compose -f docker/docker-compose.yml down -v
docker compose -f docker/docker-compose.yml up --build -d
```

The `-v` deletes all named volumes. Use only in dev.

---

## ClickHouse

### What's in it

Core tables:

| Table | Contents |
| --- | --- |
| `session_events` | Raw and parsed harness JSONL lines, token fields, tool fields, and session metadata |
| `session_stats_agg` | Pre-aggregated session list and summary metrics from `session_events` |
| `layer_snapshots` | Harness config snapshots used by version-aware insights |
| `audit_log` | Enterprise audit events |
| `security_events` | Security events for login, auth, and admin activity |
| `webhook_deliveries` | Alert webhook delivery attempts and status |

### Deduplication and aggregates

`session_events` and `layer_snapshots` use `ReplacingMergeTree` for idempotent ingest. `session_stats_agg` uses `AggregatingMergeTree` and is maintained by a materialized view.

The API query layer handles the required `FINAL` or aggregate reads. If you query ClickHouse directly, match the table engine instead of assuming every table reads the same way.

### Retention (TTL)

Controlled by `DATA_RETENTION_DAYS`:

* Default `90`: rows older than 90 days are TTL'd out.
* `0`: retention disabled (disk grows without bound).
* The server enforces a minimum of `7` on any non-zero value.

TTL runs asynchronously. Disk space is reclaimed on the next merge; don't expect instant free-up.

### Schema migrations

ClickHouse schema changes are managed separately from Alembic. Alembic is only for Postgres.

ClickHouse migration files live in:

```bash
observal-server/clickhouse/migrations/*.sql
```

The init container runs ClickHouse migrations after Alembic and before the API starts. The migration runner records applied files in `clickhouse_schema_migrations`.

On existing installations that predate versioned ClickHouse migrations, the runner detects the existing baseline tables and stamps `001_baseline.sql` as applied instead of replaying the whole baseline.

For local checks outside Docker, run the same runner from the server package:

```bash
cd observal-server
python -m services.clickhouse.migrations
```

Do not put ClickHouse DDL in startup code. Add a new migration file instead.

### Capacity planning

Rule of thumb: **~1 KB per span**.

* 10K spans/day × 90-day retention ≈ 900 MB
* 100K spans/day × 90-day retention ≈ 9 GB
* 1M spans/day × 90-day retention ≈ 90 GB

Plan 2–3× headroom for merges and replicas.

### External ClickHouse

For heavy workloads, run ClickHouse outside the compose stack (ClickHouse Cloud, a dedicated VM, etc.). Point the API at it:

```
CLICKHOUSE_URL=clickhouse://user:pass@external-clickhouse.example.com:8123/observal
```

Remove the `observal-clickhouse` service from `docker-compose.yml` or ignore it.

---

## Backup

See [Backup and restore](backup-and-restore.md). Short version:

* Postgres: `pg_dump` from a running container.
* ClickHouse: snapshot the `chdata` volume, or use ClickHouse's native `BACKUP` command.
* Both: back up before every upgrade.

## Next

→ [Authentication and SSO](authentication.md)
