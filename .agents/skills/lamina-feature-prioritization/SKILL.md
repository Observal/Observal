---
name: lamina-feature-prioritization
description: "Scope prioritization — rank workflows by invariant risk and actor impact. Not roadmap theater or featuritis dogma."
metadata:
  lamina:
    id: feature-prioritization
    problems:
      - "what to design first"
      - "scope cut"
    related:
      - lamina-stakeholder-alignment
      - lamina-invariants
      - lamina-tradeoffs
---
# Scope Prioritization (agent-native)

Prioritize **workflows and scenarios** by risk and actor impact — encoded in contract order and verify depth.

## Criteria

1. **Invariant risk** — concurrency, permissions, money, safety
2. **Actor coverage** — primary persona blocked without this workflow
3. **Dependency** — blocks other workflows
4. **Verify cost** — can we actor-walk it post-build?

Defer polish scenarios; never defer permission or invariant scenarios.

## Anti-patterns

- **Roadmap quarters** — timeline theater without contract
- **MoSCoW without actors** — priority without who is blocked

## Related

- [Invariants](../lamina-invariants/SKILL.md)
- [Tradeoffs](../lamina-tradeoffs/SKILL.md)
