<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# observal self

Manage the CLI binary itself: upgrade, downgrade, rollback, and check status.

## Subcommands

| Command | Description |
| --- | --- |
| [`self upgrade`](#observal-self-upgrade) | Upgrade to the latest CLI version |
| [`self downgrade`](#observal-self-downgrade) | Downgrade to a specific older version |
| [`self rollback`](#observal-self-rollback) | Restore the version before the last upgrade/downgrade |
| [`self status`](#observal-self-status) | Show version, install method, and update availability |

---

## `observal self upgrade`

Upgrade the CLI to the latest (or a specified) version from GitHub Releases. Downloads the binary, verifies its SHA-256 checksum, and atomically replaces the current binary. A backup is kept for rollback.

```bash
observal self upgrade
observal self upgrade --version 0.9.0
observal self upgrade --pre
observal self upgrade --force
```

| Option | Short | Default | Description |
| --- | --- | --- | --- |
| `--version` | `-v` | latest stable | Target version (e.g. 0.9.0) |
| `--pre` | | false | Include pre-release versions when resolving latest |
| `--force` | `-f` | false | Skip interactive confirmation |

**Managed installs:** If Observal was installed via Homebrew or a system package manager, the command detects this and tells you to upgrade through that manager instead.

**Concurrency safety:** An upgrade lock prevents two CLI processes from upgrading simultaneously. Stale locks (from crashed processes) are automatically detected and cleaned up after 30 minutes.

After upgrade:

```
✓ Upgraded to v0.9.0
  Backup saved: ~/.observal/bin/observal.prev
```

---

## `observal self downgrade`

Downgrade the CLI to a specific older version. Warns if the target version is below the server's minimum supported CLI version.

```bash
observal self downgrade --version 0.7.0
observal self downgrade --list
observal self downgrade --version 0.7.0 --force
```

| Option | Short | Default | Description |
| --- | --- | --- | --- |
| `--version` | `-v` | (required) | Target version to downgrade to |
| `--list` | `-l` | false | List all available versions with compatibility status |
| `--force` | `-f` | false | Skip confirmation and MIN_CLI_VERSION warning |

**Version listing** (`--list`) shows all GitHub releases with their publication dates and whether they're compatible with your connected server:

```
         Available Versions
┌─────────┬────────────┬────────────────────────┐
│ Version │ Published  │ Status                 │
├─────────┼────────────┼────────────────────────┤
│ 0.9.0   │ 2026-05-20 │ ← current              │
│ 0.8.0   │ 2026-05-01 │                        │
│ 0.7.0   │ 2026-04-15 │ (server minimum)       │
│ 0.6.0   │ 2026-04-01 │ ⚠ below server minimum │
└─────────┴────────────┴────────────────────────┘
```

**MIN_CLI_VERSION check:** If the connected server advertises a minimum CLI version and your target is below it, you'll see a warning that API calls may fail. Use `--force` to proceed anyway.

---

## `observal self rollback`

Restore the CLI to the version you had before the last upgrade or downgrade. Copies the backed-up binary over the current one.

```bash
observal self rollback
```

Only available for binary installs. If Observal is managed by Homebrew or a package manager, you'll need to install the previous version explicitly through that tool.

---

## `observal self status`

Show the current CLI version, how it was installed, and whether an update is available.

```bash
observal self status
```

Output:

```
  Version:  v0.8.0
  Install:  binary (~/.local/bin/observal)
  Latest:   v0.9.0 (update available)

  Run: observal self upgrade

  Server minimum: v0.7.0
```

Always checks GitHub for the latest version (ignores `OBSERVAL_NO_UPDATE_CHECK`).

---

## Version negotiation

The CLI and server negotiate feature availability based on their respective versions. When the CLI connects to the server:

1. The CLI sends its version via the `X-Observal-CLI-Version` header
2. The server responds with its version and minimum CLI requirement
3. The effective version is `min(cli_version, server_version)`
4. Features are gated based on the effective version

This means upgrading either side independently is safe: you just won't get new features until both sides support them. Downgrading below the server's minimum CLI version will cause API calls to fail.

## Update banner

When running any CLI command, a non-blocking background check queries GitHub for the latest release. If a newer version is available, a banner appears at the bottom of the output:

```
Update available: v0.8.0 → v0.9.0 • observal self upgrade
```

The banner is suppressed in CI environments, non-TTY output, and during `self` or `server` commands. This check runs at most once every 24 hours and never blocks the command. Disable with `OBSERVAL_NO_UPDATE_CHECK=1`.

---

## Related

* [`observal server`](server.md) for server-side upgrades (separate from CLI)
* [Environment variables](../reference/environment-variables.md) for `OBSERVAL_NO_UPDATE_CHECK`
