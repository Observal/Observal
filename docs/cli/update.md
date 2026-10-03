<!-- SPDX-License-Identifier: Apache-2.0 -->

# `observal update`

Explicit batch runner for existing Observal-managed installations. It reuses the normal `agent pull`, `registry skill install`, and `registry hook install` commands rather than running shell text from `observal outdated`. This is **not yet a startup worker**; `freeze` does not block this manual command.

```bash
observal update --all                        # preview tracked user-scope changes
observal update --all --yes                  # attempt eligible changes without prompts
observal update --all --yes --harness pi --output json
observal update --all --project --dir ./repo # preview one exact project root
observal update --all --project --dir ./repo --yes
```

For every outdated tracked item, the runner verifies the exact target release is approved for the harness. It passes an argument array (never a shell command), suppresses installer stdout/stderr to avoid exposing config values, and checks the installed-state record for the exact target **after** a successful installer exit. Each result is `available`, `updated`, `skipped`, or `failed`, with a reason and author notes. `updated` means that the existing installer completed and the installed lock shows the target; the current harness or IDE session may still need a reload. It is not an independent on-disk hash or runtime activation check. An unsuccessful command may leave partial files: inspect them before retrying.

An explicit standalone version pin is not overridden. Project agents are skipped because their committed `observal.lock` pins a version; use a reviewed `agent pull --upgrade` for those. The existing agent installer uses `--strict` and may handle added or removed components; the runner verifies its resulting component lock against the target release. Its installer may still require setup inputs or leave partial files on failure. MCPs are skipped because `registry mcp install` only generates a snippet and does not track or write a managed install. Project skill installation runs with the selected root as CWD; project hook installation passes `--dir`. The default without `--project` only considers user-scoped items. `--all` is required; without `--yes`, no installer runs.

This explicit runner is separate from automatic consent. Pi startup now uses its shared agent-install path only behind local `observal unfreeze`, with a pre-write owned-file check and durable outcome notice. The manual batch command can attempt more items because you invoked it explicitly; standalone skills, hooks and project installs are **not** silently updated by Pi startup. The manual batch runner has no rollback on partial failure. Pi's separate, gated startup path keeps a bounded private backup and restores only attributable failed writes with unchanged metadata; an ambiguous result keeps the backup and pending notice for manual repair. Other startup installers are not enabled. See [the auto-update plan](../auto-update-spec.md) and [`freeze` / `unfreeze`](freeze.md).
