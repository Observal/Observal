---
name: lamina-requirements-definition
description: "Translate product intent into traceable critical promises, graph nodes, observable scenarios, assumptions, and scope without prescribing unnecessary implementation details."
---

# Requirements definition

Write requirements as traceable product behavior:

- `intent.critical_promises[]`: outcomes the product must preserve.
- Actors, entities, operations, workflows, invariants, and dependencies: how the product stays coherent.
- `scenarios[]`: observable distinct risks and recovery.
- `decisions`: confirmed choices, assumptions, and policy forks.
- `intent.scope`: current in/out boundaries.
- `traceability[]`: promise-to-graph links.

Mark every node's criticality, provenance, confidence, and relevance. Keep stack and vendor choices out unless the user explicitly constrained them. Defer non-current behavior instead of padding the contract.
