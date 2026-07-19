<!-- SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# observal server migrate

Portable migration tools for moving an Observal instance between environments.

The workflow has two phases:

1. **Shallow copy** exports PostgreSQL registry data to a compressed archive.
2. **Deep copy** exports active ClickHouse session and operational event tables to monthly Parquet files.

Complete the shallow copy before importing telemetry so referenced users and agents exist on the target. Migration commands require the `super_admin` role and the CLI migrate extra:

```bash
pip install 'observal-cli[migrate]'
```

## Registry migration

Export PostgreSQL registry data:

```bash
observal server migrate export \
  --db-url "$DATABASE_URL" \
  --output observal-export.tar.gz
```

Validate an archive before import:

```bash
observal server migrate validate \
  --archive observal-export.tar.gz \
  --db-url "$TARGET_DATABASE_URL"
```

Import into the target PostgreSQL database:

```bash
observal server migrate import \
  --archive observal-export.tar.gz \
  --db-url "$TARGET_DATABASE_URL"
```

Registry archives include users, organizations, agents, component listings and versions, feedback, settings, and related relational records. Treat them as production backups.

## Telemetry export

```bash
observal server migrate export-telemetry \
  --clickhouse-url "clickhouse://default:clickhouse@localhost:8123/observal" \
  --manifest ./migration/observal-export.manifest.json \
  --output-dir ./migration/telemetry/
```

The deep-copy export includes only active ClickHouse tables:

| Table | Engine | Time column | Description |
| --- | --- | --- | --- |
| `session_events` | MergeTree | `timestamp` | Harness session transcript records |
| `audit_log` | MergeTree | `timestamp` | Audit trail entries |
| `security_events` | MergeTree | `timestamp` | Security event records |
| `webhook_deliveries` | MergeTree | `timestamp` | Webhook delivery history |

Each non-empty month produces `<table>_<YYYY>-<MM>.parquet`. `telemetry_manifest.json` records checksums, row counts, time ranges, migration ID, and FK validation state. Tables absent on an older source are skipped.

## Telemetry validation

```bash
observal server migrate validate-telemetry \
  --input-dir ./migration/telemetry/ \
  --clickhouse-url "clickhouse://default:clickhouse@target:8123/observal" \
  --target-db-url "$TARGET_DATABASE_URL"
```

Validation checks:

- SHA-256 checksums for every Parquet file
- Manifest row counts against the target ClickHouse instance when provided
- Agent and user references against the target PostgreSQL instance when provided

Do not import files with checksum failures.

## Telemetry import

```bash
observal server migrate import-telemetry \
  --clickhouse-url "clickhouse://default:clickhouse@target:8123/observal" \
  --input-dir ./migration/telemetry/
```

To normalize imported rows to one target project:

```bash
observal server migrate import-telemetry \
  --clickhouse-url "clickhouse://default:clickhouse@target:8123/observal" \
  --input-dir ./migration/telemetry/ \
  --project-id "target-org-id"
```

Imports are resumable. Progress is stored in the input directory, completed tables are skipped, and temporary files use a `.tmp` suffix until each operation finishes.

## Recommended sequence

```bash
# Source
observal server migrate export --db-url "$DATABASE_URL" --output registry.tar.gz
observal server migrate export-telemetry \
  --clickhouse-url "$CLICKHOUSE_URL" \
  --manifest migration_manifest.json \
  --output-dir telemetry/

# Target
observal server migrate validate --archive registry.tar.gz --db-url "$TARGET_DATABASE_URL"
observal server migrate import --archive registry.tar.gz --db-url "$TARGET_DATABASE_URL"
observal server migrate validate-telemetry \
  --input-dir telemetry/ \
  --target-db-url "$TARGET_DATABASE_URL"
observal server migrate import-telemetry \
  --clickhouse-url "$TARGET_CLICKHOUSE_URL" \
  --input-dir telemetry/
```

After import, verify registry counts, open recent sessions, and compare telemetry manifest counts with the target tables.
