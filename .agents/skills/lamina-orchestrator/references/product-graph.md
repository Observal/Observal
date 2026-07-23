# Minimum sufficient product graph

Use `run.json` as the canonical contract and treat `run.md` and `implement.md` as generated views.

## Depth

- `spark`: capture the critical promise, actors, consequential unknowns, and smallest testable behavior.
- `shape`: add the entities, operations, workflows, rules, dependencies, and distinct risks required to build the next iteration.
- `harden`: add complete lifecycle, permissions, concurrency, recovery, accessibility, and regression behavior for a trusted release.

Increase depth because of implementation risk, not because fields exist in the schema. Depth strengthens active boundaries; it does not authorize a broader product. Mark non-current behavior `deferred`; generated implementation views omit it.

## Proof budget

Every design run declares `proof_budget` before graph expansion. Hard ceilings are three critical promises, ten active operations, six active workflows, six active dependencies, six active surfaces, twelve proofs, and 48 KiB of compact ready-contract JSON. Choose smaller declared limits when possible. If an active behavior cannot be implemented and proved in the current iteration, defer it rather than diluting workflow completion.

Each `proofs[]` item binds one reachable workflow to its promises, operations, invariants, dependencies, surfaces, authoritative state, visible outcome, recovery, and test requirements. Every proof requires boundary and journey evidence. Across the packet, include reload or restart, responsive, and accessibility evidence.

## Node metadata

Every ready graph node declares `criticality`, `source`, `confidence`, and `relevance_reason`. These fields prevent speculative breadth from looking like confirmed product intent.

## References

Use typed references such as `actor.member`, `entity.invitation`, `operation.accept-invite`, and `workflow.join-household`. Keep references stable when names change.

## Scenario derivation

Derive one scenario per distinct risk. Start with unmet dependencies, declared operation failures, destructive actions, authority boundaries, concurrency, and recovery. Reuse an existing `risk_key` instead of duplicating equivalent cases.

## Ready gate

A graph is ready only when critical promises trace to critical actors, entities, operations, workflows, invariants, surfaces, scenarios, and executable proofs; blocking policy forks are resolved; references and state transitions validate; the proof budget holds; and persona findings remain explicitly labeled simulations.

Ready critical nodes must also be implementable without hidden inference:

- Actors declare trusted authority and identity proof plus a reachable enrollment, provisioning, activation, or operational-start path. An external identity platform still needs an explicit current-slice adapter and fail-closed unmet behavior.
- Entities declare stable identity, the key field contracts needed for authority/time/privacy/versioning, complete lifecycle states (including expiry or an explicit derived-status rule), and lifecycle consequences.
- Operations declare preconditions, trusted enforcement, durable effects or transitions, failures, recovery, and visible outcome.
- Operational actors identify behavior that cannot depend on an open participant browser.
- Surfaces bind actors, workflows, operations, and distinct loading, denial, stale, and recovery behavior.
- Scenarios double as proof obligations, including controlled time, separate actor contexts, trusted-boundary probes, responsive behavior, or accessibility checks where relevant.
- Critical dependencies declare their concrete fulfillment owner and mechanism, operational cadence/tolerance where relevant, visible unmet behavior, recovery, and an observable verification path. No core workflow may depend on invisible out-of-band provisioning.
