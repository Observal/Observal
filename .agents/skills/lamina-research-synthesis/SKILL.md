---
name: lamina-research-synthesis
description: "Simulation synthesis — merge parallel actor-walk and walkthrough results into findings[]. Not affinity mapping human interviews."
metadata:
  lamina:
    id: research-synthesis
    problems:
      - "merge actor walk results"
      - "dedupe verify findings"
    related:
      - lamina-usability-evaluation
      - lamina-findings-communication
      - lamina-verify
---
# Simulation Synthesis (agent-native)

After parallel verify subagents return, **merge evidence** into actionable `findings[]`.

## Framework

1. Collect persona-walk JSON, walkthrough captures, and accessibility evidence
2. Cluster by: invariant violation, permission gap, UX blocker, a11y issue
3. Deduplicate same root cause across actors
4. Rank: blocking build trust vs polish
5. Link each finding to `scenario_id`, `screen_id`, or invariant id

## Anti-patterns

- **Quote theater** — fabricated user quotes from simulated sessions
- **Insight without repro** — findings without steps or contract ref

## Related

- [Findings Communication](../lamina-research-communication/SKILL.md)
- [Verify](../lamina-verify/SKILL.md)
