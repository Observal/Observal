<!-- SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# Sandboxes

Sandboxes are isolated Docker containers registered in Observal. When an agent has a sandbox component, it gets a callable MCP tool to execute commands inside the container — no prompt engineering needed.

## Concepts

A sandbox has these properties:

| Property | Description |
|----------|-------------|
| **Runtime Type** | `docker`, `lxc`, `firecracker`, `wasm` |
| **Image** | Docker image to run (e.g., `python:3.12-slim`, `node:20-alpine`) |
| **Resource Limits** | `timeout` (seconds), `memory_mb`, `cpu_count` |
| **Network Policy** | `none` (isolated), `host`, `bridge`, `restricted` |
| **Entrypoint** | Default command (e.g., `pytest`, `npm test`, `bash`) |

## How It Works

When a sandbox is added as an agent component:

```
observal agent pull my-agent --ide claude-code
    │
    ├── Registers "observal-sandbox" MCP server
    │   └── Exposes run_sandbox_<name> as a callable tool
    │
    └── Agent sees the tool in its tool list
        └── Calls it naturally: run_sandbox_python_pytest(command="pytest tests/")
            └── MCP server → observal-sandbox-run → Docker container → output
```

The agent doesn't need instructions on how to use it — it's a tool like Read, Write, or Bash.

## CLI Commands

### Submit a sandbox

```bash
# Interactive
observal registry sandbox submit

# From JSON file
observal registry sandbox submit --from-file sandbox.json

# As a draft
observal registry sandbox submit --draft
```

### List sandboxes

```bash
observal registry sandbox list
observal registry sandbox list --runtime docker
observal registry sandbox list --search "python"
observal registry sandbox list --output json
```

### Show sandbox details

```bash
observal registry sandbox show <name-or-id>
observal registry sandbox show <name-or-id> --output json
```

### Install (deprecated — use agent components instead)

```bash
observal registry sandbox install <name> --ide claude-code
# ⚠ Prints deprecation warning — sandboxes work best as agent components
```

### Delete a sandbox

```bash
observal registry sandbox delete <name-or-id>
observal registry sandbox delete <name-or-id> --yes
```

## Examples

### Example 1: Python test runner sandbox

```json
{
  "name": "python-pytest",
  "version": "1.0.0",
  "description": "Run Python tests in an isolated container",
  "owner": "your-name",
  "runtime_type": "docker",
  "image": "python:3.12-slim",
  "resource_limits": {"timeout": 60, "memory_mb": 256},
  "network_policy": "none",
  "entrypoint": "pytest"
}
```

```bash
observal registry sandbox submit --from-file python-pytest.json
```

### Example 2: Node.js build sandbox

```json
{
  "name": "node-builder",
  "version": "1.0.0",
  "description": "Build Node.js projects in isolation",
  "owner": "your-name",
  "runtime_type": "docker",
  "image": "node:20-alpine",
  "resource_limits": {"timeout": 120, "memory_mb": 512},
  "network_policy": "none",
  "entrypoint": "npm run build"
}
```

### Example 3: Sandbox with custom Dockerfile (monorepo)

```json
{
  "name": "custom-runner",
  "version": "1.0.0",
  "description": "Custom build environment from monorepo Dockerfile",
  "owner": "your-name",
  "runtime_type": "docker",
  "image": "custom-runner:latest",
  "resource_limits": {"timeout": 300, "memory_mb": 1024},
  "network_policy": "none",
  "source_url": "https://github.com/org/infra",
  "source_ref": "main",
  "sandbox_path": "sandboxes/custom-runner"
}
```

The `sandbox_path` field specifies where the Dockerfile lives within the repo (for monorepos with multiple sandbox definitions).

### Example 4: Agent with sandbox component (recommended)

```bash
# 1. Submit the sandbox
observal registry sandbox submit --from-file python-pytest.json
# ID: 8d37c926-...

# 2. Create an agent that uses it
cat > agent.json << 'EOF'
{
  "name": "test-runner",
  "version": "1.0.0",
  "owner": "your-name",
  "model_name": "claude-sonnet-4-20250514",
  "description": "Agent that runs tests in isolated containers",
  "prompt": "You are a test runner. Run tests when asked.",
  "components": [
    {"component_type": "sandbox", "component_id": "8d37c926-..."}
  ]
}
EOF
observal agent create --from-file agent.json

# 3. Pull the agent — sandbox becomes a callable tool
observal agent pull test-runner --ide claude-code
# Registers: observal-sandbox MCP server
# Tool available: run_sandbox_python_pytest

# 4. Use the agent
# @test-runner run the tests
# Agent calls: run_sandbox_python_pytest(command="pytest tests/ -v")
# Output: test results from inside the Docker container
```

### Example 5: Running a sandbox manually

```bash
# Direct execution (for debugging)
observal-sandbox-run \
  --sandbox-id 8d37c926-... \
  --image python:3.12-slim \
  --timeout 60 \
  --command "python -c 'print(\"hello from sandbox\")'"
# Output: hello from sandbox
```

## How the MCP Integration Works

When an agent has sandbox components, `observal agent pull` injects an `observal-sandbox` MCP server into the agent config:

**Claude Code** (`.claude/agents/<name>.md` frontmatter):
```yaml
mcpServers:
  - observal-sandbox
```

**Kiro** (`~/.kiro/agents/<name>.json`):
```json
{
  "mcpServers": {
    "observal-sandbox": {
      "command": "python3",
      "args": ["-m", "observal_cli.sandbox_mcp", "--sandboxes", "[...]"]
    }
  }
}
```

The MCP server exposes one tool per sandbox:

```
Tool: run_sandbox_python_pytest
Description: Run a command in the 'python-pytest' sandbox
             (Docker: python:3.12-slim, timeout: 60s, network: none).
             Default command: pytest
Input: {"command": "pytest tests/ -v"}
```

The agent calls it like any other tool — the MCP server handles Docker execution via `observal-sandbox-run`.

## Security

- **Network isolation** — `network_policy: "none"` means no internet access inside the container
- **Resource limits** — timeout, memory, CPU are enforced by Docker
- **No host mounts** — the container runs in isolation (only working directory is mounted)
- **Subprocess safety** — commands passed via list args (no shell injection)

## Validation

When submitting a sandbox with `source_url`, the server validates that the Dockerfile exists:

```bash
# Submitting with source validation
observal registry sandbox submit --from-file sandbox-with-source.json
# Server checks: does Dockerfile exist at sandbox_path/ in the repo?
# If not found: submit succeeds with a validation warning
# If found: validated_at timestamp is set
```

Supported forges for validation: GitHub, GitLab, Bitbucket. Private repos will show a warning (server can't verify) but the submit still succeeds.
