---
name: lamina-evolutionary-rules
description: "Evolving product rules safely — reversible decisions, invariant checks as features change, deferring commitment. Use when the domain will grow or requirements are uncertain."
metadata:
  lamina:
    id: evolutionary-rules
    problems:
      - "changing product rules over time"
      - "reversible vs irreversible decisions"
      - "regression of invariants after new features"
      - "deferring design commitment"
    related:
      - lamina-tradeoffs
      - lamina-invariants
      - lamina-verify
    tags:
      - design-default
---
# Evolutionary Rules

Products change. Design rules and invariants so they can evolve without silent breakage — prefer reversible choices until the cost of waiting exceeds the cost of committing.

## Decision frameworks

- **Reversible decision**: Can be undone without corrupting domain state (toggle feature flag, add optional field).
  - When to use: Uncertain requirements, early iterations.
  - How: Document in `implement.md` as low-risk; verify after each change.

- **Irreversible decision**: Hard to undo (merge two entity types, remove invariant).
  - When to use: Only when delay cost is high and trade-offs are explicit.
  - How: Record in `decisions.md`; full scenario coverage before ship.

- **Invariant regression check**: New feature must not violate existing `domain` rules — re-run verify after external build.
  - When to use: Every `/lamina-verify` after changes touching shared entities.

- **Defer commitment**: Wait until you need the rule — but do not defer documenting invariants you already know.

## Checklists

1. Tag design decisions reversible vs irreversible in run or `decisions.md`.
2. When adding workflows, re-check all existing invariants for the touched entities.
3. After external implementation, run verify — not one-time at handoff.
4. Prefer additive rule changes over breaking changes to actor permissions.

## Anti-patterns

- **Big-bang rule change**: New payment rule breaks all issued tickets without migration scenario.
- **Forgotten invariants**: Feature ships without updating scenarios.
- **Permanent "temporary"**: Overrides that bypass invariants become architecture.

## Examples

- **Adding waitlist**: Reversible — new workflow branch. Must preserve invariant: one valid ticket per student per exam. Scenarios for waitlist → ticket promotion and edge cases.

## Related capabilities

- [Tradeoffs](../lamina-tradeoffs/SKILL.md)
- [Invariants](../lamina-invariants/SKILL.md)
- [Verify](../lamina-verify/SKILL.md)
