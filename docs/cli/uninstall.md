# observal uninstall

Completely remove a local Observal installation. The command tears down the Docker stack, removes Docker volumes and images for that stack, and then deletes the local repo, CLI config, and CLI tool unless you ask it to keep them.

Use this when you want to reset a self-hosted local install or clean up a development machine.

## Synopsis

```bash
observal uninstall [--repo-dir <path>] [--keep-config] [--keep-cli] [--keep-repo]
```

## Options

| Option | Short | Description |
| --- | --- | --- |
| `--repo-dir <path>` | `-d` | Path to the cloned Observal repo. Required if the command cannot detect the repo from the current directory or one of its parents. |
| `--keep-config` | — | Keep the local CLI config directory at `~/.observal/`. |
| `--keep-cli` | — | Keep the `observal-cli` tool installed in `uv`. |
| `--keep-repo` | — | Keep the cloned Observal repo directory. Docker teardown still runs. |

## Confirmation

`observal uninstall` is destructive and interactive. Before anything is removed, it prints the planned cleanup and asks for confirmation.

Type exactly:

```text
confirm
```

Any other response aborts the uninstall.

## Repo detection

The command must find the Observal repo before it can run Docker teardown.

Detection order:

1. If `--repo-dir <path>` is provided, that directory must contain `docker/docker-compose.yml`.
2. Otherwise, the command checks the current working directory and then walks up each parent directory looking for `docker/docker-compose.yml`.

If no repo is found, the command exits with an error and does not continue.

## What is removed by default

By default, `observal uninstall` touches these local resources:

| Resource | How it is removed |
| --- | --- |
| Docker containers for the Observal Compose stack | Runs `docker compose down -v --rmi all` from `<repo>/docker`. |
| Docker volumes for the Compose stack | Removed by the same `docker compose down -v --rmi all` command. |
| Docker images for the Compose stack | Removed by the same `docker compose down -v --rmi all` command. |
| Cloned Observal repo directory | Deletes the detected repo directory unless `--keep-repo` is set. |
| Local CLI config directory | Deletes `~/.observal/` unless `--keep-config` is set. |
| CLI tool | Runs `uv tool uninstall observal-cli` unless `--keep-cli` is set. |

The command skips a directory if it is already missing. If `docker` is not installed or Docker teardown fails, the command reports the failure and continues with the remaining cleanup steps.

## What is left behind by design

Use keep flags when you want to remove only part of the installation.

| Flag | What remains |
| --- | --- |
| `--keep-config` | `~/.observal/`, including local config, aliases, and cached CLI state. |
| `--keep-cli` | The `observal-cli` tool installed through `uv`. |
| `--keep-repo` | The cloned Observal repo directory. Docker containers, volumes, and images are still removed. |

The uninstall command only targets the detected local Observal repo, the `~/.observal/` config directory, the Docker Compose resources it tears down from `<repo>/docker`, and the `uv` tool installation named `observal-cli`.

## Complete wipe recipe

From inside the cloned Observal repo:

```bash
observal uninstall
# When prompted, type: confirm
```

If you are outside the repo, pass its path explicitly:

```bash
observal uninstall --repo-dir /path/to/Observal
# When prompted, type: confirm
```

This performs the full default cleanup:

1. Stops the Docker Compose stack.
2. Removes Compose volumes and images for that stack.
3. Deletes the cloned repo directory.
4. Deletes `~/.observal/`.
5. Uninstalls `observal-cli` through `uv`.

## Manual cleanup fallback

If the command cannot complete every step, you can clean up manually.

```bash
# 1. Tear down Docker resources from the repo's docker directory
cd /path/to/Observal/docker
docker compose down -v --rmi all

# 2. Remove local CLI state
rm -rf ~/.observal

# 3. Remove the cloned repo
rm -rf /path/to/Observal

# 4. Remove the CLI tool
uv tool uninstall observal-cli
```

On Windows PowerShell, use `Remove-Item -Recurse -Force` for directories instead of `rm -rf`.

## Windows behavior

On Windows, repo deletion, config deletion, and CLI uninstall are deferred to an auto-generated PowerShell cleanup script. This avoids file-lock issues when the current terminal or another process still has files open in the repo.

The command schedules cleanup in the background and then tells you to close the terminal window if any directory locks remain. If PowerShell cannot be started, the command prints the path to the generated script so you can run it manually:

```powershell
powershell -ExecutionPolicy Bypass -File <script-path>
```

The generated script deletes itself after it runs.

## Troubleshooting

### Repo not found

Run from inside the cloned Observal repo, or pass `--repo-dir`:

```bash
observal uninstall --repo-dir /path/to/Observal
```

The target directory must contain `docker/docker-compose.yml`.

### Docker teardown fails

Make sure Docker is installed and running, then retry from the repo:

```bash
cd /path/to/Observal/docker
docker compose down -v --rmi all
```

If Docker is not available, the uninstall command skips container teardown and continues with local file cleanup.

### Permission denied deleting files

Close editors, terminals, and shells that are using files inside the Observal repo or `~/.observal/`, then retry the delete step manually.

### `uv` is missing

If `uv` is not installed, remove the CLI tool manually using the package manager or installation method you used originally. The uninstall command reports that it could not run `uv tool uninstall observal-cli` and continues.

## Related

* [`observal doctor`](doctor.md) — diagnose a running installation
* [`observal config`](config.md) — inspect local CLI configuration
* [`observal self`](self.md) — upgrade or downgrade the CLI
