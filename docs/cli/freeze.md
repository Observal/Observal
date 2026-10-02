<!-- SPDX-License-Identifier: Apache-2.0 -->

# `observal freeze` and `observal unfreeze`

Control local consent for automatic **registry agent/component** updates. These commands never install or update an item themselves and do not affect `observal self` (CLI upgrades). Update checks and manual upgrades still work while frozen. Auto-updating defaults to **frozen** for everyone.

> **Rollout status:** Local consent, the concurrency gate, and ownership-baseline capture on successful explicit agent pulls are connected. Pi startup is check-only by default. An experimental Pi user-agent installer runs only when `OBSERVAL_PI_AUTO_APPLY=1` is explicitly set **and** this locally authenticated account has granted `observal unfreeze`; clean managed files and an approved target release are also required. This pilot is not yet recommended for production profiles. `unfreeze` alone never starts an installation.

```bash
observal unfreeze                          # Opt in for eligible personal installs
observal freeze                            # Turn off automatic installs
observal unfreeze --project --dir ./repo    # Also permit changes in this project
observal freeze --project --dir ./repo      # Revoke just this project's grant
observal freeze --output json
```

These commands require a locally signed-in account and configured registry URL, but make no network request. Preferences live in `~/.observal/auto-update-policy.json`, separate from the machine's `lockfile.json` and the project's committed `observal.lock`. Consent is keyed by **both the configured registry and the locally authenticated account ID**. Signing out, switching accounts, or overriding the stored token with an environment token cannot inherit another account's grant. Environment-only credentials cannot opt in until a matching local login. Legacy registry-only consent is discarded on the first policy change; run `observal unfreeze` again to grant consent to the current account. Project consent is local to this account and machine and applies **only** to the resolved project root, not child projects or teammates' checkouts. Project auto-updates additionally require the global `unfreeze`. A project grant can cause changes to files and `observal.lock` once the project updater is implemented: review and commit diffs deliberately.

`--dir` requires `--project`; without `--dir`, `--project` uses the current directory. Repeating either command is safe. A malformed or unsupported policy disables automatic updates and is not overwritten silently (legacy unscoped v1 grants are dropped rather than migrated). If an install is in progress, `freeze` waits for the shared per-registry gate: an install may complete before it returns, but a successful `freeze` prevents any new automatic install afterward. If waiting times out, the command fails instead of claiming it froze updates.

JSON results contain `registry`, `scope` (`user` or `project`), `project` (resolved path or `null`), `auto_update` (grant in this scope), and `effective` (after global policy). No token is emitted. Exit codes follow the [CLI error contract](README.md#exit-codes): 3 for missing registry or local account, 6 for busy gate, 7 for malformed policy or invalid project, 4 for permission errors, and 9 for other filesystem failures.

See [the startup update plan](../auto-update-spec.md) for eligibility rules and rollout stages, and [`observal outdated`](outdated.md) to check versions manually.
