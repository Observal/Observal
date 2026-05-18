<!-- SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 tsitu0 <tomsitu0102@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# VS Code

VS Code (with MCP-aware extensions) is supported at the MCP and rules level.

## What you get

* **MCP server instrumentation** — `observal doctor patch --shim --ide vscode`
* **Rules files** — `AGENTS.md` at workspace root

## What you don't get

* No hook bridge from the editor itself. If you use Copilot or Claude Code inside VS Code, use those integrations instead — they pick up hooks through their respective CLIs.

## Setup

```bash
curl -fsSL https://raw.githubusercontent.com/BlazeUp-AI/Observal/main/install.sh | bash
observal auth login

observal scan --ide vscode                         # see what's there
observal doctor patch --all --ide vscode            # instrument it
observal doctor --ide vscode                        # verify
```

Reload your VS Code window.

## Config file

`.vscode/mcp.json` in the workspace directory.

## Install an agent

```bash
observal agent pull <agent-id> --ide vscode
```

## Note on Copilot and Claude Code extensions

* If you run the **Claude Code VS Code extension**, use the [Claude Code integration](claude-code.md) — it's more complete.
* **GitHub Copilot** is separately supported at the rules level only (`AGENTS.md`). No MCP support from Copilot itself.

## Related

* [`observal scan`](../cli/scan.md)
