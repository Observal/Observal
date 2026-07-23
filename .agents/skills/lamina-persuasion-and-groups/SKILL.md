---
name: lamina-persuasion-and-groups
description: "Multi-actor dynamics — group permissions, shared resources, and social side-effects. Not persuasion craft or influence tactics."
metadata:
  lamina:
    id: persuasion-and-groups
    problems:
      - "group products"
      - "shared state between actors"
    related:
      - lamina-stakeholder-alignment
      - lamina-side-effects
      - lamina-idempotency-concurrency
---
# Multi-Actor Dynamics (agent-native)

When multiple actors share resources, model **permissions, visibility, and side-effects** — not psychological persuasion.

## Checklist

1. Who can see vs edit shared entities?
2. What notifications or visibility changes affect others?
3. Race conditions when two actors act on same resource?
4. Escalation paths (moderator, admin override)

Simulate with **parallel actor walks** in verify — two subagents, same workflow timing.

## Anti-patterns

- **Dark patterns** — manipulation tactics
- **Social proof theater** — fake urgency without product rule

## Related

- [Side Effects](../lamina-side-effects/SKILL.md)
- [Idempotency & Concurrency](../lamina-idempotency-concurrency/SKILL.md)
