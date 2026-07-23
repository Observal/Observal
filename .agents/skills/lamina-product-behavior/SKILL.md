---
name: lamina-product-behavior
description: "Represented model matches domain — UI must not imply illegal states or permissions. Use when run.json domain and screens diverge from implementation shape."
metadata:
  lamina:
    id: product-behavior
    problems:
      - "UI mirrors database or org structure"
      - "represented vs mental model"
      - "behavior before build"
    related:
      - lamina-flow-design
      - lamina-user-modeling
      - lamina-platform-posture
      - lamina-invariants
---
# Product Behavior (agent-native)

The **represented model** in `run.json` must match how actors conceive tasks — simpler than implementation, aligned with domain invariants.

## Contract encoding

| Layer | Artifact |
|-------|----------|
| Domain truth | `entities[]`, `invariants[]` |
| What actors can do | `actors.permissions`, `workflows` |
| What UI shows | `surfaces[]` — no affordance for forbidden operations |
| Illegal states | `scenarios[]` + disabled/hidden actions in screen spec |

**Implementation model** stays in external code. Lamina specifies **represented model** only.

## Frameworks

- **Goals vs tasks**: Design for stable goals; eliminate tasks technology made obsolete.
- **Capability / viability / desirability**: Record trade-offs in `decisions.md` when pillars conflict.
- **Design values**: e.g. don't make actors feel stupid — use as filter when reconciling persona panel conflicts.
- **Patterns**: Modeless feedback, reversible actions — reference in `implement.md`, don't prescribe UI library.

## Design checklists

1. No screen shows actions the actor cannot perform (or shows why disabled).
2. Entity names in UI match `entities[]` vocabulary.
3. States visible to actors match the entity lifecycles — no mystery modes.
4. Primary actor path optimized; edge cases in scenarios, not driving IA.
5. Deviations from common patterns documented in `decisions.md`.

## Verify checks

- Actor walks: forbidden operations blocked with scenario-matching `ux`.
- Invariant probes: UI never implies illegal state (e.g. two active tickets).
- Walkthrough: represented labels match contract entity names.

## Anti-patterns

- **Elastic user**: Generic actor justifying any design choice.
- **UI after coding**: Contract written to match accidental implementation.
- **Implementation-shaped menus**: File/Edit mirroring backend modules.
- **Feature lists without goals**: Workflows not traceable to actor outcomes.

## Related

- [Invariants](../lamina-invariants/SKILL.md)
- [User Modeling](../lamina-user-modeling/SKILL.md)
- [Platform Posture](../lamina-platform-posture/SKILL.md)
