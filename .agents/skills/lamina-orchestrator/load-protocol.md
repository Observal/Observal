# Skill load protocol (unattended + interactive)

Slash commands (`/lamina-init`, `/lamina-design`, `/lamina-verify`) inject only the **command** `SKILL.md`. That file must list **Required reads** as the first tool actions. The real workflow lives in supporting files — **traverse them**; do not invent procedures or artifact filenames.

## Command and supporting skills

- Command skills (`lamina-init`, `lamina-design`, `lamina-verify`, and `lamina`) are entered explicitly by the user or harness. Do not recursively invoke one after it has already been selected.
- Supporting skills (`lamina-orchestrator`, `lamina-dependencies`, `lamina-edge-cases`, and peers) are read or skill-invoked only when the active workflow selects them.

## Mandatory order (every slash turn)

1. Note the skill base directory from the expanded skill body (`Base directory for this skill: …`).
2. **Before any Write under `.lamina/`**, Read **every** path listed under that skill’s `## Required reads` section (resolve relative to the skill base / sibling skill dirs).
3. Follow the loaded **workflow** step-by-step. When a step says load a capability skill or profile from `audit-profiles.yaml`, Read/Skill-load that skill next — then apply it.
4. Artifact paths and schemas come **only** from [artifacts.md](artifacts.md) and [prompts/outputs/](prompts/outputs/). Do not invent names.
5. Design: validate before `ready_to_build`. Verify: always emit `runs/<id>/fix.md`. Never freestyle paths.
6. Spawn Agent/Task **only** for patterns the loaded skills define (persona panel, walkthrough, parallel review) — never to “do lamina-design/verify” with a homemade file list.

## Canonical artifacts (do not invent)

| Path | Role |
|------|------|
| `.lamina/business-context.md` | Init |
| `.lamina/personas.json` | Actors |
| `.lamina/runs/<run_id>/run.json` | Machine contract |
| `.lamina/runs/<run_id>/implement.md` | Ship pack |
| `.lamina/runs/<run_id>/report.md` | Narrative |
| `.lamina/runs/<run_id>/fix.md` | Post-verify product fixes |

**Forbidden substitutes:** `contract.md`, `persona-simulation.md`, `verify-report.md`, `.lamina/ready_to_build/*`, root `.lamina/implement.md` as the only contract, freestyle `edge_cases` / `preconditions` / `illegal_states` instead of the schema in artifacts.md.

## Why this exists

Unattended agents that skip Load files invent wrong paths and empty contracts. Traversing skill files is the product — not optional context.
