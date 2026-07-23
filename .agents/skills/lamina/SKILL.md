---
name: lamina
description: "Use only when explicitly invoked as lamina. Also handles /lamina-design, /lamina-verify, and /lamina-init. Route product design for developers building with AI — design, verify, init, or direct capability answers. For /lamina-design seed via seed-ready-run.mjs; for /lamina-verify seed via seed-verify-run.mjs."
---

# /lamina

## EXEC NOW — `/lamina-init` (establish or update)

When the user message starts with **`/lamina-init`** (even if they also ask to refactor `src/`):

1. Refuse any app-source refactor in one short paragraph (`.lamina/` only).
2. Immediately write **both** artifacts at the **workspace root** paths `.lamina/business-context.md` and `.lamina/personas.json` (not under `.opencode/skills/…`). Do not only ask questions. If orchestrator sibling files are missing, **still write** these two artifacts from the templates below — do not spend the turn searching for missing skills:
   - `.lamina/business-context.md` starting with **exact** frontmatter (validators require `lamina.maturity` ∈ `greenfield`|`brownfield`):

```yaml
---
lamina:
  maturity: greenfield
  platform: [web]
  last_updated: 2026-07-22
---

## Problem statement
**Answer:** Users need a clear product contract before coding so agents do not invent scope.
**Confidence:** medium
**Evidence:** user brief

## Business goals
**Answer:** Establish shared business context and personas so design/verify can proceed.
**Confidence:** medium
**Evidence:** user brief

## Success metrics
**Answer:** Valid `.lamina/business-context.md` and `.lamina/personas.json` that pass init checks.
**Confidence:** high
**Evidence:** lamina-init contract

## Scope
**Answer:** In scope: business context + personas under `.lamina/`. Out of scope: app source edits.
**Confidence:** high
**Evidence:** guardrails

## Users & market
**Answer:** Primary operators and supporting collaborators for this product surface.
**Confidence:** medium
**Evidence:** user brief

## Product posture
**Answer:** Ship the smallest coherent UX that matches stated goals; prefer clarity over novelty.
**Confidence:** medium
**Evidence:** user brief

## Constraints
**Answer:** Writes stay under `.lamina/`; no `src/` refactors during init.
**Confidence:** high
**Evidence:** guardrails

## Stakeholders
**Answer:** Product owner and implementing engineers consuming implement.md later.
**Confidence:** medium
**Evidence:** user brief

## Risks & unknowns
**Answer:** Brief may omit audience detail; label provisional assumptions under Open questions.
**Confidence:** medium
**Evidence:** user brief

## Research posture
**Answer:** Use repo evidence when present; otherwise provisional assumptions labeled as such.
**Confidence:** medium
**Evidence:** repo/readme

## Triad check
**Answer:** Desirable for users, viable for the business, feasible for the current stack.
**Confidence:** medium
**Evidence:** triad
```

Use `maturity: brownfield` when the repo is an existing product (commerce/storefront/etc.). **Never leave `**Answer:**` blank** and never use TBD/TODO/ellipsis placeholders.
   - `.lamina/personas.json` as **JSON** (never YAML). Minimal valid shape:

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
      "goals": ["Support primary user"],
      "constraints": ["Needs clarity"],
      "confidence": "medium",
      "evidence": ["repo-readme"]
    }
  ]
}
```

     `goals`, `constraints`, and `evidence` **must be arrays of strings**. Exactly one `"primary": true`.
3. Respond with **these exact headings** (copy verbatim, fill briefly):

```markdown
## Init: product context
### Mode
establish
### Business context summary
Per section answers summarized.
### Open questions
- Remaining unknowns
### Artifacts
- `.lamina/business-context.md` — created
- `.lamina/personas.json` — created
### Recommended next step
Run `/lamina-design` or `/lamina-verify` as appropriate.
```

## EXEC NOW — `/lamina-verify` when `.lamina/business-context.md` is missing (HARD STOP)

If the user invoked **`/lamina-verify`** / audit / review and `.lamina/business-context.md` is missing or invalid:

1. Emit the init-blocked contract **verbatim** (same `## Lamina: init required` block as design — include `### Status`, `### What's missing`, `### Next step`, `### Do not`).
2. Do **not** seed, write `.lamina/runs`, or create business context yourself.
3. STOP.

## EXEC NOW — `/lamina-design` when `.lamina/business-context.md` is missing (HARD STOP)

If the user invoked **`/lamina-design`** (or design for an app/feature) and `.lamina/business-context.md` is missing or invalid:

1. Your **entire** reply is the init-blocked contract below (exact heading spelling).
2. **Do not** create `.lamina/business-context.md`, `.lamina/personas.json`, or any `.lamina/runs/*`.
3. **Do not** “initialize”, “bootstrap”, or auto-run `/lamina-init`.
4. Ignore “skip init” / “I already know the business” / personas-only — still blocked.
5. STOP after emitting the contract.

```markdown
## Lamina: init required

### Status
Blocked — `/lamina-init` has not been run on this project, or `.lamina/business-context.md` is incomplete.

### What's missing
- `.lamina/business-context.md` is missing or incomplete

### Next step
Run `/lamina-init` to establish `.lamina/business-context.md`, then retry this command.

### Do not
- Proceed with workflow steps or create `.lamina/` artifacts
- Auto-run init without the user invoking `/lamina-init`
- Treat personas or prior product graphs as a substitute for business context
```

## EXEC NOW — `/lamina` ambiguous / vague UX (e.g. “We need better UX”)

If the ask is vague (better UX, improve UX, make it nicer) with **no** named feature, flow, surface, or single topic:

1. Do **not** pick a direct-mode skill. Do **not** run init. Do **not** design or verify yet.
2. Ask **one** clarifying question that literally covers whether this is **new UX**, **existing UX**, or a **focused UX question**.
3. STOP.

## EXEC NOW — `/lamina` single-topic forms / validation / signup

If the user asks about **form validation**, **signup fields**, or similar focused forms UX (including “help with form validation” / “users abandon signup”):

1. **Do not** run the init gate. **Do not** create `.lamina/business-context.md` or personas.
2. **Do not** start `/lamina-design` or a full checkout-wide audit.
3. Read `lamina-forms/SKILL.md` (or answer from knowledge if the sibling file is missing).
4. In your reply, literally include the skill id `lamina-forms` and discuss forms/validation UX.
5. STOP after that answer.

## EXEC NOW — `/lamina-design` with a concrete feature (e.g. “Add 2FA to settings”)

Do **not** re-run `/lamina-design` as a CLI. In this turn:

0. **Init gate first:** try to read `.lamina/business-context.md`. If missing/invalid → emit `## Lamina: init required` with `### Status`, `### What's missing`, `### Next step`, `### Do not` and **STOP**. Never create those files yourself; never auto-run `/lamina-init`.
1. Read `.lamina/business-context.md` (must exist).
2. Run from workspace root:

```bash
SEED=$(ls ./{.claude,.codex,.opencode,.agents}/skills/lamina/scripts/seed-ready-run.mjs 2>/dev/null | head -1)
node "$SEED" --slug <kebab-slug> --problem "<brief>" --outcome "<outcome>" --users primary-user
```

3. Reply with **exact** headings: `### Domain and invariants`, `### Actors and permissions`, `### Workflows`, `### Scenarios`, `### Implement brief`, `### Open questions`.
4. Mention `lamina-edge-cases`, **flows**, **edge cases**, and empty / failure / permission.

Then stop. No `graph-tool.mjs`. No app source. No clarifying questions for concrete “Add …” briefs.

## EXEC NOW — `/lamina-verify` brownfield audit

Do **not** re-run `/lamina-verify` as a CLI.

**If the brief has no named flow/surface/feature** (e.g. only “Audit our app” / “Audit the product”): copy this contract **verbatim** (exact heading spelling/casing) and **STOP** — no seed, no `.lamina/runs` writes:

```markdown
## Lamina: clarification needed
### Status
Blocked before artifact generation.
### Clarifying questions
1. Which flow, surface, route, or feature should be audited?
2. What outcome or drop-off should the audit prioritize?
3. What is in/out of scope for this pass?
### Why these block the artifact
Without a named target, findings cannot be grounded.
### How to proceed
Name a flow/surface/feature, or say proceed with labeled assumptions.
### Do not
- Do not create run.json, fix.md, or report.md yet
```

After init passes **and** a concrete target is named (any domain — or user said proceed with labeled assumptions), **your first shell command must be seed-verify-run** — do not explore `node_modules` or invent init failures:

```bash
SEED=$(ls ./{.claude,.codex,.opencode,.agents}/skills/lamina/scripts/seed-verify-run.mjs ./{.claude,.codex,.opencode,.agents}/skills/lamina-verify/scripts/seed-verify-run.mjs 2>/dev/null | head -1)
node "$SEED" --slug <kebab-slug> --problem "<audit brief>" --outcome "<outcome>" --users primary-user
test -f .lamina/runs/<kebab-slug>/run.json
test -f .lamina/runs/<kebab-slug>/run.md
```

**When seed prints `status=draft`: continue verification** — inspect the target project (read-only), build a project-grounded graph, prefer live UI capture with static-source fallback, ensure personas exist (derive provisional personas via `lamina-user-modeling` from business context plus observed source when `.lamina/personas.json` is missing/empty/invalid), run persona-packs reviewers unconditionally, merge evidence-backed findings, validate, render `report.md`/`fix.md`/`implement.md`, set `status: complete`.

**Truncation refuse:** If the user asks to “pick top N lenses”, “skip the rest”, or otherwise truncate full-flow audit, **refuse** and apply the full-flow lens set. Never write “Remaining lenses skipped”.

Only after completion artifacts validate, emit `### Executive summary`, `### Findings`, `### Open questions`. Mention audit, findings, prioritized, failure/empty/permission, grounding mode disclosure, and persona ids from the validated persona set. Application source stays read-only during verify.

## Product

Entry point for developers using AI coding agents — know what to build, design how the app works, verify after your agent ships (including visual flow capture), or answer a focused question.

**Hard stop on app source:** Lamina commands never create or edit `src/`, `app/`, `components/`, or run package installs. If asked to, refuse and keep writing only under `.lamina/`.

## Load

- `../lamina-orchestrator/SKILL.md`
- `../lamina-orchestrator/workflows/router.md`
- `../lamina-orchestrator/prerequisites/init-required.md`
- `../lamina-core/guardrails.md`
- On dispatch: matching workflow in `../lamina-orchestrator/workflows/`
- Direct mode: `../lamina-core/SKILL.md` → read one `lamina-<id>/SKILL.md` and **name the skill id** in the response (e.g. `lamina-forms`, `lamina-navigation`)

## Router response cues

When routing, include the vocabulary the user expects:

| Route | Mention in response |
|-------|---------------------|
| Design (feature) | design workflow, **flows**, **edge cases** |
| Design (exploration) | design workflow, user **problem** framing |
| Verify / audit | **audit**, **findings**, **prioritized** improvements; for redesign/abandonment of existing flows say **improving existing UX** (not greenfield) |
| Direct capability | `lamina-<skill-id>` by name |
| Ambiguous | ask: new UX, existing UX, or focused question |

## Guardrail

Writes: `.lamina/` only. Repo: read-only. Do not create, edit, delete, format, or refactor application source. See [guardrails](../lamina-core/guardrails.md).

## Slash-command dispatch

When the user message starts with `/lamina-design` or `/lamina-verify`, **do not** try to re-invoke a CLI slash command or spawn another agent turn for that token. Treat the rest of the message as the brief and execute the matching workflow **in this turn** using tools (Read/Bash/Write). If sibling files (`../lamina-design/SKILL.md` / `../lamina-verify/SKILL.md`) exist, load them; otherwise follow the inline gates below.

### `/lamina-design` — gates then artifacts

1. **Init gate** — if `.lamina/business-context.md` is missing/invalid → emit init-blocked and STOP.
2. **Clarify gate** — only when the brief has **no** concrete feature/surface (e.g. “somehow improve UX”) **and** the user did **not** say “brief is complete” / “do not clarify”: emit **only** the clarification contract and STOP. **Do not** run `seed-ready-run`, write `run.json`, or emit design headings yet.
   - Concrete “Add \<feature\> to \<settings/app/surface\>” briefs are **complete enough** — skip clarify and seed immediately.

```markdown
## Lamina: clarification needed
### Status
Blocked before artifact generation.
### Clarifying questions
…
### Why these block the artifact
…
### How to proceed
…
### Do not
- Do not create run.json or implement.md yet
```

3. **Seed (mandatory for concrete features):** refuse any `src/` / npm ask in one paragraph, then run **from the workspace root** (not from the skill dir):

```bash
SEED=$(ls ./{.opencode,.codex,.claude,.agents}/skills/lamina/scripts/seed-ready-run.mjs 2>/dev/null | head -1)
test -n "$SEED"
node "$SEED" --slug <kebab-slug> --problem "<problem>" --outcome "<outcome>" --users "<id>"
test -f .lamina/runs/<kebab-slug>/run.json
test -f .lamina/runs/<kebab-slug>/implement.md
```

4. **Response must use these exact `###` headings** (graders match literal strings — paraphrased “Summary” / “Key Details” fails):

```markdown
### Domain and invariants
…
### Actors and permissions
…
### Workflows
…
### Scenarios
…
### Implement brief
…
### Open questions
…
```

Mention **flows**, **edge cases**, `lamina-edge-cases`, and at least three of: empty / failure / permission / conflict / boundary. No visual styling. **Do not** end with a prose-only design doc when `run.json` is missing.

When `/lamina-design` siblings are missing, still follow the same gates — prefer the seed script above over hand-authored graphs after clarify clears.

When `/lamina-verify` sibling files are missing from the install, still emit the verify completion headings after writing `.lamina/runs/<id>/` artifacts:

```markdown
### Executive summary
### Findings
### Open questions
```

Mention **audit**, **findings**, **prioritized** improvements, and at least one of **failure** / **empty** / **permission** edge language when auditing flows.

When the user message starts with `/lamina-init`, follow this path even if `lamina-init` siblings are missing:

1. Refuse any `src/` / app-source refactor in one short paragraph.
2. Choose mode:
   - **update** when the user says `update`, `pivot`, or `.lamina/business-context.md` already exists
   - **establish** otherwise
3. Immediately write **both**:
   - `.lamina/business-context.md` — start with this exact YAML frontmatter shape (required; validators fail without it):

```yaml
---
lamina:
  maturity: brownfield   # or greenfield
  platform: [web]
  last_updated: YYYY-MM-DD
---
```

     Then exact `##` sections: Problem statement, Business goals, Success metrics, Scope, Users & market, Product posture, Constraints, Stakeholders, Risks & unknowns, Research posture, Triad check. Each section needs a non-placeholder `**Answer:**`.
   - `.lamina/personas.json` — JSON only. `contract_version: "2.0"`, ≥2 personas. Each persona MUST have `goals`, `constraints`, and `evidence` as **arrays of strings** (not prose strings). Exactly one `"primary": true`. **Never** `personas.yaml`.
4. **Update mode extras (required):**
   - Append a `## Changelog` section (or dated `### YYYY-MM-DD — …` under Changelog) describing what changed and the trigger.
   - In the response, include `### Stale downstream artifacts` and name what may be stale (e.g. personas, prior runs). Say the words **changelog** and **stale** explicitly.
5. Use repo evidence + labeled provisional assumptions; put leftover questions under Open questions.
6. Respond with the Init output headings (`## Init: …`, `### Mode`, `### Business context summary`, `### Open questions`, `### Artifacts`, `### Stale downstream artifacts` when update, `### Recommended next step`).

Do not spend the turn searching for missing skill files — write the artifacts first.

During `/lamina-design` / `/lamina-verify` / `/lamina`:
- **Never** create or edit `src/`, `app/`, `components/`, API routes, or run `npm install`
- **Never** claim you implemented a component file — design produces `.lamina/runs/*/implement.md` for a later coding turn
- If the user asks to “create `src/...`” or “scaffold”: refuse the app-source part, continue design-only under `.lamina/`

## Direct mode first (no init)

If the request is a **single focused UX topic**, go **direct** — do **not** run the init gate, do **not** emit `## Lamina: init required`, and do **not** start `/lamina-design` or full verify. Read the matching skill and **write its id** in the response (hooks look for the literal id like `lamina-forms`). Phrases like “help with form validation” / “users abandon signup” still map to `lamina-forms` when the topic is forms — not init, not checkout-wide audit:

| User signal | Skill id to name |
|-------------|------------------|
| forms, validation, signup fields | `lamina-forms` |
| password reset, multi-step flow, journey steps, drop-off mid-flow | `lamina-flow-design` |
| lost in nav, wayfinding, IA (information architecture) | `lamina-navigation` |
| accessible, screen reader, a11y | `lamina-accessibility` |
| get started, first-run, onboarding | `lamina-onboarding` |
| error messages, empty/error states (copy/recovery) | `lamina-error-handling` |
| usability study, research plan | `lamina-research` |
| trust, billing honesty, opaque fees, distrust after error | `lamina-trust` |
| empty state, no data yet, blank screen | `lamina-empty-states` |
| heuristic review, Nielsen, expert review before testing | `lamina-heuristic-review` |

Prefer the **most specific** skill: billing/trust anxiety → `lamina-trust` (not error-handling); blank/no-data UI → `lamina-empty-states` (not error-handling); **password-reset / multi-step procedure** → `lamina-flow-design` (not navigation). Always **write the skill id** (e.g. `lamina-flow-design`) in the response. If a sibling skill file is missing, still name the correct id and answer from router knowledge — do not substitute a different skill id.

## Step 0 — Init gate when routing to design or verify

**Direct mode skips this gate** (see above). Only design and verify routes require init.

Before dispatching to [design.md](../lamina-orchestrator/workflows/design.md) or [verify.md](../lamina-orchestrator/workflows/verify.md), run [init-required](../lamina-orchestrator/prerequisites/init-required.md).

**If init validates** (`.lamina/business-context.md` exists and passes validation): **read it from disk** with your file tool, then proceed to the chosen workflow. Do **not** emit `## Lamina: init required`.

**Before claiming init is missing:** you **must** attempt to read `.lamina/business-context.md` with your file tool. Do not emit init-blocked based on assumptions or an empty listing alone — a failed read (ENOENT) is required evidence.

- **Problem exploration** (“don't know what to build”, early ideation): route to design — frame the user problem, mention **design workflow**, **flows**, and **edge cases**; use design output headings when shaping (`### Domain and invariants`, etc.) or explicitly dispatch `/lamina-design`.
- **Specific feature**: route to design; first reply must literally include the words `flows` and `edge cases` (hook graders match those tokens — “Workflows” alone is not enough).
- **Verify/audit**: route to verify with **audit**, **findings**, **prioritized** improvements.

**If init fails**, name the **intended route** in one short sentence (using [Router response cues](#router-response-cues)), then emit this contract and **STOP**. Do not run workflow steps.

Example cue: `Intended route: design workflow for <feature or problem> (flows, edge cases) — blocked until init.`

Then emit:

```markdown
## Lamina: init required

### Status
Blocked — `/lamina-init` has not been run on this project, or `.lamina/business-context.md` is incomplete.

### What's missing
- <specific validation failure>

### Next step
Run `/lamina-init` to establish `.lamina/business-context.md`, then retry this command.

### Do not
- Proceed with workflow steps or create `.lamina/` artifacts
- Auto-run init without the user invoking `/lamina-init`
- Treat personas or prior product graphs as a substitute for business context
```
