# Databases

Observal runs two DBs with very different jobs.

| DB | Role | Access pattern | Schema source of truth |
| --- | --- | --- | --- |
| Postgres 16 | Registry, users, config | Relational, transactional | Alembic migrations in `observal-server/alembic/versions/` |
| ClickHouse 26.3 | Telemetry (traces, spans, scores) | Columnar, time-series, high-write | Auto-created by the server at startup |

## Postgres

### What's in it

* `users`, `roles`, RBAC bindings
* `mcps`, `agents`, `skills`, `hooks`, `prompts`, `sandboxes` — registry metadata
* `reviews` — submission review state
* `feedback`, `ratings`
* `alerts`, `alert_history`
* `scorecards`, `eval_runs`, `scoring_dimensions`, `penalties`, `dimension_weights`
* `api_keys`
* Enterprise: `audit_log`, `scim_users`, `scim_groups` (when enabled)

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

Four user-facing tables, all `ReplacingMergeTree` with soft deletes via `is_deleted` + `event_ts`:

| Table | Contents |
| --- | --- |
| `traces` | Trace headers — trace_id, parent_trace_id, trace_type, agent_id, session_id, mcp_id, start/end time, input, output, metadata, tags |
| `spans` | Individual span records — span_id, trace_id, parent_span_id, type, name, method, input, output, error, latency_ms, status, token counts, cost, retry count |
| `scores` | Eval results — score_id, trace_id, span_id, dimension name, numeric / string value, comment, metadata |
| `audit_log` | Enterprise audit events (enterprise-only) |

Plus two legacy tables retained for backward compat: `mcp_tool_calls`, `agent_interactions`.

### Deduplication

Because everything is `ReplacingMergeTree`, queries should use `FINAL` to force dedup:

```sql
SELECT * FROM traces FINAL WHERE agent_id = '...'
```

The API does this for you in its query surface. If you're querying ClickHouse directly (e.g. from Grafana), remember `FINAL`.

### Retention (TTL)

Controlled by `DATA_RETENTION_DAYS`:

* Default `90` — rows older than 90 days are TTL'd out.
* `0` — retention disabled (disk grows without bound).
* The server enforces a minimum of `7` on any non-zero value.

TTL runs asynchronously. Disk space is reclaimed on the next merge; don't expect instant free-up.

### Auto-creation at startup

The server runs `CREATE TABLE IF NOT EXISTS` for every telemetry table on startup. If ClickHouse is unavailable when the API boots, the API still starts — but telemetry ingestion and dashboard queries silently fail until ClickHouse is back.

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
