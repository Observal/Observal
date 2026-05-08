# observal migrate

Portable migration tools for moving an Observal instance between environments. The workflow has two phases:

* **Phase 1 (shallow copy)** — exports PostgreSQL registry data (users, agents, components, feedback, eval runs, etc.) to a `.tar.gz` archive of JSONL files.
* **Phase 2 (deep copy)** — exports ClickHouse telemetry data (traces, spans, scores, audit logs, security events) to monthly Parquet files.

Phase 2 depends on Phase 1. You must complete the shallow copy export and import before running the deep copy.

All migrate commands require **admin** or **super_admin** role.

### Prerequisites

The migrate commands require the `migrate` extra:

```bash
pip install 'observal-cli[migrate]'
```

This installs `asyncpg` (PostgreSQL driver) and `pyarrow` (Parquet I/O). Without it, the commands exit with an install hint.

---

## Phase 1: Shallow Copy (PostgreSQL)

### observal migrate export

Export all PostgreSQL registry data to a portable `.tar.gz` archive.

#### Synopsis

```bash
observal migrate export --db-url <postgres-url> [--output <path>]
```

#### Options

| Option | Description |
| --- | --- |
| `--db-url` | Source PostgreSQL connection string (required). Accepts `postgresql://` or `postgresql+asyncpg://` (dialect prefix is stripped automatically). |
| `--output`, `-o` | Output archive path. Defaults to `observal-export-<timestamp>.tar.gz` in the current directory. |

#### What it exports

All registry tables in dependency order:

* Organizations, enterprise config, component sources
* Users, exporter configs
* All component listings (MCPs, skills, hooks, prompts, sandboxes)
* Agents, agent goal templates, agent components
* Validation results, downloads, submissions
* Feedback, alert rules, alert history
* Eval runs, scorecards, scorecard dimensions

The export uses a `REPEATABLE READ` transaction for a consistent snapshot. No data is modified on the source.

#### Output

The archive contains:

* `manifest.json` — schema version, migration ID, table checksums, row counts, source Alembic version
* `migration_manifest.json` — used by Phase 2 as a gate (must exist before telemetry export)
* `pg/<table>.jsonl` — one JSONL file per table

A sidecar `<archive-name>.manifest.json` is written alongside the archive for Phase 2 consumption.

#### Example

```bash
observal migrate export \
  --db-url "postgresql://postgres:postgres@localhost:5432/observal" \
  --output ./migration/observal-export.tar.gz
```

```
Exporting to: ./migration/observal-export.tar.gz

✓ Export complete
  Archive:    ./migration/observal-export.tar.gz
  Migration:  a1b2c3d4-...
  Tables:     28
  Rows:       1,247
  Size:       0.8 MB
  Duration:   3.2s

⚠  Archive contains hashed credentials (passwords, API keys).
   Store securely and delete after import.
```

---

### observal migrate import

Import a migration archive into the target PostgreSQL database.

#### Synopsis

```bash
observal migrate import --db-url <postgres-url> --archive <path>
```

#### Options

| Option | Description |
| --- | --- |
| `--db-url` | Target PostgreSQL connection string (required) |
| `--archive`, `-a` | Path to the `.tar.gz` archive from `export` (required) |

#### Behavior

* Inserts rows in FK-safe order (same as `INSERT_ORDER`)
* Skips rows that already exist (matched by primary key)
* Reports inserted vs skipped counts per table
* Tables that don't exist on the target (older schema) are skipped gracefully

#### Example

```bash
observal migrate import \
  --db-url "postgresql://postgres:postgres@localhost:5432/observal" \
  --archive ./migration/observal-export.tar.gz
```

```
Importing from: ./migration/observal-export.tar.gz

✓ Import complete
  Migration:  a1b2c3d4-...
  Tables:     28
  Inserted:   1,247
  Skipped:    0
  Duration:   5.1s
```

---

### observal migrate validate

Validate archive integrity and optionally compare against a live database.

#### Synopsis

```bash
observal migrate validate --archive <path> [--db-url <postgres-url>]
```

#### Options

| Option | Description |
| --- | --- |
| `--archive`, `-a` | Path to the `.tar.gz` archive (required) |
| `--db-url` | Optional target database for cross-validation (row count comparison) |

#### What it checks

1. **Checksum verification** — SHA-256 of each JSONL file matches the manifest
2. **Cross-database comparison** (when `--db-url` provided) — row counts in the archive vs the live database

#### Example

```bash
observal migrate validate \
  --archive ./migration/observal-export.tar.gz \
  --db-url "postgresql://postgres:postgres@localhost:5432/observal"
```

```
Checksum verification:
  ✓ organizations
  ✓ users
  ✓ mcp_listings
  ...

✓ All checksums valid

Row count comparison:
  ✓ organizations: 1
  ✓ users: 12
  ✓ mcp_listings: 34
  ...

✓ All row counts match
```

---

## Phase 2: Deep Copy (ClickHouse Telemetry)

### observal migrate export-telemetry

Export ClickHouse telemetry tables to monthly Parquet files.

#### Synopsis

```bash
observal migrate export-telemetry \
  --clickhouse-url <url> \
  --manifest <path> \
  --output-dir <dir>
```

#### Options

| Option | Description |
| --- | --- |
| `--clickhouse-url` | Source ClickHouse connection string (required). Format: `clickhouse://user:pass@host:port/db` |
| `--manifest` | Path to the `migration_manifest.json` from Phase 1 (required). Acts as a gate — Phase 1 must be complete. |
| `--output-dir` | Directory for exported Parquet files (required). Must be empty or non-existent. |

#### What it exports

| Table | Engine | Time column | Description |
| --- | --- | --- | --- |
| `traces` | ReplacingMergeTree | `start_time` | Top-level trace records |
| `spans` | ReplacingMergeTree | `start_time` | Individual span records |
| `scores` | ReplacingMergeTree | `timestamp` | Eval and feedback scores |
| `audit_log` | MergeTree | `timestamp` | Audit trail entries |
| `otel_logs` | MergeTree | `Timestamp` | OpenTelemetry log records |
| `security_events` | MergeTree | `timestamp` | Security event records |
| `webhook_deliveries` | MergeTree | `timestamp` | Webhook delivery records |

Data is partitioned by month. Each non-empty month produces one Parquet file (e.g. `traces_2025-01.parquet`).

A cutoff timestamp is recorded at export start to ensure consistency — no data written after the export begins is included.

#### Output

The output directory contains:

* `<table>_<YYYY>-<MM>.parquet` — monthly Parquet files per table
* `telemetry_manifest.json` — migration ID, checksums, row counts, time ranges, FK validation state

#### Example

```bash
observal migrate export-telemetry \
  --clickhouse-url "clickhouse://default:clickhouse@localhost:8123/observal" \
  --manifest ./migration/observal-export.manifest.json \
  --output-dir ./migration/telemetry/
```

```
Exporting telemetry to: ./migration/telemetry/

  Exporting traces_2025-01.parquet (3,412 rows)...
  Exporting traces_2025-02.parquet (5,891 rows)...
  ✓ traces: 9,303 rows in 2 file(s)
  Exporting spans_2025-01.parquet (28,104 rows)...
  Exporting spans_2025-02.parquet (41,220 rows)...
  ✓ spans: 69,324 rows in 2 file(s)
  ✓ scores: 1,205 rows in 1 file(s)
  audit_log: empty
  otel_logs: empty
  security_events: empty
  webhook_deliveries: empty

✓ Telemetry export complete
  Directory:  ./migration/telemetry/
  Migration:  a1b2c3d4-...
  Rows:       79,832
  Size:       12.4 MB
  Duration:   18.7s

⚠  Parquet files may contain PII in trace input/output fields.
   Store securely and delete after import.
```

---

### observal migrate import-telemetry

Import Parquet telemetry files into the target ClickHouse instance.

#### Synopsis

```bash
observal migrate import-telemetry \
  --clickhouse-url <url> \
  --input-dir <dir> \
  [--project-id <id>]
```

#### Options

| Option | Description |
| --- | --- |
| `--clickhouse-url` | Target ClickHouse connection string (required) |
| `--input-dir` | Directory containing Parquet files and `telemetry_manifest.json` (required) |
| `--project-id` | Rewrite `project_id` in all tables to this value. Use when source and target orgs differ. |

#### Behavior

* Verifies checksums before importing anything
* Skips partitions that already have data (idempotent)
* Maintains resume state (`.import_state.json`) — safe to interrupt and re-run
* Validates resume state on restart (re-imports tables that lost data)

#### Example

```bash
observal migrate import-telemetry \
  --clickhouse-url "clickhouse://default:clickhouse@localhost:8123/observal" \
  --input-dir ./migration/telemetry/
```

```
Importing telemetry from: ./migration/telemetry/

  Importing traces_2025-01.parquet...
  Importing traces_2025-02.parquet...
  ✓ traces: 9,303 rows
  Importing spans_2025-01.parquet...
  Importing spans_2025-02.parquet...
  ✓ spans: 69,324 rows
  Importing scores_2025-02.parquet...
  ✓ scores: 1,205 rows

✓ Telemetry import complete
  Migration:  a1b2c3d4-...
  Tables:     3
  Rows:       79,832
  Duration:   22.1s
```

With project ID normalization:

```bash
observal migrate import-telemetry \
  --clickhouse-url "clickhouse://default:clickhouse@localhost:8123/observal" \
  --input-dir ./migration/telemetry/ \
  --project-id "my-local-org-id"
```

---

### observal migrate validate-telemetry

Validate telemetry Parquet files and optionally cross-check against live databases.

#### Synopsis

```bash
observal migrate validate-telemetry \
  --input-dir <dir> \
  [--clickhouse-url <url>] \
  [--target-db-url <postgres-url>]
```

#### Options

| Option | Description |
| --- | --- |
| `--input-dir` | Directory containing Parquet files (required) |
| `--clickhouse-url` | Target ClickHouse for row count comparison (optional) |
| `--target-db-url` | Target PostgreSQL for FK reference validation (optional) |

#### What it checks

1. **Checksum verification** — SHA-256 of each Parquet file matches the telemetry manifest
2. **Row count comparison** (when `--clickhouse-url` provided) — manifest counts vs live ClickHouse
3. **FK validation** (when `--target-db-url` provided) — checks that `agent_id`, `mcp_id`, and `user_id` references in telemetry data point to rows that exist in PostgreSQL. Orphaned IDs are reported (up to 10,000 per FK column).

#### Example

```bash
observal migrate validate-telemetry \
  --input-dir ./migration/telemetry/ \
  --clickhouse-url "clickhouse://default:clickhouse@localhost:8123/observal" \
  --target-db-url "postgresql://postgres:postgres@localhost:5432/observal"
```

```
Checksum verification:
  ✓ traces_2025-01.parquet
  ✓ traces_2025-02.parquet
  ✓ spans_2025-01.parquet
  ✓ spans_2025-02.parquet
  ✓ scores_2025-02.parquet

✓ All checksums valid

Row count comparison:
  ✓ traces: 9,303
  ✓ spans: 69,324
  ✓ scores: 1,205
  - audit_log: table not on target
  - otel_logs: table not on target

✓ All row counts match

FK validation:
  ✓ agent_id: 0 orphaned
  ✓ mcp_id: 0 orphaned
  ✓ user_id: 0 orphaned
```

---

## Full Migration Workflow

A complete environment migration from source to target:

```bash
# 1. Export PostgreSQL registry (shallow copy)
observal migrate export \
  --db-url "postgresql://user:pass@source-host:5432/observal" \
  --output ./migration/registry.tar.gz

# 2. Import into target PostgreSQL
observal migrate import \
  --db-url "postgresql://user:pass@target-host:5432/observal" \
  --archive ./migration/registry.tar.gz

# 3. Validate the import
observal migrate validate \
  --archive ./migration/registry.tar.gz \
  --db-url "postgresql://user:pass@target-host:5432/observal"

# 4. Export ClickHouse telemetry (deep copy)
observal migrate export-telemetry \
  --clickhouse-url "clickhouse://default:pass@source-host:8123/observal" \
  --manifest ./migration/registry.manifest.json \
  --output-dir ./migration/telemetry/

# 5. Import telemetry into target ClickHouse
observal migrate import-telemetry \
  --clickhouse-url "clickhouse://default:pass@target-host:8123/observal" \
  --input-dir ./migration/telemetry/

# 6. Validate telemetry with FK cross-check
observal migrate validate-telemetry \
  --input-dir ./migration/telemetry/ \
  --clickhouse-url "clickhouse://default:pass@target-host:8123/observal" \
  --target-db-url "postgresql://user:pass@target-host:5432/observal"
```

## Connection String Formats

| Database | Format | Example |
| --- | --- | --- |
| PostgreSQL | `postgresql://user:pass@host:port/dbname` | `postgresql://postgres:postgres@localhost:5432/observal` |
| ClickHouse | `clickhouse://user:pass@host:port/dbname` | `clickhouse://default:clickhouse@localhost:8123/observal` |
| ClickHouse (TLS) | `clickhouses://user:pass@host:port/dbname` | `clickhouses://default:clickhouse@ch.example.com:8443/observal` |

The `--db-url` for PostgreSQL accepts both `postgresql://` and `postgresql+asyncpg://` (the SQLAlchemy dialect prefix is stripped automatically). You can copy the `DATABASE_URL` from your `.env` directly.

The `clickhouses://` scheme maps to HTTPS with a default port of 8443. Use it when connecting to ClickHouse over TLS (e.g. managed ClickHouse Cloud or production instances behind TLS termination).

## Security Notes

* Archives contain **hashed** credentials (SHA-256 API keys, bcrypt passwords). They cannot be reversed, but treat them as sensitive.
* Parquet files may contain **PII** in trace input/output fields (user prompts, agent responses).
* Store migration artifacts securely and delete after successful import and validation.
* The `--project-id` flag on `import-telemetry` rewrites ownership — use it when migrating between orgs to avoid data leaking across tenants.

## Exit Codes

| Code | Meaning |
| --- | --- |
| 0 | Success |
| 1 | Error (auth failure, missing files, checksum mismatch, DB unreachable) |

## Resumability

* **Shallow copy import** skips rows that already exist (matched by primary key). Safe to re-run.
* **Deep copy import** tracks progress in `.import_state.json` inside the input directory. If interrupted, re-running picks up where it left off. Partitions with existing data are skipped.

## Related

* [`observal admin`](admin.md) — admin commands (required role for migrate)
* [`observal auth`](auth.md) — authentication (must be logged in as admin)
