# observal support

Generate and inspect diagnostic support bundles. Bundles contain **no customer data or row contents** — only aggregate counts, version info, sanitised configuration, health probes, and optional system metrics.

Use support bundles when filing issues or working with the Observal team to diagnose deployment problems.

## Subcommands

| Command | Description |
| --- | --- |
| [`support bundle`](#observal-support-bundle) | Generate a diagnostic archive |
| [`support inspect`](#observal-support-inspect) | Examine an existing bundle |

---

## `observal support bundle`

Collect diagnostics from the server and local machine, redact sensitive values, and write a `.tar.gz` archive.

### Synopsis

```bash
observal support bundle [--output <path>] [--logs-since <duration>] [--include-system | --no-include-system]
```

### Options

| Option | Short | Default | Description |
| --- | --- | --- | --- |
| `--output` | `-o` | `./observal-support-{timestamp}.tar.gz` | Archive output path |
| `--logs-since` | — | `1h` | Duration of logs to include (e.g. `1h`, `30m`, `2d`) |
| `--include-system` / `--no-include-system` | — | enabled | Include OS/CPU/memory/disk metrics |

### What it collects

The bundle command contacts the Observal server and runs local collectors in parallel. Each collector has a 10-second timeout — partial failures are reported in the manifest without blocking the rest.

**Remote collectors** (from the server):

| Collector | Contents |
| --- | --- |
| `versions` | App version, build hash, Alembic migration revision, ClickHouse version and table list |
| `health` | Latency probes for PostgreSQL, ClickHouse, and Redis |
| `config` | Allowlisted configuration keys only (see below) |
| `aggregates` | Row counts per PostgreSQL and ClickHouse table |
| `errors` | Up to 50 error fingerprints from the last 24 hours (stack templates only — no messages or arguments) |
| `logs` | Structured log lines from the in-memory ring buffer, filtered by `--logs-since` |

**Local collectors** (from the CLI machine):

| Collector | Contents |
| --- | --- |
| `system_info` | OS name/version, kernel version, CPU count, memory total/available, disk total/free, container runtime detection |

### Configuration allowlist

Only these settings are included in the bundle. All other server configuration (secrets, OAuth credentials, etc.) is excluded at the source:

```
DATABASE_URL, CLICKHOUSE_URL, REDIS_URL, REDIS_SOCKET_TIMEOUT,
EVAL_MODEL_NAME, EVAL_MODEL_PROVIDER, AWS_REGION, FRONTEND_URL,
JWT_ACCESS_TOKEN_EXPIRE_MINUTES, JWT_REFRESH_TOKEN_EXPIRE_DAYS,
JWT_SIGNING_ALGORITHM, JWT_HOOKS_TOKEN_EXPIRE_MINUTES,
RATE_LIMIT_AUTH, RATE_LIMIT_AUTH_STRICT, DATA_RETENTION_DAYS,
DEPLOYMENT_MODE
```

Even allowlisted values pass through the redaction layer before being written.

### Redaction

Every value in the bundle passes through a central redaction layer. The following patterns are automatically scrubbed:

* **JWT tokens** — `eyJ...` three-segment base64url strings
* **AWS access keys** — `AKIA` followed by 16 alphanumeric characters
* **URL credentials** — `scheme://user:password@host` → `scheme://<REDACTED>@host`
* **High-entropy strings** — Shannon entropy > 4.5 and length ≥ 32 (catches API keys, tokens, etc.)
* **Sensitive JSON keys** — values under keys matching `password`, `secret`, `token`, `api_key`, `private_key`, `credential`, `authorization`, `client_secret`, `bearer` (case-insensitive)

Redaction counts per file are recorded in the bundle manifest for auditability.

### Archive structure

The output is a gzip-compressed tar archive with this layout:

```
bundle_manifest.json          # Manifest with metadata, collector results, file inventory
versions/
  app.json                    # CLI + server version, build hash
  alembic.json                # Current migration revision
  clickhouse.json             # ClickHouse version and table list
health/
  postgres.json               # PostgreSQL latency probe
  clickhouse.json             # ClickHouse latency probe
  redis.json                  # Redis latency probe
config/
  config.json                 # Allowlisted + redacted configuration
aggregates/
  pg_table_counts.json        # Row counts per PostgreSQL table
  ch_table_counts.json        # Row counts per ClickHouse table
errors/
  recent_errors.json          # Error fingerprints (stack templates, counts, timestamps)
logs/
  recent.ndjson               # Newline-delimited JSON log entries
system/
  system.json                 # OS, CPU, memory, disk, container runtime
```

### Bundle manifest

The `bundle_manifest.json` at the root of every archive contains:

| Field | Description |
| --- | --- |
| `bundle_schema_version` | Schema version (currently `1`) |
| `created_at` | ISO 8601 timestamp |
| `cli_version` | CLI version that generated the bundle |
| `host_os` | Operating system of the generating machine |
| `node_id` | SHA-256 hash (first 12 chars) of the hostname — identifies the machine without revealing the hostname |
| `flags_used` | Options passed to the `bundle` command |
| `collector_results` | Per-collector status (`ok`, `duration_ms`, `error`) |
| `redaction_counts` | Number of redactions applied per file |
| `file_inventory` | Every file in the archive with its path, size, and SHA-256 hash |

### Size budget

If the uncompressed bundle exceeds 100 MB, you'll be prompted to confirm before writing. This is a safety check — typical bundles are well under 1 MB.

### Example

```bash
observal support bundle
```

Output:

```
✓ Support bundle written to observal-support-20260510-143022.tar.gz (42.3 KB)
  Review contents with: observal support inspect observal-support-20260510-143022.tar.gz
```

With custom options:

```bash
observal support bundle --output /tmp/diag.tar.gz --logs-since 2d --no-include-system
```

### Offline mode

If the server is unreachable, the bundle is still created with local data only. A warning is printed and the manifest records which remote collectors were skipped.

---

## `observal support inspect`

Open an existing support bundle and display its manifest, file tree, and optionally the contents of a specific file.

### Synopsis

```bash
observal support inspect <bundle-path> [--show <file>]
```

### Arguments

| Argument | Description |
| --- | --- |
| `<bundle-path>` | Path to a `.tar.gz` support bundle |

### Options

| Option | Description |
| --- | --- |
| `--show <file>` | Print the contents of a specific file from the archive |

### What it displays

1. The full bundle manifest as formatted JSON (metadata, collector results, redaction counts).
2. A tree view of all files in the archive with human-readable sizes.
3. If `--show` is specified, the raw contents of that file.

### Schema version compatibility

If the bundle was created by a newer CLI version (higher schema version), a warning is printed. Older fields are still displayed; unrecognized fields are ignored.

### Security

The inspect command rejects tar members with path traversal attacks (e.g. `../../etc/passwd`). Only safe, normalized paths are displayed or extracted.

### Example

```bash
observal support inspect observal-support-20260510-143022.tar.gz
```

Output:

```json
{
  "bundle_schema_version": "1",
  "created_at": "2026-05-10T14:30:22.123456+00:00",
  "cli_version": "0.9.2",
  "host_os": "Linux",
  "node_id": "a1b2c3d4e5f6",
  "flags_used": {
    "output": "observal-support-20260510-143022.tar.gz",
    "logs_since": "1h",
    "include_system": true
  },
  "collector_results": {
    "versions": {"ok": true, "duration_ms": 45},
    "health": {"ok": true, "duration_ms": 12},
    "config": {"ok": true, "duration_ms": 2},
    "aggregates": {"ok": true, "duration_ms": 230},
    "errors": {"ok": true, "duration_ms": 180},
    "logs": {"ok": true, "duration_ms": 5},
    "config_allowlisted": {"ok": true, "duration_ms": 0},
    "system_info": {"ok": true, "duration_ms": 3}
  },
  "redaction_counts": {
    "versions/app.json": 0,
    "config/config.json": 2,
    "logs/recent.ndjson": 1
  },
  "file_inventory": [...]
}
```

```
Bundle contents
├── aggregates/ch_table_counts.json  1.2 KB
├── aggregates/pg_table_counts.json  856 B
├── config/config.json               412 B
├── errors/recent_errors.json        3.4 KB
├── health/clickhouse.json           89 B
├── health/postgres.json             91 B
├── health/redis.json                85 B
├── logs/recent.ndjson               12.1 KB
├── system/system.json               298 B
├── versions/alembic.json            52 B
├── versions/app.json                134 B
└── versions/clickhouse.json         210 B
```

View a specific file:

```bash
observal support inspect observal-support-20260510-143022.tar.gz --show health/postgres.json
```

```json
{
  "status": "ok",
  "latency_ms": 3
}
```

---

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Bundle created / inspect succeeded |
| 1 | No data collected, bundle not found, or archive is invalid |

## Privacy guarantees

Support bundles are designed to be safe to share with third parties:

* **No customer data** — no database row contents, no user messages, no trace payloads.
* **No secrets** — passwords, tokens, API keys, and high-entropy strings are redacted.
* **No hostnames or IPs** — the `node_id` is a truncated SHA-256 hash of the hostname.
* **No usernames** — system info excludes the current user.
* **Aggregate only** — table counts, not table contents; error fingerprints, not error messages.
* **Auditable** — the manifest records exactly what was collected, what was redacted, and the SHA-256 hash of every file.

## Server endpoint

The CLI calls `POST /api/v1/support/collect` on the Observal server. This endpoint:

* Requires authentication (API key via `X-API-Key` header).
* Is rate-limited to 5 requests per minute.
* Runs each collector with a 10-second timeout.
* Returns partial results on collector failure (always HTTP 200 if at least one collector succeeds).

If your server does not have the support endpoint (older version), rebuild the server container. The CLI will still produce a bundle with local-only data.

## Related

* [`observal doctor`](doctor.md) — diagnose IDE compatibility
* [`observal ops telemetry status`](ops.md#observal-ops-telemetry-status) — check telemetry pipeline health
* [Troubleshooting](../self-hosting/troubleshooting.md) — common deployment issues
