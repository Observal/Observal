---
name: lamina-flow-design
description: "Design reachable actor workflows from typed product operations, dependencies, and terminal outcomes, including complete cross-actor handoffs and recovery."
---

# Workflow design

A workflow is a user-reachable sequence of `operation.<id>` references owned by one actor and ending in named terminal outcomes.

For each critical workflow:

1. Name its trigger and `actor_ref`.
2. Reference ordered operations rather than restating them in prose.
3. Link dependencies that change reachability.
4. Name success, rejection, degraded, and recovery terminal outcomes that materially differ.
5. Complete cross-actor handoffs through delivery, recipient binding, accept/reject, durable authority change, both projections, expiry, replay, and recovery.
6. Add surfaces only where the workflow needs a user-visible realization.

Do not create a full application flow inventory when only one product slice is being changed.
