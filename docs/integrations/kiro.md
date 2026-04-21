# Kiro CLI

[Kiro CLI](https://kiro.dev) is fully supported. It doesn't yet export OpenTelemetry natively ([kirodotdev/Kiro#6319](https://github.com/kirodotdev/Kiro/issues/6319)), so Observal uses a hook-based bridge for session lifecycle events. MCP traffic flows through `observal-shim` the same way it does everywhere else.

## What you get

* **MCP server instrumentation** via `observal-shim` (or `observal-proxy` for HTTP MCPs)
* **Session lifecycle events** via hooks — session start/stop, user prompts, tool use
* **Superpowers** — packaged bundles of MCP + steering + hooks
* **Steering files** — instruction files with YAML frontmatter for inclusion modes
* **Rules (AGENTS.md)**

## What you don't get (yet)

Kiro upstream limits these; they resolve when Kiro implements native OTEL:

| Limitation | Detail |
| --- | --- |
| **Token counts** | Kiro exposes billing credits, not input/output tokens. Observal shows credits for Kiro sessions. |
| **Cost per call** | Session-level credits only, not per-call. |
| **Model name** | Often reported as `"auto"`; Observal resolves it from Kiro's local SQLite DB when possible. |
| **Subagent lifecycle** | Kiro has no subagent events. |

## Setup

### 1. Install Kiro CLI

macOS / Linux:

```bash
curl -fsSL https://cli.kiro.dev/install | bash
```

Windows: download from [kiro.dev/download](https://kiro.dev/download).

Then:

```bash
kiro --version
kiro login
```

### 2. Install the Observal CLI

```bash
uv tool install observal-cli
observal auth login
```

### 3. Instrument Kiro MCP servers

```bash
# Project-level (.kiro/settings/mcp.json in current directory)
observal scan --ide kiro

# Global (~/.kiro/settings/mcp.json)
observal scan --ide kiro --home
```

Expected output:

```
Scanning Kiro config...
  ✓ filesystem-server   wrapped
  ✓ github-mcp          wrapped
  ✓ mcp-obsidian        wrapped

Backup saved: .kiro/settings/mcp.json.20260421_143055.bak
3 server(s) instrumented.
```

### 4. (Optional) Pull an agent from the registry

```bash
observal agent list
observal pull <agent-id> --ide kiro
```

This writes:

| File | Purpose |
| --- | --- |
| `~/.kiro/agents/<name>.json` | Agent config with Observal telemetry hooks |
| `.kiro/steering/<name>.md` | Steering file (the agent's system instructions) |

### 5. Diagnose

```bash
observal doctor --ide kiro
observal doctor --ide kiro --fix
```

Then restart Kiro.

## How telemetry reaches Observal

### Channel 1: MCP tool calls

Same as everywhere else — `observal-shim` sits between Kiro and each MCP server. Every call becomes a span. Zero behavior change, transparent interception.

### Channel 2: Session lifecycle (via hooks)

Observal installs shell hooks into each Kiro agent JSON. They fire at these events:

| Kiro event | What it captures |
| --- | --- |
| `agentSpawn` | Session start |
| `userPromptSubmit` | The user's prompt |
| `preToolUse` | Tool name and input (before the call) |
| `postToolUse` | Tool response (after the call) |
| `stop` | Session end, credit usage, resolved model ID |

Each hook is a `curl` call to `http://localhost:8000/api/v1/otel/hooks` (or your Observal server URL).

### Example agent JSON

```json
{
  "name": "my-agent",
  "hooks": {
    "agentSpawn":       "curl -s -X POST http://localhost:8000/api/v1/otel/hooks ...",
    "userPromptSubmit": "curl -s -X POST http://localhost:8000/api/v1/otel/hooks ...",
    "preToolUse":       "curl -s -X POST http://localhost:8000/api/v1/otel/hooks ...",
    "postToolUse":      "curl -s -X POST http://localhost:8000/api/v1/otel/hooks ...",
    "stop":             "curl -s -X POST http://localhost:8000/api/v1/otel/hooks ..."
  }
}
```

You don't write these by hand — `observal pull` generates them.

## View your traces

Open `http://localhost:3000/traces` and filter by **IDE → Kiro**.

Or CLI:

```bash
observal ops traces --limit 20
```

## Troubleshooting

### `observal auth login` fails — "server not reachable"

```bash
observal config show
observal config set server_url http://localhost:8000
observal auth login
```

### `observal scan` wraps 0 servers

Your Kiro MCP config may be empty or in an unexpected location. Check:

```bash
cat .kiro/settings/mcp.json        # project
cat ~/.kiro/settings/mcp.json      # global
```

Add at least one MCP server to Kiro first, then re-run `scan`.

### Hooks not firing — sessions not appearing in the dashboard

1. Confirm the `OBSERVAL_API_KEY` env var is set where Kiro runs:
   ```bash
   echo $OBSERVAL_API_KEY
   ```
2. Open the agent JSON and verify a `hooks` section exists.
3. Confirm the URL in the hook commands matches your server.

### `observal-shim` not found

```bash
uv tool install --force observal-cli
which observal-shim
```

### `observal doctor` reports issues but `--fix` doesn't resolve

Run with verbose output:

```bash
observal doctor --ide kiro --fix
observal auth status
```

If the server is unreachable, see [Self-Hosting → Troubleshooting](../self-hosting/troubleshooting.md).

## Detailed compatibility matrix

For every gap between Kiro and Claude Code (hook event names, missing fields, etc.), see the [full matrix](https://github.com/BlazeUp-AI/Observal/blob/main/docs/internal/kiro-compatibility-matrix.md) maintained as research notes in the repo.

## Related

* [`observal pull`](../cli/pull.md)
* [`observal scan`](../cli/scan.md)
* [`observal doctor`](../cli/doctor.md)
