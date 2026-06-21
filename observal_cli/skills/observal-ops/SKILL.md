---
# SPDX-FileCopyrightText: 2026 Hemalatha Madeswaran <hemalathamadeswaran@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only
name: observal-ops
command: observal
description: View traces, spans, metrics, feedback, telemetry health, and agent insight reports. Use when the user wants to see traces, check metrics, view top items, submit ratings, diagnose telemetry, or discuss how an agent is doing.
version: 2.1.0
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
observal ops traces --platform kiro --days 7 --output json
observal ops traces --turn --limit 5
observal ops traces --span --limit 3
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

## Procedure: Agent Insights

Use this when the user asks how an agent is doing, what changed, why a version regressed, what to improve, or wants to talk through an insight report.

Start with machine readable reports:

```bash
observal ops insights list AGENT_NAME --output json
observal ops insights show AGENT_NAME latest --output json
```

Fetch one section when the user asks a narrow question:

```bash
observal ops insights show AGENT_NAME latest --section at_a_glance --output json
observal ops insights show AGENT_NAME latest --section what_they_work_on --output json
observal ops insights show AGENT_NAME latest --section interaction_style --output json
observal ops insights show AGENT_NAME latest --section usage_patterns --output json
observal ops insights show AGENT_NAME latest --section what_works --output json
observal ops insights show AGENT_NAME latest --section friction_analysis --output json
observal ops insights show AGENT_NAME latest --section suggestions --output json
observal ops insights show AGENT_NAME latest --section usage_cost_analysis --output json
observal ops insights show AGENT_NAME latest --section version_comparison --output json
observal ops insights show AGENT_NAME latest --section regression_detection --output json
observal ops insights show AGENT_NAME latest --section on_the_horizon --output json
observal ops insights show AGENT_NAME latest --section fun_ending --output json
```

Section meanings:

| Section | Use for |
|---------|---------|
| `at_a_glance` | Overall health, working areas, blockers, quick win |
| `what_they_work_on` | Project areas and session counts |
| `interaction_style` | User behavior and collaboration pattern |
| `usage_patterns` | Session length, tool distribution, prompts |
| `what_works` | Agent strengths and evidence |
| `friction_analysis` | Recurring failures, severity, examples |
| `suggestions` | Config changes, features, prompts, habits |
| `usage_cost_analysis` | Cost, cache, model efficiency |
| `version_comparison` | Current version versus baseline |
| `regression_detection` | Improvements or degradations over time |
| `on_the_horizon` | Higher leverage next workflows |
| `fun_ending` | Memorable qualitative moment |

If no completed report exists, generate one:

```bash
observal ops insights generate AGENT_NAME --period 14 --wait
```

For versioned analysis, request or infer versions from `list`, then generate or show version scoped reports:

```bash
observal ops insights generate AGENT_NAME --version 1.2.0 --compare 1.1.0 --period 30 --wait
observal ops insights show AGENT_NAME latest --output json
```

Answer like an analyst: cite the report period, session count, strengths, friction, cost, version notes, and two or three concrete next actions. If data is thin, say so.

---

## Output Contract

1. One sentence stating intent.
2. The exact command in a fenced code block.
3. The result: success / specific error.
4. The next action, or "done".
