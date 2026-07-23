---
name: lamina-consistency-guarantees
description: "Product-facing consistency — what users and actors may see when, stale vs fresh data, and acceptable lag. Use when multiple views must agree without prescribing storage technology."
metadata:
  lamina:
    id: consistency-guarantees
    problems:
      - "stale data shown to users"
      - "when views must match"
      - "eventual vs immediate consistency in product terms"
      - "read-your-writes expectations"
    related:
      - lamina-invariants
      - lamina-multi-view-integrity
      - lamina-side-effects
      - lamina-idempotency-concurrency
    tags:
      - design-default
---
# Consistency Guarantees

Define what "correct enough" means for users and actors — in product language, not database jargon. Match guarantees to user expectations and risk.

## Decision frameworks

- **Strong consistency (product)**: After an action, every view immediately reflects the outcome (payment confirmed → ticket shows downloadable now).
  - When to use: Money, legal eligibility, safety-critical status.
  - How: Block success UI until authoritative state is confirmed; scenarios for lag failures.

- **Eventual consistency (product)**: Views converge after a short delay (roster updates after bulk venue change).
  - When to use: Non-critical aggregates, notifications, search indexes.
  - How: Show "updating" state; set user expectation on delay; scenarios for stale reads.

- **Read-your-writes**: Actor always sees their own recent changes (admin assigns venue → admin view shows assignment immediately).
  - When to use: Any mutating workflow.
  - How: Verify actor walk sees own action reflected.

- **Monotonic reads**: Once shown as true, status should not flip backward without explicit transition (paid → unpaid without refund flow).

## Checklists

1. Per operation, state the consistency guarantee users expect.
2. Identify views that can temporarily disagree (student app vs admin console).
3. Design feedback for lag (skeleton, "processing", refresh).
4. Write scenarios for stale read and recovery.
5. Do not prescribe storage — document product behavior only.

## Anti-patterns

- **False instant**: Success toast before state is durable — user acts on stale truth.
- **Silent staleness**: Old venue on ticket after admin changed it — no refresh or notification.
- **Over-strong everywhere**: Unnecessary blocking UX for low-risk data.

## Examples

- **Venue change**: Admin changes exam venue. Guarantee — students see updated venue within one session refresh; until then show banner "venue updated — refresh ticket." Invariant — ticket never shows old venue after download post-update without void/regenerate.

## Related capabilities

- [Invariants](../lamina-invariants/SKILL.md)
- [Multi-View Integrity](../lamina-multi-view-integrity/SKILL.md)
- [Side Effects](../lamina-side-effects/SKILL.md)
