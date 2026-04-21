# Upgrades

Safe upgrade flow for the Observal server stack.

## Before every upgrade

1. **Back up `pgdata`** and **`apidata`**. See [Backup and restore](backup-and-restore.md). Backing up `chdata` is nice-to-have — losing telemetry is painful but not catastrophic.
2. **Read the [CHANGELOG](https://github.com/BlazeUp-AI/Observal/blob/main/CHANGELOG.md)** for the releases you're jumping across. Note any breaking changes.
3. **Pin the version you're upgrading to** — don't `git pull main` blindly. Check out a release tag or a known-good commit.

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
curl http://localhost:8000/health
```

The API applies pending Alembic migrations automatically on startup. Watch the API logs for migration output:

```bash
docker logs -f observal-api
# INFO - Running migrations...
# INFO - Migration 0015_* -> 0016_add_ide_feature_fields.py applied.
# INFO - Database up to date.
```

## Zero-downtime upgrade (small teams)

If you run a single instance and have a ~30-second maintenance window:

1. Back up `pgdata`, `apidata`, `chdata`.
2. Stop the API and worker: `docker compose stop observal-api observal-worker`.
3. Apply migrations out-of-band: `observal migrate` (requires the `migrate` CLI extra).
4. Pull/rebuild new images: `docker compose pull && docker compose build observal-api observal-worker`.
5. Start: `docker compose up -d`.
6. Smoke test: `observal auth status && observal ops telemetry test`.

Web UI, Postgres, ClickHouse, Redis, OTEL collector stay up throughout. Users see a brief API outage (~15–30 s).

## Zero-downtime at scale

For blue/green upgrades on large deployments:

1. Run a second stack (`docker-compose.yml` with different project name and host ports) behind a reverse proxy.
2. Apply migrations via `observal migrate` — Alembic migrations are forward-compatible by design (API N-1 and N should both work against the same schema when migrations are additive).
3. Bring up the green stack pointing at the same `pgdata` / `chdata` / `apidata` volumes.
4. Flip the reverse proxy to green.
5. Decommission blue.

If a migration is **not** additive (rare, but happens — column drops, type changes), it gets called out in the CHANGELOG and requires a brief outage. Plan the window.

## Rolling back

If the new version breaks:

1. `docker compose -f docker/docker-compose.yml down`
2. `git checkout <previous-version>`
3. `docker compose -f docker/docker-compose.yml up --build -d`

**The catch:** if the failing version already applied a migration, downgrading to the previous API version may leave you running against a schema it doesn't know about. Options:

* **If the migration is additive** (most are) — the previous version works fine against the newer schema.
* **If the migration is destructive** — restore from the pre-upgrade `pgdata` backup. This is why the backup is step 1.

## CLI upgrades

CLI upgrades are independent of server upgrades. Users:

```bash
observal self upgrade
```

The CLI speaks a stable contract with the server — a newer CLI works against an older server and vice versa, within a release or two.

## Zero-downtime for the web UI

The web UI (Next.js, static after build) restarts instantly. Users see a brief reload if they're on the page during the deploy. No special handling required.

## OTEL collector upgrades

Pinned to `0.150.1` in `docker/docker-compose.yml`. To upgrade, bump the image tag and rebuild. Collector config at `otel-collector-config.yaml` must match the new version's schema — read the collector release notes.

## Next

→ [Backup and restore](backup-and-restore.md)
