<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# Data migration

Use data migration when you need to move an Observal instance to a new deployment, validate a backup, or copy production data into a controlled recovery environment.

Only super admins can start migration jobs.

## What can be moved

- **Registry data**: users, agents, components, versions, settings, review records, and related PostgreSQL data.
- **Telemetry data**: trace and span history stored in ClickHouse.
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
5. Review the target organization and project IDs.
6. Click **Start import**.
7. Wait for the job to finish.
8. Check agents, components, users, and traces in the target instance.

Imports are idempotent where possible. Existing rows are skipped rather than overwritten.

## CLI alternative

The CLI uses the same shared migration core as the server jobs.

```bash
observal server migrate export --db-url "$DATABASE_URL" --output backup.tar.gz
observal server migrate validate --archive backup.tar.gz --db-url "$DATABASE_URL"
observal server migrate import --db-url "$DATABASE_URL" --archive backup.tar.gz
```

Telemetry commands are separate:

```bash
observal server migrate export-telemetry --clickhouse-url "$CLICKHOUSE_URL" --manifest backup-manifest.json --output-dir telemetry
observal server migrate validate-telemetry --input-dir telemetry --clickhouse-url "$CLICKHOUSE_URL" --target-db-url "$DATABASE_URL"
observal server migrate import-telemetry --clickhouse-url "$CLICKHOUSE_URL" --input-dir telemetry
```

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
