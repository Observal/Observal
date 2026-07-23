---
name: lamina-decision-making
description: "Prioritize contract gaps and verify findings — impact × effort, primary actor filter. Use when reconciling conflicts or ranking findings[]."
metadata:
  lamina:
    id: decision-making
    problems:
      - "prioritizing findings"
      - "conflicting actor goals"
      - "analysis paralysis"
    related:
      - lamina-user-modeling
      - lamina-feature-prioritization
      - lamina-tradeoffs
---
# Decision Making (agent-native)

Rank **contract changes and verify findings** by impact on primary actor goals and invariants — output to `decisions.md`, sorted `findings[]`, and `fix.md` sections.

## Fix target classification

Before writing `fix.md`, set `fix_target` on each finding in `run.json`:

| Signal | `fix_target` |
|--------|---------------|
| Missing UI, bug, invariant violation on live product, a11y on existing screen | `product` |
| Scope change, new workflow/invariant, defer feature, contract wrong | `contract` |

**Default:** `product` when `fix_target` is unset. Product fixes belong in `fix.md` → coding session. Contract items belong in `fix.md` → `/lamina-design` delta prompt only.

## Decision filter

Does this finding change a specific design or implementation decision? If not, dig deeper or drop.

## Impact × effort (verify findings)

| Impact | high | medium | low |
|--------|------|--------|-----|
| **Definition** | Blocks workflow, invariant violation, primary actor stuck | Friction with workaround | Polish |

| Effort | high | medium | low |
|--------|------|--------|-----|
| **Definition** | Cross-workflow contract change | Localized screen/scenario | Copy/label fix |

**Sort:** high impact + low effort first; then high impact + high effort. Record rationale in `decisions.md`.

## Primary actor filter

When actors conflict:
1. Does option serve **primary** persona goals completely?
2. If no → deprioritize or cut; if yes → design fully for their scenario.
3. Log trade-off in `decisions.md` with rejected actor impact noted.

Used when reconciling parallel persona panel outputs.

## Evidence weighting

| Source | Weight |
|--------|--------|
| Invariant probe failure on live product | highest |
| Actor walk blocker (repro steps) | high |
| Walkthrough/repo grounding | medium |
| Assumption in design | low — mark `to-verify` |

Never rank invented analytics above reproduced actor failures.

## Related

- [User Modeling](../lamina-user-modeling/SKILL.md)
- [Feature Prioritization](../lamina-feature-prioritization/SKILL.md)
- [Tradeoffs](../lamina-tradeoffs/SKILL.md)
