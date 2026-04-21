# Gemini CLI

Gemini CLI is supported at the MCP and rules level. Mostly the same shape as [Cursor](cursor.md).

## What you get

* **MCP server instrumentation** — `observal scan --ide gemini-cli`
* **Rules files** — `AGENTS.md` or `GEMINI.md`

## What you don't get

* No hook bridge
* No native OTLP

## Setup

```bash
uv tool install observal-cli
observal auth login

observal scan --ide gemini-cli
observal doctor --ide gemini-cli
```

Restart Gemini CLI.

## Config file

`.gemini/settings.json` in your project directory.

## Install an agent

```bash
observal pull <agent-id> --ide gemini-cli
```

Writes MCP config + rules files. No session lifecycle hooks — telemetry is MCP-traffic-only.

## Known issues

* Support is labeled "limited" because we have less test coverage here than for Claude Code / Kiro. Feedback welcome on [GitHub Discussions](https://github.com/BlazeUp-AI/Observal/discussions).

## Related

* [`observal scan`](../cli/scan.md)
* [Use Cases → Observe MCP traffic](../use-cases/observe-mcp-traffic.md)
