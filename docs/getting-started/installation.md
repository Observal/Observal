# Installation

Install the Observal CLI — `observal` — on your machine. The CLI is what you use to log in, instrument IDE configs, pull agents, and query traces.

If you also want to **self-host** the Observal server (API + web UI + databases), see [Self-Hosting → Docker Compose setup](../self-hosting/docker-compose.md). You can install the CLI first and point it at any Observal server later.

## Requirements

* Python **3.11 or newer** (3.11, 3.12, 3.13 are tested)
* One of: `uv` (recommended), `pipx`, or `pip`

## Install with uv (recommended)

[`uv`](https://docs.astral.sh/uv/) is the fastest way to install Python CLIs. It keeps Observal isolated in its own virtualenv without polluting your system Python.

```bash
uv tool install observal-cli
```

Verify it worked:

```bash
observal --version
```

## Install with pipx

```bash
pipx install observal-cli
```

## Install with pip

```bash
pip install --user observal-cli
```

## Optional extras

Observal ships with two opt-in extras:

| Extra | What it adds | When to install |
| --- | --- | --- |
| `sandbox` | Docker SDK (for sandbox execution) | If you'll run agents inside Observal sandboxes |
| `migrate` | `asyncpg` (for the `observal migrate` command) | If you operate the server and run DB migrations from the CLI |
| `all` | Both of the above | If you're an operator doing everything |

Install an extra:

```bash
uv tool install 'observal-cli[sandbox]'
uv tool install 'observal-cli[migrate]'
uv tool install 'observal-cli[all]'
```

## Install from source (editable)

If you're contributing or testing an unreleased build:

```bash
git clone https://github.com/BlazeUp-AI/Observal.git
cd Observal
uv tool install --editable .
```

## What gets installed

Three entry points land on your `PATH`:

| Command | Purpose |
| --- | --- |
| `observal` | The main CLI |
| `observal-shim` | stdio shim — sits between your IDE and stdio MCP servers |
| `observal-proxy` | HTTP proxy — sits between your IDE and HTTP/SSE MCP servers |
| `observal-sandbox-run` | Sandbox runner invoked by Observal sandboxes |

You will almost never call the shim, proxy, or sandbox runner directly — the CLI wires them into your IDE config for you.

## Upgrade later

```bash
observal self upgrade
```

## Uninstall

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

→ [Quickstart](quickstart.md)
