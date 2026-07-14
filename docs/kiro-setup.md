<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# Kiro setup guide

Connect [Kiro](https://kiro.dev) to [Observal](https://github.com/BlazeUp-AI/Observal) for agent tracing, hook-based telemetry, and registry integration.

> **Note:** Kiro does not support native OpenTelemetry (OTEL). Observal bridges this gap using Kiro's hook system. Token and cost data are unavailable due to this limitation — see [Limitations](#limitations).

---

## Prerequisites

| Requirement | Details |
|---|---|
| Observal server | Running locally or on a remote host — see [SETUP.md](../SETUP.md) |
| Observal CLI | `uv tool install --editable .` |
| Kiro CLI | See step 1 below |

---

## Steps

### 1. Install Kiro CLI

```bash
curl -fsSL https://cli.kiro.dev/install | bash
```

Verify the installation:

```bash
kiro --version
```

---

### 2. Authenticate with Observal

```bash
observal auth login
# Server URL: http://localhost:8000  (or your remote server)
```

---

### 3. Configure Observal hooks in agent configs

Kiro uses lifecycle hooks defined in `.kiro/agents/*.md` or `.kiro/steering/`. Add the following block to each agent config file:

```yaml
hooks:
  - type: shell
    event: session_start
    command: "observal telemetry event --ide kiro --event session_start --agent $KIRO_AGENT_NAME"
  - type: shell
    event: session_end
    command: "observal telemetry event --ide kiro --event session_end --agent $KIRO_AGENT_NAME"
  - type: shell
    event: tool_call
    command: "observal telemetry event --ide kiro --event tool_call --agent $KIRO_AGENT_NAME --tool $KIRO_TOOL_NAME"
```

> **Tip:** Skip manual editing — `observal scan` (step 6) can inject these hooks automatically.

---

### 4. Install the telemetry bridge script

The telemetry bridge is a lightweight shell script that receives events from Kiro hooks and forwards them to Observal. It installs to `~/.observal/kiro-bridge.sh`.

```bash
observal install telemetry-bridge --ide kiro
```

---

### 5. Pull agents for Kiro

Browse and install agents from the Observal registry that are compatible with Kiro. This generates the appropriate `.kiro/agents/` config file for each agent.

```bash
# List available agents
observal agent list --ide kiro

# Install a specific agent
observal agent install <agent-id> --ide kiro
```

---

### 6. Scan Kiro configs

`observal scan` auto-detects your Kiro setup in one shot: it registers MCP servers, injects telemetry hooks into agent configs, and creates a timestamped backup of every modified file.

```bash
# Scan the current project
observal scan --ide kiro

# Preview changes without modifying any files
observal scan --ide kiro --dry-run

# Scan the global Kiro config (~)
observal scan --ide kiro --home

# Non-interactive mode (CI/scripts)
observal scan --ide kiro --yes
```

> **Tip:** Always run `--dry-run` first to review what will change before committing.

---

### 7. Run diagnostics

```bash
observal doctor --ide kiro
```

This checks that the Kiro CLI, server connection, hook configs, bridge script, and MCP server registrations are all in order. A passing output looks like:

```
✓ kiro CLI found (v0.x.x)
✓ Observal server reachable at http://localhost:8000
✓ Hook configs detected in .kiro/agents/
✓ Telemetry bridge installed at ~/.observal/kiro-bridge.sh
✓ 2 MCP server(s) registered
```

---

### 8. Verify telemetry is flowing

Start a Kiro session, then check for incoming traces:

```bash
observal telemetry status
```

Sessions should appear under the Kiro platform in the trace list at `http://localhost:3000`.

---

## Troubleshooting

**`observal doctor` reports "Hook configs not found"**

Run `observal scan --ide kiro` to inject hooks into your agent configs automatically.

---

**`observal doctor` reports "Telemetry bridge not found"**

Run `observal install telemetry-bridge --ide kiro` to reinstall the bridge script.

---

**No sessions appearing in the dashboard after a Kiro session**

Work through the following checks in order:

1. Confirm the Observal server is running:
   ```bash
   curl http://localhost:8000/health
   ```
2. Check server logs:
   ```bash
   docker compose logs -f observal-api
   ```
3. Confirm the bridge script is executable:
   ```bash
   ls -la ~/.observal/kiro-bridge.sh
   ```
4. Check that hooks are firing — run Kiro with verbose logging if available.

---

**`observal scan` modifies the wrong config files**

Use `--dry-run` first to preview all changes. A timestamped backup is always created before any modifications.

---

**MCP servers not detected by `observal scan`**

Ensure MCP servers are defined in the standard Kiro config location (`.kiro/settings/mcp.json` or equivalent for your Kiro version). Run `kiro config show` if unsure of the path.

---

## Limitations

Kiro does not currently support native OTEL, which limits what Observal can observe. These limitations exist because Kiro's hook system exposes only shell-level events and does not provide access to the underlying LLM request/response metadata.

| Capability | Status |
|---|---|
| MCP tool call tracing (via shim) | ✅ Available |
| Session start/end events (via hooks) | ✅ Available |
| Agent and skill discovery (via scan) | ✅ Available |
| Token usage per session | ❌ Not available |
| Cost per session | ❌ Not available |
| Model name per session | ❌ Not available |
| Distributed trace context propagation | ❌ Not available |

Token, cost, and model data will become available if Kiro adds native OTEL support in a future release.
