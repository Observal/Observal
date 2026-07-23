---
name: lamina-usability-evaluation
description: "Actor evaluation — verify-phase simulated user walks on live product. Replaces recruit-N usability labs."
metadata:
  lamina:
    id: usability-evaluation
    problems:
      - "can actors complete workflows"
      - "usability via simulation"
    related:
      - lamina-actor-simulation
      - lamina-interview-design
      - lamina-verify
---
# Actor Evaluation (agent-native)

**Usability** = simulated actors completing workflows on the **built product** during `/lamina-verify`.

## Method

1. Load personas + `run.json` workflows
2. Spawn parallel actor-walk subagents (persona-panel)
3. Each attempts happy path + edge probes
4. Record blockers: cannot find affordance, wrong feedback, dead end
5. Merge into `findings[]` with severity

Requires `status: ready_to_build` or post-build deployment — not wireframe review.

## Anti-patterns

- **Lab recruitment** — N users in a room
- **Pre-build usability** — judging flows without runnable product
- **Heuristic-only** — checklist without actor attempts

## Related

- [Actor-Walk Script Design](../lamina-interview-design/SKILL.md)
- [Verify](../lamina-verify/SKILL.md)
