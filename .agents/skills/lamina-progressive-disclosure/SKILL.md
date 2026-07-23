---
name: lamina-progressive-disclosure
description: "Progressive disclosure in contracts — essential vs advanced actions per actor. Use when novices overwhelmed or experts blocked on power features."
metadata:
  lamina:
    id: progressive-disclosure
    problems:
      - "complex interfaces"
      - "novice vs expert needs"
      - "feature overload on screen"
    related:
      - lamina-platform-posture
      - lamina-onboarding
      - lamina-discoverability
---
# Progressive Disclosure (agent-native)

Defer **advanced operations** in screen contracts — primary path stays minimal; power features reachable without blocking first workflow.

## Contract encoding

Per `surfaces[]`:
- `primary_actions[]` — required for primary actor working set
- `secondary_actions[]` — advanced, behind expand/settings/more
- `disclosure_level`: essential | standard | advanced
- Link to `platform-posture` complexity budget per actor

## Checklists

1. Primary actor completes first workflow seeing only `essential` actions.
2. Advanced ops documented — not omitted from contract entirely.
3. Same operation same label when disclosed (`content-design` consistency).
4. Expert personas in verify can reach advanced path within N steps.
5. No hiding safety-critical warnings behind disclosure.

## Verify checks

- Low-literacy persona: primary workflow without hunting advanced menus.
- Expert persona: power feature reachable; not duplicate/conflicting with primary path.
- Actor walk flags "couldn't find" for contract-promised advanced op → finding.

## Anti-patterns

- Everything on one screen — no primary path.
- Power features only via undocumented gesture.
- Disclosure used to hide errors or required permissions.

## Related

- [Platform Posture](../lamina-platform-posture/SKILL.md)
- [Onboarding](../lamina-onboarding/SKILL.md)
- [Discoverability](../lamina-discoverability/SKILL.md)
