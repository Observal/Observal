---
name: lamina-edge-cases
description: "Derive distinct product-risk scenarios from operations, dependencies, authority, lifecycles, concurrency, destructive actions, and recovery without generating exhaustive or duplicate edge-case lists."
---

# Distinct product risks

Use `scenarios[]` for observable behavior that differs from the primary path. One scenario represents one distinct risk; reuse its `risk_key` rather than multiplying equivalent cases across actors and surfaces.

Prioritize:

- Declared operation failures.
- Unmet dependencies.
- Forbidden authority or ownership.
- Invalid and stale transitions.
- Concurrent consequential mutations.
- Destructive confirmation and recovery.
- External failure that changes product behavior.

Every scenario declares `given[]`, `when.operation_ref`, `then[]`, `covers[]`, metadata, and a unique `risk_key`. Acceptance must be externally observable. “Handle gracefully” is not acceptance.

Run `graph-tool.mjs derive` for mechanical suggestions, then add only missing distinct risks. Persona preferences do not become scenarios unless they reveal a structural, safety, or evidence-backed failure.
