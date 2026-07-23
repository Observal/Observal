---
name: lamina-system-traps
description: "Recurring product failure modes from system structure — policy resistance, shifting burden, tragedy of commons. Use when fixes keep failing or symptoms return."
metadata:
  lamina:
    id: system-traps
    problems:
      - "fixes that keep failing"
      - "symptom treatment without root cause"
      - "shared resource depletion"
      - "workarounds that make problems worse"
    related:
      - lamina-feedback-loops
      - lamina-leverage-points
      - lamina-invariants
      - lamina-edge-cases
    tags:
      - design-default
---
# System Traps

Structural failure modes that persist despite local fixes. Recognize the trap before designing another band-aid UX.

## Decision frameworks

- **Policy resistance**: Fixes by one actor are countered by others optimizing different goals (admin speeds registration, exam cell tightens validation — users bounce between conflicting rules).
  - Response: Align goals across actors; soften conflicting constraints.

- **Tragedy of the commons**: Shared resource depletes because individual actors benefit from overuse (shared exam slots, API rate limits, admin override abuse).
  - Response: Enforce limits, make cost visible, assign ownership.

- **Shifting the burden**: Symptom fix (manual override, support ticket) replaces root fix (fix validation rule); dependency on workaround grows.
  - Response: Address root cause; make workaround expensive or temporary.

- **Success to the successful**: Winners take all — early registrants block others, power users hoard features.
  - Response: Diversify rules, quotas, or fair-access policies.

- **Drift to low performance**: Standards erode gradually (exceptions become the rule, "temporary" bypass becomes permanent).
  - Response: Explicit invariant checks; periodic integrity audits.

## Checklists

1. When a fix fails twice, map the trap — don't add a third local fix.
2. Identify shared resources and who pays the cost of overuse.
3. List workarounds users or admins rely on — are they shifting burden?
4. Check whether exceptions have become the default path.
5. Write scenarios in `run.json` for each trap the product must prevent.

## Anti-patterns

- **Heroic support as architecture**: Training support to fix what the product should prevent.
- **Exception sprawl**: Every edge case gets a manual override instead of a rule change.
- **Blaming users**: Traps are structural — "user error" often means trap unaddressed.

## Examples

- **Hall ticket overrides**: Admins manually reissue tickets because venue-change rules are unclear. Shifting burden — support load grows, duplicate tickets proliferate. Fix: explicit venue-change workflow with invariant checks, not more override buttons.

## Related capabilities

- [Leverage Points](../lamina-leverage-points/SKILL.md)
- [Invariants](../lamina-invariants/SKILL.md)
- [Edge Cases](../lamina-edge-cases/SKILL.md)
