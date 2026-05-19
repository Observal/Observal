<!-- SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 tsitu0 <tomsitu0102@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# Codex CLI

Codex CLI is supported at the rules level only. It does not currently expose MCP or lifecycle hooks in a way Observal can observe.

## What you get

* **Rules files** — agent rules from the registry can be installed as `AGENTS.md`

## What you don't get

* No MCP instrumentation
* No telemetry — without MCP or hooks, there's nothing for Observal to observe
* No native OTLP

In practice, Codex CLI is a rules-only target today. Use it to ship `AGENTS.md` as part of a pulled agent; use Claude Code or Kiro for anything needing telemetry.

## Install an agent (rules only)

```bash
observal agent pull <agent-id> --ide codex
```

Writes only the rules portion of the agent.

## When the situation improves

If Codex CLI adds MCP or hook support upstream, we'll extend Observal accordingly. Follow [GitHub Discussions](https://github.com/BlazeUp-AI/Observal/discussions) for updates.

## Related

* [`observal agent pull`](../cli/pull.md)
