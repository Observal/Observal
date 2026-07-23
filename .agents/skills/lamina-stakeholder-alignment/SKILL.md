---
name: lamina-stakeholder-alignment
description: "Multi-actor goal alignment — explicit trade-offs and permission conflicts in contract. Not org politics or workshop facilitation."
metadata:
  lamina:
    id: stakeholder-alignment
    problems:
      - "conflicting actor goals"
      - "permission disputes"
    related:
      - lamina-tradeoffs
      - lamina-user-modeling
      - lamina-feature-prioritization
---
# Multi-Actor Goal Alignment (agent-native)

**Stakeholders** = actors in `run.json` with goals, permissions, and conflicts — not meeting-room politics.

## Framework

1. List actors and each one's success outcome
2. Surface conflicts (student vs admin regenerates ticket; buyer vs seller refund)
3. Record resolution in `decisions.md` with trade-off rationale
4. Encode permissions in `actors` and `workflows[].dependency_refs` / `dependencies[]`

## Anti-patterns

- **Alignment theater** — workshops without contract updates
- **Hidden veto** — unstated stakeholder constraint that breaks invariants

## Related

- [Tradeoffs](../lamina-tradeoffs/SKILL.md)
- [User Modeling](../lamina-user-modeling/SKILL.md)
