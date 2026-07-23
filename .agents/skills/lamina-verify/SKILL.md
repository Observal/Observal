---
name: lamina-verify
description: "Use only when explicitly invoked as lamina-verify. Verify a live or brownfield product against its product graph: critical promises, reachable workflows, authority, invariants, state integrity, recovery, accessibility, and contract drift; emit evidence-backed fixes before merge. Vague “audit our app” briefs must clarify-and-STOP before any seed."
---

# /lamina-verify

Treat application source as read-only evidence. Write findings and reports only under `.lamina/`; a later fix turn edits application source.

Writes: `.lamina/` only. Repo: read-only. Do not create, edit, delete, format, or refactor application source.

## Gate order (do this first — before EXEC NOW)

1. **Init gate** — require a structurally valid `.lamina/business-context.md` (see Step 0). If blocked, emit init-blocked and STOP.
2. **Clarify gate** — if the audit target has **no** concrete flow/surface/feature named (signals: literally “Audit our app.”, “review the product”, only generic app/product language) **and** the user did **not** say “brief is complete” / “do not clarify” / “proceed with labeled assumptions”: emit **only** the clarification contract below and **STOP**. Do **not** run `seed-verify-run.mjs`, do **not** write `.lamina/runs`, do **not** emit Executive summary/Findings.
3. **Otherwise** → EXEC NOW (seed-verify) for concrete audits (any domain — named flow, surface, route, or feature).

### Clarification contract (copy exactly when clarify applies — keep heading casing)

```markdown
## Lamina: clarification needed
### Status
Blocked before artifact generation.
### Clarifying questions
1. Which concrete flow, surface, route, or feature should be audited?
2. Which primary persona or success outcome should ground the review?
3. Any known failure/empty/permission concerns to prioritize?
### Why these block the artifact
Need a concrete flow before writing audit artifacts.
### How to proceed
Name the flow/surface, or say proceed with labeled assumptions.
### Do not
- Do not create run.json, fix.md, or report.md yet
```

Do not paraphrase these five `###` headings. Do not seed on “Audit our app.”
## EXEC NOW — concrete audit briefs only (any named target)

Applies **only** after init passes **and** clarify does **not** apply. A named flow/surface/route/feature from **any domain** is concrete enough — EXEC NOW. Never use this path for “Audit our app.” without a named target.

Before claiming init failure: **read** `.lamina/business-context.md` with a file tool. If it exists and validates, init passes — do not invent missing context.

1. Read `.lamina/business-context.md` (required). Domain mismatch is not an init failure — note under `### Open questions`.
2. From **workspace root**, **first shell command must be** the verify seed — do **not** explore `node_modules` or invent init failures when a concrete target is already named:

```bash
SEED=$(ls ./{.claude,.codex,.opencode,.agents}/skills/lamina-verify/scripts/seed-verify-run.mjs ./{.claude,.codex,.opencode,.agents}/skills/lamina/scripts/seed-verify-run.mjs 2>/dev/null | head -1)
node "$SEED" --slug <kebab-slug> --problem "<brief>" --outcome "<outcome>" --users primary-user
test -f .lamina/runs/<kebab-slug>/run.json
test -f .lamina/runs/<kebab-slug>/run.md
```

**Never** `--help`/`-h`. **Never** `rm` / clean up `.lamina/` or the workspace. Wrong slug? Re-seed with the correct `--slug`.
If seed prints `REFUSE_SEED`, you attempted a vague audit — emit the clarification contract and STOP (no retries with invented flows).

**When seed prints `status=draft`: continue verification — do not stop or emit completion headings yet.** The seed only initializes the workspace; it never completes the audit.

3. **Inspect the target project (read-only).** Read application source and/or attempt a runnable UI. Build or load a **project-grounded** graph in `run.json`. Set `status: verifying` while auditing. Disclose grounding mode (live UI vs static source) and evidence gaps in the final report.

4. **Visual grounding:** Prefer live UI capture per `../lamina-orchestrator/patterns/visual-walkthrough.md` when a product `base_url` is runnable. Fall back to static UI source when the app cannot run; record limitations explicitly.

5. **Persona panel completion gate (unconditional for brownfield):** Persona simulation is **never** optional. If `.lamina/personas.json` is missing, empty, or invalid, read `../lamina-user-modeling/SKILL.md`, derive evidence-grounded provisional personas from `.lamina/business-context.md` plus observed brownfield source, write and validate `.lamina/personas.json`, then run `graph-tool.mjs persona-packs`. Spawn isolated reviewers per `../lamina-orchestrator/patterns/persona-panel.md` and populate `persona_findings[]` **only** from reviewer output. Never skip the panel, never inline-fake persona results.

6. **Truncation refuse:** If the user asks to “pick top N lenses”, “skip the rest”, or otherwise truncate full-flow audit, **refuse**. Apply the full-flow lens set (`lamina-flow-design`, `lamina-heuristic-review`, `lamina-navigation`, `lamina-discoverability`, `lamina-forms`, `lamina-error-handling`, `lamina-content-design`, `lamina-accessibility`, `lamina-trust`, `lamina-feedback-and-status`, `lamina-decision-making`) and say you **will not skip lenses**. Never write “Remaining lenses skipped”.

7. **Completion gate:** Write evidence-backed `findings[]`, validate with `graph-tool.mjs validate`, render `report.md`, `fix.md`, and `implement.md`, set `status: complete`, then reply with exact headings: `### Executive summary`, `### Findings`, `### Open questions`. Repeat any `@path` citations from the brief in Findings, or write **insufficient detail**. Mention **audit** / **findings** / **prioritized** improvements; empty / failure / permission; persona **id**s from the validated persona set; literally mention `lamina-user-modeling` when provisional personas were derived.

## Step 0 — Init gate

Check `.lamina/business-context.md` per `../lamina-orchestrator/prerequisites/init-required.md`.

**Hard rejects:** personas-only, “skip init”, prior run.json without business-context.

If the gate fails: emit **only** this contract and STOP:

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

## Shell workflow (fallback when seed is unavailable)

```text
node ../lamina-orchestrator/lib/graph-tool.mjs create .lamina/runs/<slug>/run.json id=<slug> stage=shape hook=audit problem="<problem>" outcome="<outcome>" users=<user-id>
# Inspect project; build grounded graph; set status=verifying; run persona panel when personas exist
# Populate evidence-backed findings[]; validate; render report.md + fix.md + implement.md; set status=complete
node ../lamina-orchestrator/lib/graph-tool.mjs validate .lamina/runs/<slug>/run.json
test -f .lamina/runs/<slug>/fix.md && test -f .lamina/runs/<slug>/report.md
```

Prefer the seed path whenever the script exists.

## Completion output contract (after evidence-backed verification)

Only after `run.json` validates at `status: complete` and `report.md`, `fix.md`, and `implement.md` exist:

```markdown
### Executive summary
### Findings
### Open questions
```

## Required reads

1. `../lamina-orchestrator/load-protocol.md`
2. `../lamina-orchestrator/artifacts.md`
3. `../lamina-orchestrator/references/product-graph.md`
4. `../lamina-orchestrator/workflows/verify.md`
5. `../lamina-orchestrator/patterns/persona-panel.md`
6. `../lamina-orchestrator/prompts/subagents/persona-panel-spawn.md`
7. `../lamina-orchestrator/prerequisites/init-required.md`
8. `../lamina-orchestrator/prompts/outputs/init-blocked.md`

## Verification order

Follow `../lamina-orchestrator/workflows/verify.md`. Inspect the target project, ground the graph in observed evidence, derive or repair personas via `lamina-user-modeling` when needed, run persona reviewers unconditionally, and render completion artifacts only after validation.
