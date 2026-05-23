<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# observal uninstall

Completely remove Observal from your system: stop Docker containers, delete volumes and images, remove the repo directory, config directory, and CLI tool.

## Synopsis

```bash
observal uninstall [--repo-dir <path>] [--keep-config] [--keep-cli] [--keep-repo]
```

## Options

| Option | Description |
| --- | --- |
| `--repo-dir, -d <path>` | Explicit path to the cloned Observal repo. If omitted, searches from CWD upward for `docker/docker-compose.yml`. |
| `--keep-config` | Preserve the `~/.observal/` config directory (credentials, aliases, telemetry buffer). |
| `--keep-cli` | Keep the `observal-cli` tool installed (skip the `uv tool uninstall` step). |
| `--keep-repo` | Keep the repo directory on disk. Docker teardown still runs. |

## What gets removed

By default (no `--keep-*` flags), the command removes:

1. **Docker stack**: runs `docker compose down -v --rmi all` in the `docker/` directory. This stops all containers, deletes volumes (including database data), and removes built images.
2. **Repo directory**: deletes the entire Observal source tree.
3. **Config directory**: deletes `~/.observal/` which contains `config.json`, `aliases.json`, and `telemetry_buffer.db`.
4. **CLI tool**: runs `uv tool uninstall observal-cli`.

## Confirmation

The command requires you to type `confirm` before proceeding. If the input does not match, the operation is aborted and nothing is changed.

## Platform behavior

| Platform | Behavior |
| --- | --- |
| Linux / macOS | All cleanup runs synchronously in the current process. |
| Windows | Docker teardown runs immediately. File and CLI deletion is deferred to a background PowerShell script that executes after the CLI process exits (avoids directory lock issues). |

## Safety notes

- This action is **irreversible**. Database volumes are destroyed along with all stored traces, spans, and user data.
- The command will not proceed if it cannot locate the repo directory (either via `--repo-dir` or by walking up from CWD). This prevents accidental partial uninstalls.
- On Windows, if the cleanup script fails to launch, the command prints manual instructions for completing removal.
- If `docker` is not found on PATH, the container teardown step is skipped with a warning.

## Examples

```bash
# Full uninstall from inside the repo
observal uninstall

# Keep credentials and CLI, only tear down Docker and delete the repo
observal uninstall --keep-config --keep-cli

# Specify repo path explicitly, but keep the source code
observal uninstall --repo-dir ~/code/Observal --keep-repo
```
