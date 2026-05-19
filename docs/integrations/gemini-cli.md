<!-- SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 tsitu0 <tomsitu0102@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# Gemini CLI

Gemini CLI is supported at the MCP, rules, hook bridge, and OTLP telemetry level.

## What you get

* **MCP server instrumentation** — `observal doctor patch --shim --ide gemini-cli`
* **Rules files** — `AGENTS.md` or `GEMINI.md`
* **OTLP telemetry** — `observal doctor patch --all` configures `~/.gemini/settings.json` to export traces via OTLP
* **Hook bridge** — `observal doctor patch --hook` injects hooks into `~/.gemini/settings.json` to capture prompts, tool I/O, agent responses, and session lifecycle events

## Setup

```bash
curl -fsSL https://raw.githubusercontent.com/BlazeUp-AI/Observal/main/install.sh | bash
observal auth login

observal scan --ide gemini-cli                     # see what's there
observal doctor patch --all --ide gemini-cli        # instrument it
observal doctor --ide gemini-cli                    # verify
```

Restart Gemini CLI.

## Config file

`.gemini/settings.json` in your project directory.

## Install an agent

```bash
observal agent pull <agent-id> --ide gemini-cli
```

Writes MCP config + rules files. OTLP telemetry and hooks are configured automatically by `observal doctor patch --all`.

## Known issues

* Support is labeled "limited" because we have less test coverage here than for Claude Code / Kiro. Feedback welcome on [GitHub Discussions](https://github.com/BlazeUp-AI/Observal/discussions).

## Related

* [`observal scan`](../cli/scan.md)
* [Use Cases → Observe MCP traffic](../use-cases/observe-mcp-traffic.md)
