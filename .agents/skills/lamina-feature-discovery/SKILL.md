---
name: lamina-feature-discovery
description: "Capability discovery — map requests to domain operations, workflows, and actors. Not generative research methods for human labs."
metadata:
  lamina:
    id: feature-discovery
    problems:
      - "what capability to add"
      - "map idea to workflows"
    related:
      - lamina-problem-framing
      - lamina-flow-design
      - lamina-task-analysis
---
# Feature Discovery (agent-native)

Discover **what the product must do** by mapping the ask to entities, operations, and workflows — not by running discovery workshops.

## Framework

1. Parse user intent → candidate operations (verbs on entities)
2. Identify affected actors and permissions
3. Draft minimal workflow skeleton for `run.json`
4. Flag unknowns for clarify gate

## Anti-patterns

- **Brainstorm decks** without domain mapping
- **Competitor copy** without invariant analysis

## Related

- [Task Analysis](../lamina-task-analysis/SKILL.md)
- [Flow Design](../lamina-flow-design/SKILL.md)
