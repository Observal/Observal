---
# SPDX-FileCopyrightText: 2026 Hemalatha Madeswaran <hemalathamadeswaran@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only
name: observal-ops
command: observal
description: View traces, spans, metrics, feedback, and telemetry health for Observal agents and MCPs. Use when the user wants to see recent traces, check metrics, view top items, submit ratings, or diagnose telemetry pipeline issues.
version: 2.0.0
owner: observal
---

# Observal Ops: Observability and Telemetry

## Critical Rules

1. **EXECUTE commands**: run them in your shell. Set timeout to 60 seconds.
2. **Pass `--output json`** on every command for stable, machine-readable output.
3. **When in doubt about a flag, run `<command> --help` first.**

---

## Procedure: Observe

```bash
observal ops overview --output json
observal ops metrics ITEM_NAME --type agent --output json
observal ops metrics ITEM_NAME --type mcp --watch
observal ops top --type agent --output json
observal ops top --type mcp --output json
observal ops traces --limit 20 --output json
observal ops traces --agent AGENT_NAME --output json
observal ops traces --mcp MCP_NAME --output json
observal ops spans TRACE_ID --output json
observal ops feedback ITEM_NAME --type mcp --output json
```

---

## Procedure: Rate Component

```bash
observal ops rate MCP_NAME --stars 5 --type mcp --comment 'Worked great'
observal ops rate AGENT_NAME --stars 4 --type agent
```

`--stars` (1-5) and `--type` are required. `--comment` is optional.

---

## Procedure: Telemetry Health

```bash
observal ops telemetry status
observal ops telemetry test
```

`status` is the reliable check: it queries server event counts and local SQLite buffer. `test` may return 404 on newer servers (legacy endpoint). If `status` shows events flowing, telemetry is healthy.

**Diagnosis:** status OK → healthy. No events → check `observal auth status`. Server reachable but no events → hooks not installed, suggest `observal doctor`.

---

## Output Contract

1. One sentence stating intent.
2. The exact command in a fenced code block.
3. The result: success / specific error.
4. The next action, or "done".
