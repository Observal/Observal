<!-- SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# Installation

Observal has two parts: a **server** you self-host and a **CLI** installed on each developer machine.

## Install the server

The server runs as a Docker Compose stack (API, web UI, PostgreSQL, ClickHouse, Redis, worker, load balancer). Prometheus and Grafana are optional deployment overlays.

> [!NOTE]
> Requires Docker Engine ≥ 24.0 with Compose v2 (`docker compose`, not `docker-compose`). Homebrew's Docker formula is outdated. Install [Docker Desktop](https://docs.docker.com/get-docker/) or use your distro's upstream packages. Verify with `docker version` and `docker compose version`.

**One-line install:**

```bash
curl -fsSL https://raw.githubusercontent.com/BlazeUp-AI/Observal/main/install-server.sh | bash
```

This downloads a config package, runs guided setup (domain, secrets, ports), pulls container images from GHCR, and starts the full stack.

**From source** (for contributors):

```bash
git clone https://github.com/BlazeUp-AI/Observal.git && cd Observal
cp .env.example .env
make up
```

For production deployment options, see [Self-Hosting](../self-hosting/docker-compose.md).

## Install the CLI

The CLI is what you use to log in, instrument harness configs, pull agents, and query traces.

## Install (standalone binary)

The standalone binary is the simplest way to install. No Python required.

```bash
curl -fsSL https://raw.githubusercontent.com/BlazeUp-AI/Observal/main/install.sh | bash
```

This downloads the latest release binary for your platform and places it on your `PATH`. The binary is the same for all editions; enterprise features activate at runtime when a valid license key is present.

To save a license key during install:

```bash
curl -fsSL https://raw.githubusercontent.com/BlazeUp-AI/Observal/main/install.sh | bash -s -- --license-key YOUR_KEY
```

This validates the Ed25519-signed key, installs the CLI, and writes the key to `~/.observal/config.json`. If the key is invalid or expired, the installer exits with an error.

Verify it worked:

```bash
observal --version
```

## Alternative: install with Python

If you prefer to install via Python, use one of these methods. Requires Python 3.11 or newer.

**pipx (recommended):**

```bash
pipx install observal-cli
```

**uv:**

```bash
uv tool install observal-cli
```

**pip:**

```bash
pip install --user observal-cli
```

### Optional extras

Observal ships with two opt-in extras for the Python install:

| Extra     | What it adds                                   | When to install                                              |
| --------- | ---------------------------------------------- | ------------------------------------------------------------ |
| `sandbox` | Docker SDK (for sandbox execution)             | If you run agents inside Observal sandboxes                  |
| `migrate` | `asyncpg` (for the `observal migrate` command) | If you operate the server and run DB migrations from the CLI |
| `all`     | Both of the above                              | If you do both                                               |

Install an extra:

```bash
uv tool install 'observal-cli[sandbox]'
```

## Install from source (for contributors)

```bash
git clone https://github.com/BlazeUp-AI/Observal.git
cd Observal
uv tool install --editable .
```

## What gets installed

Four entry points land on your `PATH`:

| Command                | Purpose                                              |
| ---------------------- | ---------------------------------------------------- |
| `observal`             | The main CLI                                         |
| `observal-shim`        | stdio shim between your harness and stdio MCP servers    |
| `observal-proxy`       | HTTP proxy between your harness and HTTP/SSE MCP servers |
| `observal-sandbox-run` | Sandbox runner invoked by Observal sandboxes         |

You will almost never call the shim, proxy, or sandbox runner directly. The CLI wires them into your harness config for you.

## Upgrade

```bash
observal self upgrade
```

## Uninstall

Standalone binary:

```bash
rm "$(which observal)"
```

Python install:

```bash
uv tool uninstall observal-cli
# or: pipx uninstall observal-cli
# or: pip uninstall observal-cli
```

Uninstalling the CLI does **not** remove your config (`~/.observal/`). Delete that folder if you want a clean slate:

```bash
rm -rf ~/.observal
```

## Next

-> [Quickstart](quickstart.md)
