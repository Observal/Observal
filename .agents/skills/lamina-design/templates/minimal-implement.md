# Implement: budgeting

Source: `run.json` contract 2.0

Stage: **shape**. Implement only the active graph, but satisfy every active critical promise at its declared trust boundary. A demo identity switcher, browser-local storage, or an open-page timer is not a substitute for authenticated authority, durable shared state, or an operational system actor unless the contract explicitly declares that prototype limitation.

## Product outcome

members see shared spend and category limits

## Proof budget

Implement the smallest complete slice. The active graph is capped at 10 operations, 6 workflows, 6 dependencies, 6 surfaces, and 12 proof obligations. Do not add current-slice behavior outside this packet. If implementation pressure appears, preserve the critical promises and proof paths and defer unrelated breadth.

## Build protocol

1. Before broad implementation, turn every proof below into named automated checks containing the exact marker `[proof:<id>]`.
2. Create a method-neutral root `product-proof-manifest.json` with version `1.0`. Use either `{"version":"1.0","proofs":[{"proof_id":"<id>","test_files":[],"evidence_levels":[],"test_requirements":[]}]}` or an equivalent id-keyed `proofs` object; map every proof to its test files, evidence levels, and test requirements.
3. Implement only enough product behavior to make the proof paths complete at their trusted boundaries, including visible loading, empty, denial, error, success, and recovery feedback where applicable.
4. Give every test a finite per-test timeout and release every test-owned server, worker, database, browser, context, listener, timer, and temporary resource from a `finally` block, including when setup or assertions fail.
5. Run the complete repository check/build/test suite at least three times. A timeout, delayed exit from open handles, skip, or nonzero exit is a proof failure; no critical proof may remain represented only by prose, types, comments, or seed data.
6. Before handoff, confirm every manifest test file exists, contains its proof marker, and is exercised by the declared test suite.

## Must preserve

- [ ] **promise.shared-view** — Household members see the same consolidated balance for linked accounts

## Executable proof obligations

### proof.shared-view

- **Promises:** promise.shared-view
- **Workflow:** workflow.link-and-view
- **Operations:** operation.link-account, operation.view-budget
- **Rules and dependencies:** invariant.household-scope, invariant.owner-only-link, dependency.oauth
- **Surfaces:** surface.budget-home
- **Given:**
- Owner links an account
- **Action:** Owner completes account link then opens budget home
- **Observable assertions:**
- Member and owner see the same consolidated balance
- **Authoritative state:** account-link.status=linked and household projection refreshed
- **Visible outcome:** Shared balance matches for owner and member
- **Recovery:** On provider failure, account stays unlinked with retry
- **Evidence levels:** boundary, journey
- **Test requirements:** restart_or_reload, responsive, accessibility

## Actors and trusted authority

### actor.owner

- **Goal:** Keep household budget accurate
- **Authority and identity proof:** link accounts and set limits
- **Reachable entry or activation path:** mobile app sign-in
- **Owns:** nothing declared
- **Permissions:** none declared
### actor.member

- **Goal:** See shared spend
- **Authority and identity proof:** view household projection
- **Reachable entry or activation path:** invite accept
- **Owns:** nothing declared
- **Permissions:** none declared

## Domain identity and lifecycle

### entity.household

- **Identity:** household id owned by primary member
- **Key field contracts:**
- id: stable id
- **States:** active → archived
- **Relationships:** entity.account-link (1:n); lifecycle: cascade-archive
- **Lifecycle consequences:**
- archive hides linked balances
### entity.account-link

- **Identity:** provider account linkage per household
- **Key field contracts:**
- status: linked|error|revoked
- **States:** unlinked → linked → error → revoked
- **Relationships:** none declared
- **Lifecycle consequences:**
- revoke removes projections

## Operations: enforcement to visible recovery

### operation.link-account

- **Actors:** actor.owner
- **Preconditions:**
- Actor is authenticated owner
- **Trusted enforcement:**
- invariant.owner-only-link
- **State transitions:**
- entity.account-link: unlinked → linked
- **Durable effects and projections:**
- Not specified
- **Failures:**
- Provider denies OAuth
- Member attempts link
- **Recovery:** Remain unlinked and offer retry
- **Visible outcome:** Account appears in household budget
### operation.view-budget

- **Actors:** actor.owner, actor.member
- **Preconditions:**
- Actor belongs to household
- **Trusted enforcement:**
- invariant.household-scope
- **State transitions:**
- Not specified
- **Durable effects and projections:**
- Render household projection
- **Failures:**
- Unauthenticated
- Non-member
- **Recovery:** Show sign-in or access denied
- **Visible outcome:** Shared balances and limits are shown

## End-to-end workflows

### workflow.link-and-view

- **Responsible actor:** actor.owner
- **Dependencies:** none declared
- **Reachable sequence:**
1. operation.link-account
2. operation.view-budget
- **Terminal outcomes:** Shared budget visible; Link failed with recovery

## Rules

- [ ] **invariant.owner-only-link** — Only owner may link accounts
- [ ] **invariant.household-scope** — Members only see their household projection

## Dependencies and degraded behavior

### dependency.oauth

- **Type:** data
- **Required edge:** operation.link-account requires entity.account-link
- **Condition:** not specified
- **Concrete fulfillment:** not specified
- **Unmet behavior:** Show recoverable link error and keep account unlinked
- **Verification:** not specified

## Surfaces and journey continuity

### surface.budget-home

- **Purpose:** Inspect shared balances and account link status
- **Primary actors:** actor.owner
- **Workflows:** workflow.link-and-view
- **Operations:** operation.link-account, operation.view-budget
- **Interaction and recovery contract:**
- Show shared balance
- Show link status

## Risk scenarios

- [ ] **scenario.link-failure** — Given OAuth provider returns error, when operation.link-account, then Account remains unlinked; User sees recoverable error
- [ ] **scenario.empty-budget** — Given No linked accounts, when operation.view-budget, then Empty state explains next step to link
- [ ] **scenario.member-denied-link** — Given Actor is member not owner, when operation.link-account, then Link is denied without changing state

## Promise trace and proof checklist

- [ ] **promise.shared-view** — prove actor.owner → entity.household → operation.link-account → operation.view-budget → workflow.link-and-view → invariant.household-scope → surface.budget-home → scenario.link-failure

## Resolved assumptions and policy forks

- **decision.monthly** [proposed; reversible_default] — Budget periods are monthly

## In scope

- link account
- view budget

## Out of scope

- tax filing

## Required implementation proof

Before handoff, trace every checked operation through reachable action → trusted enforcement → state mutation → durable commit → actor-scoped projection → visible outcome or recovery. Tests must synchronize on the authoritative post-action state rather than stale pre-action content. Use controlled clocks for time boundaries, separate authenticated contexts for multi-actor promises, and both API-boundary and UI evidence for privacy or revocation. Every test needs a finite timeout and failure-safe finally-block cleanup of all owned resources. Run the repository's build, complete test suite three times, responsive checks, and relevant accessibility checks; every run must exit cleanly with no skips or open handles.
