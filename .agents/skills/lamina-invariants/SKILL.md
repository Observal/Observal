---
name: lamina-invariants
description: "Product invariants — rules that must always hold, impossible states prevented, errors defined out of existence. Use when defining what can never happen in the product."
metadata:
  lamina:
    id: invariants
    problems:
      - "impossible states"
      - "business rules that must always hold"
      - "preventing duplicate or inconsistent records"
      - "illegal state transitions"
    related:
      - lamina-system-structure
      - lamina-dependencies
      - lamina-consistency-guarantees
      - lamina-idempotency-concurrency
      - lamina-edge-cases
    tags:
      - design-default
---
# Invariants

Rules the product must never violate. Design so illegal states are unrepresentable — not merely error-handled after the fact.

## Verify

Each `invariants[]` id gets a probe in `/lamina-verify` — attempt violation on live product; UI must prevent or recover per linked `scenarios[]`.

**Invariants vs dependencies:** Invariants are predicates that must hold in valid states. Dependencies are reachability edges — what must exist before a workflow can succeed. Do not collapse them; use [Dependencies](../lamina-dependencies/SKILL.md) for cross-feature setup.

## Decision frameworks

- **Invariant**: A predicate that must hold for every valid system state (one hall ticket per student per exam; venue capacity not exceeded; cancelled tickets cannot be downloaded).
  - When to use: Any entity with uniqueness, capacity, lifecycle, or permission constraints.
  - How: Write in user language in `run.json` `domain`; link scenarios to violation attempts.

- **Define errors out of existence**: Redesign flows so invalid actions are unavailable, not allowed-then-rejected (disable download when unpaid; hide regenerate when exam completed).
  - When to use: High-frequency violations that produce support load.
  - How: Match UI affordances to legal states only.

- **Illegal transitions**: State machine edges that must never occur (confirmed → draft without admin audit; issued → unissued without void record).
  - When to use: Lifecycle entities (orders, tickets, bookings).
  - How: Document allowed transitions in `domain`; scenarios cover blocked attempts.

## Checklists

1. List invariants per entity before screens.
2. For each invariant, define: violation attempt, expected system response, recovery UX.
3. Prefer preventing violation over catching it.
4. Write each invariant with an id in `run.json` for verify-phase checks.
5. Check UI does not imply states that violate invariants (showing "active" on cancelled ticket).

## Heuristics

- **If it can happen, it will**: Assume users and admins will hit every illegal path.
- **Invariant id in scenarios**: Link `scenarios[].invariant_ref` to domain rules for traceability.

## Anti-patterns

- **Validate late**: Accepting form submit then showing error — design out earlier.
- **Orphan invariants**: Rules in prose never tied to workflows or scenarios.
- **UI lies**: Display state that contradicts domain truth.

## Examples

- **Hall ticket invariants**: (1) At most one valid ticket per student per exam. (2) Ticket venue matches exam session venue. (3) Download only when payment confirmed and within availability window. (4) Voided ticket cannot be downloaded.

## Related capabilities

- [Dependencies](../lamina-dependencies/SKILL.md)
- [Consistency Guarantees](../lamina-consistency-guarantees/SKILL.md)
- [Idempotency and Concurrency](../lamina-idempotency-concurrency/SKILL.md)
- [Edge Cases](../lamina-edge-cases/SKILL.md)
