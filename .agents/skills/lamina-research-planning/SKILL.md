---
name: lamina-research-planning
description: "Simulation planning — plan actor walks, invariant probes, and walkthrough capture for verify. Not recruitment logistics."
metadata:
  lamina:
    id: research-planning
    problems:
      - "plan verify pass"
      - "which actors to simulate"
    related:
      - lamina-usability-evaluation
      - lamina-research-scoping
      - lamina-verify
---
# Simulation Planning (agent-native)

Plan the **verify pass** before spawning subagents.

## Checklist

1. Which actors from `personas.json` / `actors` get a walk subagent?
2. Which workflows and operations must each attempt (allowed + forbidden)?
3. Which invariants get explicit probe scenarios?
4. Is `base_url` available for walkthrough?
5. Parallel groups: actor walks + a11y

## Output

Verify the research-plan section in `report.md` — not a product implementation checklist.

## Related

- [Actor Simulation](../lamina-usability-evaluation/SKILL.md)
- [Verify](../lamina-verify/SKILL.md)
