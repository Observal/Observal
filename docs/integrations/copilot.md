<!-- SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# Copilot

GitHub Copilot in VS Code is supported at the MCP and rules level. Telemetry is MCP-traffic-only for this integration because the editor extension does not expose the same session lifecycle hook surface as Copilot CLI.

## What you get

* **MCP server instrumentation** -- `observal doctor patch --shim --ide copilot` wraps MCPs via `observal-shim`
* **Rules files** -- Copilot reads `.github/copilot-instructions.md` for repository instructions

## What you don't get

* No hook bridge from the VS Code extension -- no session start/stop, user prompt, or subagent events
* No native OTLP
* No skill packages

If lifecycle hooks matter, use [Copilot CLI](copilot-cli.md), Claude Code, or Kiro instead.

## Setup

```bash
curl -fsSL https://raw.githubusercontent.com/BlazeUp-AI/Observal/main/install.sh | bash
observal auth login

observal scan --ide copilot                         # see what's there
observal doctor patch --shim --ide copilot           # instrument MCP servers
observal doctor --ide copilot                        # verify
```

Reload VS Code after patching so Copilot sees the updated MCP config.

## Config file

`.vscode/mcp.json` in your workspace stores Copilot MCP servers under the `servers` key. After `doctor patch --shim`, local MCP entries route through `observal-shim`. A timestamped `.bak` is saved next to the file before it is modified.

Rules live in `.github/copilot-instructions.md`.

## Install an agent

```bash
observal pull <agent-id> --ide copilot
```

What gets written:

* MCP servers appended to `.vscode/mcp.json`
* `.github/copilot-instructions.md` with the agent's rules

Copilot reloads rules and MCP configuration with the workspace. Reload the VS Code window if the new config is not picked up immediately.

## Caveats

* Copilot configuration is project-level. Repeat `doctor patch` for each workspace that has its own `.vscode/mcp.json`.
* Because there are no lifecycle hooks, traces are tool-call-level. You won't see prompt-to-session timelines unless you use Copilot CLI.
* Copilot CLI is a separate integration with its own config paths under `~/.copilot/`.

## Related

* [Copilot CLI](copilot-cli.md)
* [`observal scan`](../cli/scan.md)
* [Use Cases -> Observe MCP traffic](../use-cases/observe-mcp-traffic.md)
