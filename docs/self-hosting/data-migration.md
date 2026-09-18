<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Srihari <sriharilegend23@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Data migration

Use data migration when you need to move an Observal instance to a new deployment, validate a backup, or copy production data into a controlled recovery environment.

Only super admins can start migration jobs.

## What can be moved

- **Registry data**: users, agents, components, versions, settings, review records, and related PostgreSQL data.
- **Telemetry data**: session events, session checkpoints, session summaries, layer snapshots, audit events, security events, and webhook delivery history stored in DuckDB.
- **Registry + telemetry**: a full instance move when both stores are available.

## Before you start

1. Confirm both source and target instances are on compatible Observal versions.
2. Schedule a maintenance window if users are actively changing registry data.
3. Make sure the target deployment has enough disk space for uploaded artifacts.
4. Decide whether you need registry data only or registry plus telemetry.
5. Treat exported files like production backups. They can contain hashed credentials, API keys, and telemetry with PII.

## Export from the source instance

1. Open **Admin → Settings → Data Migration**.
2. Click **Migrate**.
3. Select **Export**.
4. Choose the export scope:
   - **Registry data** for PostgreSQL records only.
   - **Telemetry data** for session, audit, and security history only. The export is a single self-describing `telemetry_export.tar.gz` (Parquet partitions plus `telemetry_manifest.json`).
   - **Registry + telemetry** for a full move.
5. Click **Start export**.
6. Wait for the job to finish.
7. Download every artifact shown in the result.
8. Store the artifacts in a secure temporary location.

## Validate before import

Run validation on the target instance before importing.

1. Open **Admin → Settings → Data Migration** on the target instance.
2. Select **Validate**.
3. Upload the artifacts from the export.
4. Choose the same scope you plan to import.
5. Click **Start validation**.
6. Review the result:
   - Checksums should pass.
   - Table counts should match expectations.
   - Telemetry validation should not report broken registry references unless you intentionally skipped registry data.

Do not import artifacts that fail checksum validation.

## Import into the target instance

1. Open **Admin → Settings → Data Migration** on the target instance.
2. Select **Import**.
3. Upload the validated artifacts.
4. Choose the import scope.
5. Telemetry-only imports accept the `telemetry_export.tar.gz` from the export as-is; a registry archive on its own is rejected because it carries no telemetry tables.
6. Imports normalize all project-keyed telemetry to the deployment project `default`.
7. Click **Start import**.
8. Wait for the job to finish.
9. Check agents, components, users, and sessions in the target instance.

Imports are idempotent where possible. Existing rows are skipped rather than overwritten.

## CLI alternative

The CLI uses the same shared migration core as the server jobs. Source commands read `DATABASE_URL` and `DUCKDB_ANALYTICS_URL`; target commands read `TARGET_DATABASE_URL` and `DUCKDB_ANALYTICS_URL`.

Upgrading an existing ClickHouse-backed installation is a one-way migration:

```bash
observal server migrate duckdb \
  --clickhouse-url clickhouse://default:clickhouse@observal-clickhouse:8123/observal \
  --duckdb-url duckdb://observal-duckdb:8484/observal \
  --duckdb-token "$DUCKDB_ANALYTICS_TOKEN" \
  --export-dir ./telemetry-export
```

The command exports Parquet partitions, loads them into the analytics service,
and verifies checksums plus per-table row counts. It is idempotent per export,
never modifies the ClickHouse source, and has no reverse direction.

## Telemetry between two DuckDB instances

The same artifact flow works between two DuckDB deployments:

```bash
observal server migrate export-telemetry \
  --duckdb-url duckdb://source-duckdb:8484/observal \
  --duckdb-token "$DUCKDB_ANALYTICS_TOKEN" \
  --output-dir ./telemetry-export

observal server migrate validate-telemetry --input-dir ./telemetry-export

observal server migrate import-telemetry \
  --duckdb-url duckdb://target-duckdb:8484/observal \
  --duckdb-token "$DUCKDB_ANALYTICS_TOKEN" \
  --input-dir ./telemetry-export
```

Exports carry every telemetry table, including `session_stats_agg`: summaries are
written by the ingest path rather than rebuilt on import, so they must travel
with the events. Imports transactionally replace rows by logical identity and
prune incoming identities for append-only tables, so repeating an import is safe.

```bash
observal server migrate export --file backup.tar.gz --output json
observal server migrate validate --archive backup.tar.gz --output json
observal server migrate import --archive backup.tar.gz --output json
```

Telemetry commands are separate (DuckDB source and target):

```bash
observal server migrate export-telemetry --duckdb-url duckdb://source-duckdb:8484/observal --output-dir telemetry --output json
observal server migrate validate-telemetry --duckdb-url duckdb://target-duckdb:8484/observal --input-dir telemetry --output json
observal server migrate import-telemetry --duckdb-url duckdb://target-duckdb:8484/observal --input-dir telemetry --output json
```

### Copying telemetry with super-admin credentials only

When you cannot reach the source analytics service directly, `scripts/fetch_seed_telemetry.py`
drives the super-admin migration API on both sides: it starts an export on the
source, waits for the job, downloads the artifact with checksum verification,
uploads it to the target as a telemetry import, and prints the import result.

```bash
python scripts/fetch_seed_telemetry.py \
  --source-url https://source.example.com \
  --source-email admin@source.example.com \
  --target-url http://localhost \
  --target-email super@target.example.com \
  --out .seed-telemetry
```

Passwords come from `--source-password`/`--target-password` or from
`SOURCE_PASSWORD`/`TARGET_PASSWORD`. Add `--insecure` for a stack with a
self-signed certificate. Re-running against a target that already holds the
telemetry is safe: the import reports zero inserted rows.

## Cleanup

1. Confirm the target instance works.
2. Delete local copies of migration artifacts.
3. Remove temporary upload files from the target host if you copied them outside the UI.
4. Keep only the backup copy required by your retention policy.

## Troubleshooting

### Validation fails

Re-download the artifacts from the source export. If checksums still fail, create a new export.

### Import skips rows

Rows are skipped when they already exist on the target. This is expected for retrying a partially completed import.

### Telemetry import has missing registry references

Import registry data first, then validate and import telemetry again.

### Jobs time out

Increase the migration job timeout setting or split registry and telemetry into separate operations.
