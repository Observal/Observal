---
name: lamina-init
description: "Use only when explicitly invoked as lamina-init. Turn an incomplete product idea into usable business context and evidence-grounded personas, asking only high-leverage questions and labeling provisional assumptions for later product-graph design."
---

# /lamina-init

## EXEC NOW — establish artifacts (copy shape)

Write both files at workspace-root `.lamina/business-context.md` and `.lamina/personas.json` (never under `.opencode/skills/…`) before responding. If orchestrator siblings are missing, still write the artifacts — do not search for missing skill files. Frontmatter MUST include `lamina.maturity` as `greenfield` or `brownfield`:

```yaml
---
lamina:
  maturity: greenfield
  platform: [web]
  last_updated: 2026-07-22
---
```

`personas.json` MUST use arrays for `goals`, `constraints`, and `evidence` (never bare strings):

```json
{
  "contract_version": "2.0",
  "personas": [
    {
      "id": "primary-user",
      "role": "Primary user",
      "primary": true,
      "goals": ["Complete core task"],
      "constraints": ["Limited time"],
      "confidence": "medium",
      "evidence": ["repo-readme"]
    },
    {
      "id": "secondary-user",
      "role": "Secondary user",
      "goals": ["Assist primary user"],
      "constraints": ["Needs clarity"],
      "confidence": "medium",
      "evidence": ["repo-readme"]
    }
  ]
}
```


## Product

Capture the minimum context needed to shape the product and persist it in `.lamina/business-context.md`. Establish mode also writes evidence-grounded `.lamina/personas.json` using Contract v2.

**Establish mode must create both** `.lamina/business-context.md` and `.lamina/personas.json` before you respond. Never edit application source (`src/`, `app/`, `lib/`, etc.) even when the user asks to refactor or implement — init writes `.lamina/` only.

If the user mixes a forbidden app-source ask with init: **refuse the refactor in one short paragraph**, then **still complete establish** using repo evidence and labeled provisional assumptions. Do not stop after questions alone in agent-primary / eval runs — write the two artifacts, then list remaining open questions under the init output contract.

## Establish artifacts (non-negotiable)

1. **`.lamina/business-context.md`** — Must start with YAML frontmatter under a top-level `lamina:` key (`maturity`, `platform`, `last_updated`), then these `##` headings **exactly once each** (copy names verbatim):
   `Problem statement`, `Business goals`, `Success metrics`, `Scope`, `Users & market`, `Product posture`, `Constraints`, `Stakeholders`, `Risks & unknowns`, `Research posture`, `Triad check`.
   Each section needs a non-placeholder `**Answer:**` line plus confidence/evidence per `lamina-business-context`.
2. **`.lamina/personas.json`** — `contract_version: "2.0"`, evidence-grounded personas (≥2 in establish mode), each with `id`, `role`, goals, constraints, `confidence`, and `evidence` refs. **Exactly one** persona must include `"primary": true`. **Filename must be `personas.json` — never `personas.yaml` or YAML.** Write JSON with a `.json` extension only; if you are about to write YAML, stop and emit JSON instead.

Run `node ../../scripts/check_lamina_init.mjs <workspace>` and `node ../../scripts/check_lamina_personas.mjs <workspace>` when available; do not report success while either check fails.

## Completion output contract

After writing artifacts, your response must use **these exact headings** from `../lamina-orchestrator/prompts/outputs/init.md`:

```markdown
## Init: <project or product name>
### Mode
establish | update
### Business context summary
Per section: answer, confidence (high | medium | low)
### Open questions
Only questions the user explicitly skipped, refused, or deferred
### Artifacts
- `.lamina/business-context.md` — created or updated
- `.lamina/personas.json` — created or updated (establish mode)
### Recommended next step
One command and why
```

## Modes

- **establish** (default) — first-time bootstrap
- **update** — pivot, new market, scope change; merges into existing file and appends changelog

### Update mode (required extras)

When the user says `update` / `pivot`, or `.lamina/business-context.md` already exists:

1. Merge changed sections into the existing business context (do not invent a blank file).
2. Append a dated `## Changelog` entry (`### YYYY-MM-DD — short label` with Changed / Trigger / Stale bullets).
3. Emit `### Stale downstream artifacts` in the completion output and name what may need refresh (personas, prior runs, etc.).
4. Say **changelog** and **stale** in the user-facing response so the update contract is explicit.

## Required reads (do this before anything else)

You are already inside this slash skill. **Do not** call `Skill` for `lamina-init`.

The skill base directory is printed above this body. Resolve paths from that base.

**Your first tool calls must be `Read` on each of these files, in order. Do not Write under `.lamina/` until all of them are read.**

1. `../lamina-orchestrator/load-protocol.md`
2. `../lamina-orchestrator/SKILL.md`
3. `../lamina-orchestrator/workflows/init.md`
4. `../lamina-orchestrator/artifacts.md`
5. `../lamina-orchestrator/audit-profiles.yaml`
6. `../lamina-business-context/SKILL.md`
7. `../lamina-orchestrator/prompts/outputs/init.md`

Then follow `workflows/init.md`. Load `lamina-user-modeling` before writing `personas.json`; load other supporting skills only when the product evidence requires them.

`business-context.md` must use every canonical `##` section heading from `lamina-business-context` exactly once. Do not combine or rename required sections (for example, keep `## Business goals` separate from `## Problem statement`, and `## Success metrics` separate from narrative success signals). Run the init check when available before reporting success.

**Do not invent artifact paths.** Only names in `artifacts.md`.

**Do not** spawn Agent/Task to “run lamina-init” with a homemade file list.

## Guardrail

Writes: `.lamina/` only. Repo: read-only. Do not create, edit, delete, format, or refactor application source. See [guardrails](../lamina-core/guardrails.md).

## Subagent hints

- **Brownfield:** [field-research](../lamina-field-research/SKILL.md)
- **Interactive:** prefer clarifying questions when humans can answer
**Agent-primary / eval:** Prefer writing provisional `.lamina/business-context.md` + `.lamina/personas.json` from repo evidence within the first few tool rounds. If orchestrator sibling files are missing from the skill install, still write both artifacts using the Establish artifacts contract above — do not spend the whole turn searching for missing skill files.
