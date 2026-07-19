<!-- SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Upgrades

Safe upgrade flow for the Observal server stack.

## Quick upgrade (recommended)

If you installed Observal via `observal server start` (the embedded stack), the CLI handles upgrades automatically:

```bash
observal server upgrade
observal server upgrade --version 0.9.0
```

This pulls new Docker images, backs up your database, recreates containers, and runs health checks. If the health check fails, it rolls back automatically. Requires **super_admin** role.

See [`observal server upgrade`](../cli/server.md#observal-server-upgrade) for full details.

## Before a manual upgrade

1. **Back up `pgdata`** and **`apidata`**. See [Backup and restore](backup-and-restore.md). Backing up `chdata` is nice-to-have; losing telemetry is painful but not catastrophic.
2. **Read the [CHANGELOG](https://github.com/Observal/Observal/blob/main/CHANGELOG.md)** for the releases you're jumping across. Note any breaking changes.
3. **Pin the version you're upgrading to**: don't `git pull main` blindly. Check out a release tag or a known-good commit.

## Standard upgrade

```bash
cd Observal

# Fetch and check out the target version
git fetch --tags
git checkout v0.9.1

# Rebuild images
docker compose -f docker/docker-compose.yml pull
docker compose -f docker/docker-compose.yml up --build -d

# Verify
docker compose -f docker/docker-compose.yml ps
curl http://localhost/health
```

The init container applies pending Postgres Alembic migrations and ClickHouse SQL migrations before the API starts. Watch the init logs for migration output:

```bash
docker logs -f observal-init
# Running database migrations...
# Running ClickHouse migrations...
```

## Zero-downtime upgrade (small teams)

If you run a single instance and have a ~30-second maintenance window:

1. Back up `pgdata`, `apidata`, `chdata`.
2. Stop the API and worker: `docker compose stop observal-api observal-worker`.
3. Apply migrations out of band with `alembic upgrade head` and `python -m services.clickhouse.migrations` from `observal-server`, or run the init container once.
4. Pull/rebuild new images: `docker compose pull && docker compose build observal-api observal-worker`.
5. Start: `docker compose up -d`.
6. Smoke test: `observal auth status && observal ops telemetry test`.

Web UI, Postgres, ClickHouse, Redis stay up throughout. Users see a brief API outage (~15–30 s).

## Zero-downtime at scale

For blue/green upgrades on large deployments:

1. Run a second stack (`docker-compose.yml` with different project name and host ports) behind a reverse proxy.
2. Apply migrations before traffic cutover. Alembic handles Postgres and `services.clickhouse.migrations` handles ClickHouse. Additive migrations should work with API N-1 and N during the rollout.
3. Bring up the green stack pointing at the same `pgdata` / `chdata` / `apidata` volumes.
4. Flip the reverse proxy to green.
5. Decommission blue.

If a migration is **not** additive (rare, but happens: column drops, type changes), it gets called out in the CHANGELOG and requires a brief outage. Plan the window.

## Rolling back

If the new version breaks:

1. `docker compose -f docker/docker-compose.yml down`
2. `git checkout <previous-version>`
3. `docker compose -f docker/docker-compose.yml up --build -d`

**The catch:** if the failing version already applied a migration, downgrading to the previous API version may leave you running against a schema it doesn't know about. Options:

* **If the migration is additive** (most are): the previous version works fine against the newer schema.
* **If the migration is destructive**: restore from the pre-upgrade `pgdata` backup. This is why the backup is step 1.

## CLI upgrades

CLI upgrades are independent of server upgrades. Users:

```bash
observal self upgrade
```

The CLI speaks a stable contract with the server. A newer CLI works against an older server and vice versa, within a release or two.

On the first command after upgrading from a release that generated `observal-shim` entries, the CLI restores the original MCP command in known home and current-project config files. It writes a `.pre-unshim.bak` copy before each change. A malformed wrapped entry stops the command with a visible migration error rather than guessing at the original executable.

## Zero-downtime for the web UI

The web UI is a static Vite build and restarts instantly. Users see a brief reload if they are on the page during the deploy. No special handling required.

## Next

→ [Backup and restore](backup-and-restore.md)
