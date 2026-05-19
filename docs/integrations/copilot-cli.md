<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 tsitu0 <tomsitu0102@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# Copilot CLI

[Copilot CLI](https://docs.github.com/en/copilot/github-copilot-in-the-cli) is the standalone agentic coding CLI from GitHub (binary: `copilot`). Observal uses a hook-based bridge for session lifecycle events and `observal-shim` for MCP server instrumentation.

## What you get

* **MCP server instrumentation** via `observal-shim` (or `observal-proxy` for HTTP MCPs)
* **Session lifecycle events** via hooks — session start/end, user prompts, tool use, errors
* **Rules** (`.github/copilot-instructions.md`)

## What you don't get (yet)

| Limitation | Detail |
| --- | --- |
| **Token counts** | Copilot CLI does not expose token usage in hook payloads. |
| **Cost per call** | No per-call cost data available. |
| **Session enrichment** | No local conversation store to read turn counts or model info at session end. |

## Setup

### 1. Install Copilot CLI

```bash
curl -fsSL https://gh.io/copilot-install | bash
copilot --version
```

### 2. Install the Observal CLI

```bash
curl -fsSL https://raw.githubusercontent.com/BlazeUp-AI/Observal/main/install.sh | bash
observal auth login
```

### 3. Discover and instrument Copilot CLI

```bash
# See what MCP servers are configured
observal scan --ide copilot-cli

# Instrument them (hooks + shims + OTel)
observal doctor patch --all --ide copilot-cli
```

`doctor patch --all` does three things:

1. **Wraps MCP servers** in `~/.copilot/mcp-config.json` with `observal-shim`
2. **Injects hooks** into `~/.copilot/config.json` for session lifecycle telemetry
3. **Discovers** any project-level MCP servers in `.mcp.json`

### 4. (Optional) Pull an agent from the registry

```bash
observal agent list
observal agent pull <agent-id> --ide copilot-cli
```

This writes:

| File | Purpose |
| --- | --- |
| `.github/copilot-instructions.md` | Rules / system instructions |
| `.mcp.json` | MCP servers wrapped with `observal-shim` |

### 5. Diagnose

```bash
observal doctor --ide copilot-cli
```

### 6. Repair hooks

```bash
observal doctor patch --hook --ide copilot-cli
```

Then restart Copilot CLI.

## Config locations

| Purpose | Path |
| --- | --- |
| Settings + hooks | `~/.copilot/config.json` |
| User MCP servers | `~/.copilot/mcp-config.json` |
| Project MCP servers | `.mcp.json` (project root) |
| Rules | `.github/copilot-instructions.md` |

## How telemetry reaches Observal

### Channel 1: MCP tool calls

Same as everywhere else — `observal-shim` sits between Copilot CLI and each MCP server. Every call becomes a span.

### Channel 2: Session lifecycle (via hooks)

Observal installs hooks into `~/.copilot/config.json` under the `hooks` key. They fire at these events:

| Copilot CLI event | What it captures |
| --- | --- |
| `sessionStart` | Session begins |
| `userPromptSubmitted` | The user's prompt |
| `preToolUse` | Tool name and input (before the call) |
| `postToolUse` | Tool response (after the call) |
| `sessionEnd` | Session ends |
| `errorOccurred` | Errors during the session |

Each hook runs a Python script that reads stdin JSON, injects Observal metadata (`service_name`, `session_id`, user identity), and POSTs to `http://localhost:8000/api/v1/otel/hooks`.

### Example hook in config.json

```json
{
  "hooks": {
    "sessionStart": [
      {
        "type": "command",
        "bash": "cat | python3 /path/to/copilot_cli_hook.py --url http://localhost:8000/api/v1/otel/hooks",
        "powershell": "python /path/to/copilot_cli_hook.py --url http://localhost:8000/api/v1/otel/hooks",
        "timeoutSec": 10
      }
    ]
  }
}
```

You don't write these by hand -- `observal doctor patch --all --ide copilot-cli` generates them.

## View your traces

Open `http://localhost:3000/traces` and filter by **IDE -> copilot-cli**.

Or CLI:

```bash
observal ops traces --limit 20
```

## Troubleshooting

### Hooks not firing — sessions not appearing in the dashboard

1. Confirm hooks are in `~/.copilot/config.json`:
   ```bash
   cat ~/.copilot/config.json | python3 -m json.tool
   ```
2. Verify `disableAllHooks` is not `true` in the config.
3. Confirm the URL in the hook commands matches your server.
4. Re-inject hooks: `observal doctor patch --hook --ide copilot-cli`

### `observal doctor patch` wraps 0 servers

Your Copilot CLI MCP config may be empty. Check:

```bash
cat ~/.copilot/mcp-config.json    # user-level
cat .mcp.json                      # project-level
```

Add at least one MCP server first, then re-run `doctor patch`.

### `observal-shim` not found

Reinstall:

```bash
curl -fsSL https://raw.githubusercontent.com/BlazeUp-AI/Observal/main/install.sh | bash
which observal-shim
```

## Related

* [`observal agent pull`](../cli/pull.md)
* [`observal scan`](../cli/scan.md)
* [`observal doctor`](../cli/doctor.md)
