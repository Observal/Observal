<!-- SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Observal Contributors -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# `observal server migrate`

Move PostgreSQL registry data and telemetry between Observal deployments.

The analytics store is DuckDB. Instances that still run ClickHouse use the
one-way `duckdb` command below to move their telemetry across; the
deployment-to-deployment commands further down move registry and telemetry data
between two Observal instances.

Migration uses the supplied database connections directly. Local shell and database access are the authorization boundary; the command does not authenticate against a configured Observal API.

Install the optional dependency first:

```bash
pip install 'observal-cli[migrate]'
```

Keep connection URLs in environment variables or secret files managed by the shell. Source commands read `DATABASE_URL` and `DUCKDB_ANALYTICS_URL`; target commands read `TARGET_DATABASE_URL` and `DUCKDB_ANALYTICS_URL`. Explicit URL options remain available when no secret is embedded. Do not paste credentials into shared shell history, logs, or issue reports. JSON results and categorized errors never echo a connection URL.

## Workflow

1. Export PostgreSQL. This creates a checksummed registry archive and a migration manifest.
2. Validate and import PostgreSQL on the target.
3. Export DuckDB using the PostgreSQL migration manifest.
4. Validate and import DuckDB on the target.

PostgreSQL must be imported first so referenced users and agents exist before telemetry validation.

## One-way ClickHouse → DuckDB migration

```bash
observal server migrate duckdb \
  --clickhouse-url clickhouse://default:clickhouse@observal-clickhouse:8123/observal \
  --duckdb-url duckdb://observal-duckdb:8484/observal \
  --duckdb-token "$DUCKDB_ANALYTICS_TOKEN" \
  --export-dir ./telemetry-export
```

The command runs three steps:

1. **Export** every telemetry table from ClickHouse to monthly Parquet partitions
   plus a checksummed `telemetry_manifest.json`.
2. **Load** those partitions into the DuckDB analytics service, transactionally
   replacing rows by logical identity (and pruning incoming identities for
   append-only tables) so re-runs are idempotent.
3. **Verify** artifact checksums and per-table row counts against the manifest.

Verification fails (exit code 7 with a categorized error) when exported data is
missing from DuckDB, or when a fresh table took fewer rows than the manifest
expects. A target that already holds rows — a running instance, or a repeated
migration — legitimately shows more rows than the export carries; those extra
counts are reported per table instead of failing the run.

ClickHouse is never modified, so a failed run can be repeated or abandoned, and
the previous release remains a valid rollback target.

Options:

- `--export-dir` must not exist for a fresh export; pass `--skip-export` to retry
  the load from an existing directory.
- `--skip-verify` skips the row-count comparison (checksums are still reported).
- `--duckdb-token` reads `DUCKDB_ANALYTICS_TOKEN` by default.

## PostgreSQL export

```bash
observal server migrate export \
  --file registry.tar.gz \
  --output json
```

`--file/-f` selects the archive destination. `--output/-o` always selects `table` or `json`. Existing destinations fail with a conflict instead of being overwritten.

The archive and sidecar manifest are written atomically with owner-only permissions. A partial archive is not published after failure.

Example JSON fields:

```json
{
  "archive": "registry.tar.gz",
  "manifest": "registry.manifest.json",
  "migration_id": "7b84e503-63af-4b89-a1cd-abf48f0452f3",
  "table_counts": {"users": 8, "agents": 21},
  "total_rows": 342,
  "size_bytes": 1048576,
  "duration_seconds": 2.4
}
```

## PostgreSQL validation and import

```bash
observal server migrate validate \
  --archive registry.tar.gz \
  --output json

observal server migrate import \
  --archive registry.tar.gz \
  --output json
```

Validation checks archive structure and SHA-256 checksums. When a target URL is provided, it also compares table row counts. Checksum failure returns a categorized validation error. Row-count differences remain explicit result data.

Import verifies checksums before insertion. Existing rows are skipped according to the migration service's idempotent import rules. The result contains per-table inserted and skipped counts plus warnings.

## Telemetry export (instance moves)

These leaves move telemetry between two DuckDB-backed instances and require a
new destination directory:

```bash
observal server migrate export-telemetry \
  --duckdb-url duckdb://source-duckdb:8484/observal \
  --output-dir telemetry-export \
  --output json
```

The destination must not already exist. This lets the exporter remove the complete directory after failure without touching pre-existing files. The directory and streamed Parquet files use restrictive permissions and atomic temporary files.

The export covers every telemetry table (sessions, checkpoints, summaries, layer snapshots, audit, security, webhook deliveries). Each non-empty month produces a Parquet file, and `telemetry_manifest.json` records checksums, row counts, and the migration ID.

## Telemetry validation and import

```bash
observal server migrate validate-telemetry \
  --duckdb-url duckdb://target-duckdb:8484/observal \
  --input-dir telemetry-export \
  --output json

observal server migrate import-telemetry \
  --duckdb-url duckdb://target-duckdb:8484/observal \
  --input-dir telemetry-export \
  --output json
```

Telemetry validation checks:

* Parquet checksums
* Manifest row counts against the target DuckDB service when a `--duckdb-url` is supplied

Checksum failure is fatal. Row-count differences and orphan groups are returned explicitly.

Telemetry import is resumable. Completed tables are skipped and progress state remains in the input directory. Imported project-keyed rows normalize to the deployment project `default`. Use the one-way `duckdb` command above when the source is ClickHouse and the destination is a DuckDB deployment.

## Human and JSON behavior

All six leaves accept `--output table|json`. Human mode renders progress and summaries. JSON mode is finite, prompt-free, suppresses progress and warnings from stdout, and returns one result document. Failures leave stdout empty and emit one categorized error to stderr.

Cleartext ClickHouse transport with credentials produces a human warning. JSON mode does not print a banner; operators should use `clickhouses://` for TLS.

## Exit codes

| Code | Category | Typical migration cause |
| --- | --- | --- |
| 2 | Usage | Missing required option or unsupported output mode |
| 4 | Permission | Destination or source path is not accessible |
| 5 | Not found | Archive, manifest, or input directory is missing |
| 6 | Conflict | Archive or telemetry destination already exists |
| 7 | Validation | Invalid archive, failed checksum, or missing phase prerequisite |
| 9 | Unavailable | Optional dependency, database, network, or migration service failure |

## Recommended sequence

```bash
# Source
observal server migrate export --file registry.tar.gz --output json
observal server migrate export-telemetry \
  --duckdb-url duckdb://source-duckdb:8484/observal \
  --output-dir telemetry-export \
  --output json

# Target
observal server migrate validate --archive registry.tar.gz --output json
observal server migrate import --archive registry.tar.gz --output json
observal server migrate validate-telemetry \
  --duckdb-url duckdb://target-duckdb:8484/observal \
  --input-dir telemetry-export \
  --output json
observal server migrate import-telemetry \
  --duckdb-url duckdb://target-duckdb:8484/observal \
  --input-dir telemetry-export \
  --output json
```
