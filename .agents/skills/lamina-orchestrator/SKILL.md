---
name: lamina-orchestrator
description: "Product design workflows — domain contracts, implement brief, verify loop. Load via Read or Skill tool when /lamina-* workflows need it."
---

# Lamina Orchestrator

Coordinates design → `ready_to_build` → external build → verify. Mode B: never writes app source.

**Guardrail:** `.lamina/` only. See [guardrails](../lamina-core/guardrails.md).

**Load protocol:** [load-protocol.md](load-protocol.md) — traverse Load lists; never invent artifact filenames.

## Modes

| Mode | When | Load |
|------|------|------|
| **Direct** | One clear topic | [lamina-core](../lamina-core/SKILL.md) → one skill |
| **Workflow** | Slash command | This skill → workflow → [audit-profiles.yaml](audit-profiles.yaml) |

## Workflows

| Workflow | File |
|----------|------|
| Router | [workflows/router.md](workflows/router.md) |
| Init | [workflows/init.md](workflows/init.md) |
| Design | [workflows/design.md](workflows/design.md) |
| Verify | [workflows/verify.md](workflows/verify.md) |

## Steps

1. **Select** — skills from audit-profiles for workflow section
2. **Apply** — **Read/Skill-load** each skill; write `run.json` incrementally under `.lamina/runs/<run_id>/`
3. **Deliver** — output contract; design ends at validated `ready_to_build` + ship-pack `implement.md`; verify ends at `findings[]` + always `fix.md`

## Files

| File | Purpose |
|------|---------|
| [load-protocol.md](load-protocol.md) | How slash + supporting skills load |
| [lib/validate-run.mjs](lib/validate-run.mjs) | Contract validator (ships with this skill) |
| [artifacts.md](artifacts.md) | `run.json` schema, lifecycle |
| [merge-rules.md](merge-rules.md) | Merge order, grounding |
| [audit-profiles.yaml](audit-profiles.yaml) | Section → skills |
| [prerequisites/init-required.md](prerequisites/init-required.md) | Init gate |
