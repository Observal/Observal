---
name: lamina-user-modeling
description: "Create evidence-grounded product actors and provisional personas, distinguish roles from preferences, and conduct bounded persona perspective reviews without treating simulations as user research."
---

# User modeling

Write `.lamina/personas.json` with Contract v2. Each persona contains role, goals, constraints, evidence references, confidence, and whether it is primary.

Use research, explicit user input, analytics, support evidence, or brownfield behavior as evidence. Keep inferred personas low or medium confidence. Do not invent demographics or preferences that do not change product behavior.

Actors in `run.json` define authority, ownership, and operations. Personas add perspective and constraints; they do not replace the authorization model.
When the mapping is known, record typed `actor_refs` on the persona so isolated reviews can receive only the relevant graph slice.

For perspective review, select at most three personas with materially different goals, authority, vulnerability, or context. Require graph citations and classify findings. Preserve simulated preference as `persona_hypothesis`; promote only structural, safety, contradiction, or evidence-backed findings.
