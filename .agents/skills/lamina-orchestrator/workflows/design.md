# Product graph workflow

## 1. Select depth

- Use `spark` when the idea itself is being shaped.
- Use `shape` when the next build needs a coherent product slice.
- Use `harden` when consequential behavior is approaching trusted release.

Do not increase depth merely because the schema supports more fields. `harden` changes the rigor of active boundaries, not the breadth of the current product slice.

Choose `harden` when any critical promise depends on authenticated authority, sensitive actor-scoped data, durable multi-actor state, an operational timer or delivery actor, destructive control, or safety-relevant behavior. A `shape` contract may prototype those concerns only when its promises and visible copy honestly limit the product to that prototype posture.

## 1a. Select risk capabilities

Use `audit-profiles.yaml` and load only the capabilities activated by the product:

- Multi-actor shared state or sensitive projections: system structure, multi-view integrity, trust, consistency, and idempotency/concurrency.
- Local dates/times, time boundaries, expiry, recurrence, retries, or external delivery: time semantics first, then dependencies, side effects, error handling, and idempotency/concurrency.
- Consequence-sensitive or safety-relevant behavior: invariants, edge cases, system traps, and task analysis.
- Interactive user-facing workflows: information architecture, navigation, feedback/status, forms, and accessibility.
- Material evidence gaps: research scoping; retain unsupported preferences as research debt rather than requirements.

Load two to four skills that cover the active risks. State which risk caused each load.

## 2. Establish intent

Record the user problem, outcome, target users, critical promises, constraints, success signals, and current scope. Ask at most three questions, only for high-impact ambiguity. In unattended work, label coherent assumptions and unresolved policy forks.

## 3. Set the proof budget

Declare the smallest limits that can realize the critical promises. Hard ceilings are three critical promises, ten active operations, six active workflows, six active dependencies, six active surfaces, twelve proofs, and 48 KiB of compact ready-contract JSON. If a behavior cannot fit and receive executable proof in this iteration, defer it. Production governance, broad CRUD, richer recurrence, optional integrations, and speculative recovery paths do not enter the active graph unless the brief makes them necessary to a critical promise.

## 4. Build the minimum graph

Add:

- Actors with goals, ownership, authority, and reachable entry or activation paths.
- Entities with identity, key field contracts, complete states or explicit derived statuses, relationships, and lifecycle consequences.
- User-visible operations with preconditions, state transitions, effects, enforcement, failures, and recovery.
- End-to-end workflows with reachable terminal outcomes.
- Invariants at the trusted enforcement boundary.
- Dependencies with concrete fulfillment, operational tolerances where relevant, explicit unmet behavior, recovery, and verification.
- Surfaces only when they materially realize the workflow.

Every node declares criticality, provenance, confidence, and relevance. Defer non-current behavior.
Classify every consequential temporal field as an instant, date-only value, local wall time plus IANA zone, duration, recurrence, or derived deadline/expiry. For local wall time, preserve untouched local components through the client boundary, resolve them in the declared subject/place zone at a trusted server, and define DST gap/overlap recovery. For recurring work, define rollover/catch-up behavior so a valid daily or periodic workflow cannot silently disappear after its first day.
Use `source: user` only for a requirement actually supplied by the brief or a direct answer; use `derived` or `assumed` for structural consequences and reversible defaults. Do not cite hidden harness filenames or generic labels such as `task_input` as evidence.
When a persona maps to an actor, record `persona_refs` on the actor so a reviewer can receive the relevant graph slice without broadening to unrelated critical nodes.

## 5. Derive distinct risks

Run `graph-tool.mjs derive --write` once after the minimum graph is stable. Cover declared failures, unmet dependencies, destructive actions, authority boundaries, concurrency, and recovery. Add only risks that produce meaningfully different product behavior.

Before persona walks or readiness, run `graph-tool.mjs preflight` to get coverage gaps, derived scenario suggestions, and draft validation errors in one pass.

## 6. Walk perspectives

Run `graph-tool.mjs persona-packs` to build ≤3 scoped reviewer payloads. Spawn all packs in **one parallel batch** when the host supports subagents. Follow [the persona panel protocol](../patterns/persona-panel.md) and [its isolated reviewer contract](../prompts/subagents/persona-panel-spawn.md). Cite graph nodes and classify every finding. Promote structural, safety, contradiction, and evidence-backed findings; retain preference findings as research hypotheses.

## 7. Compile executable proofs

For each critical workflow, add a compact proof that binds its promise, operations, invariants, dependencies, and surfaces to:

- Reachable setup and action.
- Authoritative post-action state that survives reload or restart.
- Visible outcome and recovery feedback.
- Boundary-level and journey-level automated evidence.
- Controlled-clock, separate-actor, dependency-failure, replay/concurrency, responsive, or accessibility requirements when applicable.

Every critical promise, operation, workflow, invariant, dependency, and surface must appear in at least one proof. Prefer one proof that covers a coherent workflow over one proof per schema node.

## 8. Validate readiness

Resolve contradictions and blocking policy forks. Confirm each critical promise traces through actor, entity, operation, workflow, invariant, surface, scenario, and executable proof. Confirm every critical actor can actually enter or activate the product with proof of identity when consequential; entering a public email alone is not authentication. Confirm every critical entity has implementable key fields and lifecycle outcomes, and every critical dependency has a current-slice fulfillment and proof path. Confirm “what happened” promises visibly attribute consequential events to an actor and authoritative time. Confirm the implementation projection preserves actor authority, entity identity/lifecycle, operation enforcement/effects/failures/recovery, dependencies, operational actors, surface behavior, and proof obligations. Run `graph-tool.mjs ready` once to validate draft, flip `ready_to_build`, re-validate with proof packet, and render `run.md` plus `implement.md`.
