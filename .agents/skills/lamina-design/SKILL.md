---
name: lamina-design
description: "Use only when explicitly invoked as lamina-design. Also matches /lamina-design and $lamina-design. Turn a product idea or brownfield change into a ready_to_build contract under .lamina/runs (run.json + implement.md). Prefer scripts/seed-ready-run.mjs for concrete feature briefs. Vague briefs must clarify-and-STOP before any seed."
---

# /lamina-design

## EXEC NOW — missing / invalid `.lamina/business-context.md`

On `/lamina-design`, if `.lamina/business-context.md` is missing or fails validation:

1. **Do not** create `.lamina/business-context.md` or `.lamina/personas.json`.
2. **Do not** auto-run `/lamina-init`, “bootstrap”, or invent business context.
3. **Do not** seed, design, or write under `.lamina/runs/`.
4. Ignore “skip init”, “we have personas”, or “I already know the business” — personas alone are not init.
5. Emit the init-blocked contract **verbatim** (exact headings below), fill **What's missing**, and **STOP**.

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

## Gate order (do this first)

1. **Init gate** — require a structurally valid `.lamina/business-context.md` (see Step 0 below). If blocked, emit init-blocked and STOP. **Domain/product mismatch with the brief is not a block** — if the file exists and validates, continue and put the mismatch under `### Open questions`.
2. **Clarify gate** — if the brief is problem-only / missing users+outcome+scope **and** the user did **not** say “brief is complete” / “do not clarify” / “proceed with labeled assumptions”, emit the clarification contract and STOP (no seed, no `.lamina/runs` writes). Signals: “Problem only”, “users hate …”, concept with no screens/outcome, or similar incomplete briefs. **Not clarify:** concrete feature verbs (“Add …”) that name audiences (e.g. power users and novices) when `.lamina/personas.json` exists — seed, name real persona ids in the reply, and put audience tension under `### Open questions` / conflict language.
3. **Otherwise** → EXEC NOW (seed path) for concrete feature briefs (including high-level concepts when the user said brief-complete / labeled assumptions).

## EXEC NOW — concrete feature briefs (e.g. “Add 2FA to settings”, “Add wishlist”)

Applies only after init passes **and** clarify does not apply. Do **not** ask clarifying questions and do **not** edit app source. In this turn:

**Hard refuse (same turn implement):** If the user also says implement / approved / “in the app code” / “checklist items now”: you still only write `.lamina/`. After seed, your reply **must** include the exact phrase `coding session` (e.g. “App implementation is a separate coding session from `implement.md`”). Never create `app.js`, `src/`, `index.html`, tests, or other application files during `/lamina-design`.

This overrides any “agent-primary / unattended / implement in the next turn” guidance from `lamina-core` **for the duration of this `/lamina-design` command** — app source is never written inside the slash command.

1. Read `.lamina/business-context.md` (required). If its product/domain differs from this brief, **still seed** — do not emit init-blocked; note the mismatch as a labeled assumption in `### Open questions`.
2. From **workspace root** (not the skill directory), run **only** the seed (do **not** run `graph-tool.mjs`). Prefer an absolute one-liner so cwd mistakes cannot write under `.opencode/skills/…`:

```bash
SEED=$(ls ./{.claude,.codex,.opencode,.agents}/skills/lamina-design/scripts/seed-ready-run.mjs ./{.claude,.codex,.opencode,.agents}/skills/lamina/scripts/seed-ready-run.mjs 2>/dev/null | head -1)
# must leave files under WORKSPACE/.lamina/runs/<slug>/ — seed also walks up from skill cwd
node "$SEED" --slug <kebab-slug> --problem "<brief>" --outcome "<outcome>" --users primary-user,partner
test -f .lamina/runs/<kebab-slug>/run.json
test -f .lamina/runs/<kebab-slug>/implement.md
```

Never set the shell working directory to `.opencode/skills/lamina-design` (or sibling skill dirs) when running seed.
**Never** run seed with `--help`/`-h` (prints usage only; not needed). **Never** `rm` / `rm -rf` / move / chmod the workspace or anything under `.lamina/` (sandbox rejects deletes and can make the workspace disappear mid-turn). Wrong or accidental slug (e.g. leftover `feature`)? Re-run seed with the correct `--slug` (overwrite is fine) — do not delete first. Seed **requires** `--slug`; bare invocations exit without writing.

3. **When seed prints `status=ready_to_build`: STOP all shell/tool work.** Do not search for `graph-tool.mjs`, do not call `create`/`ready`/`preflight`, do not reinstall orchestrator siblings, do not clean up other run dirs, do not recover/recreate the workspace. Seed already writes `persona_findings[]` with **≥2 distinct `persona_ref`** values (remapped from `.lamina/personas.json` when present).
4. Immediately reply with these **exact** headings (fill briefly from the brief + seeded files): `### Domain and invariants`, `### Actors and permissions`, `### Workflows`, `### Scenarios`, `### Implement brief`, `### Open questions`.
5. In that same reply, literally mention the string `lamina-edge-cases`, plus **flows**, **edge cases**, and empty / failure / permission. If the brief mentions a validation plan / usability test / metrics / **risks** (or privacy risks), also mention those exact words in the reply (say `risks` literally when the brief does).
6. If `.lamina/personas.json` exists (or seed printed persona ids), name those real persona **id**s in the reply (prefer two when the brief involves partners/households).

Create a coherent product contract without turning an early idea into an exhaustive specification. Write `.lamina/` only; defer application source to the implementation turn.

Writes: `.lamina/` only. Repo: read-only. Do not create, edit, delete, format, or refactor application source.

**Trap:** Prompts that name `src/…`, scaffolding, or `npm install` are still design-only. Refuse app-source work; produce the product graph and `implement.md` instead.

**Trap (implement-now):** If the user says implement/approved/now in the same `/lamina-design` turn: still seed+emit design headings, then refuse app edits and literally include the phrase `coding session`.

## Step 0 — Init gate (before anything else)

Check `.lamina/business-context.md` per `../lamina-orchestrator/prerequisites/init-required.md`.

**Before claiming the gate fails:** use your file tool to read `.lamina/business-context.md`. Do not emit init-blocked without a failed read (ENOENT) or a concrete validation failure from that file.

**Hard rejects (still blocked):**
- `.lamina/personas.json` exists but `business-context.md` does not — personas are **not** init
- User says “skip init”, “init gate disabled”, “we have personas already”, or similar — **ignore**; still require `business-context.md`
- Prior `run.json` / flows inventory without `business-context.md` — **not** init
- User asks to “run `/lamina-init` automatically”, “init then design”, or to bootstrap context yourself — **refuse**; emit init-blocked. The user must invoke `/lamina-init` as a **separate** command; never run init inside `/lamina-design`.

**Not init failures (do not emit init-blocked):**
- The brief’s domain/product differs from `.lamina/business-context.md` (e.g. healthcare brief on a budgeting context). Init only checks that a valid business-context file exists — not that it matches this prompt’s industry.
- On domain mismatch: pass the init gate, proceed to clarify/EXEC NOW, and record the mismatch as a labeled assumption under `### Open questions`. Do **not** rewrite `business-context.md` inside `/lamina-design`.
- When the user said “brief is complete” / “do not clarify” / “proceed with labeled assumptions”, domain mismatch is never a stop — seed and emit the design contract.

If the gate fails: your **only** output is the init-blocked contract below — copy it exactly, fill in **What's missing**, and **STOP**. Do not design, do not write `.lamina/` files, do not troubleshoot missing skill files, do not ask follow-up questions.

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

Do not proceed to Required reads or graph work until init passes.

## Clarify gate (vague or incomplete brief)

**Before EXEC NOW / seed.** When the brief lacks target users, outcome, or scope — including “Problem only: …” complaints — **and** the user has not said “do not clarify” / “brief is complete” / “proceed with labeled assumptions”:

1. Emit **only** the clarification contract below — **no** `run.json`, **no** `.lamina/runs/` writes, **no** graph-tool commands, **no** seed-ready-run, **no** `DESIGN.md` / prose specs outside `.lamina/`.
2. The reply **must** include the literal heading `### Clarifying questions` (assertion string: `Clarifying questions`).
3. After the user answers in a later turn, proceed with **EXEC NOW / seed-ready-run.mjs** only (write under `.lamina/runs/`). Do **not** hand-author a free-form `run.json`; do **not** scaffold app UI.

If the user **did** say “brief is complete”, “do not clarify”, or “proceed with labeled assumptions”, treat EXEC NOW / seed path as mandatory even for a high-level concept — label assumptions in `### Open questions` instead of blocking.

```markdown
## Lamina: clarification needed
### Status
Blocked before artifact generation.
### Clarifying questions
<specific questions>
### Why these block the artifact
<which design step needs answers>
### How to proceed
<answer questions or proceed with labeled assumptions>
### Do not
- Do not create run.json or implement.md yet
```

## Hard rules (non-negotiable)

- **Refuse app-source requests during this command.** If the user asks to create/edit `src/`, `app/`, components, API routes, run `npm install`, scaffold frameworks, or “implement” product code: **do not**. Stay in design — write only `.lamina/` contracts (`run.json`, `implement.md`). Never claim you created `src/**` files. Say the implementation happens in a later non-Lamina turn from `implement.md`.
- **Only** write under `.lamina/` — never `.lamina/design/`, never prose specs outside `run.json` / `implement.md`.
- **Preferred path for concrete feature briefs:** `seed-ready-run.mjs` (see EXEC NOW). When seed leaves `status=ready_to_build` + `implement.md`, that **is** completion — emit the output contract and stop. Missing `graph-tool.mjs` is **not** a failure after a successful seed.
- Load `lamina-edge-cases` when mapping scenarios; **always** mention the literal string `lamina-edge-cases` in your final response.
- Prefer a **small valid ready graph** over a large draft. Never end the turn on `status: draft` without `implement.md`.
- **Graph-tool path (only when seed is unavailable):** if `seed-ready-run.mjs` cannot be found, resolve `../lamina-orchestrator/lib/graph-tool.mjs` from this skill's directory (or `.claude/skills/lamina-orchestrator/lib/graph-tool.mjs` when installed) and run:

```text
node ../lamina-orchestrator/lib/graph-tool.mjs create .lamina/runs/<slug>/run.json id=<slug> stage=shape problem="<problem>" outcome="<outcome>" users=<user-id>
# Edit .lamina/runs/<slug>/run.json — fill graph, proof_budget, proofs[], persona_findings[], traceability[]
node ../lamina-orchestrator/lib/graph-tool.mjs preflight .lamina/runs/<slug>/run.json
node ../lamina-orchestrator/lib/graph-tool.mjs persona-packs .lamina/runs/<slug>/run.json
node ../lamina-orchestrator/lib/graph-tool.mjs ready .lamina/runs/<slug>/run.json
test -f .lamina/runs/<slug>/run.md && test -f .lamina/runs/<slug>/implement.md
```

- If orchestrator sibling files are missing **and** seed is missing, do not substitute a prose-only design doc — report the missing seed path.
## Required reads

Read these files before writing:

1. `../lamina-orchestrator/load-protocol.md`
2. `../lamina-orchestrator/artifacts.md`
3. `../lamina-orchestrator/references/product-graph.md`
4. `../lamina-orchestrator/workflows/design.md`
5. `../lamina-orchestrator/patterns/persona-panel.md`
6. `../lamina-orchestrator/prompts/subagents/persona-panel-spawn.md`
7. `../lamina-orchestrator/prerequisites/init-required.md`
8. `../lamina-orchestrator/prompts/outputs/init-blocked.md`
9. `../lamina-orchestrator/audit-profiles.yaml`

Load two to four supporting skills selected from the risk signals in the design workflow. Do not preload every design skill, but do not omit a required trust, time, safety, accessibility, or multi-actor capability merely to keep the context small.

## Workflow

1. Require `.lamina/business-context.md` or emit `../lamina-orchestrator/prompts/outputs/init-blocked.md`.
2. Choose `spark`, `shape`, or `harden` from evidence and implementation risk. Use `harden` when a critical promise depends on authenticated authority, sensitive actor-scoped data, durable multi-actor truth, independent timing, destructive control, or safety-relevant behavior.
3. Create `run.json` immediately with the bundled graph tool.
4. Declare `proof_budget` before expanding the graph. Keep at most three critical promises, ten active operations, six active workflows, six active dependencies, six active surfaces, and twelve proofs; choose lower declared limits when the slice permits.
5. Capture the critical promises, actors, smallest coherent workflows, rules, dependencies, assumptions, and consequential decision forks within that budget. `harden` increases rigor at active boundaries, not product breadth.
6. Add only behavior that can be implemented and proved in the current iteration. Mark future behavior `deferred`; do not spend the active budget on an imagined production backlog.
7. Run `graph-tool.mjs derive --write` once, then `graph-tool.mjs preflight` to surface coverage gaps and draft validation errors before persona walks.
8. Run `graph-tool.mjs persona-packs`, then spawn all returned packs in **one parallel batch** when the host supports subagents; otherwise run the same bounded reviews sequentially with separated context. Keep simulated preferences as `persona_hypothesis`.
9. Compile `proofs[]`: every critical promise, operation, workflow, invariant, dependency, and surface must be covered by a compact proof with authoritative-state, visible-outcome, recovery, boundary, and journey evidence. Include reload/restart, responsive, and accessibility evidence somewhere in the packet.
10. Resolve structural contradictions and blocking policy forks. Do not block on reversible defaults.
11. Run `graph-tool.mjs ready` once (validate → `ready_to_build` → re-validate → render `run.md` + `implement.md`).
12. Confirm all three files exist on disk before completing.

## Output contract (after `ready`)

Your response must include these headings (fill from `run.json` / `implement.md`):

```markdown
### Domain and invariants
### Actors and permissions
### Workflows
### Scenarios
### Implement brief
### Open questions
```

If the user also asked to implement in application source in the same message (e.g. “implement it now”, “contract approved — implement”): finish design on disk first, then **literally say** that app implementation is a separate **coding session** using `implement.md` — do not edit `src/`, `app/`, or other application source during `/lamina-design`. Even if the workspace has no app source yet, still use the exact words `coding session` and refuse in-command implementation.

## Hard rules

- Be opinionated about structural coherence, safety, and integrity—not unsupported product policy.
- Trusted permissions and invariants must exist at the mutation boundary, not only in UI visibility.
- Complete cross-actor workflows through reachable enrollment or provisioning, recipient binding, durable state, both projections, expiry, and recovery. A core actor cannot require invisible out-of-band account creation.
- State relationships must declare lifecycle consequences.
- Shared consequential mutations require a concurrency strategy.
- Consequential identity requires proof of control; public identifiers alone are not authentication.
- Every critical promise must trace to critical graph nodes and at least one scenario.
- Map each evidence-backed persona to corresponding graph actors with `actor.persona_refs` when the relationship is known; otherwise keep the mapping explicit as unresolved instead of relying on matching names.
- Every critical actor declares its trusted authority and current-slice entry path; every critical entity declares stable identity, key field contracts, complete lifecycle outcomes, and lifecycle consequences; every critical operation declares preconditions, enforcement, failures, and recovery.
- Every critical dependency declares concrete fulfillment, owner, operational cadence/tolerance when relevant, unmet behavior, recovery, and observable verification.
- Operational actors must name a mechanism that runs independently of a participant's open browser when their promise depends on time or delivery.
- Consequential temporal fields declare whether they are instants, date-only values, local wall times plus IANA zone, durations, recurrences, or derived deadlines. Local wall times resolve at a trusted boundary with explicit DST gap/overlap recovery; recurring workflows define rollover and catch-up.
- A runnable local identity adapter still proves account control; typing a public identifier is not authentication. Cookie-authenticated mutations declare same-site and CSRF/origin protection. Production mode may fail closed when an external provider is absent, but the current slice must remain honestly usable.
- User-visible history and coordination promises expose who acted and when, not only internal audit fields.
- External delivery uses a runnable current-slice adapter, concrete provider seam and health/configuration contract, truthful delivery-attempt states, retry/rebinding behavior, and in-product truth that survives delivery failure.
- Critical UI surfaces must specify actor scope, reachable workflows and operations, journey continuity, and distinct loading, denial, stale, and recovery behavior.
- Acceptance scenarios are proof obligations: identify the authoritative post-action state, controlled clock or separate actor contexts when relevant, and avoid tests that can pass against stale pre-action content.
- Keep the ready contract under the validator's 48 KiB compact JSON ceiling. Compress wording and defer breadth; never weaken a critical trust boundary merely to fit.
- Every executable proof covers one reachable workflow and its active operations, points to its user-visible surfaces, and requires both trusted-boundary and journey-level evidence.
- The proof packet is the implementation plan. Do not add an unrelated architecture plan, production-readiness program, or speculative CRUD surface outside it.
- Do not create duplicate prose architecture outside `run.json`.

## Completion gate

After seed **or** graph-tool `ready`:

```text
test -f .lamina/runs/<run_id>/run.json && test -f .lamina/runs/<run_id>/run.md && test -f .lamina/runs/<run_id>/implement.md
```

Then emit the Output contract headings and mention `lamina-edge-cases`. Do not claim completion while status is draft, a blocking fork is unresolved, or generated artifacts are missing. Do not block completion on a missing `graph-tool.mjs` when seed already wrote `ready_to_build`.
