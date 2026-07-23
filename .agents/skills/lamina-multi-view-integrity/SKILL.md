---
name: lamina-multi-view-integrity
description: "Consistency across actor views — student, admin, and system surfaces must reflect the same domain truth. Use in multi-actor products when roles see different slices of one system."
metadata:
  lamina:
    id: multi-view-integrity
    problems:
      - "multi-actor product design"
      - "admin vs user view mismatch"
      - "service handoffs between roles"
      - "backstage vs frontstage consistency"
    related:
      - lamina-modularity-boundaries
      - lamina-consistency-guarantees
      - lamina-user-modeling
      - lamina-side-effects
    tags:
      - design-default
---
# Multi-View Integrity

One product, many actor views — each role sees what they need, but all views must agree on domain truth. Design handoffs and visibility across student, admin, exam cell, payment, and support paths.

## Decision frameworks

- **Actor view**: What this role sees, can do, and must not see — derived from permissions, not separate products.
  - When to use: Any product with more than one role.
  - How: `actors` in `run.json` + `personas.json` goals and permissions.

- **Frontstage vs backstage**: User-visible flow vs operations another role performs (student downloads ticket; exam cell assigns venue; payment gateway confirms fee).
  - When to use: Service-style workflows with handoffs.
  - How: Map workflow steps to owning actor; side effects on handoff.

- **Cross-view consistency check**: Same entity id, same lifecycle state, compatible fields across views (admin "cancelled" → student sees cancelled, not downloadable).

## Checklists

1. List all actors and their primary operations on each entity.
2. For each workflow, mark which actor performs each step.
3. Define what each actor sees after each state transition.
4. Write scenarios when views can disagree and how product resolves.
5. Verify phase: walk each actor path on live product.
6. When actors coordinate around history, show compatible actor, action, and authoritative-time attribution in every permitted projection; do not keep the promised “who/when” only in backend fields.

## Anti-patterns

- **Split brain**: Admin voids ticket; student still downloads.
- **Leaked backstage**: Internal admin notes visible to students.
- **Orphan handoff**: Payment succeeds but ticket never unlocks — no actor owns the gap.

## Examples

- **Exam cell + student**: Exam cell publishes venue. Student ticket must show same venue. Invigilator roster lists students for that venue only. Scenarios — venue change after ticket issued triggers regen workflow and notification.

## Related capabilities

- [Modularity Boundaries](../lamina-modularity-boundaries/SKILL.md)
- [Consistency Guarantees](../lamina-consistency-guarantees/SKILL.md)
- [User Modeling](../lamina-user-modeling/SKILL.md)
- [Side Effects](../lamina-side-effects/SKILL.md)
