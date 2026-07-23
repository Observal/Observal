---
name: lamina-idempotency-concurrency
description: "Duplicate actions and simultaneous edits — double-submit, concurrent admin updates, and safe retries in product behavior. Use when shared resources can be mutated by multiple actors or requests."
metadata:
  lamina:
    id: idempotency-concurrency
    problems:
      - "double submit"
      - "concurrent edit conflicts"
      - "duplicate records"
      - "race conditions in product workflows"
    related:
      - lamina-invariants
      - lamina-consistency-guarantees
      - lamina-edge-cases
      - lamina-side-effects
    tags:
      - design-default
---
# Idempotency and Concurrency

Design product behavior so duplicate actions and simultaneous edits cannot break invariants — without prescribing database locks or frameworks.

## Decision frameworks

- **Idempotent operation**: Repeating the action has the same effect as once (click "generate ticket" twice → still one ticket).
  - When to use: Any create or payment action.
  - How: Disable button after submit; show existing result on repeat; scenarios for double-click.

- **Concurrent edit conflict**: Two actors change the same resource (two admins assign different venues).
  - When to use: Shared admin resources, collaborative editing.
  - How: Last-write-wins with audit, optimistic conflict UI, or lock-while-editing — document product choice in `scenarios`.

- **Fencing**: Stale action cannot apply after state changed (regenerate ticket on exam already completed → blocked with clear reason).

## Checklists

1. List mutating operations; mark which must be idempotent.
2. For shared editable resources, define conflict behavior.
3. Design UX for in-flight requests (disabled submit, progress).
4. Write scenarios: `concurrent_edit`, duplicate submit, stale action.
5. Verify phase: attempt duplicate and concurrent paths on live product.

## Anti-patterns

- **Double ticket on double-click**: No idempotency on create.
- **Silent overwrite**: Admin B's venue change lost without notice.
- **Optimistic UI without rollback**: Show success then revert confusingly.

## Examples

- **Two admins, one exam**: Admin A assigns Hall 1; Admin B assigns Hall 2 simultaneously. Product rule — second save warns "venue changed since you opened; review and confirm" with diff, not silent overwrite.

## Related capabilities

- [Invariants](../lamina-invariants/SKILL.md)
- [Consistency Guarantees](../lamina-consistency-guarantees/SKILL.md)
- [Edge Cases](../lamina-edge-cases/SKILL.md)
