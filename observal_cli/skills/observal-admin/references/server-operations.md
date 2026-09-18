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

Rollback restores PostgreSQL, managed Docker image state, and DuckDB when the selected backup contains `analytics.tar.gz`. A legacy backup restores PostgreSQL only. Verify service status and version after completion.

`server upgrade` refuses a legacy compose topology containing ClickHouse but no DuckDB. Complete the one-time cutover in `docs/architecture/duckdb-replacement.md`, including refreshing the release compose file and configuring the shared analytics token, before retrying.

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

Upgrading an installation that still runs ClickHouse is a one-way operation:

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
