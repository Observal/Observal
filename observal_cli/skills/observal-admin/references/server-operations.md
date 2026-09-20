<!-- SPDX-FileCopyrightText: 2026 Observal Contributors -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Server operations

## Contents

- Service lifecycle
- Upgrade and rollback
- PostgreSQL migration
- ClickHouse telemetry migration
- Safety checks

Local server commands use shell, filesystem, Docker, and database authority. API roles do not constrain that local authority.

## Service lifecycle

```bash
observal server status --output json
observal server start --background --output json
observal server restart --background --output json
observal server logs api --lines 100 --output json
observal server stop --output json
```

JSON start and restart require background mode. Verify final service status rather than trusting the launch response alone.

## Upgrade and rollback

Read current and available versions first:

```bash
observal server versions --output json
observal server upgrade --dry-run --output json
```

Execute only the requested direction:

```bash
observal server upgrade --version VERSION --force --output json
observal server rollback --force --output json
```

Rollback restores PostgreSQL, managed Docker image state, and DuckDB when the selected compatible backup contains `analytics.tar.gz`; without that archive, DuckDB data is unchanged. A completed ClickHouse-to-DuckDB cutover is permanent: rollback retains the DuckDB compose, secrets, and completion marker, and never reactivates ClickHouse. Targets older than the marker's `to_version` are rejected before any restore, even with `--force`; `server upgrade --version` cannot bypass this boundary. Invalid marker metadata or a non-DuckDB-only compose also blocks the operation. Choose a compatible backup; never delete the marker or restore the saved ClickHouse compose to bypass the guard. Verify service status and version after completion.

`server upgrade` detects a legacy ClickHouse deployment (ClickHouse compose file or `CLICKHOUSE_URL` in `.env` with no DuckDB token, plus this project's `observal-clickhouse` container) and runs the one-time cutover itself: PostgreSQL backup, release compose/nginx install (server-package) with the old file kept as `docker-compose.clickhouse.bak.yml`, analytics token provisioning, `observal-duckdb` start, ClickHouse export/load/verify, deploy, post-deploy re-verification, then `docker stop` of ClickHouse with its volume kept and a `.observal-cutover-complete.json` marker. Any failure before deploy leaves the old release running; a health-check failure after deploy restores the legacy compose file. `--dry-run` reports `clickhouse_cutover: true` when a cutover would run. The CLI must be upgraded first (`observal self upgrade`); the previous CLI cannot perform the cutover. Refuses when the compose file is legacy but no ClickHouse container exists. Embedded installs (`observal server start`) run the same cutover automatically on start, relaunching the old ClickHouse binary on port 18124 for the export.

## PostgreSQL migration

Export, validate, then import:

```bash
observal server migrate export --file registry.tar.gz --output json
observal server migrate validate --archive registry.tar.gz --output json
observal server migrate import --archive registry.tar.gz --output json
```

Source commands read `DATABASE_URL`; target commands read `TARGET_DATABASE_URL`. Keep URLs out of output and logs. Never replace these commands with hand-written SQL.

## Telemetry migration

```bash
observal server migrate export-telemetry --duckdb-url duckdb://observal-duckdb:8484/observal --output-dir telemetry-export --output json
observal server migrate validate-telemetry --duckdb-url duckdb://observal-duckdb:8484/observal --input-dir telemetry-export --output json
observal server migrate import-telemetry --duckdb-url duckdb://observal-duckdb:8484/observal --input-dir telemetry-export --output json
```

These leaves move telemetry between DuckDB-backed instances; they read `DUCKDB_ANALYTICS_URL` and `DUCKDB_ANALYTICS_TOKEN`. Export requires a new destination directory. Validate files and Registry references before import.

`observal server upgrade` runs this step automatically for Docker deployments. Use the standalone command for Helm, Terraform, or when driving the cutover by hand (it must run before `helm upgrade` / `terraform apply`):

```bash
observal server migrate duckdb --clickhouse-url clickhouse://default:clickhouse@observal-clickhouse:8123/observal --duckdb-url duckdb://observal-duckdb:8484/observal --export-dir telemetry-export --output json
```

The command exports, loads, and verifies; it never modifies ClickHouse and has no reverse direction.

## Safety checks

- Confirm source, destination, and backup location before import, upgrade, rollback, or reset.
- Use dry run when available.
- Stop after validation failure. Do not import a damaged archive.
- Report counts, versions, warnings, and final service health.
- Never expose database URLs, generated secrets, archive contents, or customer rows.
