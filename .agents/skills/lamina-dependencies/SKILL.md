---
name: lamina-dependencies
description: "Map prerequisite, data, lifecycle, and reachability dependencies between typed product-graph nodes, including explicit behavior when a dependency is unmet."
---

# Dependencies

Use top-level `dependencies[]` when one product behavior relies on another node. Dependencies prevent silent happy paths when setup, ownership, state, or another workflow is missing.

```json
{
  "id": "accept-requires-live-invite",
  "type": "prerequisite",
  "from": "workflow.accept-invite",
  "to": "entity.invitation",
  "required_state": "pending",
  "unmet_behavior": "Reject acceptance, explain expiry or prior use, and offer a new invitation path",
  "criticality": "critical",
  "source": "derived",
  "confidence": "high",
  "relevance_reason": "The workflow cannot succeed without a pending invitation"
}
```

## Procedure

1. Inspect every critical workflow and relationship.
2. Add only dependencies that change reachability, fidelity, lifecycle, or recovery.
3. Use typed `from` and `to` references.
4. State observable `unmet_behavior`; do not use vague precondition prose.
5. Add one scenario with a distinct `risk_key` when the unmet behavior materially affects the product.
6. During verification, force the unmet state and confirm the product blocks, degrades, or recovers exactly as contracted.
7. For timezone data, schedulers, identity, delivery, storage, or runtime-version-specific APIs, name the current-slice adapter/runtime, owner, activation path, health check, cadence/tolerance, and fail-closed production posture.

Avoid infrastructure/vendor dependencies unless they alter user-visible product behavior.
