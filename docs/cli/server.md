<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# observal server

Manage the embedded Observal server stack (PostgreSQL, ClickHouse, Redis, API, web UI).

All commands operate on the local Docker Compose stack. The `upgrade`, `rollback`, and `versions` commands require **super_admin** role.

## Subcommands

| Command | Description |
| --- | --- |
| [`server start`](#observal-server-start) | Start all services |
| [`server stop`](#observal-server-stop) | Stop all services |
| [`server restart`](#observal-server-restart) | Restart all services |
| [`server status`](#observal-server-status) | Show service status |
| [`server logs`](#observal-server-logs) | View service logs |
| [`server install`](#observal-server-install) | Download dependency binaries |
| [`server config`](#observal-server-config) | Show current configuration |
| [`server reset`](#observal-server-reset) | Wipe all data |
| [`server upgrade`](#observal-server-upgrade) | Upgrade to a new version |
| [`server rollback`](#observal-server-rollback) | Roll back to previous version |
| [`server versions`](#observal-server-versions) | List available versions |

---

## `observal server start`

Start all services and the Observal API server. On first run, downloads database binaries and initializes data directories.

```bash
observal server start
observal server start --port 9000
observal server start --background
```

| Option | Short | Default | Description |
| --- | --- | --- | --- |
| `--port` | `-p` | 8000 | API port |
| `--host` | | 0.0.0.0 | Bind address |
| `--background` | `-d` | false | Run in background (daemonize) |

If the default port is in use, the server automatically tries fallback ports (8001, 8002, 8010, 8100).

---

## `observal server stop`

Gracefully shut down all services in reverse order: API, Redis, ClickHouse, PostgreSQL.

```bash
observal server stop
```

---

## `observal server restart`

Stop and restart all services.

```bash
observal server restart
observal server restart --port 9000
```

| Option | Short | Default | Description |
| --- | --- | --- | --- |
| `--port` | `-p` | 8000 | API port |
| `--host` | | 0.0.0.0 | Bind address |

---

## `observal server status`

Show a table of all service statuses (running, stopped, not initialized) with their ports.

```bash
observal server status
```

Output:

```
        Observal Service Status
┌────────────┬─────────┬──────┐
│ Service    │ Status  │ Port │
├────────────┼─────────┼──────┤
│ Postgres   │ running │ 5480 │
│ Clickhouse │ running │ 8124 │
│ Redis      │ running │ 6380 │
│ Api        │ running │ 8000 │
└────────────┴─────────┴──────┘
```

---

## `observal server logs`

Show or follow service logs.

```bash
observal server logs
observal server logs postgres
observal server logs api --follow
observal server logs redis --lines 200
```

| Argument | Description |
| --- | --- |
| `[SERVICE]` | Service name: `postgres`, `clickhouse`, `redis`, `api`. Omit for all. |

| Option | Short | Default | Description |
| --- | --- | --- | --- |
| `--follow` | `-f` | false | Follow log output (like `tail -f`) |
| `--lines` | `-n` | 50 | Number of lines to show |

---

## `observal server install`

Download database dependency binaries (PostgreSQL, ClickHouse, Redis). Runs automatically on first `server start`, but can be invoked manually to pre-download.

```bash
observal server install
observal server install --upgrade
```

| Option | Description |
| --- | --- |
| `--upgrade` | Re-download even if already installed |

---

## `observal server config`

Show current server configuration (ports, data directories, API URL).

```bash
observal server config
```

---

## `observal server reset`

Stop all services and wipe all data (databases, config, keys). Requires re-initialization on next start.

```bash
observal server reset
observal server reset --force
```

| Option | Short | Description |
| --- | --- | --- |
| `--force` | `-f` | Skip confirmation prompt |

> **Warning:** This is destructive. All traces, users, agents, and configuration will be permanently deleted.

---

## `observal server upgrade`

Upgrade the server to the latest or a specified version. Pulls new Docker images from GHCR, creates a database backup, and recreates containers with a health check.

**Requires super_admin role.**

```bash
observal server upgrade
observal server upgrade --version 0.9.0
observal server upgrade --dry-run
observal server upgrade --skip-backup --force
```

| Option | Short | Default | Description |
| --- | --- | --- | --- |
| `--version` | `-v` | latest | Target version (e.g. 0.9.0) |
| `--skip-backup` | | false | Skip pre-upgrade database backup |
| `--dry-run` | | false | Show upgrade plan without applying changes |
| `--force` | `-f` | false | Skip interactive confirmation |

**What happens during an upgrade:**

1. Resolves target version (latest from GitHub if not specified)
2. Verifies the Docker image exists on GHCR
3. Acquires an upgrade lock (prevents concurrent upgrades)
4. Creates a database backup (unless `--skip-backup`)
5. Pulls new images: `ghcr.io/observal/observal-{api,web}:<version>`
6. Updates `.env` with the new version
7. Recreates containers via `docker compose up -d`
8. Runs health checks for up to 120 seconds
9. If health check fails, automatically rolls back

After a successful upgrade:

```
✓ Upgraded to v0.9.0
  Backup: ~/.observal/backups/v0.8.0-20260523T100000
  Rollback: observal server rollback
```

---

## `observal server rollback`

Rollback the server to a previous version from backup. Restores the database, reverts Docker images, and recreates containers.

**Requires super_admin role.**

```bash
observal server rollback
observal server rollback --from-backup ~/.observal/backups/v0.7.0-20260521T120000
observal server rollback --force
```

| Option | Short | Description |
| --- | --- | --- |
| `--from-backup` | | Path to a specific backup directory (default: most recent) |
| `--force` | `-f` | Skip interactive confirmation |

If no backup path is specified, the most recent backup is used.

---

## `observal server versions`

List available server versions from GHCR alongside local backup status. Shows which versions have images available and which have local database backups.

**Requires super_admin role.**

```bash
observal server versions
```

Output:

```
         Server Versions
┌─────────┬────────────┬──────┬─────────┐
│ Version │ Status     │ GHCR │ Backup  │
├─────────┼────────────┼──────┼─────────┤
│ 0.9.0   │ ← current │ ✓    │ -       │
│ 0.8.0   │            │ ✓    │ 42 MB   │
│ 0.7.0   │            │ ✓    │ 38 MB   │
└─────────┴────────────┴──────┴─────────┘
```

---

## Permissions

| Command | Role required |
| --- | --- |
| `start`, `stop`, `restart`, `status`, `logs`, `install`, `config`, `reset` | None (local shell access) |
| `upgrade`, `rollback`, `versions` | super_admin |

The super_admin check calls `/api/v1/auth/whoami` and verifies the authenticated user's role. If you're not logged in or lack the role, the command exits with a permission error.

---

## Related

* [Upgrades guide](../self-hosting/upgrades.md) for manual and zero-downtime upgrade strategies
* [Backup and restore](../self-hosting/backup-and-restore.md) for database backup details
* [`observal self`](self.md) for CLI version management (separate from server)
